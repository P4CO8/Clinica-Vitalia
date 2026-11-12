from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os
from uuid import uuid4

import psycopg
import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.database import DatabaseUnavailable
from app.validation import local_today

ADMIN_URL = os.environ.get("VITALIA_TEST_URL", "")
APP_URL = os.environ.get("VITALIA_TEST_APP_URL", "")
pytestmark = pytest.mark.skipif(not ADMIN_URL or not APP_URL, reason="Requiere VITALIA_TEST_URL y VITALIA_TEST_APP_URL")
PASSWORD = "ClaveWebPrueba_123!"


@pytest.fixture
def configuration():
    with psycopg.connect(ADMIN_URL, autocommit=True) as connection:
        name = connection.execute("SELECT current_database()").fetchone()[0]
        if not name.endswith("_pruebas"):
            pytest.fail("Usa una base exclusiva terminada en _pruebas.")
    with psycopg.connect(APP_URL) as connection:
        app_database, app_user = connection.execute("SELECT current_database(),current_user").fetchone()
        if app_database != name or app_user != "vitalia_app":
            pytest.fail("La conexión de aplicación debe usar vitalia_app y la misma base de pruebas.")
    return {
        "DATA_BACKEND": "postgres",
        "POSTGRES_URL": APP_URL,
        "SECRET_KEY": "clave-estable-para-las-pruebas-dev03",
        "TESTING": True,
    }


@pytest.fixture
def account(configuration):
    username = "recepcion_" + uuid4().hex[:12]
    user_id = uuid4()
    with psycopg.connect(ADMIN_URL) as connection:
        connection.execute(
            """INSERT INTO clinica.usuarios(usuario_id,nombre_usuario,password_hash,rol_id)
            SELECT %s,%s,%s,rol_id FROM clinica.roles WHERE nombre='RECEPCION'""",
            (user_id, username, generate_password_hash(PASSWORD)),
        )
    return username, user_id


@pytest.fixture
def client(configuration, account):
    app = create_app(config=configuration)
    client = app.test_client()
    assert client.post("/login", data={"username": account[0], "password": PASSWORD}).status_code == 302
    return client


def patient_data():
    return {"first_names": "Laura", "last_names": "Méndez", "document_type": "CC",
            "document_number": str(uuid4().int)[:18], "birth_date": "1990-05-10",
            "phone": "3001234567", "blood_type": "O+"}


def test_login_and_patient_survive_a_new_application(configuration, account, client):
    data = patient_data()
    assert client.post("/pacientes", data=data).status_code == 302
    cookie = client.get_cookie("session")
    restarted = create_app(config=configuration).test_client()
    restarted.set_cookie("session", cookie.value)
    directory = restarted.get("/pacientes")
    assert directory.status_code == 200
    assert data["document_number"] in directory.get_data(as_text=True)
    with psycopg.connect(ADMIN_URL) as connection:
        row = connection.execute(
            """SELECT p.paciente_id,h.historia_id FROM clinica.pacientes p
            JOIN clinica.historias_clinicas h USING(paciente_id) WHERE p.numero_documento=%s""",
            (data["document_number"],),
        ).fetchone()
        assert row and row[0].startswith("PAC-")
        saved_hash = connection.execute(
            "SELECT password_hash FROM clinica.usuarios WHERE usuario_id=%s", (account[1],)
        ).fetchone()[0]
        assert saved_hash != PASSWORD and saved_hash.startswith("scrypt:")


def test_wrong_or_inactive_account_is_rejected(configuration, account):
    client = create_app(config=configuration).test_client()
    assert client.post("/login", data={"username": account[0], "password": "wrong"}).status_code == 401
    with psycopg.connect(ADMIN_URL) as connection:
        connection.execute("UPDATE clinica.usuarios SET activo=false WHERE usuario_id=%s", (account[1],))
    assert client.post("/login", data={"username": account[0], "password": PASSWORD}).status_code == 401


def test_username_is_case_insensitive(configuration, account):
    client = create_app(config=configuration).test_client()
    assert client.post("/login", data={"username": account[0].upper(), "password": PASSWORD}).status_code == 302
    assert client.get("/pacientes").status_code == 200


def test_session_rechecks_active_user(account, client):
    with psycopg.connect(ADMIN_URL) as connection:
        connection.execute("UPDATE clinica.usuarios SET activo=false WHERE usuario_id=%s", (account[1],))
    assert client.get("/pacientes").status_code == 302


def test_role_changes_apply_to_existing_session(account, client):
    with psycopg.connect(ADMIN_URL) as connection:
        connection.execute(
            "UPDATE clinica.usuarios SET rol_id=(SELECT rol_id FROM clinica.roles WHERE nombre='MEDICO') WHERE usuario_id=%s",
            (account[1],),
        )
    for path in ("/inicio", "/pacientes", "/pacientes/nuevo", "/agenda"):
        assert client.get(path).status_code == 403
    assert client.post("/pacientes", data=patient_data()).status_code == 403
    assert client.post("/pacientes/cancelar").status_code == 403


def test_admin_can_manage_patients(account, client):
    with psycopg.connect(ADMIN_URL) as connection:
        connection.execute(
            "UPDATE clinica.usuarios SET rol_id=(SELECT rol_id FROM clinica.roles WHERE nombre='ADMINISTRADOR') WHERE usuario_id=%s",
            (account[1],),
        )
    assert client.post("/pacientes", data=patient_data()).status_code == 302


