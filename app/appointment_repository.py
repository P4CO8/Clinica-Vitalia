from dataclasses import dataclass, field, replace
from datetime import datetime
from threading import Lock
from uuid import uuid4

from .validation import COLOMBIA_TIMEZONE


@dataclass(frozen=True)
class Doctor:
    doctor_id: str
    name: str
    active: bool = True


DOCTORS = (
    Doctor("MED-001", "Dra. Valentina Gómez"),
    Doctor("MED-002", "Dr. Santiago Rojas"),
)

STATUS_LABELS = {
    "PENDIENTE": "Pendiente",
    "EN_ATENCION": "En atención",
    "CERRADA": "Cerrada",
    "CANCELADA": "Cancelada",
    "ATENDIDA": "Atendida",
}


def local_time(value):
    if value.tzinfo is not None:
        return value.astimezone(COLOMBIA_TIMEZONE).replace(tzinfo=None)
    return value


def local_now():
    return datetime.now(COLOMBIA_TIMEZONE).replace(tzinfo=None)


@dataclass(frozen=True)
class Appointment:
    patient_id: str
    doctor_id: str
    start_at: datetime
    end_at: datetime
    appointment_id: str = field(default_factory=lambda: f"CIT-{uuid4().hex[:8].upper()}")
    status: str = "PENDIENTE"
    closed_by_time: bool = False
    revision: int = 0

    @property
    def status_label(self):
        return "Completada" if self.status == "CERRADA" else STATUS_LABELS[self.status]


class AppointmentConflictError(ValueError):
    pass


class AppointmentStateError(ValueError):
    pass


class AppointmentNotFoundError(LookupError):
    pass


