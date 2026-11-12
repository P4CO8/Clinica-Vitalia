-- Autor: Francisco Salom Zuluaga
-- Fecha de creación: 2025-01-15
-- Versión: 1.0
-- Descripción: Preparar roles de conexión y base de datos.
-- Ejecutar conectado a postgres, como postgres. Conserva las contraseñas existentes.
\set ON_ERROR_STOP on
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vitalia_app') THEN
        CREATE ROLE vitalia_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vitalia_lector') THEN
        CREATE ROLE vitalia_lector NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
END;
$$;
SELECT 'CREATE DATABASE clinica_vitalia OWNER postgres'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'clinica_vitalia')
\gexec
-- Para asignar o cambiar la contraseña de conexión, usar interactivamente
-- \password vitalia_app
-- El usuario de despliegue administra el esquema. vitalia_app ejecuta la aplicación.
