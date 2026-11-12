import json
import os
from pathlib import Path

from dotenv import dotenv_values
from flask import Flask, g, render_template
from werkzeug.security import generate_password_hash

from .agenda import agenda_bp
from .clinical import clinical_bp
from .clinical_repository import PostgresClinicalRepository
from .billing import billing_bp
from .billing_repository import PostgresBillingRepository
from .message_repository import PostgresMessageRepository
from .messages import messages_bp
from .admin import admin_bp
from .appointment_repository import InMemoryAppointmentRepository
from .auth import auth_bp, csrf_token, load_current_user
from .database import (
    ConfigurationError, Database, DatabaseUnavailable,
    PostgresPatientRepository, PostgresUserRepository,
)
from .repository import InMemoryPatientRepository
from .postgres_appointments import PostgresAppointmentRepository, AppointmentPermissionError
from .routes import patients_bp
from .validation import local_today


def create_app(repository=None, auth_path=None, config=None):
    app = Flask(__name__)
    project_root = Path(__file__).resolve().parent.parent
    settings = {**dotenv_values(project_root / ".env", interpolate=False), **os.environ}
    app.config.update(
        DATA_BACKEND=settings.get("DATA_BACKEND", "postgres").lower(),
        POSTGRES_URL=settings.get("POSTGRES_URL", ""),
        SECRET_KEY=settings.get("SECRET_KEY", ""),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if config:
        app.config.update(config)
    # La inyección explícita conserva los contratos de las pruebas y del modo local.
    if repository is not None or auth_path is not None:
        app.config["DATA_BACKEND"] = "memory"
    mode = app.config["DATA_BACKEND"]
    if mode not in {"postgres", "memory"}:
        raise ConfigurationError("DATA_BACKEND debe ser postgres o memory.")

    if mode == "postgres":
        if not app.config["POSTGRES_URL"] or len(app.config["SECRET_KEY"]) < 24:
            raise ConfigurationError("Completa la configuración local ejecutando python configurar.py.")
        database = Database(app.config["POSTGRES_URL"])
        database.verify_schema()
        app.config["DATABASE"] = database
        app.config["PATIENT_REPOSITORY"] = PostgresPatientRepository(database)
        app.config["USER_REPOSITORY"] = PostgresUserRepository(database)
    else:
        app.config["SECRET_KEY"] = app.config["SECRET_KEY"] or "dev-only-secret"
        app.config["DEMO_USER"] = "recepcion"
        app.config["DEMO_PASSWORD"] = "Recepcion123!"
        users = {"recepcion": generate_password_hash(app.config["DEMO_PASSWORD"])}
        users_path = Path(auth_path) if auth_path else Path(app.instance_path) / "users.json"
        if repository is None or auth_path is not None:
            if users_path.exists():
                try:
                    users.update(json.loads(users_path.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    app.logger.exception("No se pudo leer el archivo local de usuarios")
        app.config["AUTH_USERS"] = users
        app.config["AUTH_USERS_PATH"] = users_path
        app.config["PATIENT_REPOSITORY"] = (
            repository if repository is not None else InMemoryPatientRepository()
        )

    app.config["APPOINTMENT_REPOSITORY"] = (
        PostgresAppointmentRepository(database, lambda: g.current_user.user_id if g.current_user else None)
        if mode == "postgres" else InMemoryAppointmentRepository()
    )
    if mode == "postgres":
        from .database import PostgresAdministrationRepository
        app.config["ADMIN_REPOSITORY"] = PostgresAdministrationRepository(database)
        app.config["CLINICAL_REPOSITORY"] = PostgresClinicalRepository(database)
        app.config["BILLING_REPOSITORY"] = PostgresBillingRepository(database)
        app.config["MESSAGE_REPOSITORY"] = PostgresMessageRepository(database)
    app.before_request(load_current_user)
    app.context_processor(lambda: {"csrf_token": csrf_token})
    app.context_processor(lambda: {"today": local_today().isoformat()})
    app.register_blueprint(auth_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(agenda_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(clinical_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(messages_bp)

    @app.errorhandler(DatabaseUnavailable)
    def database_error(error):
        app.logger.warning("Operación interrumpida por falta de conexión con PostgreSQL")
        return render_template(
            "error.html", error_title="La conexión necesita un momento",
            error_message="Comprueba que la máquina virtual y el túnel estén activos. Luego intenta nuevamente.",
        ), 503

    @app.errorhandler(AppointmentPermissionError)
    @app.errorhandler(403)
    def forbidden(error):
        return render_template(
            "error.html", error_title="Acceso restringido",
            error_message="Tu cuenta no tiene permiso para abrir este módulo.",
        ), 403

    @app.errorhandler(500)
    def internal_error(error):
        return render_template(
            "error.html", error_title="No pudimos completar la operación",
            error_message="Intenta nuevamente. Si continúa, comunícalo al administrador.",
        ), 500

    return app
