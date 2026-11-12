
from getpass import getpass
import os
from pathlib import Path
import secrets
import tempfile
from urllib.parse import quote

from dotenv import dotenv_values, set_key
import psycopg
from werkzeug.security import check_password_hash, generate_password_hash


def save_environment(path, database_url):
    previous = dotenv_values(path, interpolate=False)
    secret = previous.get("SECRET_KEY", "")
    if len(secret) < 24 or secret == "replace-with-a-local-development-key":
        secret = secrets.token_hex(32)
    descriptor, temporary_name = tempfile.mkstemp(prefix="vitalia-", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        if path.exists():
            temporary.write_bytes(path.read_bytes())
        for key, value in (
            ("DATA_BACKEND", "postgres"),
            ("POSTGRES_URL", database_url),
            ("SECRET_KEY", secret),
        ):
            set_key(temporary, key, value, quote_mode="always")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    root = Path(__file__).resolve().parent
    print("Clínica Vitalia — Configuración local")
    print("Mantén la máquina virtual y la pestaña del túnel SSH abiertas.")
    db_password = getpass("Contraseña PostgreSQL de vitalia_app: ")
    database_url = (
        "postgresql://vitalia_app:" + quote(db_password, safe="")
        + "@127.0.0.1:55432/clinica_vitalia"
    )
    try:
        with psycopg.connect(database_url, connect_timeout=5) as connection:
            versions = {row[0] for row in connection.execute("SELECT version FROM clinica.version_esquema")}
            if not {"1.0", "1.1", "1.2", "1.3"}.issubset(versions):
                raise SystemExit("Ejecuta primero python actualizar_sql.py y repite la configuración.")
            print("Conexión a PostgreSQL y versión 1.3 verificadas.")
            username = input("Usuario para entrar en la página [recepcion]: ").strip() or "recepcion"
            if len(username) < 3 or len(username) > 50:
                raise SystemExit("El usuario debe tener entre 3 y 50 caracteres.")
            password = getpass("Contraseña de esa cuenta web, mínimo 12 caracteres: ")
            confirmation = getpass("Repite la contraseña de la cuenta web: ")
            if len(password) < 12 or password != confirmation:
                raise SystemExit("Las contraseñas deben coincidir y tener al menos 12 caracteres.")
            existing = connection.execute(
                """SELECT u.password_hash, u.activo, r.nombre FROM clinica.usuarios u
                JOIN clinica.roles r USING (rol_id) WHERE lower(u.nombre_usuario)=lower(%s)""",
                (username,),
            ).fetchone()
            if existing:
                if not existing[1] or existing[2] not in {"RECEPCION", "ADMINISTRADOR"}:
                    raise SystemExit("Esa cuenta no está habilitada para recepción. Elige otra cuenta.")
                if not check_password_hash(existing[0], password):
                    raise SystemExit("La cuenta ya existe con otra contraseña. Usa su contraseña actual.")
            else:
                connection.execute(
                    """INSERT INTO clinica.usuarios(nombre_usuario,password_hash,rol_id)
                    SELECT %s,%s,rol_id FROM clinica.roles WHERE nombre='RECEPCION'""",
                    (username, generate_password_hash(password)),
                )
            save_environment(root / ".env", database_url)
    except psycopg.OperationalError:
        raise SystemExit("No se pudo autenticar la conexión. Comprueba el túnel y la contraseña PostgreSQL.") from None
    except psycopg.Error:
        raise SystemExit("Revisa que la instalación SQL esté completa y vitalia_app tenga sus permisos.") from None
    except OSError:
        raise SystemExit("No se pudo escribir .env. Comprueba los permisos de la carpeta del proyecto.") from None
    print("Configuración guardada en .env y cuenta web lista. Ejecuta python run.py.")


if __name__ == "__main__":
    main()
