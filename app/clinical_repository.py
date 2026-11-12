from datetime import date
from uuid import uuid4


class PostgresClinicalRepository:
    def __init__(self, database):
        self.database = database

    def appointments(self, user):
        with self.database.connect() as connection:
            params = []
            filter_sql = ""
            if user.role == "MEDICO":
                filter_sql = "AND m.usuario_id = %s"
                params.append(user.user_id)
            return connection.execute(
                f"""
                SELECT c.cita_id, c.estado, c.inicio, c.fin,
                       p.paciente_id, p.nombres, p.apellidos,
                       m.nombre AS medico,
                       a.atencion_id
                FROM clinica.citas c
                JOIN clinica.pacientes p ON p.paciente_id = c.paciente_id
                JOIN clinica.medicos m ON m.medico_id = c.medico_id
                LEFT JOIN clinica.atenciones a ON a.cita_id = c.cita_id
                WHERE c.estado IN ('PROGRAMADA', 'ATENDIDA') {filter_sql}
                ORDER BY c.inicio
                """,
                params,
            ).fetchall()

    def medications(self):
        with self.database.connect() as connection:
            return connection.execute(
                "SELECT medicamento_id, nombre, presentacion FROM clinica.medicamentos ORDER BY nombre, presentacion"
            ).fetchall()

    def patient(self, patient_id):
        with self.database.connect() as connection:
            return connection.execute(
                "SELECT paciente_id, nombres, apellidos, tipo_documento, numero_documento FROM clinica.pacientes WHERE paciente_id=%s",
                (patient_id,),
            ).fetchone()

    def can_view_history(self, patient_id, user):
        with self.database.connect() as connection:
            if user.role == "ADMINISTRADOR":
                return connection.execute(
                    "SELECT 1 FROM clinica.pacientes WHERE paciente_id=%s",
                    (patient_id,),
                ).fetchone() is not None
            return connection.execute(
                """SELECT 1
                FROM clinica.citas c
                JOIN clinica.medicos m ON m.medico_id=c.medico_id
                WHERE c.paciente_id=%s AND m.usuario_id=%s AND m.activo""",
                (patient_id, user.user_id),
            ).fetchone() is not None

    def history(self, patient_id):
        with self.database.connect() as connection:
            return connection.execute(
                """SELECT a.atencion_id, a.fecha_atencion, a.motivo_consulta,
                    m.nombre AS medico,
                    COALESCE(string_agg(DISTINCT d.descripcion, ' | '), '') AS diagnosticos,
                    COALESCE(string_agg(DISTINCT t.descripcion, ' | '), '') AS tratamientos
                FROM clinica.atenciones a
                JOIN clinica.citas c ON c.cita_id=a.cita_id
                JOIN clinica.medicos m ON m.medico_id=c.medico_id
                LEFT JOIN clinica.diagnosticos d ON d.atencion_id=a.atencion_id
                LEFT JOIN clinica.tratamientos t ON t.atencion_id=a.atencion_id
                WHERE c.paciente_id=%s
                GROUP BY a.atencion_id, a.fecha_atencion, a.motivo_consulta, m.nombre
                ORDER BY a.fecha_atencion DESC""",
                (patient_id,),
            ).fetchall()

    def register_attention(self, appointment_id, user, values):
        with self.database.connect() as connection:
            if user.role == "MEDICO":
                owner = connection.execute(
                    """SELECT 1 FROM clinica.citas c
                    JOIN clinica.medicos m ON m.medico_id=c.medico_id
                    WHERE c.cita_id=%s AND m.usuario_id=%s AND m.activo""",
                    (appointment_id, user.user_id),
                ).fetchone()
                if owner is None:
                    raise ValueError("La cita no pertenece al médico autenticado.")
            attention_id = uuid4()
            connection.execute(
                "CALL pck_clinica.SP_registrar_atencion(%s,%s,%s,%s)",
                (attention_id, appointment_id, values["reason"], user.user_id),
            )
            connection.execute(
                """INSERT INTO clinica.diagnosticos(diagnostico_id, atencion_id, codigo, descripcion)
                VALUES (%s,%s,%s,%s)""",
                (uuid4(), attention_id, values["diagnosis_code"] or None, values["diagnosis"]),
            )
            treatment_id = uuid4()
            connection.execute(
                """INSERT INTO clinica.tratamientos(
                    tratamiento_id, atencion_id, descripcion, fecha_inicio
                ) VALUES (%s,%s,%s,%s)""",
                (treatment_id, attention_id, values["treatment"], date.today()),
            )
            if values["medication_id"]:
                if not all(values[key] for key in ("dose", "frequency", "duration")):
                    raise ValueError("Completa dosis, frecuencia y duración del medicamento.")
                connection.execute(
                    """INSERT INTO clinica.tratamiento_medicamento(
                        tratamiento_id, medicamento_id, dosis, frecuencia, duracion
                    ) VALUES (%s,%s,%s,%s,%s)""",
                    (
                        treatment_id, int(values["medication_id"]), values["dose"],
                        values["frequency"], values["duration"],
                    ),
                )
