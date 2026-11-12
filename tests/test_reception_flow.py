import pytest

from app import create_app
from app.repository import InMemoryPatientRepository


@pytest.fixture
def client():
    app = create_app(InMemoryPatientRepository())
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post("/login", data={"username": "recepcion", "password": "Recepcion123!"})
    return client


def test_reception_navigation_and_cancel(client):
    home = client.get("/inicio")
    directory = client.get("/pacientes")
    form = client.get("/pacientes/nuevo")
    cancel = client.post("/pacientes/cancelar")

    assert home.status_code == 200
    assert "Clínica Vitalia — Sistema de gestión clínica." in home.get_data(as_text=True)
    assert directory.status_code == 200
    assert "Registrar paciente" in directory.get_data(as_text=True)
    assert form.status_code == 200
    assert "Nombres" in form.get_data(as_text=True)
    assert "Cancelar" in form.get_data(as_text=True)
    assert cancel.status_code == 302
    assert cancel.headers["Location"].endswith("/pacientes")


def test_valid_patient_is_registered_with_internal_id(client):
    response = client.post(
        "/pacientes",
        data={
            "first_names": "Laura",
            "last_names": "Méndez",
            "document_type": "CC",
            "document_number": "001234",
            "birth_date": "1990-05-10",
            "phone": "3001234567",
            "blood_type": "O+",
        },
        follow_redirects=True,
    )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Paciente registrado correctamente." in body
    assert "Laura Méndez" in body
    assert "CC 001234" in body
    assert "PAC-" in body


def test_homonyms_with_different_documents_are_allowed(client):
    common = {
        "first_names": "Laura",
        "last_names": "Méndez",
        "birth_date": "1990-05-10",
    }
    first = client.post(
        "/pacientes",
        data=dict(common, document_type="CC", document_number="001234"),
    )
    second = client.post(
        "/pacientes",
        data=dict(common, document_type="CC", document_number="005678"),
    )
    directory = client.get("/pacientes")
    body = directory.get_data(as_text=True)

    assert first.status_code == 302
    assert second.status_code == 302
    assert body.count("Laura Méndez") == 2
    assert "CC 001234" in body
    assert "CC 005678" in body


def test_passport_accepts_letters_and_numbers(client):
    response = client.post(
        "/pacientes",
        data={
            "first_names": "Carlos",
            "last_names": "Ríos",
            "document_type": "PAS",
            "document_number": "AB123CD",
            "birth_date": "1988-03-20",
        },
    )

    assert response.status_code == 302
    assert "PAS AB123CD" in client.get("/pacientes").get_data(as_text=True)


def test_document_type_is_required(client):
    response = client.post(
        "/pacientes",
        data={
            "first_names": "Carlos",
            "last_names": "Ríos",
            "document_number": "123456",
            "birth_date": "1988-03-20",
        },
    )

    assert response.status_code == 400
    assert "Selecciona un tipo de documento" in response.get_data(as_text=True)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (
            {
                "first_names": "Laura2",
                "last_names": "Méndez",
                "document_type": "CC",
                "document_number": "001234",
                "birth_date": "1990-05-10",
            },
            "Escribe el nombre con letras.",
        ),
        (
            {
                "first_names": "Laura",
                "last_names": "Méndez",
                "document_type": "CC",
                "document_number": "001234",
                "birth_date": "2999-05-10",
            },
            "Esta fecha es incorrecta.",
        ),
    ],
)
def test_invalid_patient_is_not_listed_and_values_are_preserved(client, data, message):
    response = client.post("/pacientes", data=data)
    directory = client.get("/pacientes")

    assert response.status_code == 400
    assert message in response.get_data(as_text=True)
    assert "Laura Méndez" not in directory.get_data(as_text=True)
    assert "001234" not in directory.get_data(as_text=True)


def test_document_requires_minimum_length(client):
    response = client.post(
        "/pacientes",
        data={
            "first_names": "Laura",
            "last_names": "Méndez",
            "document_type": "CC",
            "document_number": "1",
            "birth_date": "1990-05-10",
        },
    )

    assert response.status_code == 400
    assert "El documento debe tener mínimo 3 caracteres." in response.get_data(as_text=True)


def test_document_type_and_number_must_be_unique(client):
    valid = {
        "first_names": "Laura",
        "last_names": "Méndez",
        "document_type": "CC",
        "document_number": "001234",
        "birth_date": "1990-05-10",
    }
    client.post("/pacientes", data=valid)

    duplicate = dict(valid, first_names="Otra", last_names="Persona")
    response = client.post("/pacientes", data=duplicate)
    directory = client.get("/pacientes")

    assert response.status_code == 400
    assert "Este documento ya está registrado." in response.get_data(as_text=True)
    assert "Otra Persona" not in directory.get_data(as_text=True)
