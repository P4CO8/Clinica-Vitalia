ALTER TABLE clinica.usuarios
    ADD COLUMN IF NOT EXISTS nombres varchar(100) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS apellidos varchar(100) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS tipo_documento varchar(3) NOT NULL DEFAULT 'CC',
    ADD COLUMN IF NOT EXISTS numero_documento varchar(20) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS telefono varchar(15) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS formacion_academica text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS seguridad_social_salud_ocupacional text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS bioseguridad text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS antecedentes text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS datos_financieros_tributarios text NOT NULL DEFAULT '';

CREATE OR REPLACE FUNCTION clinica.fn_proteger_ultimo_administrador()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    administrador_activo boolean;
    administradores_activos integer;
BEGIN
    SELECT r.nombre = 'ADMINISTRADOR' AND OLD.activo
    INTO administrador_activo
    FROM clinica.roles r
    WHERE r.rol_id = OLD.rol_id;

    IF administrador_activo AND (
        TG_OP = 'DELETE' OR (TG_OP = 'UPDATE' AND NOT NEW.activo)
    ) THEN
        SELECT count(*) INTO administradores_activos
        FROM clinica.usuarios u
        JOIN clinica.roles r ON r.rol_id = u.rol_id
        WHERE r.nombre = 'ADMINISTRADOR' AND u.activo;

        IF administradores_activos <= 1 THEN
            RAISE EXCEPTION
                'No se puede eliminar o desactivar al último administrador activo';
        END IF;
    END IF;

    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

DROP TRIGGER IF EXISTS trg_proteger_ultimo_administrador ON clinica.usuarios;
CREATE TRIGGER trg_proteger_ultimo_administrador
BEFORE UPDATE OF activo OR DELETE ON clinica.usuarios
FOR EACH ROW EXECUTE FUNCTION clinica.fn_proteger_ultimo_administrador();

INSERT INTO clinica.version_esquema(version) VALUES ('1.8')
ON CONFLICT (version) DO NOTHING;
