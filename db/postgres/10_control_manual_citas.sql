\set ON_ERROR_STOP on
\if :{?VITALIA_INSTALL}
\else
BEGIN;
\endif
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM clinica.version_esquema WHERE version = '1.3') THEN
        RAISE EXCEPTION 'Aplica primero el esquema 1.3.';
    END IF;
END $$;

DROP PROCEDURE IF EXISTS pck_agenda.SP_cambiar_estado_cita(varchar,varchar,uuid,integer);
DROP PROCEDURE IF EXISTS pck_agenda.SP_cambiar_estado_cita(varchar,varchar,uuid,integer,boolean);

CREATE PROCEDURE pck_agenda.SP_cambiar_estado_cita(
    p_cita_id varchar, p_estado varchar, p_actor uuid, p_revision integer,
    p_forzar boolean DEFAULT false
) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, clinica AS $$
DECLARE
    r_cita clinica.citas%ROWTYPE;
    VV_medico varchar(40);
BEGIN
    PERFORM clinica.fn_exigir_rol(p_actor, ARRAY['ADMINISTRADOR','RECEPCION']);
    IF p_estado IS NULL OR p_estado NOT IN ('PROGRAMADA','EN_ATENCION','CERRADA','CANCELADA') THEN
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
    IF r_cita.estado = p_estado OR
       (p_estado = 'PROGRAMADA' AND r_cita.estado = 'PROGRAMADA') THEN
        RETURN;
    END IF;
    IF p_revision IS NULL OR r_cita.revision <> p_revision THEN
        RAISE EXCEPTION USING ERRCODE = 'P1006', MESSAGE = 'La cita cambió en otra pantalla. Actualiza y vuelve a intentarlo.';
    END IF;
    IF NOT p_forzar AND r_cita.estado IN ('CERRADA','CANCELADA','ATENDIDA') THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'La cita ya está cerrada, cancelada o atendida.';
    END IF;
    IF NOT p_forzar AND p_estado = 'CANCELADA' THEN
        CALL pck_agenda.SP_cancelar_cita(p_cita_id, p_actor);
        RETURN;
    END IF;
    IF NOT p_forzar AND p_estado = 'EN_ATENCION' THEN
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
    ELSIF NOT p_forzar AND r_cita.inicio > clock_timestamp() THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'Una cita futura puede cancelarse, pero todavía no puede cerrarse.';
    END IF;
    UPDATE clinica.citas SET estado = p_estado,
        cierre_automatico = false, actualizado_por = p_actor
    WHERE cita_id = p_cita_id;
END;
$$;

REVOKE EXECUTE ON PROCEDURE pck_agenda.SP_cambiar_estado_cita(varchar,varchar,uuid,integer,boolean) FROM PUBLIC;
GRANT EXECUTE ON PROCEDURE pck_agenda.SP_cambiar_estado_cita(varchar,varchar,uuid,integer,boolean) TO vitalia_app;
INSERT INTO clinica.version_esquema(version) VALUES ('1.4') ON CONFLICT DO NOTHING;
\if :{?VITALIA_INSTALL}
\else
COMMIT;
\endif
