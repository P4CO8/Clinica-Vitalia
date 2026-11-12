import re
from flask import abort, Blueprint, current_app, flash, g, redirect, render_template, request, url_for

from .auth import login_required, reception_required, require_csrf
from .appointment_repository import DOCTORS, available_actions, patient_appointments
from .database import DatabaseUnavailable
from .repository import DuplicateDocumentError, PatientValidationError
from .validation import DOCUMENT_TYPES, normalize_name, validate_patient_form


patients_bp = Blueprint("patients", __name__)


def empty_form():
    return {
        "first_names": "", "last_names": "", "document_type": "", "document_number": "",
        "birth_date": "", "phone": "", "blood_type": "",
    }


@patients_bp.get("/")
@login_required
def legacy_home():
    return redirect(url_for("patients.home"))


@patients_bp.get("/inicio")
@login_required
@reception_required
def home():
    if g.current_user and g.current_user.role == "ADMINISTRADOR":
        return redirect(url_for("admin.index"))
    return render_template("home.html", active_module="inicio")


@patients_bp.get("/pacientes")
@login_required
@reception_required
def directory():
    selected_filter = request.args.get("estado", "todos")
    if selected_filter not in {"todos", "activos", "inactivos"}:
        abort(400)
    patients = current_app.config["PATIENT_REPOSITORY"].list_all()
    if selected_filter == "activos":
        patients = [patient for patient in patients if patient.active]
    elif selected_filter == "inactivos":
        patients = [patient for patient in patients if not patient.active]
    return render_template(
        "patients/index.html",
        patients=patients, selected_filter=selected_filter,
        attention_by_patient=patient_appointments(current_app.config["APPOINTMENT_REPOSITORY"].list_all()),
        attention_doctors={doctor.doctor_id: doctor for doctor in current_app.config["APPOINTMENT_REPOSITORY"].list_doctors()},
        attention_actions=available_actions,
        attention_now=current_app.config["APPOINTMENT_REPOSITORY"].now(),
        active_module="pacientes",
    )


@patients_bp.get("/pacientes/nuevo")
@login_required
@reception_required
def new_patient():
    return render_template(
        "patients/new.html",
        form=empty_form(),
        errors={},
        document_types=DOCUMENT_TYPES,
        active_module="pacientes",
    )


@patients_bp.route("/pacientes/<internal_id>/editar", methods=["GET", "POST"])
@login_required
@reception_required
def edit_patient(internal_id):
    patient = next((p for p in current_app.config["PATIENT_REPOSITORY"].list_all()
                    if p.internal_id == internal_id), None)
    if patient is None:
        abort(404)
    form = {
        "first_names": patient.first_names, "last_names": patient.last_names,
        "document_type": patient.document_type, "document_number": patient.document_number,
        "birth_date": patient.birth_date, "phone": patient.phone, "blood_type": patient.blood_type,
    }
    errors = {}
    if request.method == "POST":
        require_csrf()
        form = {key: request.form.get(key, "").strip() for key in form}
        form["first_names"] = normalize_name(form["first_names"])
        form["last_names"] = normalize_name(form["last_names"])
        errors = validate_patient_form(**form)
        if not errors:
            try:
                updated = current_app.config["PATIENT_REPOSITORY"].update(internal_id, **form)
            except DuplicateDocumentError:
                errors["document_number"] = "Este documento ya está registrado."
            except PatientValidationError as error:
                errors = error.errors
            else:
                if updated is None:
                    abort(404)
                flash("Paciente actualizado correctamente.", "success")
                return redirect(url_for("patients.directory"))
    return render_template(
        "patients/edit.html", form=form, errors=errors,
        document_types=DOCUMENT_TYPES, patient=patient, active_module="pacientes",
    ), 400 if errors else 200


@patients_bp.route("/pacientes", methods=["POST"])
@patients_bp.post("/patients")
@login_required
@reception_required
def create_patient():
    form = {
        key: request.form.get(key, "").strip()
        for key in ("first_names", "last_names", "document_type", "document_number", "birth_date", "phone", "blood_type")
    }
    # Compatibilidad con el formulario anterior durante la transición.
    if not form["first_names"] and request.form.get("name"):
        form["first_names"] = request.form.get("name", "").strip()
    if not form["document_number"] and request.form.get("document"):
        form["document_number"] = request.form.get("document", "").strip()
    form["first_names"] = normalize_name(form["first_names"])
    form["last_names"] = normalize_name(form["last_names"])
    errors = validate_patient_form(**form)
    if errors:
        return render_template("patients/new.html", form=form, errors=errors, document_types=DOCUMENT_TYPES, active_module="pacientes"), 400
    try:
        current_app.config["PATIENT_REPOSITORY"].add(**form)
    except DuplicateDocumentError:
        errors["document_number"] = "Este documento ya está registrado."
        return render_template("patients/new.html", form=form, errors=errors, document_types=DOCUMENT_TYPES, active_module="pacientes"), 400
    except PatientValidationError as error:
        return render_template("patients/new.html", form=form, errors=error.errors, document_types=DOCUMENT_TYPES, active_module="pacientes"), 400
    except DatabaseUnavailable:
        raise
    except Exception:
        current_app.logger.exception("No se pudo registrar el paciente")
        flash("No se pudo registrar al paciente. Intenta de nuevo.", "error")
        return render_template("patients/new.html", form=form, errors={}, document_types=DOCUMENT_TYPES, active_module="pacientes"), 500
    flash("Paciente registrado correctamente.", "success")
    return redirect(url_for("patients.directory"))


@patients_bp.post("/pacientes/<internal_id>/estado")
@login_required
@reception_required
def change_status(internal_id):
    require_csrf()
    requested = request.form.get("activo", "")
    if requested not in {"true", "false"} or not re.fullmatch(r"PAC-[0-9A-Fa-f]{8,32}", internal_id):
        abort(400)
    patient = current_app.config["PATIENT_REPOSITORY"].set_active(internal_id, requested == "true")
    if patient is None:
        abort(404)
    flash("Paciente activado." if patient.active else "Paciente desactivado. Su historial se conserva.", "success")
    return redirect(url_for("patients.directory", estado=request.form.get("estado", "todos")))


@patients_bp.post("/pacientes/cancelar")
@login_required
@reception_required
def cancel_new_patient():
    return redirect(url_for("patients.directory"))
