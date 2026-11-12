-- Autor: Francisco Salom Zuluaga
-- Fecha de creación: 2025-05-05
-- Versión: 1.0
-- Descripción: Insertar roles y catálogos iniciales.
INSERT INTO clinica.roles (nombre) VALUES
    ('ADMINISTRADOR'), ('RECEPCION'), ('MEDICO'), ('FACTURACION')
ON CONFLICT (nombre) DO NOTHING;
INSERT INTO clinica.especialidades (nombre) VALUES ('Medicina general'), ('Medicina interna')
ON CONFLICT (nombre) DO NOTHING;
INSERT INTO clinica.medicos (medico_id, nombre, registro_profesional) VALUES
    ('MED-001', 'Dra. Valentina Gómez', 'PRUEBA-MED-001'),
    ('MED-002', 'Dr. Santiago Rojas', 'PRUEBA-MED-002')
ON CONFLICT (medico_id) DO NOTHING;
INSERT INTO clinica.medico_especialidad (medico_id, especialidad_id)
SELECT m.medico_id, e.especialidad_id FROM clinica.medicos m
CROSS JOIN clinica.especialidades e
WHERE e.nombre = 'Medicina general' AND m.medico_id IN ('MED-001','MED-002')
ON CONFLICT DO NOTHING;
INSERT INTO clinica.medicamentos (nombre, presentacion) VALUES
    ('Medicamento de prueba', 'Presentación de prueba')
ON CONFLICT DO NOTHING;
INSERT INTO clinica.servicios (nombre, tarifa) VALUES
    ('Consulta general', 80000.00), ('Control médico', 50000.00)
ON CONFLICT DO NOTHING;
