# Modelo y decisiones

El sistema usa PostgreSQL para datos transaccionales: usuarios, pacientes,
citas, atención clínica, facturas y pagos. Las operaciones sensibles se
implementan con procedimientos, triggers y transacciones.

MongoDB se reserva para evoluciones clínicas documentales y conserva referencias
a los identificadores relacionales. Los roles de aplicación limitan el acceso
por módulo y las operaciones financieras usan `NUMERIC` en PostgreSQL y
`Decimal` en Python.
