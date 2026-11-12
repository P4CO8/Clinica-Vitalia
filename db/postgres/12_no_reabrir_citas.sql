\set ON_ERROR_STOP on
\if :{?VITALIA_INSTALL}
\else
BEGIN;
\endif
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM clinica.version_esquema WHERE version = '1.5') THEN
        RAISE EXCEPTION 'Aplica primero el esquema 1.5.';
    END IF;
END $$;

CREATE OR REPLACE FUNCTION clinica.fn_validar_cierre_cita()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.estado = 'PROGRAMADA' AND OLD.estado <> 'PROGRAMADA' THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002',
            MESSAGE = 'Una cita cancelada debe conservarse como historial y agendarse nuevamente.';
    END IF;
    IF NEW.estado = 'CERRADA' AND OLD.estado <> 'EN_ATENCION' THEN
        RAISE EXCEPTION USING ERRCODE = 'P1002',
            MESSAGE = 'Una cita que no fue atendida debe cancelarse o reprogramarse.';
    END IF;
    RETURN NEW;
END;
$$;

INSERT INTO clinica.version_esquema(version) VALUES ('1.6') ON CONFLICT DO NOTHING;
\if :{?VITALIA_INSTALL}
\else
COMMIT;
\endif
