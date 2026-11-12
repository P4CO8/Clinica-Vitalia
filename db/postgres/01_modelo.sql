-- Autor: Francisco Salom Zuluaga
-- Fecha de creación: 2025-02-20
-- Versión: 1.2
-- Descripción: Modelo relacional y restricciones base de Clínica Vitalia.
-- Ejecutar con instalar.sql dentro de una base vacía y como administrador.
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE SCHEMA clinica;
CREATE SCHEMA pck_agenda;
CREATE SCHEMA pck_clinica;
CREATE SCHEMA pck_facturacion;
CREATE SCHEMA pck_auditoria;

CREATE TABLE clinica.version_esquema (
    version varchar(20) PRIMARY KEY,
    instalado_en timestamptz NOT NULL DEFAULT current_timestamp
);
CREATE TABLE clinica.roles (
    rol_id smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre varchar(30) NOT NULL UNIQUE,
    CONSTRAINT ck_roles_nombre CHECK (nombre IN ('ADMINISTRADOR','RECEPCION','MEDICO','FACTURACION'))
);
CREATE TABLE clinica.usuarios (
    usuario_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre_usuario varchar(50) NOT NULL,
    password_hash text NOT NULL CHECK (length(password_hash) > 20),
    rol_id smallint NOT NULL REFERENCES clinica.roles,
    nombres varchar(100) NOT NULL DEFAULT '',
    apellidos varchar(100) NOT NULL DEFAULT '',
    tipo_documento varchar(3) NOT NULL DEFAULT 'CC',
    numero_documento varchar(20) NOT NULL DEFAULT '',
    telefono varchar(15) NOT NULL DEFAULT '',
    formacion_academica text NOT NULL DEFAULT '',
    seguridad_social_salud_ocupacional text NOT NULL DEFAULT '',
    bioseguridad text NOT NULL DEFAULT '',
    antecedentes text NOT NULL DEFAULT '',
    datos_financieros_tributarios text NOT NULL DEFAULT '',
    activo boolean NOT NULL DEFAULT true,
    creado_en timestamptz NOT NULL DEFAULT current_timestamp,
    CONSTRAINT ck_usuario_nombre CHECK (nombre_usuario = btrim(nombre_usuario) AND length(nombre_usuario) >= 3)
);
CREATE UNIQUE INDEX ix_usuarios_nombre ON clinica.usuarios (lower(nombre_usuario));

CREATE TABLE clinica.pacientes (
    paciente_id varchar(40) PRIMARY KEY DEFAULT ('PAC-' || replace(gen_random_uuid()::text, '-', '')),
    nombres varchar(100) NOT NULL,
    apellidos varchar(100) NOT NULL,
    tipo_documento varchar(3) NOT NULL CHECK (tipo_documento IN ('CC','TI','CE','PAS')),
    numero_documento varchar(20) NOT NULL,
    fecha_nacimiento date NOT NULL,
    telefono varchar(15) NOT NULL DEFAULT '',
    grupo_sanguineo varchar(3) NOT NULL DEFAULT '',
    activo boolean NOT NULL DEFAULT true,
    creado_en timestamptz NOT NULL DEFAULT current_timestamp,
    CONSTRAINT ck_pacientes_nombres CHECK (nombres ~ '^[[:alpha:]]+([ ’''-][[:alpha:]]+)*$'),
    CONSTRAINT ck_pacientes_apellidos CHECK (apellidos ~ '^[[:alpha:]]+([ ’''-][[:alpha:]]+)*$'),
    CONSTRAINT ck_pacientes_documento CHECK (
        (tipo_documento = 'PAS' AND numero_documento ~ '^[A-Za-z0-9]{3,20}$')
        OR (tipo_documento <> 'PAS' AND numero_documento ~ '^[0-9]{3,20}$')
    ),
    CONSTRAINT ck_pacientes_telefono CHECK (telefono = '' OR telefono ~ '^[0-9]{7,15}$'),
    CONSTRAINT ck_pacientes_sangre CHECK (grupo_sanguineo IN ('','A+','A-','B+','B-','AB+','AB-','O+','O-'))
);
CREATE UNIQUE INDEX ix_pacientes_documento ON clinica.pacientes (tipo_documento, lower(numero_documento));

