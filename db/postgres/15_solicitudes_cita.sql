CREATE TABLE IF NOT EXISTS clinica.solicitudes_cita (
    solicitud_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cita_id varchar(40) NOT NULL REFERENCES clinica.citas,
    solicitado_por uuid NOT NULL REFERENCES clinica.usuarios,
    tipo varchar(20) NOT NULL CHECK (tipo IN ('CANCELAR_CITA','NOTA')),
    mensaje text NOT NULL CHECK (btrim(mensaje) <> ''),
    estado varchar(12) NOT NULL DEFAULT 'PENDIENTE' CHECK (estado IN ('PENDIENTE','RESUELTO')),
    resuelto_por uuid REFERENCES clinica.usuarios,
    creado_en timestamptz NOT NULL DEFAULT current_timestamp,
    resuelto_en timestamptz
);
CREATE INDEX IF NOT EXISTS ix_solicitudes_cita_estado ON clinica.solicitudes_cita (estado, creado_en);
GRANT INSERT, UPDATE, SELECT ON clinica.solicitudes_cita TO vitalia_app;
INSERT INTO clinica.version_esquema(version) VALUES ('1.9')
ON CONFLICT (version) DO NOTHING;
