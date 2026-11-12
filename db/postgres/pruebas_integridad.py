import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import psycopg

TEST_URL = os.environ.get("VITALIA_TEST_URL", "")


class IntegridadPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not TEST_URL:
            raise unittest.SkipTest("Define VITALIA_TEST_URL para una base terminada en _pruebas.")
        with psycopg.connect(TEST_URL) as connection:
            name = connection.execute("SELECT current_database()").fetchone()[0]
            if not name.endswith("_pruebas"):
                raise RuntimeError("Usa una base exclusiva terminada en _pruebas.")
            cls.version = connection.execute("SELECT version()").fetchone()[0]
        print(cls.version)

    def setUp(self):
        self.connection = psycopg.connect(TEST_URL)
        self.patient = "PAC-" + uuid4().hex
        self.doctor = "MED-" + uuid4().hex
        self.other_doctor = "MED-" + uuid4().hex
        self.actor = uuid4()
        self.doctor_actor = uuid4()
        self.cashier = uuid4()
        for actor, role in (
            (self.actor, "RECEPCION"),
            (self.doctor_actor, "MEDICO"),
            (self.cashier, "FACTURACION"),
        ):
            self.connection.execute(
                """INSERT INTO clinica.usuarios (usuario_id,nombre_usuario,password_hash,rol_id)
                SELECT %s,%s,%s,rol_id FROM clinica.roles WHERE nombre=%s""",
                (actor, "prueba_" + uuid4().hex, "HASH_EXCLUSIVO_PARA_PRUEBAS_SQL", role),
            )
        self.document = str(uuid4().int)[:18]
        self.connection.execute(
            """INSERT INTO clinica.pacientes
            (paciente_id,nombres,apellidos,tipo_documento,numero_documento,fecha_nacimiento)
            VALUES (%s,'Laura','Méndez','CC',%s,'1990-05-10')""",
            (self.patient, self.document),
        )
        for doctor, actor in ((self.doctor, self.doctor_actor), (self.other_doctor, None)):
            self.connection.execute(
                """INSERT INTO clinica.medicos (medico_id,nombre,registro_profesional,usuario_id)
                VALUES (%s,'Profesional de prueba',%s,%s)""",
                (doctor, uuid4().hex, actor),
            )
        self.start = datetime(2030, 1, 10, 14, tzinfo=timezone.utc)
        self.connection.commit()

    def tearDown(self):
        self.connection.rollback()
        self.connection.close()

    def call_appointment(self, connection, code=None, doctor=None, start=None, end=None, actor=None):
        code = code or "CIT-" + uuid4().hex
        connection.execute(
            "CALL pck_agenda.SP_agendar_cita(%s,%s,%s,%s,%s,%s)",
            (code, self.patient, doctor or self.doctor, start or self.start,
             end or (self.start + timedelta(minutes=30)), actor or self.actor),
        )
        return code

    def expect_state(self, state, operation):
        with self.assertRaises(psycopg.Error) as error:
            with self.connection.transaction():
                operation()
        self.assertEqual(error.exception.sqlstate, state)

    def make_invoice(self):
        invoice = uuid4()
        self.connection.execute(
            "INSERT INTO clinica.facturas (factura_id,paciente_id,creado_por) VALUES (%s,%s,%s)",
            (invoice, self.patient, self.cashier),
        )
        self.connection.execute(
            """INSERT INTO clinica.detalle_factura
            (factura_id,servicio_id,descripcion,cantidad,precio_unitario)
            SELECT %s,servicio_id,'Consulta',1,100000 FROM clinica.servicios LIMIT 1""",
            (invoice,),
        )
        self.connection.execute("CALL pck_facturacion.SP_emitir_factura(%s,%s)", (invoice, self.cashier))
        return invoice

    def pay(self, connection, invoice, amount, request=None):
        return connection.execute(
            "CALL pck_facturacion.SP_registrar_pago(%s,%s,'EFECTIVO','',%s,%s,NULL)",
            (invoice, amount, self.cashier, request or uuid4()),
        ).fetchone()[0]

    def test_01_historia_unica_y_relaciones(self):
        count = self.connection.execute(
            "SELECT count(*) FROM clinica.historias_clinicas WHERE paciente_id=%s", (self.patient,)
        ).fetchone()[0]
        self.assertEqual(count, 1)
        self.expect_state("23505", lambda: self.connection.execute(
            "INSERT INTO clinica.historias_clinicas (paciente_id) VALUES (%s)", (self.patient,)
        ))

    def test_02_documentos_y_homonimos(self):
        self.connection.execute(
            """INSERT INTO clinica.pacientes (nombres,apellidos,tipo_documento,numero_documento,fecha_nacimiento)
            VALUES ('Laura','Méndez','CE',%s,'1990-05-10')""", (self.document,)
        )
        self.connection.execute(
            """INSERT INTO clinica.pacientes (nombres,apellidos,tipo_documento,numero_documento,fecha_nacimiento)
            VALUES ('Carlos','Ríos','PAS',%s,'1990-05-10')""", ("AB" + self.document,)
        )
        self.expect_state("23505", lambda: self.connection.execute(
            """INSERT INTO clinica.pacientes (nombres,apellidos,tipo_documento,numero_documento,fecha_nacimiento)
            VALUES ('Otra','Persona','CC',%s,'1990-05-10')""", (self.document,)
        ))

    def test_03_nacimiento_futuro(self):
        self.expect_state("P1002", lambda: self.connection.execute(
            "UPDATE clinica.pacientes SET fecha_nacimiento='2999-01-01' WHERE paciente_id=%s", (self.patient,)
        ))

    def test_04_cruces_contiguas_otro_medico(self):
        self.call_appointment(self.connection)
        self.call_appointment(self.connection, start=self.start + timedelta(minutes=30),
                              end=self.start + timedelta(minutes=60))
        self.call_appointment(self.connection, doctor=self.other_doctor)
        self.expect_state("P1001", lambda: self.call_appointment(
            self.connection, start=self.start + timedelta(minutes=10), end=self.start + timedelta(minutes=20)
        ))

    def test_05_cancelacion_libera_horario(self):
        code = self.call_appointment(self.connection)
        self.connection.execute("CALL pck_agenda.SP_cancelar_cita(%s,%s)", (code, self.actor))
        self.call_appointment(self.connection)
        self.assertEqual(self.connection.execute(
            "SELECT estado FROM clinica.citas WHERE cita_id=%s", (code,)
        ).fetchone()[0], "CANCELADA")

    def test_06_reprogramar_conflicto_conserva_original(self):
        code = self.call_appointment(self.connection)
        self.call_appointment(self.connection, start=self.start + timedelta(hours=1),
                              end=self.start + timedelta(hours=2))
        self.expect_state("P1001", lambda: self.connection.execute(
            "CALL pck_agenda.SP_reprogramar_cita(%s,%s,%s,%s)",
            (code, self.start + timedelta(hours=1), self.start + timedelta(hours=2), self.actor),
        ))
        self.assertEqual(self.connection.execute(
            "SELECT inicio FROM clinica.citas WHERE cita_id=%s", (code,)
        ).fetchone()[0], self.start)

    def test_07_permisos_actor(self):
        self.expect_state("P1003", lambda: self.call_appointment(self.connection, actor=self.doctor_actor))

    def test_08_atencion_y_auditoria(self):
        code = self.call_appointment(self.connection)
        self.connection.execute(
            "CALL pck_clinica.SP_registrar_atencion(%s,%s,%s,%s)",
            (uuid4(), code, "Control", self.doctor_actor),
        )
        self.assertEqual(self.connection.execute(
            "SELECT estado FROM clinica.citas WHERE cita_id=%s", (code,)
        ).fetchone()[0], "ATENDIDA")
        self.assertEqual(self.connection.execute(
            "SELECT count(*) FROM clinica.auditoria_citas WHERE cita_id=%s", (code,)
        ).fetchone()[0], 2)
        self.expect_state("P1002", lambda: self.connection.execute(
            "CALL pck_agenda.SP_cancelar_cita(%s,%s)", (code, self.actor)
        ))

    def test_09_rollback_cita_y_auditoria(self):
        code = self.call_appointment(self.connection)
        self.connection.rollback()
        for table in ("citas", "auditoria_citas"):
            self.assertEqual(self.connection.execute(
                f"SELECT count(*) FROM clinica.{table} WHERE cita_id=%s", (code,)
            ).fetchone()[0], 0)

    def test_10_saldo_pago_y_sobrepago(self):
        invoice = self.make_invoice()
        self.pay(self.connection, invoice, Decimal("30000"))
        self.assertEqual(self.connection.execute(
            "SELECT pck_facturacion.fn_saldo_factura(%s)", (invoice,)
        ).fetchone()[0], Decimal("70000"))
        self.expect_state("P1005", lambda: self.pay(self.connection, invoice, Decimal("70001")))

    def test_11_reintento_pago(self):
        invoice = self.make_invoice()
        request = uuid4()
        first = self.pay(self.connection, invoice, Decimal("30000"), request)
        second = self.pay(self.connection, invoice, Decimal("30000"), request)
        self.assertEqual(first, second)
        self.expect_state("P1004", lambda: self.pay(self.connection, invoice, Decimal("30001"), request))

    def test_12_detalle_emitido_bloqueado(self):
        invoice = self.make_invoice()
        self.expect_state("P1002", lambda: self.connection.execute(
            "UPDATE clinica.detalle_factura SET precio_unitario=1 WHERE factura_id=%s", (invoice,)
        ))

    def test_13_permisos_conexion_flask(self):
        self.connection.execute("SET LOCAL ROLE vitalia_app")
        self.connection.execute(
            "UPDATE clinica.pacientes SET telefono='3001234567' WHERE paciente_id=%s", (self.patient,)
        )
        self.call_appointment(self.connection)
        self.expect_state("42501", lambda: self.connection.execute("DELETE FROM clinica.auditoria_citas"))

    def test_14_concurrencia_citas(self):
        barrier = Barrier(2)
        def submit():
            with psycopg.connect(TEST_URL) as connection:
                barrier.wait(timeout=10)
                try:
                    self.call_appointment(connection)
                    connection.commit()
                    return "OK"
                except psycopg.Error as error:
                    connection.rollback()
                    return error.sqlstate
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: submit(), range(2)))
        self.assertCountEqual(results, ["OK", "P1001"])

    def test_15_concurrencia_pagos(self):
        invoice = self.make_invoice()
        self.connection.commit()
        barrier = Barrier(2)
        def submit():
            with psycopg.connect(TEST_URL) as connection:
                barrier.wait(timeout=10)
                try:
                    self.pay(connection, invoice, Decimal("70000"))
                    connection.commit()
                    return "OK"
                except psycopg.Error as error:
                    connection.rollback()
                    return error.sqlstate
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: submit(), range(2)))
        self.assertCountEqual(results, ["OK", "P1005"])
        self.assertEqual(self.connection.execute(
            "SELECT pck_facturacion.fn_saldo_factura(%s)", (invoice,)
        ).fetchone()[0], Decimal("30000"))

    def test_16_persistencia_commit_y_reportes(self):
        invoice = self.make_invoice()
        self.pay(self.connection, invoice, Decimal("30000"))
        code = self.call_appointment(self.connection)
        self.connection.commit()
        with psycopg.connect(TEST_URL) as other:
            self.assertEqual(other.execute(
                "SELECT count(*) FROM clinica.citas WHERE cita_id=%s", (code,)
            ).fetchone()[0], 1)
            self.assertEqual(other.execute(
                "SELECT clinica.fn_cartera_paciente(%s)", (self.patient,)
            ).fetchone()[0], Decimal("70000"))
            self.assertTrue(other.execute(
                "SELECT * FROM clinica.fn_citas_periodo(%s,%s)",
                (self.start, self.start + timedelta(days=1)),
            ).fetchall())


    def test_17_lector_solo_consulta(self):
        invoice = self.make_invoice()
        self.connection.execute("SET LOCAL ROLE vitalia_lector")
        self.assertTrue(self.connection.execute(
            "SELECT * FROM clinica.v_cartera WHERE factura_id=%s", (invoice,)
        ).fetchone())
        self.expect_state("42501", lambda: self.connection.execute(
            "UPDATE clinica.pacientes SET telefono='3001234567' WHERE paciente_id=%s", (self.patient,)
        ))

    def test_18_idempotencia_cita_y_rollback_facturacion(self):
        code = self.call_appointment(self.connection)
        self.call_appointment(self.connection, code=code)
        self.assertEqual(self.connection.execute(
            "SELECT count(*) FROM clinica.auditoria_citas WHERE cita_id=%s", (code,)
        ).fetchone()[0], 1)
        invoice = self.make_invoice()
        self.pay(self.connection, invoice, Decimal("30000"))
        self.connection.rollback()
        self.assertEqual(self.connection.execute(
            "SELECT count(*) FROM clinica.facturas WHERE factura_id=%s", (invoice,)
        ).fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
