import re

from app import create_app
from app.repository import InMemoryPatientRepository


def logged_client():
    app = create_app(InMemoryPatientRepository())
    app.config["TESTING"] = True
    client = app.test_client()
    assert client.post("/login", data={"username": "recepcion", "password": "Recepcion123!"}).status_code == 302
    return app, client


def test_status_is_idempotent_and_requires_csrf():
    app, client = logged_client()
    assert client.post("/pacientes", data={
        "first_names": "Ana", "last_names": "Lopez", "document_type": "CC",
        "document_number": "000123", "birth_date": "1990-01-01",
    }).status_code == 302
    patient = app.config["PATIENT_REPOSITORY"].list_all()[0]
    page = client.get("/pacientes").get_data(as_text=True)
    token = re.search(r'name="_csrf_token" value="([^"]+)"', page).group(1)
    endpoint = f"/pacientes/{patient.internal_id}/estado"
    assert client.post(endpoint, data={"activo": "false"}).status_code == 400
    assert client.post(endpoint, data={"_csrf_token": token, "activo": "false"}).status_code == 302
    assert not app.config["PATIENT_REPOSITORY"].list_all()[0].active
    assert client.post(endpoint, data={"_csrf_token": token, "activo": "false"}).status_code == 302
    assert patient.internal_id not in client.get("/agenda/nueva").get_data(as_text=True)


def test_invalid_and_missing_patient_status_ids():
    _, client = logged_client()
    page = client.get("/pacientes").get_data(as_text=True)
    token = re.search(r'name="_csrf_token" value="([^"]+)"', page).group(1)
    assert client.post("/pacientes/PAC-invalid/estado", data={
        "_csrf_token": token, "activo": "false",
    }).status_code == 400
    assert client.post("/pacientes/PAC-12345678/estado", data={
        "_csrf_token": token, "activo": "false",
    }).status_code == 404
