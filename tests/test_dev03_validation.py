from datetime import timedelta

import pytest

from app import create_app
from app.database import ConfigurationError
from app.repository import InMemoryPatientRepository
from app.validation import local_today

VALID = {
    "first_names": "María José", "last_names": "O’Neill",
    "document_type": "CC", "document_number": "001234",
    "birth_date": "1990-05-10", "phone": "3001234567", "blood_type": "O+",
}


@pytest.fixture
def client():
    app = create_app(InMemoryPatientRepository())
    app.config["TESTING"] = True
    client = app.test_client()
    client.post("/login", data={"username": "recepcion", "password": "Recepcion123!"})
    return client


@pytest.mark.parametrize(("field", "value"), [
    ("first_names", "Ana123"), ("last_names", "123"), ("first_names", "Ana²"),
    ("first_names", "Ana_María"), ("first_names", "Ana--María"),
    ("first_names", "<script>alert</script>"), ("first_names", "A" * 101),
    ("document_number", "ABC123"), ("document_number", "１２３４５"),
    ("document_number", "12 345"), ("document_number", "123.456"),
    ("document_number", "1" * 21), ("document_type", "OTRO"),
    ("birth_date", "2026-02-30"), ("birth_date", "19900510"),
    ("birth_date", "01/01/1990"), ("birth_date", "1800-01-01"),
    ("birth_date", (local_today() + timedelta(days=1)).isoformat()),
    ("phone", "300ABC1234"), ("phone", "123"), ("phone", "1" * 16),
    ("phone", "１２３４５６７"), ("blood_type", "Z+"),
])
def test_invalid_input_keeps_form_and_does_not_save(client, field, value):
    data = dict(VALID, **{field: value})
    response = client.post("/pacientes", data=data)
    assert response.status_code == 400
    assert "field-error" in response.get_data(as_text=True)
    assert client.application.config["PATIENT_REPOSITORY"].list_all() == []


@pytest.mark.parametrize("names", ["María José", "Jean-Pierre", "O'Neill", "O’Neill", "李明"])
def test_letter_names_and_separators_are_accepted(client, names):
    data = dict(VALID, first_names=names)
    assert client.post("/pacientes", data=data).status_code == 302


def test_pas_alphanumeric_and_same_number_with_different_type(client):
    assert client.post("/pacientes", data=VALID).status_code == 302
    assert client.post("/pacientes", data=dict(VALID, document_type="CE")).status_code == 302
    assert client.post("/pacientes", data=dict(VALID, document_type="PAS", document_number="AB1234")).status_code == 302


def test_names_normalize_decomposed_accents(client):
    assert client.post("/pacientes", data=dict(VALID, first_names="Mari\u0301a")).status_code == 302
    assert client.application.config["PATIENT_REPOSITORY"].list_all()[0].first_names == "María"


def test_past_and_malformed_appointment_times(client):
    client.post("/pacientes", data=VALID)
    patient = client.application.config["PATIENT_REPOSITORY"].list_all()[0]
    data = {"patient_id": patient.internal_id, "doctor_id": "MED-001",
            "date": "2000-01-01", "start_time": "09:00", "end_time": "09:30"}
    assert client.post("/agenda", data=data).status_code == 400
    data.update(date="2030-01-01", start_time="09:00+01:00")
    assert client.post("/agenda", data=data).status_code == 400


def test_postgres_configuration_is_explicit():
    with pytest.raises(ConfigurationError):
        create_app(config={"DATA_BACKEND": "postgres", "POSTGRES_URL": "", "SECRET_KEY": ""})


def test_injected_repository_remains_isolated_from_postgres_configuration(monkeypatch):
    monkeypatch.setenv("DATA_BACKEND", "postgres")
    monkeypatch.setenv("POSTGRES_URL", "postgresql://unreachable")
    app = create_app(InMemoryPatientRepository())
    assert app.config["DATA_BACKEND"] == "memory"


def test_invalid_backend_is_rejected():
    with pytest.raises(ConfigurationError):
        create_app(config={"DATA_BACKEND": "invalid"})


def test_cancel_route_enforces_permission(client):
    with client.session_transaction() as session:
        session["user"] = "otro"
    assert client.post("/pacientes/cancelar").status_code == 403
