from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import re

import pytest

from app import create_app
from app.appointment_repository import (
    DOCTORS, AppointmentConflictError, AppointmentNotFoundError, AppointmentStateError,
    InMemoryAppointmentRepository, patient_appointments,
)
from app.repository import InMemoryPatientRepository


class Clock:
    def __init__(self):
        self.value = datetime(2030, 1, 15, 15, 0)

    def __call__(self):
        return self.value


@pytest.fixture
def workflow():
    clock = Clock()
    repo = InMemoryAppointmentRepository(clock)
    appointment = repo.add("PAC-12345678", DOCTORS[0].doctor_id,
                           datetime(2030, 1, 15, 16), datetime(2030, 1, 15, 16, 30))
    return clock, repo, appointment


def test_pending_is_cancelled_at_end_not_at_start(workflow):
    clock, repo, appointment = workflow
    for instant in [datetime(2030, 1, 15, 16), datetime(2030, 1, 15, 16, 29, 59, 999999)]:
        clock.value = instant
        assert repo.list_all()[0].status == "PENDIENTE"
    clock.value = appointment.end_at
    expired = repo.list_all()[0]
    assert expired.status == "CANCELADA" and not expired.closed_by_time
    assert expired.status_label == "Cancelada"
    assert repo.list_all()[0] == expired


def test_in_attention_requires_manual_closing_even_after_scheduled_end(workflow):
    clock, repo, appointment = workflow
    clock.value = appointment.start_at
    repo.change_status(appointment.appointment_id, "EN_ATENCION")
    clock.value = appointment.end_at + timedelta(hours=2)
    assert repo.list_all()[0].status == "EN_ATENCION"
    closed = repo.change_status(appointment.appointment_id, "CERRADA", patient_active=False)
    assert closed.status == "CERRADA" and not closed.closed_by_time
    assert repo.change_status(appointment.appointment_id, "CERRADA") == closed


def test_future_attention_and_future_closing_are_rejected(workflow):
    _, repo, appointment = workflow
    for target in ("EN_ATENCION", "CERRADA"):
        with pytest.raises(AppointmentStateError):
            repo.change_status(appointment.appointment_id, target)
    assert repo.list_all()[0].status == "PENDIENTE"


def test_expired_appointment_is_cancelled_and_cannot_start(workflow):
    clock, repo, appointment = workflow
    clock.value = appointment.end_at
    for target in ("EN_ATENCION",):
        with pytest.raises(AppointmentStateError):
            repo.change_status(appointment.appointment_id, target)
    assert repo.list_all()[0].status == "CANCELADA"


def test_cancellation_is_final_idempotent_and_releases_slot(workflow):
    _, repo, appointment = workflow
    cancelled = repo.change_status(appointment.appointment_id, "CANCELADA")
    assert repo.change_status(appointment.appointment_id, "CANCELADA") == cancelled
    with pytest.raises(AppointmentStateError):
        repo.change_status(appointment.appointment_id, "EN_ATENCION")
    other = repo.add("PAC-87654321", appointment.doctor_id, appointment.start_at, appointment.end_at)
    assert other.appointment_id != appointment.appointment_id
    assert len(repo.list_all()) == 2


def test_inactive_patient_cannot_start_but_can_cancel(workflow):
    clock, repo, appointment = workflow
    clock.value = appointment.start_at
    with pytest.raises(AppointmentStateError):
        repo.change_status(appointment.appointment_id, "EN_ATENCION", patient_active=False)
    assert repo.change_status(appointment.appointment_id, "CANCELADA", patient_active=False).status == "CANCELADA"


def test_in_attention_cannot_cancel_or_return_to_pending(workflow):
    clock, repo, appointment = workflow
    clock.value = appointment.start_at
    repo.change_status(appointment.appointment_id, "EN_ATENCION")
    for target in ("CANCELADA", "PENDIENTE", "INVENTADO"):
        with pytest.raises(AppointmentStateError):
            repo.change_status(appointment.appointment_id, target)


def test_missing_appointment_rejected(workflow):
    _, repo, _ = workflow
    with pytest.raises(AppointmentNotFoundError):
        repo.change_status("CIT-00000000", "CERRADA")


def test_utc_clock_and_aware_appointments_use_bogota(workflow):
    clock, repo, appointment = workflow
    clock.value = datetime(2030, 1, 15, 21, 30, tzinfo=timezone.utc)
    assert repo.list_all()[0].status == "CANCELADA"
    clock.value = datetime(2030, 1, 15, 20, tzinfo=timezone.utc)
    added = repo.add("PAC-87654321", DOCTORS[1].doctor_id,
                     datetime(2030, 1, 15, 21, tzinfo=timezone.utc),
                     datetime(2030, 1, 15, 21, 30, tzinfo=timezone.utc))
    assert added.start_at == datetime(2030, 1, 15, 16)


def test_summary_selects_nearest_pending_then_current_attention(workflow):
    clock, repo, appointment = workflow
    future = repo.add(appointment.patient_id, DOCTORS[1].doctor_id,
                      appointment.start_at + timedelta(days=1), appointment.end_at + timedelta(days=1))
    assert patient_appointments(repo.list_all())[appointment.patient_id] == appointment
    clock.value = appointment.start_at
    repo.change_status(appointment.appointment_id, "EN_ATENCION")
    clock.value = future.end_at + timedelta(days=1)
    assert patient_appointments(repo.list_all())[appointment.patient_id].appointment_id == appointment.appointment_id
    repo.change_status(appointment.appointment_id, "CERRADA")
    assert patient_appointments(repo.list_all())[appointment.patient_id].appointment_id == future.appointment_id


