from flask import Blueprint, jsonify, render_template, request

from blueprints import db
from models import trains as trains_model

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    return render_template(
        "search.html", trains=None, source="", destination="", travel_date=""
    )


@main_bp.route("/search")
def search():
    source = request.args.get("source", "").strip()
    destination = request.args.get("destination", "").strip()
    travel_date = request.args.get("date", "").strip()

    results = None
    if source and destination:
        with db() as conn:
            results = [dict(row) for row in trains_model.search_trains(conn, source, destination)]

    return render_template(
        "search.html",
        trains=results,
        source=source,
        destination=destination,
        travel_date=travel_date,
    )


@main_bp.route("/stations")
def stations():
    query = request.args.get("q", "").strip()
    with db() as conn:
        rows = trains_model.search_stations(conn, query, limit=12)
    return jsonify([dict(row) for row in rows])


@main_bp.route("/schedule/<int:train_id>")
def schedule(train_id):
    with db() as conn:
        train = trains_model.get_train(conn, train_id)
        if train is None:
            return render_template("error.html", message="Train not found."), 404
        stops = trains_model.get_stops(conn, train_id)
    return render_template("schedule.html", train=dict(train), stops=[dict(s) for s in stops])
