-- Autor: Francisco Salom Zuluaga
-- Fecha de creación: 2026-01-20
-- Versión: 1.3
-- Descripción: Agenda persistente, estados operativos, concurrencia y auditoría.
-- Aplicar como postgres sobre el esquema 1.2. Conserva los registros existentes.
\set ON_ERROR_STOP on
\if :{?VITALIA_INSTALL}
\else
BEGIN;
\endif
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM clinica.version_esquema WHERE version = '1.2') THEN
        RAISE EXCEPTION 'Aplica primero el esquema 1.2.';
    END IF;
END $$;
ALTER TABLE clinica.citas ADD COLUMN IF NOT EXISTS cierre_automatico boolean NOT NULL DEFAULT false;
ALTER TABLE clinica.citas ADD COLUMN IF NOT EXISTS revision integer NOT NULL DEFAULT 0;
ALTER TABLE clinica.citas DROP CONSTRAINT IF EXISTS citas_estado_check;
ALTER TABLE clinica.citas ADD CONSTRAINT citas_estado_check
    CHECK (estado IN ('PROGRAMADA','EN_ATENCION','CERRADA','CANCELADA','ATENDIDA'));
ALTER TABLE clinica.citas DROP CONSTRAINT IF EXISTS ck_citas_cierre;
ALTER TABLE clinica.citas ADD CONSTRAINT ck_citas_cierre
    CHECK (NOT cierre_automatico OR estado = 'CERRADA');
ALTER TABLE clinica.citas DROP CONSTRAINT IF EXISTS ex_citas_medico;
ALTER TABLE clinica.citas ADD CONSTRAINT ex_citas_medico EXCLUDE USING gist (
    medico_id WITH =, tstzrange(inicio, fin, '[)') WITH &&
) WHERE (estado IN ('PROGRAMADA','EN_ATENCION','ATENDIDA'));

CREATE OR REPLACE FUNCTION pck_agenda.fn_revision_cita()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, clinica AS $$
BEGIN
    NEW.revision := OLD.revision + 1;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS tr_cita_revision ON clinica.citas;
CREATE TRIGGER tr_cita_revision BEFORE UPDATE ON clinica.citas
FOR EACH ROW EXECUTE FUNCTION pck_agenda.fn_revision_cita();

CREATE OR REPLACE FUNCTION pck_agenda.fn_validar_fecha_cita()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, clinica AS $$
BEGIN
    IF TG_OP = 'INSERT' AND EXISTS (SELECT 1 FROM clinica.citas WHERE cita_id = NEW.cita_id) THEN
        RETURN NEW;
    END IF;
    IF NEW.estado = 'PROGRAMADA' AND (
        TG_OP = 'INSERT' OR NEW.inicio IS DISTINCT FROM OLD.inicio OR NEW.fin IS DISTINCT FROM OLD.fin
        OR NEW.paciente_id IS DISTINCT FROM OLD.paciente_id OR NEW.medico_id IS DISTINCT FROM OLD.medico_id
    ) THEN
        PERFORM 1 FROM clinica.pacientes WHERE paciente_id = NEW.paciente_id AND activo FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'Selecciona un paciente activo.';
        END IF;
        IF NEW.inicio < clock_timestamp() THEN
            RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'Selecciona una fecha y hora que aún no hayan pasado.';
        END IF;
        PERFORM 1 FROM clinica.medicos WHERE medico_id = NEW.medico_id AND activo FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'Selecciona un médico activo.';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE PROCEDURE pck_agenda.SP_agendar_cita(
    p_cita_id varchar, p_paciente_id varchar, p_medico_id varchar,
    p_inicio timestamptz, p_fin timestamptz, p_actor uuid
) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, clinica AS $$
DECLARE
    r_cita clinica.citas%ROWTYPE;
    e_detalle text;