def test_concurrent_start_and_cancel_do_not_overwrite_terminal_state(workflow):
    clock, repo, appointment = workflow
    clock.value = appointment.start_at
    def change(target):
        try:
            return repo.change_status(appointment.appointment_id, target).status
        except AppointmentStateError:
            return "RECHAZADA"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(change, ("EN_ATENCION", "CANCELADA")))
    assert results.count("RECHAZADA") == 1
    assert repo.list_all()[0].status in {"EN_ATENCION", "CANCELADA"}


@pytest.fixture
def web(workflow):
    clock, repo, appointment = workflow
    patients = InMemoryPatientRepository()
    patient = patients.add(first_names="Laura", last_names="Méndez", document_type="CC",
                           document_number="001234", birth_date="1990-05-10")
    # La relación apunta al ID completo realmente registrado.
    repo = InMemoryAppointmentRepository(clock)
    appointment = repo.add(patient.internal_id, DOCTORS[0].doctor_id,
                           appointment.start_at, appointment.end_at)
    app = create_app(patients)
    app.config.update(TESTING=True, APPOINTMENT_REPOSITORY=repo)
    client = app.test_client()
    client.post("/login", data={"username": "recepcion", "password": "Recepcion123!"})
    page = client.get("/pacientes").get_data(as_text=True)
    token = re.search(r'name="_csrf_token" value="([^"]+)"', page).group(1)
    return clock, repo, appointment, app, client, token


def test_doctor_and_attention_visible_on_patient_and_agenda(web):
    clock, repo, appointment, app, client, token = web
    for route in ("/pacientes", "/agenda"):
        page = client.get(route).get_data(as_text=True)
        assert DOCTORS[0].name in page and "Pendiente" in page
    clock.value = appointment.start_at
    response = client.post(f"/agenda/{appointment.appointment_id}/estado", data={
        "_csrf_token": token, "estado_cita": "EN_ATENCION", "volver": "pacientes", "filtro": "activos",
    })
    assert response.status_code == 303 and "estado=activos" in response.location
    assert "En atención" in client.get(response.location).get_data(as_text=True)
    assert app.config["PATIENT_REPOSITORY"].list_all()[0].active


def test_web_expiration_and_stale_start_rejected(web):
    clock, repo, appointment, app, client, token = web
    clock.value = appointment.end_at
    assert "Cancelada" in client.get("/pacientes").get_data(as_text=True)
    response = client.post(f"/agenda/{appointment.appointment_id}/estado", data={
        "_csrf_token": token, "estado_cita": "EN_ATENCION",
    })
    assert response.status_code == 409
    assert repo.list_all()[0].status == "CANCELADA"


def test_status_endpoint_rejects_invalid_state_redirect_and_id(web):
    _, repo, appointment, _, client, token = web
    path = f"/agenda/{appointment.appointment_id}/estado"
    assert client.get(path).status_code == 405
    for data in ({"estado_cita": "INVENTADO"}, {"estado_cita": "CANCELADA", "volver": "https://ejemplo"},
                 {"estado_cita": "CANCELADA", "filtro": "invalido"}):
        assert client.post(path, data={"_csrf_token": token, **data}).status_code == 400
    assert client.post("/agenda/CIT-00000000/estado", data={
        "_csrf_token": token, "estado_cita": "CANCELADA",
    }).status_code == 404
    assert repo.list_all()[0].status == "PENDIENTE"


def test_csrf_missing_empty_wrong_rejected_and_auth_required(web):
    _, repo, appointment, app, client, token = web
    path = f"/agenda/{appointment.appointment_id}/estado"
    for csrf in (None, "", "incorrecto"):
        data = {"estado_cita": "CANCELADA"}
        if csrf is not None:
            data["_csrf_token"] = csrf
        assert client.post(path, data=data).status_code == 400
    other = app.test_client()
    assert other.post(path, data={}).status_code == 302
    with other.session_transaction() as session:
        session["user"] = "otro"
    assert other.post(path, data={}).status_code == 403
    with client.session_transaction() as session:
        session.pop("_csrf_token", None)
    assert client.post(path, data={"estado_cita": "CANCELADA"}).status_code == 400
    assert repo.list_all()[0].status == "PENDIENTE"


def test_cancel_via_ui_preserves_patient_and_shows_doctor(web):
    _, repo, appointment, app, client, token = web
    response = client.post(f"/agenda/{appointment.appointment_id}/estado", data={
        "_csrf_token": token, "estado_cita": "CANCELADA", "volver": "pacientes",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert "Cancelada" in response.get_data(as_text=True) and DOCTORS[0].name in response.get_data(as_text=True)
    assert app.config["PATIENT_REPOSITORY"].list_all()[0].active
    assert len(repo.list_all()) == 1


def test_patient_without_appointment_does_not_invent_doctor():
    patients = InMemoryPatientRepository()
    patients.add(first_names="Ana", last_names="Torres")
    client = create_app(patients).test_client()
    client.post("/login", data={"username": "recepcion", "password": "Recepcion123!"})
    body = client.get("/pacientes").get_data(as_text=True)
    assert "Sin médico asignado" in body and "Sin cita asignada" in body
