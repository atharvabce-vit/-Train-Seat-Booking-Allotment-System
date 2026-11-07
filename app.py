import logging
import os
import secrets
import uuid

from flask import Flask, g, jsonify, request, session

from blueprints.admin import admin_bp
from blueprints.api import api_bp
from blueprints.booking import booking_bp
from blueprints.main import main_bp
from config import BERTH_NAMES, CLASS_NAMES, LOG_LEVEL, QUOTA_NAMES
from db import create_tables, get_connection
from migrate import run_migrations
from models.api_auth import ensure_default_token

# The JSON API authenticates with its own token, so it is exempt from CSRF.
CSRF_EXEMPT_PREFIXES = ("/api/",)


def csrf_token():
    """Return this session's CSRF token, creating one on first use."""
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "train-booking-dev-secret")

    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app.logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    connection = get_connection()
    create_tables(connection)
    run_migrations(connection, verbose=False)
    ensure_default_token(connection)
    connection.close()

    app.register_blueprint(main_bp)
    app.register_blueprint(booking_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def request_context():
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and not request.path.startswith(
            CSRF_EXEMPT_PREFIXES
        ):
            sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if not sent or sent != session.get("_csrf_token"):
                return "CSRF validation failed.", 400
        return None

    @app.after_request
    def tag_response(response):
        request_id = getattr(g, "request_id", "")
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.context_processor
    def inject_globals():
        return {
            "class_names": CLASS_NAMES,
            "quota_names": QUOTA_NAMES,
            "berth_names": BERTH_NAMES,
        }

    @app.route("/healthz")
    def healthz():
        try:
            connection = get_connection()
            connection.execute("SELECT 1").fetchone()
            connection.close()
        except Exception as error:  # pragma: no cover - only on a broken DB
            app.logger.exception("health check failed")
            return jsonify({"status": "error", "database": str(error)}), 503
        return jsonify({"status": "ok", "database": "ok"})

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=int(os.environ.get("PORT", 5000)))
