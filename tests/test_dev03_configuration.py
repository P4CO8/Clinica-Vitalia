from urllib.parse import quote

from dotenv import dotenv_values

from configurar import save_environment


def test_configuration_preserves_existing_keys_and_encodes_password(tmp_path):
    path = tmp_path / ".env"
    secret = "clave-de-sesion-anterior-que-debe-conservarse"
    path.write_text(f"SECRET_KEY='{secret}'\nMONGODB_URI='mongodb://ejemplo'\n")
    password = "Clave@#:%/de prueba"
    url = "postgresql://vitalia_app:" + quote(password, safe="") + "@127.0.0.1:55432/clinica_vitalia"
    save_environment(path, url)
    values = dotenv_values(path, interpolate=False)
    assert values["SECRET_KEY"] == secret
    assert values["MONGODB_URI"] == "mongodb://ejemplo"
    assert values["POSTGRES_URL"] == url
    assert values["DATA_BACKEND"] == "postgres"


def test_generated_session_key_is_stable_on_reconfiguration(tmp_path):
    path = tmp_path / ".env"
    save_environment(path, "postgresql://primera")
    first = dotenv_values(path)["SECRET_KEY"]
    save_environment(path, "postgresql://segunda")
    assert len(first) >= 24
    assert dotenv_values(path)["SECRET_KEY"] == first
