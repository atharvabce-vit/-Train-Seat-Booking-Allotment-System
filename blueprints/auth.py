from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from blueprints import db
from models import auth as auth_model

auth_bp = Blueprint("auth", __name__)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please sign in to continue.")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def _start_session(user):
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    session["user_role"] = user["role"] or "passenger"


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        form = request.form
        with db() as conn:
            try:
                user_id = auth_model.register_user(
                    conn, form.get("name"), form.get("email"),
                    form.get("password"), form.get("phone"),
                )
            except auth_model.AuthError as error:
                flash(str(error))
                return redirect(url_for("auth.register"))
            user = auth_model.get_user(conn, user_id)
        _start_session(user)
        flash("Welcome aboard! Your account has been created.")
        return redirect(url_for("main.index"))
    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        with db() as conn:
            user = auth_model.authenticate(
                conn, request.form.get("email"), request.form.get("password")
            )
        if user is None:
            flash("Invalid e-mail or password.")
            return redirect(url_for("auth.login"))
        _start_session(user)
        flash(f"Welcome back, {user['name']}.")
        return redirect(request.args.get("next") or url_for("main.index"))
    return render_template("login.html")


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.pop("user_id", None)
    session.pop("user_name", None)
    session.pop("user_role", None)
    flash("You have been signed out.")
    return redirect(url_for("main.index"))
