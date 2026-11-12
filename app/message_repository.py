class PostgresMessageRepository:
    def __init__(self, database):
        self.database = database

    def list_for(self, user):
        with self.database.connect() as connection:
            condition = "1=1"
            params = []
            if user.role == "MEDICO":
                condition = "s.solicitado_por=%s"
                params.append(user.user_id)
            return connection.execute(
                f"""SELECT s.solicitud_id, s.tipo, s.mensaje, s.estado, s.creado_en,
                    s.cita_id, u.nombre_usuario AS remitente,
                    p.nombres || ' ' || p.apellidos AS paciente,
                    c.inicio
                FROM clinica.solicitudes_cita s
                JOIN clinica.usuarios u ON u.usuario_id=s.solicitado_por
                JOIN clinica.citas c ON c.cita_id=s.cita_id
                JOIN clinica.pacientes p ON p.paciente_id=c.paciente_id
                WHERE {condition}
                ORDER BY s.creado_en DESC""",
                params,
            ).fetchall()

    def doctor_appointments(self, user):
        with self.database.connect() as connection:
            return connection.execute(
                """SELECT c.cita_id, p.nombres || ' ' || p.apellidos AS paciente,
                    c.inicio
                FROM clinica.citas c
                JOIN clinica.medicos m ON m.medico_id=c.medico_id
                JOIN clinica.pacientes p ON p.paciente_id=c.paciente_id
                WHERE m.usuario_id=%s AND c.estado='PROGRAMADA'
                ORDER BY c.inicio""",
                (user.user_id,),
            ).fetchall()

    def send(self, appointment_id, user, message_type, body):
        with self.database.connect() as connection:
            valid = connection.execute(
                """SELECT 1 FROM clinica.citas c
                JOIN clinica.medicos m ON m.medico_id=c.medico_id
                WHERE c.cita_id=%s AND m.usuario_id=%s AND c.estado='PROGRAMADA'""",
                (appointment_id, user.user_id),
            ).fetchone()
            if valid is None:
                raise ValueError("Solo puedes escribir sobre una cita programada asignada a ti.")
            connection.execute(
                """INSERT INTO clinica.solicitudes_cita(cita_id, solicitado_por, tipo, mensaje)
                VALUES (%s,%s,%s,%s)""",
                (appointment_id, user.user_id, message_type, body),
            )

    def resolve(self, message_id, user, action):
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT cita_id, estado FROM clinica.solicitudes_cita WHERE solicitud_id=%s FOR UPDATE",
                (message_id,),
            ).fetchone()
            if row is None:
                raise ValueError("La solicitud no existe.")
            if row["estado"] != "PENDIENTE":
                raise ValueError("La solicitud ya fue gestionada.")
            if action == "CANCELAR_CITA":
                connection.execute(
                    "CALL pck_agenda.SP_cancelar_cita(%s,%s)",
                    (row["cita_id"], user.user_id),
                )
            connection.execute(
                """UPDATE clinica.solicitudes_cita
                SET estado='RESUELTO', resuelto_por=%s, resuelto_en=current_timestamp
                WHERE solicitud_id=%s""",
                (user.user_id, message_id),
            )
