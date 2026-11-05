import logging
import os

from flask import Flask, jsonify

from blueprints.admin import admin_bp
from blueprints.api import api_bp
from blueprints.booking import booking_bp
from blueprints.main import main_bp
from config import BERTH_NAMES, CLASS_NAMES, LOG_LEVEL, QUOTA_NAMES
from db import create_tables, get_connection
from migrate import run_migrations
from models.api_auth import ensure_default_token


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