BEGIN
    PERFORM clinica.fn_exigir_rol(p_actor, ARRAY['ADMINISTRADOR','RECEPCION']);
    IF p_cita_id IS NULL OR btrim(p_cita_id) = '' THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'Falta el identificador de la cita.';
    END IF;
    IF p_inicio IS NULL OR p_fin IS NULL OR p_fin <= p_inicio THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'Verifica el horario de la cita.';
    END IF;
    -- Serializa reservas del mismo médico para evitar interbloqueos de EXCLUDE.
    PERFORM pg_advisory_xact_lock(hashtextextended(p_medico_id, 0));
    -- El bloqueo compartido impide desactivar al médico durante el alta.
    PERFORM 1 FROM clinica.medicos WHERE medico_id = p_medico_id AND activo FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'Selecciona un médico activo.';
    END IF;
    INSERT INTO clinica.citas (
        cita_id, paciente_id, medico_id, inicio, fin, creado_por, actualizado_por
    ) VALUES (p_cita_id, p_paciente_id, p_medico_id, p_inicio, p_fin, p_actor, p_actor)
    ON CONFLICT (cita_id) DO NOTHING;
    SELECT * INTO r_cita FROM clinica.citas WHERE cita_id = p_cita_id;
    IF r_cita.paciente_id IS DISTINCT FROM p_paciente_id
       OR r_cita.medico_id IS DISTINCT FROM p_medico_id
       OR r_cita.inicio IS DISTINCT FROM p_inicio OR r_cita.fin IS DISTINCT FROM p_fin THEN
        RAISE EXCEPTION USING ERRCODE = 'P1004', MESSAGE = 'La solicitud ya existe con otros datos.';
    END IF;
EXCEPTION
    WHEN exclusion_violation THEN
        RAISE EXCEPTION USING ERRCODE = 'P1001', MESSAGE = 'El médico ya tiene una cita en ese horario.';
    WHEN foreign_key_violation OR check_violation THEN
        GET STACKED DIAGNOSTICS e_detalle = CONSTRAINT_NAME;
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'Verifica el paciente y el horario.', DETAIL = e_detalle;
END;
$$;

CREATE OR REPLACE PROCEDURE pck_agenda.SP_cerrar_vencidas(p_actor uuid)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, clinica AS $$
BEGIN
    PERFORM clinica.fn_exigir_rol(p_actor, ARRAY['ADMINISTRADOR','RECEPCION']);
    UPDATE clinica.citas SET estado = 'CANCELADA', cierre_automatico = false, actualizado_por = p_actor
    WHERE estado = 'PROGRAMADA' AND fin <= clock_timestamp();
END;
$$;

CREATE OR REPLACE PROCEDURE pck_agenda.SP_reprogramar_cita(
    p_cita_id varchar, p_inicio timestamptz, p_fin timestamptz, p_actor uuid
) LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, clinica AS $$
DECLARE
    r_cita clinica.citas%ROWTYPE;
    VV_medico varchar(40);
BEGIN
    PERFORM clinica.fn_exigir_rol(p_actor, ARRAY['ADMINISTRADOR','RECEPCION']);
    SELECT medico_id INTO VV_medico FROM clinica.citas WHERE cita_id = p_cita_id;
    IF VV_medico IS NOT NULL THEN
        PERFORM pg_advisory_xact_lock(hashtextextended(VV_medico, 0));
    END IF;
    SELECT * INTO r_cita FROM clinica.citas WHERE cita_id = p_cita_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = 'P1007', MESSAGE = 'No se encontró la cita.';
    END IF;
    IF r_cita.estado <> 'PROGRAMADA' OR r_cita.fin <= clock_timestamp() THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'Solo se reprograman citas pendientes y vigentes.';
    END IF;
    UPDATE clinica.citas SET inicio = p_inicio, fin = p_fin, actualizado_por = p_actor
    WHERE cita_id = p_cita_id;
EXCEPTION
    WHEN exclusion_violation THEN
        RAISE EXCEPTION USING ERRCODE = 'P1001', MESSAGE = 'El médico ya tiene una cita en ese horario.';
    WHEN check_violation OR not_null_violation THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'Verifica el horario de la cita.';
