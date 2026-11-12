import re
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from .auth import administrator_required, require_csrf
from .database import DatabaseUnavailable
import psycopg


admin_bp = Blueprint("admin", __name__, url_prefix="/administracion")
SPECIALTY_CATEGORIES = (
    "Especialidades Clínicas (Médicas)",
    "Especialidades Quirúrgicas",
    "Medicina Crítica y Diagnóstica",
)


def administration():
    if current_app.config["DATA_BACKEND"] != "postgres":
        abort(403)
    return current_app.config["ADMIN_REPOSITORY"]


@admin_bp.get("/")
@administrator_required
def index():
    repo = administration()
    return render_template(
        "admin/index.html", users=repo.users(), doctors=repo.doctors(),
        specialties=repo.specialties(), specialty_categories=SPECIALTY_CATEGORIES,
        roles=repo.roles(),
        doctor_users=repo.available_doctor_users(), active_module="administracion",
    )


@admin_bp.post("/usuarios")
@administrator_required
def create_user():
    require_csrf()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    role_id = request.form.get("role_id", "")
    personal_data = {
        "first_names": request.form.get("first_names", "").strip(),
        "last_names": request.form.get("last_names", "").strip(),
        "document_type": request.form.get("document_type", "").strip(),
        "document_number": request.form.get("document_number", "").strip(),
        "phone": request.form.get("phone", "").strip(),
        "training": request.form.get("training", "").strip(),
        "occupational": request.form.get("occupational", "").strip(),
        "biosecurity": request.form.get("biosecurity", "").strip(),
        "backgrounds": request.form.get("backgrounds", "").strip(),
        "financial": request.form.get("financial", "").strip(),
    }
    if (
        not 3 <= len(username) <= 50
        or not re.search(r"[A-Z]", password)
        or not re.search(r"[^A-Za-z0-9]", password)
        or not role_id.isdigit()
        or not personal_data["first_names"]
        or not personal_data["last_names"]
        or personal_data["document_type"] not in {"CC", "TI", "CE", "PAS"}
        or not personal_data["document_number"]
        or len(personal_data["first_names"]) > 100
        or len(personal_data["last_names"]) > 100
        or len(personal_data["document_number"]) > 20
        or len(personal_data["phone"]) > 15
        or any(len(value) > 500 for value in personal_data.values())
    ):
        flash("Completa los datos obligatorios y verifica la contraseña: debe incluir una mayúscula y un carácter especial.", "error")
        return redirect(url_for("admin.index"))
    try:
        administration().create_user(username, generate_password_hash(password), int(role_id), personal_data)
    except psycopg.errors.UniqueViolation:
        flash("Ese usuario ya existe.", "error")
    except (psycopg.Error, DatabaseUnavailable):
        current_app.logger.exception("No se pudo crear el usuario")
        flash("No se pudo crear el usuario.", "error")
    else:
        flash("Usuario creado correctamente. Sus permisos se activaron según el rol asignado.", "success")
    return redirect(url_for("admin.index"))


@admin_bp.post("/usuarios/<user_id>/estado")
@administrator_required
def user_status(user_id):
    require_csrf()
    requested = request.form.get("activo")
    if requested not in {"true", "false"}:
        abort(400)
    try:
        result = administration().set_user_active(
            user_id, requested == "true", g.current_user.user_id
        )
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("admin.index"))
    except (psycopg.Error, DatabaseUnavailable):
        current_app.logger.exception("No se pudo actualizar el estado del usuario")
        flash("No se puede desactivar al último administrador activo.", "error")
        return redirect(url_for("admin.index"))
    if result is None:
        abort(404)
    flash("Estado de usuario actualizado.", "success")
    return redirect(url_for("admin.index"))


@admin_bp.post("/especialidades")
@administrator_required
def create_specialty():
    require_csrf()
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip()
    if not name or len(name) > 100 or category not in SPECIALTY_CATEGORIES:
        flash("La especialidad debe tener entre 1 y 100 caracteres.", "error")
    else:
        try:
            administration().create_specialty(name, category)
        except psycopg.errors.UniqueViolation:
            flash("Esa especialidad ya existe.", "error")
        except (psycopg.Error, DatabaseUnavailable):
            current_app.logger.exception("No se pudo crear la especialidad")
            flash("No se pudo crear la especialidad.", "error")
        else:
            flash("Especialidad creada correctamente.", "success")
    return redirect(url_for("admin.index"))


@admin_bp.post("/medicos")
@administrator_required
def create_doctor():
    require_csrf()
    name = request.form.get("name", "").strip()
    professional_id = request.form.get("professional_id", "").strip()
    user_id = request.form.get("user_id", "").strip()
    specialty_ids = [value for value in request.form.getlist("specialty_ids") if value.isdigit()]
    if not name or not professional_id or not user_id or len(name) > 200 or len(professional_id) > 40:
        flash("Verifica el nombre y el registro profesional.", "error")
        return redirect(url_for("admin.index"))
    try:
        administration().create_doctor(name, professional_id, user_id, specialty_ids)
    except psycopg.errors.UniqueViolation:
        flash("El registro profesional o usuario ya está asociado.", "error")
    except (psycopg.Error, DatabaseUnavailable):
        current_app.logger.exception("No se pudo crear el médico")
        flash("No se pudo crear el médico.", "error")
    except ValueError as error:
        flash(str(error), "error")
    else:
        flash("Médico creado correctamente.", "success")
    return redirect(url_for("admin.index"))


@admin_bp.post("/medicos/<doctor_id>/estado")
@administrator_required
def doctor_status(doctor_id):
    require_csrf()
    requested = request.form.get("activo")
    if requested not in {"true", "false"}:
        abort(400)
    if administration().set_doctor_active(doctor_id, requested == "true") is None:
        abort(404)
    flash("Estado del médico actualizado.", "success")
    return redirect(url_for("admin.index"))
