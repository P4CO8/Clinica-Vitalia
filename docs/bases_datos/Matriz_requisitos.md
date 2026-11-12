# Matriz de requisitos

| Requisito | Implementación |
| --- | --- |
| Autenticación y autorización | Flask, sesiones y roles SQL |
| Gestión de pacientes | `app/routes.py` y repositorios PostgreSQL |
| Agenda | `app/agenda.py` y paquete `pck_agenda` |
| Atención clínica | `app/clinical.py` y paquete `pck_clinica` |
| Comunicación interna | `app/messages.py` y `solicitudes_cita` |
| Facturación y pagos | `app/billing.py` y paquete `pck_facturacion` |
| Integridad | Restricciones, triggers y procedimientos |
| Persistencia documental | Scripts de `db/mongo` |
| Pruebas | Archivos de `tests/` |
