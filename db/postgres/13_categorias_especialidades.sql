ALTER TABLE clinica.especialidades
    ADD COLUMN IF NOT EXISTS categoria varchar(50);

UPDATE clinica.especialidades
SET categoria = 'Especialidades Clínicas (Médicas)'
WHERE categoria IS NULL OR btrim(categoria) = '';

ALTER TABLE clinica.especialidades
    ALTER COLUMN categoria SET DEFAULT 'Especialidades Clínicas (Médicas)',
    ALTER COLUMN categoria SET NOT NULL;

ALTER TABLE clinica.especialidades
    DROP CONSTRAINT IF EXISTS ck_especialidades_categoria;

ALTER TABLE clinica.especialidades
    ADD CONSTRAINT ck_especialidades_categoria CHECK (
        categoria IN (
            'Especialidades Clínicas (Médicas)',
            'Especialidades Quirúrgicas',
            'Medicina Crítica y Diagnóstica'
        )
    );

INSERT INTO clinica.version_esquema(version) VALUES ('1.7')
ON CONFLICT (version) DO NOTHING;