END;
$$;

CREATE OR REPLACE PROCEDURE pck_agenda.SP_reprogramar_cita_controlada(
    p_cita_id varchar, p_inicio timestamptz, p_fin timestamptz, p_actor uuid, p_revision integer
) LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, clinica AS $$
DECLARE
    r_cita clinica.citas%ROWTYPE;
    VV_medico varchar(40);
BEGIN
    PERFORM clinica.fn_exigir_rol(p_actor, ARRAY['ADMINISTRADOR','RECEPCION']);
    SELECT medico_id INTO VV_medico FROM clinica.citas WHERE cita_id = p_cita_id;
    IF VV_medico IS NOT NULL THEN
        PERFORM pg_advisory_xact_lock(hashtextextended(VV_medico, 0));
    END IF;
    SELECT * INTO r_cita FROM clinica.citas WHERE cita_id = p_cita_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = 'P1007', MESSAGE = 'No se encontró la cita.';
    END IF;
    -- Un reintento confirmado con el mismo resultado no duplica la auditoría.
    IF r_cita.estado = 'PROGRAMADA' AND r_cita.inicio = p_inicio AND r_cita.fin = p_fin THEN RETURN; END IF;
    IF p_revision IS NULL OR r_cita.revision <> p_revision THEN
        RAISE EXCEPTION USING ERRCODE = 'P1006', MESSAGE = 'La cita cambió en otra pantalla. Actualiza y vuelve a intentarlo.';
    END IF;
    CALL pck_agenda.SP_reprogramar_cita(p_cita_id, p_inicio, p_fin, p_actor);
END;
$$;

CREATE OR REPLACE PROCEDURE pck_agenda.SP_cancelar_cita(p_cita_id varchar, p_actor uuid)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, clinica AS $$
DECLARE
    r_cita clinica.citas%ROWTYPE;
BEGIN
    PERFORM clinica.fn_exigir_rol(p_actor, ARRAY['ADMINISTRADOR','RECEPCION']);
    SELECT * INTO r_cita FROM clinica.citas WHERE cita_id = p_cita_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = 'P1007', MESSAGE = 'No se encontró la cita.';
    END IF;
    IF r_cita.estado = 'CANCELADA' THEN RETURN; END IF;
    IF r_cita.estado <> 'PROGRAMADA' OR r_cita.fin <= clock_timestamp() THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'Solo se cancelan turnos pendientes y vigentes.';
    END IF;
    UPDATE clinica.citas SET estado = 'CANCELADA', actualizado_por = p_actor WHERE cita_id = p_cita_id;
END;
$$;

CREATE OR REPLACE PROCEDURE pck_agenda.SP_cambiar_estado_cita(
    p_cita_id varchar, p_estado varchar, p_actor uuid, p_revision integer
) LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, clinica AS $$
DECLARE
    r_cita clinica.citas%ROWTYPE;
    VV_medico varchar(40);
