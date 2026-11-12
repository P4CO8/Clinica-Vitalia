import re
from datetime import datetime
from uuid import uuid4

from flask import abort, Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from .auth import login_required, reception_required, require_csrf
from .database import DatabaseUnavailable
from .validation import COLOMBIA_TIMEZONE
from .appointment_repository import (
    AppointmentConflictError, AppointmentNotFoundError, AppointmentStateError, available_actions,
)


agenda_bp = Blueprint("agenda", __name__)
FORM_FIELDS = ("patient_id", "doctor_id", "date", "start_time", "end_time", "appointment_id")


def repository():
    return current_app.config["APPOINTMENT_REPOSITORY"]


def new_identifier():
    identifier = f"CIT-{uuid4().hex}"
    session["appointment_requests"] = (session.get("appointment_requests", []) + [identifier])[-20:]
    return identifier


def empty_form():
    return {**dict.fromkeys(FORM_FIELDS, ""), "appointment_id": new_identifier()}


def render_new(form, errors, status=200, appointment=None):
    patients = [p for p in current_app.config["PATIENT_REPOSITORY"].list_all() if p.active]
    return render_template(
        "agenda/new.html", form=form, errors=errors, patients=patients,
        doctors=[d for d in repository().list_doctors() if d.active],
        active_module="agenda", appointment=appointment,
    ), status


def parse_interval(form):
    errors = {}
    values = []
    for field, label in (("start_time", "Verifica la fecha y hora de inicio."),
                         ("end_time", "Verifica la hora de fin.")):
        try:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", form.get("date", "")) or not re.fullmatch(r"[0-9]{2}:[0-9]{2}", form.get(field, "")):
                raise ValueError
            value = datetime.fromisoformat(f"{form['date']}T{form[field]}").replace(tzinfo=COLOMBIA_TIMEZONE)
        except ValueError:
            value = None
            errors["date" if field == "start_time" else field] = label
        values.append(value)
    start, end = values
    if start and end and end <= start:
        errors["end_time"] = "La hora de fin debe ser posterior al inicio."
    if start and start < datetime.now(COLOMBIA_TIMEZONE):
        errors["start_time"] = "Selecciona una fecha y hora que aún no hayan pasado."
    return start, end, errors


def find_appointment(appointment_id):
    if not re.fullmatch(r"CIT-[A-Za-z0-9_-]{8,35}", appointment_id):
        abort(400)
    item = next((a for a in repository().list_all() if a.appointment_id == appointment_id), None)
    if item is None:
        abort(404)
    return item


def expected_revision():
    value = request.form.get("revision", "")
    if not value and current_app.config["DATA_BACKEND"] == "memory":
        return None
    if not re.fullmatch(r"[0-9]{1,10}", value) or int(value) > 2147483647:
        abort(400)
    return int(value)


@agenda_bp.get("/agenda")
@login_required
@reception_required
def index():
    patients = {p.internal_id: p for p in current_app.config["PATIENT_REPOSITORY"].list_all()}
    doctors = {d.doctor_id: d for d in repository().list_doctors()}
    show_history = request.args.get("historial") == "1"
    all_appointments = repository().list_all()
    appointments = (
        [item for item in all_appointments if item.status == "CANCELADA"]
        if show_history
        else [item for item in all_appointments if item.status != "CANCELADA"]
    )
    return render_template(
        "agenda/index.html", appointments=appointments, patients=patients, doctors=doctors,
        show_history=show_history,
        active_module="agenda", attention_actions=available_actions, attention_now=repository().now(),
    )


@agenda_bp.get("/agenda/nueva")
@login_required
@reception_required
def new():
    return render_new(empty_form(), {})


