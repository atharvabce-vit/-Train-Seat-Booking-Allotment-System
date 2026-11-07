import logging
import os
import secrets
import time
import uuid

from flask import Flask, g, jsonify, request, session

from blueprints.admin import admin_bp
from blueprints.api import api_bp
from blueprints.auth import auth_bp
from blueprints.booking import booking_bp
from blueprints.main import main_bp
from config import BERTH_NAMES, CLASS_NAMES, LOG_LEVEL, QUOTA_NAMES
from db import create_tables, get_connection
from migrate import run_migrations
from models.api_auth import ensure_default_token
import metrics

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
    app.register_blueprint(auth_bp)

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def request_context():
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        g.started_at = time.perf_counter()
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
        if request.endpoint != "metrics_endpoint":
            latency = (time.perf_counter() - getattr(g, "started_at", time.perf_counter())) * 1000
            metrics.record(request.path, response.status_code, latency)
        return response

    @app.context_processor
    def inject_globals():
        current_user = None
        if session.get("user_id"):
            current_user = {
                "id": session["user_id"],
                "name": session.get("user_name", ""),
                "role": session.get("user_role", "passenger"),
            }
        return {
            "class_names": CLASS_NAMES,
            "quota_names": QUOTA_NAMES,
            "berth_names": BERTH_NAMES,
            "current_user": current_user,
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

    @app.route("/metrics")
    def metrics_endpoint():
        payload = metrics.snapshot()
        connection = get_connection()
        try:
            payload["database"] = {
                table: connection.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
                for table in ("users", "trains", "bookings", "passengers", "payments", "seat_holds")
            }
        finally:
            connection.close()
        return jsonify(payload)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=int(os.environ.get("PORT", 5000)))
