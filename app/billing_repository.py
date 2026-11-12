from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4


class PostgresBillingRepository:
    def __init__(self, database):
        self.database = database

    def patients(self):
        with self.database.connect() as connection:
            return connection.execute(
                """SELECT paciente_id, nombres, apellidos
                FROM clinica.pacientes WHERE activo ORDER BY apellidos, nombres"""
            ).fetchall()

    def services(self):
        with self.database.connect() as connection:
            return connection.execute(
                "SELECT servicio_id, nombre, tarifa FROM clinica.servicios ORDER BY nombre"
            ).fetchall()

    def invoices(self):
        with self.database.connect() as connection:
            return connection.execute(
                """SELECT f.factura_id, f.estado, f.fecha_emision,
                    p.nombres || ' ' || p.apellidos AS paciente,
                    pck_facturacion.fn_total_factura(f.factura_id) AS total,
                    pck_facturacion.fn_saldo_factura(f.factura_id) AS saldo
                FROM clinica.facturas f
                JOIN clinica.pacientes p ON p.paciente_id=f.paciente_id
                ORDER BY f.fecha_emision DESC"""
            ).fetchall()

    def create_invoice(self, user_id, patient_id, service_id, quantity):
        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            raise ValueError("La cantidad debe ser un número entero positivo.") from None
        if quantity <= 0:
            raise ValueError("La cantidad debe ser un número entero positivo.")
        with self.database.connect() as connection:
            service = connection.execute(
                "SELECT servicio_id, nombre, tarifa FROM clinica.servicios WHERE servicio_id=%s",
                (service_id,),
            ).fetchone()
            if service is None:
                raise ValueError("El servicio seleccionado no existe.")
            invoice = connection.execute(
                """INSERT INTO clinica.facturas(paciente_id, creado_por)
                VALUES (%s,%s) RETURNING factura_id""",
                (patient_id, user_id),
            ).fetchone()
            connection.execute(
                """INSERT INTO clinica.detalle_factura(
                    factura_id, servicio_id, descripcion, cantidad, precio_unitario
                ) VALUES (%s,%s,%s,%s,%s)""",
                (invoice["factura_id"], service["servicio_id"], service["nombre"],
                 quantity, service["tarifa"]),
            )
            return invoice["factura_id"]

    def issue_invoice(self, invoice_id, user_id):
        with self.database.connect() as connection:
            connection.execute(
                "CALL pck_facturacion.SP_emitir_factura(%s,%s)",
                (invoice_id, user_id),
            )

    def register_payment(self, invoice_id, amount, method, reference, user_id, request_id):
        try:
            request_id = UUID(str(request_id))
        except (ValueError, AttributeError, TypeError):
            raise ValueError("La solicitud de pago no es válida. Recarga la factura.") from None
        try:
            amount = Decimal(str(amount))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("El monto debe ser un número válido.") from None
        if amount <= 0 or amount.as_tuple().exponent < -2:
            raise ValueError("El monto debe ser positivo y tener máximo dos decimales.")
        if method not in {"EFECTIVO", "TRANSFERENCIA", "TARJETA"}:
            raise ValueError("Selecciona un medio de pago válido.")
        with self.database.connect() as connection:
            payment_id = uuid4()
            connection.execute(
                """CALL pck_facturacion.SP_registrar_pago(
                    %s,%s,%s,%s,%s,%s,%s
                )""",
                (invoice_id, amount, method, reference[:100], user_id, request_id, payment_id),
            )
