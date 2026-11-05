from flask import Blueprint, jsonify, render_template, request

from blueprints import db
from blueprints.booking import get_or_create_user
from config import CLASS_NAMES
from models import trains as trains_model
from models.booking import BookingError, NoSeatsError, book_seats, cancel_booking, join_queue
from models.fare import fare_per_passenger
from models.pnr import get_booking_by_pnr

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _payload():
    return request.get_json(silent=True) or {}


@api_bp.route("/docs")
def docs():
    return render_template("api_docs.html")


@api_bp.route("/stations")
def stations():
    query = request.args.get("q", "").strip()
    with db() as conn:
        rows = trains_model.search_stations(conn, query, limit=20)
    return jsonify({"stations": [dict(row) for row in rows]})


@api_bp.route("/trains")
def trains():
    with db() as conn:
        rows = conn.execute("SELECT id, train_number, train_name, runs_on FROM trains ORDER BY train_number").fetchall()
    return jsonify({"trains": [dict(row) for row in rows]})


@api_bp.route("/search")
def search():
    source = request.args.get("from", "").strip()
    destination = request.args.get("to", "").strip()
    if not source or not destination:
        return jsonify({"error": "Query parameters 'from' and 'to' are required."}), 400
    with db() as conn:
        results = [dict(row) for row in trains_model.search_trains(conn, source, destination)]
    return jsonify({"count": len(results), "results": results})


@api_bp.route("/availability")
def availability():
    train_id = request.args.get("train_id", type=int)
    class_code = request.args.get("class", "").strip()
    travel_date = request.args.get("date", "").strip()
    from_seq = request.args.get("from_seq", type=int)
    to_seq = request.args.get("to_seq", type=int)
    quota = request.args.get("quota", "GN").upper()

    if not (train_id and class_code and travel_date and from_seq and to_seq):
        return jsonify({"error": "train_id, class, date, from_seq and to_seq are required."}), 400

    with db() as conn:
        train = trains_model.get_train(conn, train_id)
        if train is None:
            return jsonify({"error": "Train not found."}), 404
        distance = trains_model.segment_distance(conn, train_id, from_seq, to_seq)
        payload = {
            "train_id": train_id,
            "class": class_code,
            "class_name": CLASS_NAMES.get(class_code, class_code),
            "date": travel_date,
            "quota": quota,
            "from_seq": from_seq,
            "to_seq": to_seq,
            "distance_km": distance,
            "capacity": trains_model.quota_seat_count(conn, train_id, class_code, quota),
            "available": trains_model.available_count(
                conn, train_id, class_code, travel_date, from_seq, to_seq, quota
            ),
            "fare_per_passenger": fare_per_passenger(class_code, distance, quota),
            "tatkal_open": trains_model.tatkal_open(conn, train_id, travel_date, from_seq),
        }
    return jsonify(payload)


@api_bp.route("/book", methods=["POST"])
def book():
    data = _payload()
    user = data.get("user") or {}
    passengers = data.get("passengers") or []
    required = ["train_id", "class", "date", "from_seq", "to_seq"]
    missing = [field for field in required if data.get(field) in (None, "")]
    if missing or not user.get("email") or not passengers:
        return jsonify({"error": f"Missing fields: {', '.join(missing) or 'user/passengers'}"}), 400

    with db() as conn:
        user_id = get_or_create_user(
            conn, user.get("name", "Guest"), user["email"], user.get("phone")
        )
        try:
            pnr = book_seats(
                conn, user_id, data["train_id"], data["class"], data["date"],
                data["from_seq"], data["to_seq"], passengers,
                data.get("quota", "GN").upper(),
            )
            status = "confirmed"
        except NoSeatsError:
            pnr, status, position = join_queue(
                conn, user_id, data["train_id"], data["class"], data["date"],
                data["from_seq"], data["to_seq"], data.get("quota", "GN").upper(), passengers,
            )
            return jsonify({"pnr": pnr, "status": status, "queue_position": position}), 201
        except BookingError as error:
            return jsonify({"error": str(error)}), 400

    return jsonify({"pnr": pnr, "status": status}), 201


@api_bp.route("/pnr/<pnr>")
def pnr(pnr):
    with db() as conn:
        record = get_booking_by_pnr(conn, pnr)
    if record is None:
        return jsonify({"error": "PNR not found."}), 404
    return jsonify(record)


@api_bp.route("/cancel/<pnr>", methods=["POST"])
def cancel(pnr):
    with db() as conn:
        try:
            result = cancel_booking(conn, pnr)
        except BookingError as error:
            return jsonify({"error": str(error)}), 400
    return jsonify({"pnr": pnr, "cancelled": True, "refund": result["refund"], "promoted": result["promoted"]})