@agenda_bp.post("/agenda")
@login_required
@reception_required
def create():
    if current_app.config["DATA_BACKEND"] == "postgres":
        require_csrf()
    form = {key: request.form.get(key, "").strip() for key in FORM_FIELDS}
    if not form["appointment_id"] and current_app.config["DATA_BACKEND"] == "memory":
        form["appointment_id"] = new_identifier()
    if not re.fullmatch(r"CIT-[A-Za-z0-9_-]{8,35}", form["appointment_id"]):
        abort(400)
    if current_app.config["DATA_BACKEND"] == "postgres" and form["appointment_id"] not in session.get("appointment_requests", []):
        abort(400)
    start, end, errors = parse_interval(form)
    patient_ids = {p.internal_id for p in current_app.config["PATIENT_REPOSITORY"].list_all() if p.active}
    doctor_ids = {d.doctor_id for d in repository().list_doctors() if d.active}
    if not form["patient_id"]:
        errors["patient_id"] = "Selecciona un paciente."
    elif form["patient_id"] not in patient_ids:
        errors["patient_id"] = "Selecciona un paciente válido."
    if form["doctor_id"] not in doctor_ids:
        errors["doctor_id"] = "Selecciona un médico válido."
    if errors:
        return render_new(form, errors, 400)
    try:
        repository().add(form["patient_id"], form["doctor_id"], start, end,
                         appointment_id=form["appointment_id"])
    except AppointmentConflictError:
        errors["start_time"] = "El médico ya tiene una cita en ese horario."
        return render_new(form, errors, 400)
    except AppointmentStateError as error:
        errors["start_time"] = str(error)
        return render_new(form, errors, 400)
    except DatabaseUnavailable:
        raise
    except PermissionError:
        raise
    except Exception:
        current_app.logger.exception("No se pudo agendar la cita")
        flash("No se pudo agendar la cita. Intenta de nuevo.", "error")
        return render_new(form, {}, 500)
    flash("Cita agendada correctamente.", "success")
    return redirect(url_for("agenda.index"))


@agenda_bp.post("/agenda/<appointment_id>/estado")
@login_required
@reception_required
def change_status(appointment_id):
    require_csrf()
    status = request.form.get("estado_cita", "")
    force = request.form.get("forzar") == "1"
    destination = request.form.get("volver", "agenda")
    selected_filter = request.form.get("filtro", "todos")
    if (status not in {"PENDIENTE", "EN_ATENCION", "CERRADA", "CANCELADA"} or destination not in {"agenda", "pacientes"}
            or selected_filter not in {"todos", "activos", "inactivos"}):
        abort(400)
    revision = expected_revision()
    appointment = find_appointment(appointment_id)
    patient = next((p for p in current_app.config["PATIENT_REPOSITORY"].list_all()
                    if p.internal_id == appointment.patient_id), None)
    if patient is None:
        abort(404)
    try:
        updated = repository().change_status(appointment_id, status, patient_active=patient.active,
                                             expected_revision=revision, force=force)
    except AppointmentNotFoundError:
        abort(404)
    except AppointmentStateError as error:
        return render_template("error.html", error_title="Revisa el estado de la cita", error_message=str(error)), 409
    flash("Estado de la cita: " + updated.status_label + ".", "success")
    if destination == "pacientes":
        return redirect(url_for("patients.directory", estado=selected_filter), code=303)
    return redirect(url_for("agenda.index"), code=303)


@agenda_bp.route("/agenda/<appointment_id>/reprogramar", methods=["GET", "POST"])
@login_required
@reception_required
def reschedule(appointment_id):
    if request.method == "POST":
        require_csrf()
    appointment = find_appointment(appointment_id)
    if appointment.status != "PENDIENTE":
        return render_template("error.html", error_title="La cita ya cambió de estado",
                               error_message="Solo se reprograman citas pendientes y vigentes."), 409
    patients = {p.internal_id: p for p in current_app.config["PATIENT_REPOSITORY"].list_all()}
    doctors = {d.doctor_id: d for d in repository().list_doctors()}
    patient = patients.get(appointment.patient_id)
    doctor = doctors.get(appointment.doctor_id)
    if not patient or not doctor or not patient.active or not doctor.active:
        return render_template("error.html", error_title="Revisa los datos de la cita",
                               error_message="El paciente y el médico deben estar activos para reprogramar."), 409
    form = {"date": appointment.start_at.strftime("%Y-%m-%d"), "start_time": appointment.start_at.strftime("%H:%M"),
            "end_time": appointment.end_at.strftime("%H:%M"), "revision": str(appointment.revision)}
    errors, code = {}, 200
    if request.method == "POST":
        form = {key: request.form.get(key, "").strip() for key in form}
        revision = expected_revision()
        start, end, errors = parse_interval(form)
        code = 400 if errors else 200
        if not errors:
            try:
                repository().reschedule(appointment_id, start, end, expected_revision=revision)
            except AppointmentConflictError:
                errors["start_time"] = "El médico ya tiene una cita en ese horario. La cita original se conserva."
                code = 400
            except AppointmentNotFoundError:
                abort(404)
            except AppointmentStateError as error:
                errors["start_time"] = str(error)
                code = 409
            else:
                flash("Cita reprogramada correctamente.", "success")
                return redirect(url_for("agenda.index"), code=303)
    return render_template("agenda/reschedule.html", appointment=appointment, patient=patient,
                           doctor=doctor, form=form, errors=errors, active_module="agenda"), code
