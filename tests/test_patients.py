import pytest

from app import create_app
from app.repository import InMemoryPatientRepository


@pytest.fixture
def app():
    application = create_app(InMemoryPatientRepository())
    application.config.update(TESTING=True)
    return application


def test_registration_route_is_closed(app):
    client = app.test_client()
    assert client.get("/register").status_code == 404
    assert client.post("/register").status_code == 404


def test_legacy_account_cannot_access_patients(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session["user"] = "cuenta_anterior"
    response = client.get("/pacientes")
    assert response.status_code == 403


def test_reception_can_access_patients(app):
    client = app.test_client()
    login = client.post(
        "/login",
        data={"username": "recepcion", "password": "Recepcion123!"},
    )
    directory = client.get("/pacientes")
    assert login.status_code == 302
    assert directory.status_code == 200


def test_login_has_no_registration_link(app):
    response = app.test_client().get("/login")
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Registrarse" not in body
