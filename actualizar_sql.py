import os
from pathlib import Path
import subprocess
from uuid import uuid4

from dotenv import dotenv_values
import psycopg


MIGRATIONS = (
    ("1.1", "07_validacion_dev03.sql"),
    ("1.2", "08_estado_pacientes.sql"),
    ("1.3", "09_agenda_persistente.sql"),
    ("1.4", "10_control_manual_citas.sql"),
    ("1.5", "11_regla_cierre_citas.sql"),
    ("1.6", "12_no_reabrir_citas.sql"),
    ("1.7", "13_categorias_especialidades.sql"),
    ("1.8", "14_datos_personal_usuarios.sql"),
    ("1.9", "15_solicitudes_cita.sql"),
)


def installed_versions(url):
    with psycopg.connect(url, connect_timeout=5) as connection:
        rows = connection.execute(
            "SELECT version FROM clinica.version_esquema"
        ).fetchall()

    return {row[0] for row in rows}


def verify_update(url):
    with psycopg.connect(url, connect_timeout=5) as connection:
        versions = {
            row[0]
            for row in connection.execute(
                "SELECT version FROM clinica.version_esquema"
            ).fetchall()
        }

        column = connection.execute(
            """
            SELECT data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'clinica'
              AND table_name = 'pacientes'
              AND column_name = 'activo'
            """
        ).fetchone()

    if not {"1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "1.8", "1.9"}.issubset(versions):
        raise SystemExit(
            "La base aún no registra todas las versiones hasta 1.8."
        )

    with psycopg.connect(url, connect_timeout=5) as connection:
        fields = {r[0] for r in connection.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='clinica' AND table_name='citas'"
        ).fetchall()}
    if not {"revision", "cierre_automatico"}.issubset(fields):
        raise SystemExit("La agenda está incompleta. Revisa la migración 1.3.")
    if column != ("boolean", "NO"):
        raise SystemExit(
            "La actualización está incompleta: falta pacientes.activo "
            "como booleano obligatorio. Revisa la migración 1.2."
        )


def main():
    root = Path(__file__).resolve().parent
    destination = "francisco@127.0.0.1"
    step = "leer la configuración"

    settings = {
        **dotenv_values(root / ".env", interpolate=False),
        **os.environ,
    }

    url = settings.get("POSTGRES_URL")

    if not url:
        raise SystemExit(
            "Falta POSTGRES_URL. Revisa la configuración local .env."
        )

    print("Actualización PostgreSQL de Clínica Vitalia")
    print("Mantén la VM encendida y el túnel SSH abierto.")

    try:
        step = "consultar las versiones por el túnel PostgreSQL"
        installed = installed_versions(url)

        if "1.0" not in installed:
            raise SystemExit(
                "No se encontró el esquema base 1.0. Revisa la conexión."
            )

        pending = [
            (version, filename)
            for version, filename in MIGRATIONS
            if version not in installed
        ]

        for version, filename in pending:
            local_file = root / "db" / "postgres" / filename

            if not local_file.is_file():
                raise SystemExit(
                    f"Falta db/postgres/{filename}. Recupera ese archivo."
                )

        for version, filename in pending:
            remote_file = (
                f"/tmp/vitalia_{version.replace('.', '_')}_"
                f"{uuid4().hex}.sql"
            )

            print(
                f"Aplicando migración {version}: {filename}",
                flush=True,
            )
            print(
                "SSH y sudo pueden pedir la contraseña "
                "de francisco en Ubuntu.",
                flush=True,
            )

            step = f"copiar la migración {version} a la VM"

            subprocess.run(
                [
                    "scp",
                    "-P",
                    "2222",
                    str(root / "db" / "postgres" / filename),
                    f"{destination}:{remote_file}",
                ],
                check=True,
            )

            step = f"ejecutar la migración {version} en PostgreSQL"

            subprocess.run(
                [
                    "ssh",
                    "-t",
                    "-p",
                    "2222",
                    destination,
                    f"chmod 644 {remote_file} && "
                    "sudo -u postgres psql -X -v ON_ERROR_STOP=1 "
                    f"-d clinica_vitalia -f {remote_file} "
                    f"&& rm -f {remote_file}",
                ],
                check=True,
            )

            step = f"comprobar la migración {version}"

            if version not in installed_versions(url):
                raise SystemExit(
                    "La conexión configurada no registra "
                    f"la versión {version}. "
                    "Revisa que POSTGRES_URL apunte "
                    "a la misma base de la VM."
                )

        step = "verificar la versión 1.6 y la columna activo"
        verify_update(url)

    except FileNotFoundError:
        raise SystemExit(
            "Windows necesita OpenSSH con los comandos ssh y scp."
        ) from None

    except subprocess.CalledProcessError as error:
        raise SystemExit(
            f"Falló el paso: {step}. "
            f"Código de salida: {error.returncode}. "
            "Revisa el error mostrado arriba."
        ) from None

    except psycopg.Error:
        raise SystemExit(
            f"Falló el paso: {step}. "
            "Comprueba el túnel, la conexión PostgreSQL, "
            "el esquema y los permisos."
        ) from None

    except KeyboardInterrupt:
        raise SystemExit(
            "Actualización cancelada por el usuario."
        ) from None

    print(
        "Versión 1.3, agenda persistente y columna pacientes.activo "
        "verificadas correctamente."
    )
    print("Ejecuta python run.py para iniciar la página.")


if __name__ == "__main__":
    main()