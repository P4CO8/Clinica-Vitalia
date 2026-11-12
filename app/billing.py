import psycopg
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, session, url_for
from uuid import uuid4

from .auth import require_csrf
from .database import DatabaseUnavailable


billing_bp = Blueprint("billing", __name__, url_prefix="/facturacion")


def billing_access(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.current_user or g.current_user.role not in {"FACTURACION", "ADMINISTRADOR"}:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def billing_repository():
    repository = current_app.config.get("BILLING_REPOSITORY")
    if repository is None:
        raise DatabaseUnavailable("Facturación requiere el modo PostgreSQL.")
    return repository


@billing_bp.get("/")
@billing_access
def index():
    repo = billing_repository()
    invoices = repo.invoices()
    request_ids = session.setdefault("billing_request_ids", {})
    for invoice in invoices:
        invoice_id = str(invoice["factura_id"])
        request_ids.setdefault(invoice_id, str(uuid4()))
    session.modified = True
    return render_template(
        "billing/index.html",
        invoices=invoices,
        patients=repo.patients(),
        services=repo.services(),
        active_module="facturacion",
    )


@billing_bp.post("/facturas")
@billing_access
def create_invoice():
    require_csrf()
    patient_id = request.form.get("patient_id", "").strip()
    service_id = request.form.get("service_id", "").strip()
    try:
        invoice_id = billing_repository().create_invoice(
            g.current_user.user_id, patient_id, service_id, request.form.get("quantity")
        )
    except ValueError as error:
        flash(str(error), "error")
    except (psycopg.Error, DatabaseUnavailable):
        current_app.logger.exception("No se pudo crear la factura")
        flash("No se pudo crear la factura. No se guardaron cambios parciales.", "error")
    else:
        flash(f"Factura creada como borrador: {invoice_id}.", "success")
    return redirect(url_for("billing.index"))


@billing_bp.post("/facturas/<invoice_id>/emitir")
@billing_access
def issue_invoice(invoice_id):
    require_csrf()
    try:
        billing_repository().issue_invoice(
            invoice_id, g.current_user.user_id
        )
    except (psycopg.Error, DatabaseUnavailable):
        current_app.logger.exception("No se pudo emitir la factura")
        flash("No se pudo emitir la factura. Verifica que tenga detalle.", "error")
    else:
        flash("Factura emitida correctamente.", "success")
    return redirect(url_for("billing.index"))


@billing_bp.post("/facturas/<invoice_id>/pagos")
@billing_access
def register_payment(invoice_id):
    require_csrf()
    try:
        billing_repository().register_payment(
            invoice_id, request.form.get("amount"), request.form.get("method"),
            request.form.get("reference", "").strip(), g.current_user.user_id,
            request.form.get("solicitud_id", "").strip(),
        )
    except ValueError as error:
        flash(str(error), "error")
    except (psycopg.Error, DatabaseUnavailable):
        current_app.logger.exception("No se pudo registrar el pago")
        flash("No se pudo registrar el pago. Verifica el saldo y el estado de la factura.", "error")
    else:
        session.setdefault("billing_request_ids", {}).pop(str(invoice_id), None)
        session.modified = True
        flash("Pago registrado correctamente.", "success")
    return redirect(url_for("billing.index"))