def test_duplicate_homonyms_and_passport(client):
    data = patient_data()
    assert client.post("/pacientes", data=data).status_code == 302
    assert client.post("/pacientes", data=data).status_code == 400
    data["document_number"] = str(uuid4().int)[:18]
    assert client.post("/pacientes", data=data).status_code == 302
    data.update(document_type="PAS", document_number="AB" + uuid4().hex[:8].upper())
    assert client.post("/pacientes", data=data).status_code == 302
    data["document_number"] = data["document_number"].lower()
    assert client.post("/pacientes", data=data).status_code == 400


def test_new_patient_is_available_in_agenda(client):
    data = patient_data()
    client.post("/pacientes", data=data)
    assert data["first_names"] in client.get("/agenda/nueva").get_data(as_text=True)


def test_database_outage_is_visible_and_recovers(client):
    database = client.application.config["DATABASE"]
    original = database.url
    database.url = "postgresql://127.0.0.1:1/unavailable"
    response = client.get("/pacientes")
    assert response.status_code == 503
    assert "túnel" in response.get_data(as_text=True)
    assert "Traceback" not in response.get_data(as_text=True)
    assert client.post("/logout").status_code == 302
    database.url = original
    assert client.get("/login").status_code == 200


@pytest.mark.parametrize(("column", "value", "state"), [
    ("nombres", "Ana123", "23514"),
    ("nombres", "Ana--María", "23514"),
    ("numero_documento", "AB1234", "23514"),
    ("fecha_nacimiento", (local_today() + timedelta(days=1)).isoformat(), "P1002"),
    ("fecha_nacimiento", "1800-01-01", "P1002"),
    ("telefono", "ABC123456", "23514"),
    ("grupo_sanguineo", "Z+", "23514"),
])
def test_sql_also_rejects_invalid_values(column, value, state, configuration):
    data = patient_data()
    with psycopg.connect(configuration["POSTGRES_URL"]) as connection:
        identifier = connection.execute(
            """INSERT INTO clinica.pacientes(nombres,apellidos,tipo_documento,numero_documento,fecha_nacimiento)
            VALUES (%s,%s,%s,%s,%s) RETURNING paciente_id""",
            (data["first_names"], data["last_names"], data["document_type"], data["document_number"], data["birth_date"]),
        ).fetchone()[0]
    with pytest.raises(psycopg.Error) as error:
        with psycopg.connect(configuration["POSTGRES_URL"]) as connection:
            # column proviene exclusivamente de la parametrización cerrada de esta prueba.
            connection.execute(f"UPDATE clinica.pacientes SET {column}=%s WHERE paciente_id=%s", (value, identifier))
    assert error.value.sqlstate == state


def test_failed_transaction_rolls_back_patient_and_history(configuration):
    data = patient_data()
    database = create_app(config=configuration).config["DATABASE"]
    with pytest.raises(psycopg.errors.DivisionByZero):
        with database.connect() as connection:
            connection.execute(
                """INSERT INTO clinica.pacientes(nombres,apellidos,tipo_documento,numero_documento,fecha_nacimiento)
                VALUES (%s,%s,%s,%s,%s)""",
                (data["first_names"], data["last_names"], data["document_type"], data["document_number"], data["birth_date"]),
            )
            connection.execute("SELECT 1/0")
    with psycopg.connect(ADMIN_URL) as connection:
        assert connection.execute(
            "SELECT count(*) FROM clinica.pacientes WHERE numero_documento=%s", (data["document_number"],)
        ).fetchone()[0] == 0


def test_simultaneous_duplicate_is_saved_once(configuration, account):
    data = patient_data()
    app = create_app(config=configuration)
    def submit():
        with app.test_client() as client:
            client.post("/login", data={"username": account[0], "password": PASSWORD})
            return client.post("/pacientes", data=data).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        result = list(executor.map(lambda _: submit(), range(2)))
    assert sorted(result) == [302, 400]


def test_legacy_session_cannot_authenticate_postgres(configuration):
    client = create_app(config=configuration).test_client()
    with client.session_transaction() as session:
        session["user"] = "recepcion"
    assert client.get("/pacientes").status_code == 302
    assert client.get("/register").status_code == 404


def test_missing_schema_fails_without_using_memory(configuration):
    bad = dict(configuration, POSTGRES_URL="postgresql://127.0.0.1:1/unavailable")
    with pytest.raises(DatabaseUnavailable):
        create_app(config=bad)

def test_invalid_database_password_fails(configuration):
    options = psycopg.conninfo.conninfo_to_dict(configuration["POSTGRES_URL"])
    options["password"] = "wrong-password"
    broken = dict(configuration, POSTGRES_URL=psycopg.conninfo.make_conninfo(**options))
    with pytest.raises(DatabaseUnavailable):
        create_app(config=broken)

def test_sql_rejects_past_appointment(account, configuration):
    client = create_app(config=configuration).test_client()
    data = patient_data()
    with psycopg.connect(ADMIN_URL) as connection:
        patient_id = connection.execute(
            """INSERT INTO clinica.pacientes(nombres,apellidos,tipo_documento,numero_documento,fecha_nacimiento)
            VALUES (%s,%s,%s,%s,%s) RETURNING paciente_id""",
            (data["first_names"], data["last_names"], data["document_type"], data["document_number"], data["birth_date"]),
        ).fetchone()[0]
    with pytest.raises(psycopg.Error) as error:
        with psycopg.connect(configuration["POSTGRES_URL"]) as connection:
            connection.execute("CALL pck_agenda.SP_agendar_cita(%s,%s,%s,%s,%s,%s)",
                ("CIT-"+uuid4().hex, patient_id, "MED-001",
                 "2000-01-01T09:00:00-05:00", "2000-01-01T09:30:00-05:00", account[1]))
    assert error.value.sqlstate == "P1002"
