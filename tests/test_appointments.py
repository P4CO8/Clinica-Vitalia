from concurrent.futures import ThreadPoolExecutor

import pytest

from app import create_app
from app.appointment_repository import DOCTORS
from app.repository import InMemoryPatientRepository


@pytest.fixture
def app():
    patients = InMemoryPatientRepository()
    patients.add(
        first_names="Laura",
        last_names="Méndez",
        document_type="CC",
        document_number="001234",
        birth_date="1990-05-10",
    )
    application = create_app(patients)
    application.config.update(TESTING=True)
    return application


@pytest.fixture
def client(app):
    test_client = app.test_client()
    test_client.post("/login", data={"username": "recepcion", "password": "Recepcion123!"})
    return test_client


def appointment_data(client, **overrides):
    patient_id = client.application.config["PATIENT_REPOSITORY"].list_all()[0].internal_id
    data = {
        "patient_id": patient_id,
        "doctor_id": DOCTORS[0].doctor_id,
        "date": "2026-12-01",
        "start_time": "09:00",
        "end_time": "09:30",
    }
    data.update(overrides)
    return data


def test_agenda_navigation_and_empty_form(client):
    assert client.get("/agenda").status_code == 200
    response = client.get("/agenda/nueva")
    assert response.status_code == 200
    assert "Volver a la agenda" in response.get_data(as_text=True)
    assert "Laura Méndez" in response.get_data(as_text=True)


def test_valid_appointment_is_listed(client):
    response = client.post("/agenda", data=appointment_data(client), follow_redirects=True)
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Cita agendada correctamente." in body
    assert "01/12/2026" in body
    assert "09:00" in body and "09:30" in body
    assert "Dra. Valentina Gómez" in body


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"patient_id": ""}, "Selecciona un paciente."),
        ({"doctor_id": "MED-999"}, "Selecciona un médico válido."),
        ({"date": "fecha"}, "Verifica la fecha y hora de inicio."),
        ({"end_time": "08:00"}, "La hora de fin debe ser posterior al inicio."),
    ],
)
def test_invalid_appointment_is_not_saved_and_values_are_kept(client, overrides, message):
    response = client.post("/agenda", data=appointment_data(client, **overrides))
    body = response.get_data(as_text=True)
    assert response.status_code == 400
    assert message in body
    assert "09:00" in body
    assert len(client.application.config["APPOINTMENT_REPOSITORY"].list_all()) == 0


def test_overlapping_same_doctor_is_rejected(client):
    client.post("/agenda", data=appointment_data(client))
    response = client.post(
        "/agenda",
        data=appointment_data(client, start_time="09:15", end_time="09:45"),
    )
    assert response.status_code == 400
    assert "El médico ya tiene una cita en ese horario" in response.get_data(as_text=True)
    assert len(client.application.config["APPOINTMENT_REPOSITORY"].list_all()) == 1


def test_contiguous_other_doctor_and_other_date_are_allowed(client):
    client.post("/agenda", data=appointment_data(client))
    contiguous = client.post(
        "/agenda",
        data=appointment_data(client, start_time="09:30", end_time="10:00"),
    )
    other_doctor = client.post(
        "/agenda",
        data=appointment_data(client, doctor_id=DOCTORS[1].doctor_id),
    )
    other_date = client.post(
        "/agenda",
        data=appointment_data(client, date="2026-12-02"),
    )
    assert contiguous.status_code == 302
    assert other_doctor.status_code == 302
    assert other_date.status_code == 302
    appointments = client.application.config["APPOINTMENT_REPOSITORY"].list_all()
    assert len(appointments) == 4


def test_two_crossing_submissions_only_save_one(app):
    client = app.test_client()
    client.post("/login", data={"username": "recepcion", "password": "Recepcion123!"})
    data = appointment_data(client)

    def submit():
        return client.post("/agenda", data=data)

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: submit(), range(2)))

    assert sorted(response.status_code for response in responses) == [302, 400]
    assert len(app.config["APPOINTMENT_REPOSITORY"].list_all()) == 1


def test_agenda_access_requires_session_and_reception(app):
    anonymous = app.test_client()
    assert anonymous.get("/agenda").status_code == 302
    unauthorized = app.test_client()
    with unauthorized.session_transaction() as session:
        session["user"] = "cuenta_antigua"
    assert unauthorized.get("/agenda").status_code == 403
    assert unauthorized.post("/agenda", data={}).status_code == 403
