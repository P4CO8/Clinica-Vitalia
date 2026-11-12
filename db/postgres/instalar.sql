-- Autor: Francisco Salom Zuluaga
-- Fecha de creación: 2026-11-11
-- Versión: 1.3
-- Descripción: Instalación atómica del modelo y la agenda persistente en una base vacía.
\set ON_ERROR_STOP on
\set VITALIA_INSTALL on
BEGIN;
SET LOCAL TIME ZONE 'America/Bogota';
\ir 01_modelo.sql
\ir 02_logica.sql
\ir 03_catalogos.sql
\ir 04_reportes.sql
\ir 05_permisos.sql
INSERT INTO clinica.version_esquema(version) VALUES ('1.0'), ('1.1'), ('1.2');
\ir 09_agenda_persistente.sql
\ir 10_control_manual_citas.sql
\ir 11_regla_cierre_citas.sql
\ir 12_no_reabrir_citas.sql
\ir 13_categorias_especialidades.sql
\ir 14_datos_personal_usuarios.sql
\ir 15_solicitudes_cita.sql
COMMIT;
\unset VITALIA_INSTALL
