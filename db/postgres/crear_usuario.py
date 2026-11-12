import argparse
from getpass import getpass
import os
import re
from pathlib import Path
from dotenv import dotenv_values

import psycopg
from werkzeug.security import generate_password_hash

parser = argparse.ArgumentParser(description="Crear una cuenta web de Clínica Vitalia")
parser.add_argument("usuario")
parser.add_argument("rol", choices=["ADMINISTRADOR", "RECEPCION", "MEDICO", "FACTURACION"])
args = parser.parse_args()
settings = {**dotenv_values(Path(__file__).resolve().parents[2] / ".env", interpolate=False), **os.environ}
url = settings.get("POSTGRES_URL")
if not url:
    parser.error("Define POSTGRES_URL con la conexión local.")
if args.usuario != args.usuario.strip() or len(args.usuario) < 3:
    parser.error("El usuario debe tener al menos tres caracteres, sin espacios en los extremos.")
password = getpass("Contraseña de la cuenta web: ")
confirmation = getpass("Confirma la contraseña: ")
if password != confirmation or not re.search(r"[A-Z]", password) or not re.search(r"[^A-Za-z0-9]", password):
    parser.error("La contraseña debe coincidir y tener una mayúscula y un carácter especial.")
try:
    with psycopg.connect(url) as connection:
        row = connection.execute(
            """INSERT INTO clinica.usuarios (nombre_usuario,password_hash,rol_id)
            SELECT %s,%s,rol_id FROM clinica.roles WHERE nombre=%s
            RETURNING usuario_id""",
            (args.usuario, generate_password_hash(password), args.rol),
        ).fetchone()
        if not row:
            parser.error("El rol no existe. Ejecuta primero la instalación SQL.")
    print("Cuenta creada. ID", row[0])
except psycopg.errors.UniqueViolation:
    parser.error("El nombre de usuario ya está registrado.")
