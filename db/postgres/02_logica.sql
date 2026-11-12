-- Autor: Francisco Salom Zuluaga
-- Fecha de creación: 2025-04-10
-- Versión: 1.2
-- Descripción: Rutinas base y triggers de agenda, atención, facturación y auditoría.
CREATE FUNCTION clinica.fn_exigir_rol(p_actor uuid, p_roles text[])
RETURNS void LANGUAGE plpgsql STABLE
SET search_path = pg_catalog, clinica AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM clinica.usuarios u JOIN clinica.roles r USING (rol_id)
        WHERE u.usuario_id = p_actor AND u.activo AND r.nombre = ANY(p_roles)
    ) THEN
        RAISE EXCEPTION USING ERRCODE = 'P1003', MESSAGE = 'Usuario sin permiso para esta operación.';
    END IF;
END;
$$;

CREATE FUNCTION clinica.fn_validar_nacimiento()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, clinica AS $$
DECLARE
    VD_hoy date := (current_timestamp AT TIME ZONE 'America/Bogota')::date;
BEGIN
    IF NEW.fecha_nacimiento > VD_hoy
       OR extract(year FROM age(VD_hoy, NEW.fecha_nacimiento)) > 120 THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'Verifica la fecha de nacimiento.';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER tr_paciente_nacimiento BEFORE INSERT OR UPDATE ON clinica.pacientes
FOR EACH ROW EXECUTE FUNCTION clinica.fn_validar_nacimiento();

CREATE FUNCTION clinica.fn_abrir_historia()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, clinica AS $$
BEGIN
    INSERT INTO clinica.historias_clinicas (paciente_id) VALUES (NEW.paciente_id);
    RETURN NEW;
END;
$$;
CREATE TRIGGER tr_paciente_historia AFTER INSERT ON clinica.pacientes
FOR EACH ROW EXECUTE FUNCTION clinica.fn_abrir_historia();

CREATE FUNCTION pck_auditoria.fn_cambio_cita()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, clinica AS $$
BEGIN
    INSERT INTO clinica.auditoria_citas (
        cita_id, actor_id, accion, estado_anterior, estado_nuevo,
        inicio_anterior, inicio_nuevo, fin_anterior, fin_nuevo
    ) VALUES (
        NEW.cita_id, NEW.actualizado_por, TG_OP,
        CASE WHEN TG_OP = 'UPDATE' THEN OLD.estado END, NEW.estado,
        CASE WHEN TG_OP = 'UPDATE' THEN OLD.inicio END, NEW.inicio,
        CASE WHEN TG_OP = 'UPDATE' THEN OLD.fin END, NEW.fin
    );
    RETURN NEW;
END;
$$;
CREATE TRIGGER tr_cita_auditoria AFTER INSERT OR UPDATE ON clinica.citas
FOR EACH ROW EXECUTE FUNCTION pck_auditoria.fn_cambio_cita();