CREATE TABLE clinica.medicos (
    medico_id varchar(40) PRIMARY KEY DEFAULT ('MED-' || replace(gen_random_uuid()::text, '-', '')),
    nombre varchar(200) NOT NULL CHECK (btrim(nombre) <> ''),
    registro_profesional varchar(40) NOT NULL UNIQUE,
    usuario_id uuid UNIQUE REFERENCES clinica.usuarios,
    activo boolean NOT NULL DEFAULT true
);
CREATE TABLE clinica.especialidades (
    especialidad_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre varchar(100) NOT NULL UNIQUE,
    categoria varchar(50) NOT NULL DEFAULT 'Especialidades Clínicas (Médicas)'
);
CREATE TABLE clinica.medico_especialidad (
    medico_id varchar(40) REFERENCES clinica.medicos,
    especialidad_id integer REFERENCES clinica.especialidades,
    PRIMARY KEY (medico_id, especialidad_id)
);
CREATE TABLE clinica.historias_clinicas (
    historia_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    paciente_id varchar(40) NOT NULL UNIQUE REFERENCES clinica.pacientes,
    fecha_apertura timestamptz NOT NULL DEFAULT current_timestamp,
    antecedentes text NOT NULL DEFAULT ''
);
CREATE TABLE clinica.citas (
    cita_id varchar(40) PRIMARY KEY DEFAULT ('CIT-' || replace(gen_random_uuid()::text, '-', '')),
    paciente_id varchar(40) NOT NULL REFERENCES clinica.pacientes,
    medico_id varchar(40) NOT NULL REFERENCES clinica.medicos,
    inicio timestamptz NOT NULL,
    fin timestamptz NOT NULL,
    estado varchar(15) NOT NULL DEFAULT 'PROGRAMADA' CHECK (estado IN ('PROGRAMADA','CANCELADA','ATENDIDA')),
    creado_por uuid NOT NULL REFERENCES clinica.usuarios,
    actualizado_por uuid NOT NULL REFERENCES clinica.usuarios,
    creado_en timestamptz NOT NULL DEFAULT current_timestamp,
    CONSTRAINT ck_citas_intervalo CHECK (fin > inicio),
    CONSTRAINT ck_citas_fecha CHECK (
        (inicio AT TIME ZONE 'America/Bogota')::date = (fin AT TIME ZONE 'America/Bogota')::date
    ),
    CONSTRAINT ex_citas_medico EXCLUDE USING gist (
        medico_id WITH =, tstzrange(inicio, fin, '[)') WITH &&
    ) WHERE (estado IN ('PROGRAMADA','ATENDIDA'))
);
CREATE INDEX ix_citas_paciente ON clinica.citas (paciente_id, inicio);
CREATE INDEX ix_citas_inicio ON clinica.citas (inicio);

