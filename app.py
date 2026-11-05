import os

from flask import Flask

from blueprints.admin import admin_bp
from blueprints.api import api_bp
from blueprints.booking import booking_bp
from blueprints.main import main_bp
from config import BERTH_NAMES, CLASS_NAMES, QUOTA_NAMES
from db import create_tables, get_connection


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "train-booking-dev-secret")

    connection = get_connection()
    create_tables(connection)
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

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=int(os.environ.get("PORT", 5000)))