class InMemoryAppointmentRepository:
    def __init__(self, clock=None):
        self._appointments = []
        self._lock = Lock()
        self._clock = clock or local_now

    def now(self):
        return local_time(self._clock())

    def _close_expired(self, now):
        self._appointments = [
            replace(item, status="CANCELADA", closed_by_time=False, revision=item.revision + 1)
            if item.status == "PENDIENTE" and item.end_at <= now else item
            for item in self._appointments
        ]

    def list_all(self):
        with self._lock:
            self._close_expired(self.now())
            return sorted(self._appointments, key=lambda item: item.start_at)

    def list_doctors(self):
        return list(DOCTORS)

    def add(self, patient_id, doctor_id, start_at, end_at, appointment_id=None):
        start_at, end_at = local_time(start_at), local_time(end_at)
        with self._lock:
            now = self.now()
            self._close_expired(now)
            existing = next((a for a in self._appointments if a.appointment_id == appointment_id), None)
            if existing:
                if (existing.patient_id, existing.doctor_id, existing.start_at, existing.end_at) == (patient_id, doctor_id, start_at, end_at):
                    return existing
                raise AppointmentStateError("La solicitud ya existe con otros datos.")
            if end_at <= start_at or start_at.date() != end_at.date():
                raise AppointmentStateError("Verifica el intervalo de la cita.")
            if start_at < now:
                raise AppointmentStateError("Selecciona una fecha y hora que aún no hayan pasado.")
            if any(
                appointment.doctor_id == doctor_id
                and appointment.status in {"PENDIENTE", "EN_ATENCION"}
                and start_at < appointment.end_at
                and appointment.start_at < end_at
                for appointment in self._appointments
            ):
                raise AppointmentConflictError
            appointment = Appointment(patient_id, doctor_id, start_at, end_at, **({"appointment_id": appointment_id} if appointment_id else {}))
            self._appointments.append(appointment)
            return appointment

    def change_status(self, appointment_id, new_status, patient_active=True, expected_revision=None, force=False):
        if new_status not in {"PENDIENTE", "EN_ATENCION", "CERRADA", "CANCELADA"}:
            raise AppointmentStateError("Selecciona un estado de atención válido.")
        with self._lock:
            now = self.now()
            self._close_expired(now)
            for index, item in enumerate(self._appointments):
                if item.appointment_id != appointment_id:
                    continue
                if item.status == new_status:
                    return item
                if expected_revision is not None and item.revision != expected_revision:
                    raise AppointmentStateError("La cita cambió en otra pantalla. Actualiza y vuelve a intentarlo.")
                if new_status == "PENDIENTE" and item.status != "PENDIENTE":
                    raise AppointmentStateError("Una cita cancelada debe conservarse como historial y agendarse nuevamente.")
                if not force and item.status in {"CERRADA", "CANCELADA", "ATENDIDA"}:
                    raise AppointmentStateError("La cita ya está cerrada o cancelada. Actualiza la página.")
                if not force and new_status == "EN_ATENCION":
                    if not patient_active:
                        raise AppointmentStateError("Reactiva al paciente antes de iniciar la atención.")
                    if not item.start_at <= now < item.end_at:
                        raise AppointmentStateError("La atención solo puede iniciarse dentro del horario de la cita.")
                elif not force and new_status == "CANCELADA" and item.status != "PENDIENTE":
                    raise AppointmentStateError("Una cita en atención debe finalizarse con Cerrar atención.")
                elif new_status == "CERRADA" and item.status != "EN_ATENCION":
                    raise AppointmentStateError("Una cita que no fue atendida debe cancelarse o reprogramarse.")
                updated = replace(item, status=new_status, closed_by_time=False, revision=item.revision + 1)
                self._appointments[index] = updated
                return updated
        raise AppointmentNotFoundError("No se encontró la cita.")

    def reschedule(self, appointment_id, start_at, end_at, expected_revision=None):
        start_at, end_at = local_time(start_at), local_time(end_at)
        with self._lock:
            now = self.now()
            self._close_expired(now)
            for index, item in enumerate(self._appointments):
                if item.appointment_id != appointment_id:
                    continue
                if item.status != "PENDIENTE":
                    raise AppointmentStateError("Solo se reprograman citas pendientes y vigentes.")
                if item.start_at == start_at and item.end_at == end_at:
                    return item
                if expected_revision is not None and item.revision != expected_revision:
                    raise AppointmentStateError("La cita cambió en otra pantalla. Actualiza y vuelve a intentarlo.")
                if start_at < now or end_at <= start_at or start_at.date() != end_at.date():
                    raise AppointmentStateError("Selecciona un intervalo futuro válido en un mismo día.")
                if any(a.appointment_id != appointment_id and a.doctor_id == item.doctor_id
                       and a.status in {"PENDIENTE", "EN_ATENCION", "ATENDIDA"}
                       and start_at < a.end_at and a.start_at < end_at for a in self._appointments):
                    raise AppointmentConflictError
                updated = replace(item, start_at=start_at, end_at=end_at, revision=item.revision + 1)
                self._appointments[index] = updated
                return updated
        raise AppointmentNotFoundError("No se encontró la cita.")


def available_actions(appointment, now, patient_active=True):
    now = local_time(now)
    if appointment.status == "EN_ATENCION":
        return (("CERRADA", "Cerrar atención"),)
    if appointment.status != "PENDIENTE":
        return ()
    actions = []
    if appointment.start_at <= now < appointment.end_at:
        if patient_active:
            actions.append(("EN_ATENCION", "Poner en turno"))
    if now < appointment.end_at:
        actions.append(("CANCELADA", "Cancelar turno"))
    return tuple(actions)


def manual_actions(appointment):
    return (
        ("EN_ATENCION", "Poner en turno"),
        ("CANCELADA", "Cancelar cita"),
    )


def patient_appointments(appointments):
    """Prioriza atención abierta, próxima cita y, en su defecto, última cita."""
    groups = {}
    for item in appointments:
        groups.setdefault(item.patient_id, []).append(item)
    result = {}
    for patient_id, items in groups.items():
        in_progress = [item for item in items if item.status == "EN_ATENCION"]
        pending = [item for item in items if item.status == "PENDIENTE"]
        if in_progress:
            result[patient_id] = max(in_progress, key=lambda item: item.start_at)
        elif pending:
            result[patient_id] = min(pending, key=lambda item: item.start_at)
        else:
            result[patient_id] = max(items, key=lambda item: item.start_at)
    return result
