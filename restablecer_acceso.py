
from getpass import getpass
from pathlib import Path
import sys


def reset_password(database, username, password, confirmation):
    from werkzeug.security import generate_password_hash

    if password != confirmation or not 12 <= len(password) <= 1024:
        raise ValueError("Las contraseñas deben coincidir y tener entre 12 y 1024 caracteres.")
    with database.connect() as connection:
        user = connection.execute(
            "SELECT usuario_id, activo FROM clinica.usuarios "
            "WHERE lower(nombre_usuario)=lower(%s) FOR UPDATE",
            (username,),
        ).fetchone()
        if user is None:
            raise ValueError("Esa cuenta no existe. Revisa el nombre de usuario.")
        if not user["activo"]:
            raise ValueError("La cuenta está inactiva. El administrador debe revisar su acceso.")
        connection.execute(
            "UPDATE clinica.usuarios SET password_hash=%s WHERE usuario_id=%s",
            (generate_password_hash(password), user["usuario_id"]),
        )


def main():
    root = Path(__file__).resolve().parent
    if not (root / "app" / "__init__.py").is_file():
        root = Path.cwd()
    if not (root / "app" / "__init__.py").is_file():
        raise SystemExit("Copia este archivo junto a run.py y ejecútalo desde esa carpeta.")
    sys.path.insert(0, str(root))
    try:
        from app import create_app
        from app.database import ConfigurationError, DatabaseUnavailable
        import psycopg
    except ImportError:
        raise SystemExit("Instala primero las dependencias: python -m pip install -r requirements.txt") from None
    try:
        application = create_app()
        if application.config["DATA_BACKEND"] != "postgres":
            raise ValueError("Ejecuta python configurar.py para habilitar PostgreSQL.")
        print("Clínica Vitalia — Recuperación de acceso web")
        username = input("Usuario de la página [francisco]: ").strip() or "francisco"
        if not 3 <= len(username) <= 50:
            raise ValueError("El nombre de usuario debe tener entre 3 y 50 caracteres.")
        password = getpass("Nueva contraseña de la página, mínimo 12 caracteres: ")
        confirmation = getpass("Repite la nueva contraseña: ")
        reset_password(application.config["DATABASE"], username, password, confirmation)
    except (ValueError, ConfigurationError, DatabaseUnavailable) as error:
        raise SystemExit(str(error)) from None
    except psycopg.Error:
        raise SystemExit("No se pudo actualizar la cuenta. Comprueba los permisos de PostgreSQL.") from None
    except (KeyboardInterrupt, EOFError):
        raise SystemExit("Recuperación cancelada.") from None
    print(f"Contraseña web actualizada para {username}.")
    print("Abre http://127.0.0.1:5001 e ingresa con tu nueva contraseña.")


if __name__ == "__main__":
    main()
