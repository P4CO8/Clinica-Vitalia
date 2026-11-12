from functools import wraps
import secrets

from flask import Blueprint, abort, current_app, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash


auth_bp = Blueprint("auth", __name__)


def csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def require_csrf():
    token = session.get("_csrf_token")
    submitted = request.form.get("_csrf_token", "")
    if not token or not secrets.compare_digest(submitted, token):
        abort(400, description="Solicitud no válida.")


def find_registered_user(username):
    normalized = username.casefold()
    return next(
        (registered for registered in current_app.config["AUTH_USERS"] if registered.casefold() == normalized),
        None,
    )


def load_current_user():
    g.current_user = None
    if current_app.config["DATA_BACKEND"] != "postgres":
        return
    if request.endpoint in {"static", "auth.login", "auth.logout"}:
        return
    if "user_id" in session:
        user = current_app.config["USER_REPOSITORY"].find_by_id(session["user_id"])
        if user is None or not user.active:
            session.clear()
            return
        g.current_user = user
        session["user"] = user.username
    elif "user" in session:
        session.clear()


def password_matches(password_hash, password):
    try:
        return check_password_hash(password_hash, password)
    except (ValueError, TypeError):
        return False


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", error="", username="")
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    if len(username) > 50 or len(password) > 1024:
        return render_template("login.html", error="Usuario o contraseña incorrectos", username=username[:50]), 401

    if current_app.config["DATA_BACKEND"] == "postgres":
        user = current_app.config["USER_REPOSITORY"].find_by_username(username)
        if user and user.active and password_matches(user.password_hash, password):
            session.clear()
            session["user_id"] = user.user_id
            session["user"] = user.username
            destinations = {
                "ADMINISTRADOR": "admin.index",
                "MEDICO": "clinical.index",
                "RECEPCION": "patients.home",
                "FACTURACION": "billing.index",
            }
            return redirect(url_for(destinations.get(user.role, "patients.home")))
    else:
        registered = find_registered_user(username)
        password_hash = current_app.config["AUTH_USERS"].get(registered) if registered else None
        if password_hash and password_matches(password_hash, password):
            session.clear()
            session["user"] = registered
            return redirect(url_for("patients.home"))
    return render_template(
        "login.html", error="Usuario o contraseña incorrectos", username=username,
    ), 401


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    return "Not Found", 404


@auth_bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if current_app.config["DATA_BACKEND"] == "postgres":
            authenticated = g.current_user is not None
        else:
            authenticated = "user" in session
        if not authenticated:
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped_view


def reception_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if current_app.config["DATA_BACKEND"] == "postgres":
            authorized = (
                g.current_user is not None
                and g.current_user.role in {"RECEPCION", "ADMINISTRADOR"}
            )
        else:
            authorized = (
                session.get("user", "").casefold() == current_app.config["DEMO_USER"].casefold()
            )
        if not authorized:
            abort(403)
        return view(*args, **kwargs)
    return wrapped_view


def administrator_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if current_app.config["DATA_BACKEND"] == "postgres":
            authorized = g.current_user is not None and g.current_user.role == "ADMINISTRADOR"
        else:
            authorized = False
        if not authorized:
            abort(403)
        return view(*args, **kwargs)
    return wrapped_view
