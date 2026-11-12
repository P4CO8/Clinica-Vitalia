-- Autor: Francisco Salom Zuluaga
-- Fecha de creación: 2025-09-14
-- Versión: 1.1
-- Descripción: Migrar validaciones de identidad y fechas.
-- Ejecutar como postgres sobre clinica_vitalia, con versión 1.0 ya instalada.
\set ON_ERROR_STOP on
BEGIN;
ALTER TABLE clinica.pacientes DROP CONSTRAINT ck_pacientes_nombres;
ALTER TABLE clinica.pacientes ADD CONSTRAINT ck_pacientes_nombres
    CHECK (nombres ~ '^[[:alpha:]]+([ ’''-][[:alpha:]]+)*$');
ALTER TABLE clinica.pacientes DROP CONSTRAINT ck_pacientes_apellidos;
ALTER TABLE clinica.pacientes ADD CONSTRAINT ck_pacientes_apellidos
    CHECK (apellidos ~ '^[[:alpha:]]+([ ’''-][[:alpha:]]+)*$');
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
DROP TRIGGER IF EXISTS tr_cita_fecha ON clinica.citas;
CREATE TRIGGER tr_cita_fecha BEFORE INSERT OR UPDATE ON clinica.citas
FOR EACH ROW EXECUTE FUNCTION pck_agenda.fn_validar_fecha_cita();
REVOKE EXECUTE ON FUNCTION pck_agenda.fn_validar_fecha_cita() FROM PUBLIC;
INSERT INTO clinica.version_esquema(version) VALUES ('1.1') ON CONFLICT DO NOTHING;
COMMIT;
