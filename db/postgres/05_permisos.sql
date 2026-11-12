-- Autor: Francisco Salom Zuluaga
-- Fecha de creación: 2025-07-18
-- Versión: 1.0
-- Descripción: Permisos de conexión, objetos y rutinas.
DO $$
BEGIN
    EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO vitalia_app, vitalia_lector', current_database());
END;
$$;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA clinica, pck_agenda, pck_clinica, pck_facturacion, pck_auditoria FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA clinica, pck_agenda, pck_clinica, pck_facturacion, pck_auditoria FROM PUBLIC;
REVOKE EXECUTE ON ALL PROCEDURES IN SCHEMA pck_agenda, pck_clinica, pck_facturacion FROM PUBLIC;
GRANT USAGE ON SCHEMA clinica, pck_agenda, pck_clinica, pck_facturacion TO vitalia_app;
GRANT SELECT ON ALL TABLES IN SCHEMA clinica TO vitalia_app;
GRANT INSERT, UPDATE ON clinica.pacientes, clinica.usuarios, clinica.medicos,
    clinica.especialidades, clinica.medico_especialidad, clinica.diagnosticos,
    clinica.tratamientos, clinica.medicamentos, clinica.tratamiento_medicamento,
    clinica.servicios, clinica.facturas, clinica.detalle_factura TO vitalia_app;
GRANT UPDATE (antecedentes) ON clinica.historias_clinicas TO vitalia_app;
GRANT DELETE ON clinica.detalle_factura, clinica.medico_especialidad,
    clinica.tratamiento_medicamento TO vitalia_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA clinica TO vitalia_app;
GRANT EXECUTE ON ALL PROCEDURES IN SCHEMA pck_agenda, pck_clinica, pck_facturacion TO vitalia_app;
GRANT EXECUTE ON FUNCTION pck_facturacion.fn_total_factura(uuid),
    pck_facturacion.fn_saldo_factura(uuid), clinica.fn_citas_periodo(timestamptz,timestamptz),
    clinica.fn_ingresos_periodo(timestamptz,timestamptz),
    clinica.fn_cartera_paciente(varchar) TO vitalia_app;
GRANT USAGE ON SCHEMA clinica, pck_facturacion TO vitalia_lector;
GRANT SELECT ON clinica.v_cartera, clinica.v_facturas_pendientes TO vitalia_lector;
-- El backend aplica los permisos por usuario, rol y recurso antes de cada operación.
-- Agenda, atención, pagos y auditoría se escriben mediante rutinas y triggers.

GRANT EXECUTE ON FUNCTION pck_facturacion.fn_total_factura(uuid),
    pck_facturacion.fn_saldo_factura(uuid) TO vitalia_lector;
