-- Autor: Francisco Salom Zuluaga
-- Fecha de creación: 2025-10-06
-- Versión: 1.2
-- Descripción: Migrar estado administrativo y validar pacientes activos.
\set ON_ERROR_STOP on
BEGIN;
ALTER TABLE clinica.pacientes ADD COLUMN IF NOT EXISTS activo boolean;
UPDATE clinica.pacientes SET activo = true WHERE activo IS NULL;
ALTER TABLE clinica.pacientes ALTER COLUMN activo SET DEFAULT true;
ALTER TABLE clinica.pacientes ALTER COLUMN activo SET NOT NULL;

CREATE OR REPLACE FUNCTION pck_agenda.fn_validar_fecha_cita()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, clinica AS $$
BEGIN
    IF TG_OP = 'INSERT' AND EXISTS (SELECT 1 FROM clinica.citas WHERE cita_id = NEW.cita_id) THEN
        RETURN NEW;
    END IF;
    IF NEW.estado = 'PROGRAMADA' AND (
        TG_OP = 'INSERT' OR NEW.inicio IS DISTINCT FROM OLD.inicio OR NEW.fin IS DISTINCT FROM OLD.fin
    ) THEN
        IF NOT EXISTS (
            SELECT 1 FROM clinica.pacientes
            WHERE paciente_id = NEW.paciente_id AND activo
        ) THEN
            RAISE EXCEPTION USING ERRCODE = 'P1002', MESSAGE = 'Selecciona un paciente activo.';
        END IF;
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
DROP TRIGGER IF EXISTS tr_cita_fecha ON clinica.citas;
CREATE TRIGGER tr_cita_fecha BEFORE INSERT OR UPDATE ON clinica.citas
FOR EACH ROW EXECUTE FUNCTION pck_agenda.fn_validar_fecha_cita();
REVOKE EXECUTE ON FUNCTION pck_agenda.fn_validar_fecha_cita() FROM PUBLIC;
INSERT INTO clinica.version_esquema(version) VALUES ('1.2') ON CONFLICT DO NOTHING;
COMMIT;
