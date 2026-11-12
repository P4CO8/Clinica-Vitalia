from functools import wraps

import psycopg
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from .auth import require_csrf
from .database import DatabaseUnavailable


messages_bp = Blueprint("messages", __name__, url_prefix="/mensajes")


def message_access(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.current_user or g.current_user.role not in {"MEDICO", "RECEPCION", "ADMINISTRADOR"}:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


@messages_bp.get("/")
@message_access
def index():
    repo = current_app.config["MESSAGE_REPOSITORY"]
    return render_template(
        "messages/index.html",
        messages=repo.list_for(g.current_user),
        appointments=repo.doctor_appointments(g.current_user),
        active_module="mensajes",
    )


@messages_bp.post("/enviar")
@message_access
def send():
    require_csrf()
    if g.current_user.role != "MEDICO":
        abort(403)
    appointment_id = request.form.get("appointment_id", "").strip()
    message_type = request.form.get("message_type", "").strip()
    body = request.form.get("body", "").strip()
    if message_type not in {"CANCELAR_CITA", "NOTA"} or not body or len(body) > 2000:
        flash("Selecciona el tipo de solicitud y escribe un mensaje válido.", "error")
        return redirect(url_for("messages.index"))
    try:
        current_app.config["MESSAGE_REPOSITORY"].send(
            appointment_id, g.current_user, message_type, body
        )
    except ValueError as error:
        flash(str(error), "error")
    except (psycopg.Error, DatabaseUnavailable):
        current_app.logger.exception("No se pudo enviar el mensaje a recepción")
        flash("No se pudo enviar el mensaje. Intenta nuevamente.", "error")
    else:
        flash("Mensaje enviado a Recepción.", "success")
    return redirect(url_for("messages.index"))


@messages_bp.post("/<message_id>/resolver")
@message_access
def resolve(message_id):
    require_csrf()
    if g.current_user.role not in {"RECEPCION", "ADMINISTRADOR"}:
        abort(403)
    action = request.form.get("action", "")
    if action not in {"RESUELTO", "CANCELAR_CITA"}:
        abort(400)
    try:
        current_app.config["MESSAGE_REPOSITORY"].resolve(message_id, g.current_user, action)
    except ValueError as error:
        flash(str(error), "error")
    except (psycopg.Error, DatabaseUnavailable):
        current_app.logger.exception("No se pudo resolver el mensaje")
        flash("No se pudo resolver la solicitud.", "error")
    else:
        flash("Solicitud gestionada correctamente.", "success")
    return redirect(url_for("messages.index"))
