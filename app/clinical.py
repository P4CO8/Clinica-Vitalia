from uuid import uuid4

import psycopg
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from .auth import administrator_required, require_csrf
from .database import DatabaseUnavailable


clinical_bp = Blueprint("clinical", __name__, url_prefix="/clinica")


def clinical_repository():
    if current_app.config["DATA_BACKEND"] != "postgres":
        abort(403)
    return current_app.config["CLINICAL_REPOSITORY"]


def clinical_access(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.current_user or g.current_user.role not in {"MEDICO", "ADMINISTRADOR"}:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


@clinical_bp.get("/")
@clinical_access
def index():
    repo = clinical_repository()
    return render_template(
        "clinical/index.html",
        appointments=repo.appointments(g.current_user),
        medications=repo.medications(),
        active_module="clinica",
    )


@clinical_bp.get("/pacientes/<patient_id>/historia")
@clinical_access
def history(patient_id):
    repo = clinical_repository()
    if not repo.can_view_history(patient_id, g.current_user):
        abort(403)
    return render_template(
        "clinical/history.html",
        patient=repo.patient(patient_id),
        records=repo.history(patient_id),
        active_module="clinica",
    )


@clinical_bp.post("/citas/<appointment_id>/atencion")
@clinical_access
def register_attention(appointment_id):
    require_csrf()
    values = {
        "reason": request.form.get("reason", "").strip(),
        "diagnosis": request.form.get("diagnosis", "").strip(),
        "diagnosis_code": request.form.get("diagnosis_code", "").strip(),
        "treatment": request.form.get("treatment", "").strip(),
        "medication_id": request.form.get("medication_id", "").strip(),
        "dose": request.form.get("dose", "").strip(),
        "frequency": request.form.get("frequency", "").strip(),
        "duration": request.form.get("duration", "").strip(),
    }
    if not values["reason"] or not values["diagnosis"] or not values["treatment"]:
        flash("Motivo, diagnóstico y tratamiento son obligatorios.", "error")
        return redirect(url_for("clinical.index"))
    try:
        clinical_repository().register_attention(appointment_id, g.current_user, values)
    except ValueError as error:
        flash(str(error), "error")
    except (psycopg.Error, DatabaseUnavailable):
        current_app.logger.exception("No se pudo registrar la atención clínica")
        flash("No se registró la atención. No se guardaron cambios parciales.", "error")
    else:
        flash("Atención clínica registrada correctamente.", "success")
    return redirect(url_for("clinical.index"))