BEGIN
    PERFORM clinica.fn_exigir_rol(p_actor, ARRAY['ADMINISTRADOR','RECEPCION']);
    IF p_estado IS NULL OR p_estado NOT IN ('EN_ATENCION','CERRADA','CANCELADA') THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'Selecciona un estado de atención válido.';
    END IF;
    SELECT medico_id INTO VV_medico FROM clinica.citas WHERE cita_id = p_cita_id;
    IF VV_medico IS NOT NULL THEN
        PERFORM pg_advisory_xact_lock(hashtextextended(VV_medico, 0));
    END IF;
    SELECT * INTO r_cita FROM clinica.citas WHERE cita_id = p_cita_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = 'P1007', MESSAGE = 'No se encontró la cita.';
    END IF;
    IF r_cita.estado = p_estado THEN RETURN; END IF;
    IF p_revision IS NULL OR r_cita.revision <> p_revision THEN
        RAISE EXCEPTION USING ERRCODE = 'P1006', MESSAGE = 'La cita cambió en otra pantalla. Actualiza y vuelve a intentarlo.';
    END IF;
    IF r_cita.estado IN ('CERRADA','CANCELADA','ATENDIDA') THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'La cita ya está cerrada, cancelada o atendida.';
    END IF;
    IF p_estado = 'CANCELADA' THEN
        CALL pck_agenda.SP_cancelar_cita(p_cita_id, p_actor);
        RETURN;
    END IF;
    IF p_estado = 'EN_ATENCION' THEN
        IF clock_timestamp() < r_cita.inicio OR clock_timestamp() >= r_cita.fin THEN
            RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'La atención solo puede iniciarse dentro del horario de la cita.';
        END IF;
        PERFORM 1 FROM clinica.pacientes WHERE paciente_id = r_cita.paciente_id AND activo FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'Reactiva al paciente antes de iniciar la atención.';
        END IF;
        PERFORM 1 FROM clinica.medicos WHERE medico_id = r_cita.medico_id AND activo FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'El médico ya no está activo.';
        END IF;
    ELSIF r_cita.inicio > clock_timestamp() THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'Una cita futura puede cancelarse, pero todavía no puede cerrarse.';
    END IF;
    UPDATE clinica.citas SET estado = p_estado,
        cierre_automatico = false,
        actualizado_por = p_actor
    WHERE cita_id = p_cita_id;
END;
$$;

-- La atención clínica futura también admite un turno iniciado desde recepción.
CREATE OR REPLACE PROCEDURE pck_clinica.SP_registrar_atencion(
    p_atencion_id uuid, p_cita_id varchar, p_motivo text, p_actor uuid
) LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, clinica AS $$
DECLARE
    r_cita clinica.citas%ROWTYPE;
BEGIN
    PERFORM clinica.fn_exigir_rol(p_actor, ARRAY['ADMINISTRADOR','MEDICO']);
    SELECT * INTO r_cita FROM clinica.citas WHERE cita_id = p_cita_id FOR UPDATE;
    IF NOT FOUND OR r_cita.estado NOT IN ('PROGRAMADA','EN_ATENCION') THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'La cita debe estar pendiente o en atención.';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM clinica.usuarios u JOIN clinica.roles r USING (rol_id)
        WHERE u.usuario_id = p_actor AND (r.nombre = 'ADMINISTRADOR' OR EXISTS (
            SELECT 1 FROM clinica.medicos m WHERE m.medico_id = r_cita.medico_id
            AND m.usuario_id = p_actor AND m.activo
        ))
    ) THEN
        RAISE EXCEPTION USING ERRCODE = 'P1003', MESSAGE = 'La cita corresponde a otro médico.';
    END IF;
    INSERT INTO clinica.atenciones(atencion_id,cita_id,motivo_consulta,registrado_por)
    VALUES(p_atencion_id,p_cita_id,p_motivo,p_actor);
    UPDATE clinica.citas SET estado = 'ATENDIDA', actualizado_por = p_actor WHERE cita_id = p_cita_id;
END;
$$;

REVOKE EXECUTE ON FUNCTION pck_agenda.fn_revision_cita(), pck_agenda.fn_validar_fecha_cita() FROM PUBLIC;
REVOKE EXECUTE ON PROCEDURE pck_agenda.SP_cerrar_vencidas(uuid),
    pck_agenda.SP_reprogramar_cita_controlada(varchar,timestamptz,timestamptz,uuid,integer),
    pck_agenda.SP_cambiar_estado_cita(varchar,varchar,uuid,integer) FROM PUBLIC;
GRANT EXECUTE ON PROCEDURE pck_agenda.SP_cerrar_vencidas(uuid),
    pck_agenda.SP_reprogramar_cita_controlada(varchar,timestamptz,timestamptz,uuid,integer),
    pck_agenda.SP_cambiar_estado_cita(varchar,varchar,uuid,integer) TO vitalia_app;
INSERT INTO clinica.version_esquema(version) VALUES ('1.3') ON CONFLICT DO NOTHING;
\if :{?VITALIA_INSTALL}
\else
COMMIT;
\endif
