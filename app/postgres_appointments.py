from time import sleep
from uuid import UUID, uuid4

import psycopg

from .appointment_repository import (
    Appointment, Doctor, AppointmentConflictError, AppointmentNotFoundError,
    AppointmentStateError, local_now, local_time,
)
from .database import DatabaseUnavailable
from .validation import COLOMBIA_TIMEZONE


class AppointmentPermissionError(PermissionError):
    pass


def aware_bogota(value):
    return value.replace(tzinfo=COLOMBIA_TIMEZONE) if value.tzinfo is None else value.astimezone(COLOMBIA_TIMEZONE)


def appointment_from_row(row):
    return Appointment(
        patient_id=row["paciente_id"], doctor_id=row["medico_id"],
        start_at=local_time(row["inicio"]), end_at=local_time(row["fin"]),
        appointment_id=row["cita_id"],
        status="PENDIENTE" if row["estado"] == "PROGRAMADA" else row["estado"],
        closed_by_time=row["cierre_automatico"], revision=row["revision"],
    )


class PostgresAppointmentRepository:
    def __init__(self, database, actor_provider):
        self.database = database
        self.actor_provider = actor_provider

    def now(self):
        return local_now()

    def _actor(self):
        try:
            return UUID(str(self.actor_provider()))
        except (ValueError, TypeError, AttributeError):
            raise AppointmentPermissionError("La sesión necesita autenticarse nuevamente.") from None

    def _run(self, operation):
        # Cada intento abre una transacción nueva: commit al salir, rollback al fallar.
        for attempt in range(3):
            try:
                with self.database.connect() as connection:
                    return operation(connection)
            except (psycopg.Error, DatabaseUnavailable) as error:
                original = error.__cause__ if isinstance(error, DatabaseUnavailable) else error
                state = getattr(original, "sqlstate", None)
                if state in {"40001", "40P01"}:
                    if attempt < 2:
                        sleep(0.03 * (attempt + 1))
                        continue
                    raise AppointmentStateError("La agenda está ocupada. Actualiza e intenta nuevamente.") from error
                if isinstance(error, DatabaseUnavailable):
                    raise
                if state in {"P1001", "23P01"}:
                    raise AppointmentConflictError from error
                if state == "P1003" or state == "42501":
                    raise AppointmentPermissionError("Tu cuenta no tiene permiso para esta operación.") from error
                if state == "P1007":
                    raise AppointmentNotFoundError from error
                if state in {"P1002", "P1004", "P1006"}:
                    raise AppointmentStateError(error.diag.message_primary) from error
                if state == "42883":
                    raise DatabaseUnavailable(
                        "La base no tiene actualizadas las rutinas de citas. "
                        "Ejecuta python actualizar_sql.py."
                    ) from error
                if state in {"23503", "23514", "23502", "22007", "22008", "22001"}:
                    raise AppointmentStateError("Verifica el paciente, el médico y el horario de la cita.") from error
                raise

    def list_doctors(self):
        def operation(connection):
            # También conserva nombres de médicos desactivados en citas anteriores.
            rows = connection.execute(
                "SELECT medico_id,nombre,activo FROM clinica.medicos ORDER BY nombre,medico_id"
            ).fetchall()
            return [Doctor(row["medico_id"], row["nombre"], row["activo"]) for row in rows]
        return self._run(operation)

    def list_all(self):
        actor = self._actor()
        def operation(connection):
            connection.execute("CALL pck_agenda.SP_cerrar_vencidas(%s)", (actor,))
            rows = connection.execute("SELECT * FROM clinica.citas ORDER BY inicio,cita_id").fetchall()
            return [appointment_from_row(row) for row in rows]
        return self._run(operation)

    def add(self, patient_id, doctor_id, start_at, end_at, appointment_id=None):
        actor = self._actor()
        identifier = appointment_id or f"CIT-{uuid4().hex}"
        start, end = aware_bogota(start_at), aware_bogota(end_at)
        def operation(connection):
            connection.execute(
                "CALL pck_agenda.SP_agendar_cita(%s,%s,%s,%s,%s,%s)",
                (identifier, patient_id, doctor_id, start, end, actor),
            )
            row = connection.execute("SELECT * FROM clinica.citas WHERE cita_id=%s", (identifier,)).fetchone()
            return appointment_from_row(row)
        return self._run(operation)

    def change_status(self, appointment_id, new_status, patient_active=True, expected_revision=None, force=False):
        actor = self._actor()
        def operation(connection):
            connection.execute(
                "CALL pck_agenda.SP_cambiar_estado_cita(%s,%s,%s,%s,%s)",
                (appointment_id, "PROGRAMADA" if new_status == "PENDIENTE" else new_status,
                 actor, expected_revision, force),
            )
            row = connection.execute("SELECT * FROM clinica.citas WHERE cita_id=%s", (appointment_id,)).fetchone()
            return appointment_from_row(row)
        return self._run(operation)

    def reschedule(self, appointment_id, start_at, end_at, expected_revision=None):
        actor = self._actor()
        def operation(connection):
            connection.execute(
                "CALL pck_agenda.SP_reprogramar_cita_controlada(%s,%s,%s,%s,%s)",
                (appointment_id, aware_bogota(start_at), aware_bogota(end_at), actor, expected_revision),
            )
            row = connection.execute("SELECT * FROM clinica.citas WHERE cita_id=%s", (appointment_id,)).fetchone()
            return appointment_from_row(row)
        return self._run(operation)
