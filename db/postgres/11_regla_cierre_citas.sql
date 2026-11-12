\set ON_ERROR_STOP on
\if :{?VITALIA_INSTALL}
\else
BEGIN;
\endif
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM clinica.version_esquema WHERE version = '1.4') THEN
        RAISE EXCEPTION 'Aplica primero el esquema 1.4.';
    END IF;
END $$;

CREATE OR REPLACE PROCEDURE pck_agenda.SP_cerrar_vencidas(p_actor uuid)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, clinica AS $$
BEGIN
    PERFORM clinica.fn_exigir_rol(p_actor, ARRAY['ADMINISTRADOR','RECEPCION']);
    UPDATE clinica.citas
    SET estado = 'CANCELADA', cierre_automatico = false, actualizado_por = p_actor
    WHERE estado = 'PROGRAMADA' AND fin <= clock_timestamp();
END;
$$;

CREATE OR REPLACE FUNCTION clinica.fn_validar_cierre_cita()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.estado = 'CERRADA' AND OLD.estado <> 'EN_ATENCION' THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002',
            MESSAGE = 'Una cita que no fue atendida debe cancelarse o reprogramarse.';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validar_cierre_cita ON clinica.citas;
CREATE TRIGGER trg_validar_cierre_cita
BEFORE UPDATE OF estado ON clinica.citas
FOR EACH ROW EXECUTE FUNCTION clinica.fn_validar_cierre_cita();

INSERT INTO clinica.version_esquema(version) VALUES ('1.5') ON CONFLICT DO NOTHING;
\if :{?VITALIA_INSTALL}
\else
COMMIT;
\endif
