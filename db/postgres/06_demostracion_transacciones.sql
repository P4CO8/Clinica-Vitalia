-- Autor: Francisco Salom Zuluaga
-- Fecha de creación: 2025-08-22
-- Versión: 1.0
-- Descripción: Demostrar commit, rollback y manejo de excepciones.
\set ON_ERROR_STOP on
BEGIN;
INSERT INTO clinica.pacientes (
    paciente_id, nombres, apellidos, tipo_documento, numero_documento, fecha_nacimiento
) VALUES ('PAC-TRANSACCION', 'Paciente', 'Transacción', 'PAS', 'TXDEMO001', '1990-01-01')
ON CONFLICT DO NOTHING;
COMMIT;
SELECT paciente_id FROM clinica.pacientes WHERE paciente_id = 'PAC-TRANSACCION';
-- Devuelve una fila tras el COMMIT.

BEGIN;
UPDATE clinica.pacientes SET telefono = '3001234567' WHERE paciente_id = 'PAC-TRANSACCION';
ROLLBACK;
SELECT telefono = '' AS rollback_correcto FROM clinica.pacientes WHERE paciente_id = 'PAC-TRANSACCION';

-- El bloque captura una excepción y comprueba que su escritura anterior se revirtió.
DO $$
BEGIN
    BEGIN
        UPDATE clinica.pacientes SET telefono = '3007654321' WHERE paciente_id = 'PAC-TRANSACCION';
        RAISE EXCEPTION USING ERRCODE = 'P1099', MESSAGE = 'Error provocado para demostrar atomicidad.';
    EXCEPTION WHEN SQLSTATE 'P1099' THEN
        IF (SELECT telefono FROM clinica.pacientes WHERE paciente_id = 'PAC-TRANSACCION') <> '' THEN
            RAISE EXCEPTION 'Falló la prueba de rollback';
        END IF;
    END;
    RAISE NOTICE 'Excepción controlada y escritura revertida';
END;
$$;