CREATE PROCEDURE pck_agenda.SP_agendar_cita(
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

CREATE PROCEDURE pck_agenda.SP_reprogramar_cita(
    p_cita_id varchar, p_inicio timestamptz, p_fin timestamptz, p_actor uuid
) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, clinica AS $$
DECLARE
    VV_estado varchar(15);
BEGIN
    PERFORM clinica.fn_exigir_rol(p_actor, ARRAY['ADMINISTRADOR','RECEPCION']);
    SELECT estado INTO VV_estado FROM clinica.citas WHERE cita_id = p_cita_id FOR UPDATE;
    IF NOT FOUND OR VV_estado <> 'PROGRAMADA' THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'La cita debe estar programada.';
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

CREATE PROCEDURE pck_agenda.SP_cancelar_cita(p_cita_id varchar, p_actor uuid)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, clinica AS $$
DECLARE
    VV_estado varchar(15);
BEGIN
    PERFORM clinica.fn_exigir_rol(p_actor, ARRAY['ADMINISTRADOR','RECEPCION']);
    SELECT estado INTO VV_estado FROM clinica.citas WHERE cita_id = p_cita_id FOR UPDATE;
    IF NOT FOUND OR VV_estado = 'ATENDIDA' THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'La cita no está disponible para cancelar.';
    END IF;
    IF VV_estado = 'CANCELADA' THEN
        RETURN;
    END IF;
    UPDATE clinica.citas SET estado = 'CANCELADA', actualizado_por = p_actor WHERE cita_id = p_cita_id;
END;
$$;

CREATE PROCEDURE pck_clinica.SP_registrar_atencion(
    p_atencion_id uuid, p_cita_id varchar, p_motivo text, p_actor uuid
) LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, clinica AS $$
DECLARE
    r_cita clinica.citas%ROWTYPE;
BEGIN
    PERFORM clinica.fn_exigir_rol(p_actor, ARRAY['ADMINISTRADOR','MEDICO']);
    SELECT * INTO r_cita FROM clinica.citas WHERE cita_id = p_cita_id FOR UPDATE;
    IF NOT FOUND OR r_cita.estado <> 'PROGRAMADA' THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'La cita debe estar programada para atenderla.';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM clinica.usuarios u JOIN clinica.roles r USING (rol_id)
        WHERE u.usuario_id = p_actor AND (
            r.nombre = 'ADMINISTRADOR' OR EXISTS (
                SELECT 1 FROM clinica.medicos m WHERE m.medico_id = r_cita.medico_id
                AND m.usuario_id = p_actor AND m.activo
            )
        )
    ) THEN
        RAISE EXCEPTION USING ERRCODE = 'P1003', MESSAGE = 'La cita corresponde a otro médico.';
    END IF;
    INSERT INTO clinica.atenciones (atencion_id, cita_id, motivo_consulta, registrado_por)
    VALUES (p_atencion_id, p_cita_id, p_motivo, p_actor);
    UPDATE clinica.citas SET estado = 'ATENDIDA', actualizado_por = p_actor WHERE cita_id = p_cita_id;
END;
$$;

CREATE FUNCTION pck_facturacion.fn_total_factura(p_factura_id uuid)
RETURNS numeric LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, clinica AS $$
    SELECT coalesce(sum(cantidad * precio_unitario), 0)
    FROM clinica.detalle_factura WHERE factura_id = p_factura_id;
$$;
CREATE FUNCTION pck_facturacion.fn_saldo_factura(p_factura_id uuid)
RETURNS numeric LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, clinica AS $$
    SELECT pck_facturacion.fn_total_factura(p_factura_id) - coalesce(
        (SELECT sum(monto) FROM clinica.pagos WHERE factura_id = p_factura_id), 0
    );
$$;

CREATE FUNCTION pck_facturacion.fn_proteger_detalle()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, clinica AS $$
DECLARE
    V_factura uuid;
    VV_estado varchar(10);
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.factura_id IS DISTINCT FROM OLD.factura_id THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'El detalle pertenece a otra factura.';
    END IF;
    V_factura := CASE WHEN TG_OP = 'DELETE' THEN OLD.factura_id ELSE NEW.factura_id END;
    SELECT estado INTO VV_estado FROM clinica.facturas WHERE factura_id = V_factura FOR UPDATE;
    IF NOT FOUND OR VV_estado <> 'BORRADOR' THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'Solo se modifica el detalle de una factura en borrador.';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER tr_detalle_borrador BEFORE INSERT OR UPDATE OR DELETE ON clinica.detalle_factura
FOR EACH ROW EXECUTE FUNCTION pck_facturacion.fn_proteger_detalle();

CREATE FUNCTION pck_facturacion.fn_validar_factura()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, clinica AS $$
BEGIN
    IF TG_OP = 'INSERT' AND NEW.estado <> 'BORRADOR' THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'La factura debe comenzar en borrador.';
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.estado = 'EMITIDA' THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'La factura ya fue emitida.';
    END IF;
    IF NEW.estado = 'EMITIDA' AND pck_facturacion.fn_total_factura(NEW.factura_id) <= 0 THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'La factura debe tener un total mayor que cero.';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER tr_factura_validar BEFORE INSERT OR UPDATE ON clinica.facturas
FOR EACH ROW EXECUTE FUNCTION pck_facturacion.fn_validar_factura();

CREATE PROCEDURE pck_facturacion.SP_emitir_factura(p_factura_id uuid, p_actor uuid)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, clinica AS $$
DECLARE
    VV_estado varchar(10);