CREATE TABLE clinica.atenciones (
    atencion_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cita_id varchar(40) NOT NULL UNIQUE REFERENCES clinica.citas,
    motivo_consulta text NOT NULL CHECK (btrim(motivo_consulta) <> ''),
    registrado_por uuid NOT NULL REFERENCES clinica.usuarios,
    fecha_atencion timestamptz NOT NULL DEFAULT current_timestamp
);
-- La historia y el paciente de una atención se obtienen de su cita.
-- Evita guardar de nuevo paciente_id, medico_id e historia_id en atenciones.
CREATE TABLE clinica.diagnosticos (
    diagnostico_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    atencion_id uuid NOT NULL REFERENCES clinica.atenciones,
    codigo varchar(20),
    descripcion text NOT NULL CHECK (btrim(descripcion) <> '')
);
CREATE TABLE clinica.tratamientos (
    tratamiento_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    atencion_id uuid NOT NULL REFERENCES clinica.atenciones,
    descripcion text NOT NULL CHECK (btrim(descripcion) <> ''),
    fecha_inicio date NOT NULL,
    fecha_fin date,
    CHECK (fecha_fin IS NULL OR fecha_fin >= fecha_inicio)
);
CREATE TABLE clinica.medicamentos (
    medicamento_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre varchar(150) NOT NULL,
    presentacion varchar(100) NOT NULL,
    UNIQUE (nombre, presentacion)
);
CREATE TABLE clinica.tratamiento_medicamento (
    tratamiento_id uuid REFERENCES clinica.tratamientos,
    medicamento_id integer REFERENCES clinica.medicamentos,
    dosis varchar(100) NOT NULL,
    frecuencia varchar(100) NOT NULL,
    duracion varchar(100) NOT NULL,
    PRIMARY KEY (tratamiento_id, medicamento_id)
);
CREATE TABLE clinica.servicios (
    servicio_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre varchar(150) NOT NULL UNIQUE,
    tarifa numeric(12,2) NOT NULL CHECK (tarifa >= 0)
);
CREATE TABLE clinica.facturas (
    factura_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    paciente_id varchar(40) NOT NULL REFERENCES clinica.pacientes,
    estado varchar(10) NOT NULL DEFAULT 'BORRADOR' CHECK (estado IN ('BORRADOR','EMITIDA')),
    creado_por uuid NOT NULL REFERENCES clinica.usuarios,
    fecha_emision timestamptz NOT NULL DEFAULT current_timestamp
);
CREATE TABLE clinica.detalle_factura (
    detalle_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    factura_id uuid NOT NULL REFERENCES clinica.facturas,
    servicio_id integer NOT NULL REFERENCES clinica.servicios,
    descripcion varchar(200) NOT NULL CHECK (btrim(descripcion) <> ''),
    cantidad integer NOT NULL CHECK (cantidad > 0),
    precio_unitario numeric(12,2) NOT NULL CHECK (precio_unitario >= 0)
);
CREATE INDEX ix_detalle_factura ON clinica.detalle_factura (factura_id);
CREATE TABLE clinica.pagos (
    pago_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    factura_id uuid NOT NULL REFERENCES clinica.facturas,
    monto numeric(12,2) NOT NULL CHECK (monto > 0),
    medio varchar(20) NOT NULL CHECK (medio IN ('EFECTIVO','TRANSFERENCIA','TARJETA')),
    referencia varchar(100) NOT NULL DEFAULT '',
    registrado_por uuid NOT NULL REFERENCES clinica.usuarios,
    fecha_pago timestamptz NOT NULL DEFAULT current_timestamp,
    solicitud_id uuid NOT NULL UNIQUE
);
CREATE INDEX ix_pagos_factura ON clinica.pagos (factura_id);
CREATE TABLE clinica.auditoria_citas (
    evento_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cita_id varchar(40) NOT NULL REFERENCES clinica.citas,
    actor_id uuid NOT NULL REFERENCES clinica.usuarios,
    accion varchar(20) NOT NULL,
    fecha timestamptz NOT NULL DEFAULT current_timestamp,
    estado_anterior varchar(15),
    estado_nuevo varchar(15) NOT NULL,
    inicio_anterior timestamptz,
    inicio_nuevo timestamptz NOT NULL,
    fin_anterior timestamptz,
    fin_nuevo timestamptz NOT NULL
);
CREATE INDEX ix_auditoria_cita_fecha ON clinica.auditoria_citas (cita_id, fecha);
CREATE INDEX ix_diagnosticos_atencion ON clinica.diagnosticos (atencion_id);
CREATE INDEX ix_tratamientos_atencion ON clinica.tratamientos (atencion_id);
CREATE INDEX ix_facturas_paciente ON clinica.facturas (paciente_id, fecha_emision);
