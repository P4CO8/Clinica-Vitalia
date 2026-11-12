# Diccionario de datos

## Esquema `clinica`

- `usuarios`: cuentas, credenciales, roles y datos de contratación.
- `pacientes`: identificación, datos personales y estado administrativo.
- `medicos`: profesionales vinculados a usuarios.
- `especialidades`: catálogo de especialidades médicas.
- `citas`: agenda, paciente, médico, horario y estado.
- `atenciones`: atención clínica asociada a una cita.
- `diagnosticos`, `tratamientos` y `medicamentos`: información clínica.
- `servicios`: catálogo de servicios y tarifas.
- `facturas` y `detalle_factura`: facturación con precios históricos.
- `pagos`: pagos inmutables asociados a facturas y solicitudes idempotentes.
- `solicitudes_cita`: comunicación interna Médico–Recepción.

Las claves primarias, foráneas, restricciones y tipos completos están definidos
en `db/postgres/01_modelo.sql` y sus migraciones.