BEGIN
    PERFORM clinica.fn_exigir_rol(p_actor, ARRAY['ADMINISTRADOR','FACTURACION']);
    SELECT estado INTO VV_estado FROM clinica.facturas WHERE factura_id = p_factura_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'La factura no existe.';
    END IF;
    IF VV_estado = 'EMITIDA' THEN RETURN; END IF;
    UPDATE clinica.facturas SET estado = 'EMITIDA' WHERE factura_id = p_factura_id;
END;
$$;

CREATE FUNCTION pck_facturacion.fn_validar_pago()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, clinica AS $$
DECLARE
    VV_estado varchar(10);
    V_saldo numeric;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'Un pago registrado conserva sus datos.';
    END IF;
    SELECT estado INTO VV_estado FROM clinica.facturas WHERE factura_id = NEW.factura_id FOR UPDATE;
    IF NOT FOUND OR VV_estado <> 'EMITIDA' THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'La factura debe estar emitida para recibir pagos.';
    END IF;
    V_saldo := pck_facturacion.fn_saldo_factura(NEW.factura_id);
    IF NEW.monto > V_saldo THEN
        RAISE EXCEPTION USING ERRCODE = 'P1005', MESSAGE = 'El pago supera el saldo de la factura.';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER tr_pago_validar BEFORE INSERT OR UPDATE OR DELETE ON clinica.pagos
FOR EACH ROW EXECUTE FUNCTION pck_facturacion.fn_validar_pago();

CREATE PROCEDURE pck_facturacion.SP_registrar_pago(
    p_factura_id uuid, p_monto numeric, p_medio varchar, p_referencia varchar,
    p_actor uuid, p_solicitud_id uuid, INOUT p_pago_id uuid
) LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, clinica AS $$
DECLARE
    r_pago clinica.pagos%ROWTYPE;
BEGIN
    PERFORM clinica.fn_exigir_rol(p_actor, ARRAY['ADMINISTRADOR','FACTURACION']);
    -- Serializa altas y reintentos para la misma factura.
    PERFORM 1 FROM clinica.facturas WHERE factura_id = p_factura_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'La factura no existe.';
    END IF;
    SELECT * INTO r_pago FROM clinica.pagos WHERE solicitud_id = p_solicitud_id;
    IF FOUND THEN
        IF r_pago.factura_id IS DISTINCT FROM p_factura_id OR r_pago.monto IS DISTINCT FROM p_monto
           OR r_pago.medio IS DISTINCT FROM p_medio OR r_pago.referencia IS DISTINCT FROM p_referencia
           OR r_pago.registrado_por IS DISTINCT FROM p_actor THEN
            RAISE EXCEPTION USING ERRCODE = 'P1004', MESSAGE = 'La solicitud ya existe con otros datos.';
        END IF;
        p_pago_id := r_pago.pago_id;
        RETURN;
    END IF;
    p_pago_id := coalesce(p_pago_id, gen_random_uuid());
    INSERT INTO clinica.pagos (pago_id, factura_id, monto, medio, referencia, registrado_por, solicitud_id)
    VALUES (p_pago_id, p_factura_id, p_monto, p_medio, p_referencia, p_actor, p_solicitud_id);
END;
$$;

CREATE OR REPLACE FUNCTION pck_agenda.fn_validar_fecha_cita()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, clinica AS $$
BEGIN
    IF TG_OP = 'INSERT' AND EXISTS (SELECT 1 FROM clinica.citas WHERE cita_id = NEW.cita_id) THEN
        RETURN NEW;
    END IF;
    IF NEW.estado = 'PROGRAMADA' AND (
        TG_OP = 'INSERT' OR NEW.inicio IS DISTINCT FROM OLD.inicio OR NEW.fin IS DISTINCT FROM OLD.fin
    ) THEN
        IF NEW.inicio < current_timestamp THEN
            RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'Selecciona una fecha y hora que aún no hayan pasado.';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM clinica.medicos WHERE medico_id = NEW.medico_id AND activo) THEN
            RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'Selecciona un médico activo.';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER tr_cita_fecha BEFORE INSERT OR UPDATE ON clinica.citas
FOR EACH ROW EXECUTE FUNCTION pck_agenda.fn_validar_fecha_cita();
