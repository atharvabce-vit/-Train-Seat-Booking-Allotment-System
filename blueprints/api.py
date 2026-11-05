from flask import Blueprint, jsonify, render_template, request

from blueprints import db
from blueprints.booking import get_or_create_user
from config import CLASS_NAMES
from models import cache, trains as trains_model
from models.api_auth import rate_limited, validate_token
from models.booking import (
    BookingError,
    NoSeatsError,
    book_round_trip,
    book_seats,
    cancel_booking,
    cancel_passengers,
    join_queue,
    reschedule_booking,
)
from models.fare import fare_per_passenger
from models.pnr import get_booking_by_pnr
from openapi import SPEC

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _payload():
    return request.get_json(silent=True) or {}


def _token():
    return request.headers.get("X-API-Token") or request.args.get("token", "")


def _require_token():
    """Return a (json, status) error tuple when the caller may not write."""
    with db() as conn:
        if not validate_token(conn, _token()):
            return jsonify({"error": "A valid X-API-Token header is required."}), 401
    return None


@api_bp.before_request
def _throttle():
    key = _token() or request.remote_addr or "anonymous"
    if rate_limited(key):
        return jsonify({"error": "Rate limit exceeded. Try again shortly."}), 429
    return None


@api_bp.route("/docs")
def docs():
    return render_template("api_docs.html", spec_url="/api/openapi.json")


@api_bp.route("/openapi.json")
def openapi_spec():
    return jsonify(SPEC)


@api_bp.route("/stations")
def stations():
    query = request.args.get("q", "").strip().lower()

    def load():
        with db() as conn:
            return [dict(row) for row in trains_model.search_stations(conn, query, limit=20)]

    return jsonify({"stations": cache.remember(f"stations:{query}", load, ttl_seconds=60)})


@api_bp.route("/trains")
def trains():
    with db() as conn:
        rows = conn.execute(
            "SELECT id, train_number, train_name, runs_on FROM trains ORDER BY train_number"
        ).fetchall()
    return jsonify({"trains": [dict(row) for row in rows]})


@api_bp.route("/search")
def search():
    source = request.args.get("from", "").strip()
    destination = request.args.get("to", "").strip()
    if not source or not destination:
        return jsonify({"error": "Query parameters 'from' and 'to' are required."}), 400

    def load():
        with db() as conn:
            return [dict(row) for row in trains_model.search_trains(conn, source, destination)]

    results = cache.remember(
        f"search:{source.lower()}:{destination.lower()}", load, ttl_seconds=30
    )
    return jsonify({"count": len(results), "results": results})


def _leg_args():
    train_id = request.args.get("train_id", type=int)
    class_code = (request.args.get("cls") or request.args.get("class") or "").strip()
    travel_date = request.args.get("date", "").strip()
    from_seq = request.args.get("from_seq", type=int)
    to_seq = request.args.get("to_seq", type=int)
    quota = request.args.get("quota", "GN").upper()
    return train_id, class_code, travel_date, from_seq, to_seq, quota


@api_bp.route("/availability")
def availability():
    train_id, class_code, travel_date, from_seq, to_seq, quota = _leg_args()
    if not (train_id and class_code and travel_date and from_seq and to_seq):
        return jsonify({"error": "train_id, cls, date, from_seq and to_seq are required."}), 400

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


@api_bp.route("/seatmap")
def seatmap():
    train_id, class_code, travel_date, from_seq, to_seq, quota = _leg_args()
    if not (train_id and class_code and travel_date and from_seq and to_seq):
        return jsonify({"error": "train_id, cls, date, from_seq and to_seq are required."}), 400
    with db() as conn:
        free = {
            seat["seat_id"]
            for seat in trains_model.available_seats(
                conn, train_id, class_code, travel_date, from_seq, to_seq, quota
            )
        }
        rows = conn.execute(
            """
            SELECT s.id AS seat_id, s.seat_number, s.berth_type, c.coach_name, c.position
            FROM seats s JOIN coaches c ON c.id = s.coach_id
            WHERE c.train_id = ? AND c.class_code = ?
            ORDER BY c.position, c.coach_name, s.seat_number
            """,
            (train_id, class_code),
        ).fetchall()
    coaches = {}
    for row in rows:
        coach = coaches.setdefault(row["coach_name"], [])
        coach.append(
            {
                "seat_id": row["seat_id"],
                "seat_number": row["seat_number"],
                "berth_type": row["berth_type"],
                "status": "available" if row["seat_id"] in free else "booked",
            }
        )
    return jsonify({"coaches": [{"name": name, "seats": seats} for name, seats in coaches.items()]})


@api_bp.route("/book", methods=["POST"])
def book():
    denied = _require_token()
    if denied:
        return denied

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
                discount_pct=data.get("discount_pct", 0),
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


def _normalise_leg(raw):
    return {
        "train_id": raw.get("train_id"),
        "class_code": raw.get("class_code") or raw.get("class", ""),
        "travel_date": raw.get("travel_date") or raw.get("date", ""),
        "from_seq": raw.get("from_seq"),
        "to_seq": raw.get("to_seq"),
        "quota": (raw.get("quota") or "GN").upper(),
        "passengers": raw.get("passengers") or [],
    }


@api_bp.route("/book-round-trip", methods=["POST"])
def book_trip():
    denied = _require_token()
    if denied:
        return denied

    data = _payload()
    user = data.get("user") or {}
    outbound = data.get("outbound") or {}
    inbound = data.get("return") or {}
    if not user.get("email") or not outbound or not inbound:
        return jsonify({"error": "'user', 'outbound' and 'return' are required."}), 400

    outbound = _normalise_leg(outbound)
    inbound = _normalise_leg(inbound)
    with db() as conn:
        user_id = get_or_create_user(
            conn, user.get("name", "Guest"), user["email"], user.get("phone")
        )
        try:
            result = book_round_trip(conn, user_id, outbound, inbound)
        except BookingError as error:
            return jsonify({"error": str(error)}), 400
        except NoSeatsError:
            return jsonify({"error": "Not enough seats on one of the legs."}), 409
    return jsonify(result), 201


@api_bp.route("/pnr/<pnr>")
def pnr(pnr):
    with db() as conn:
        record = get_booking_by_pnr(conn, pnr)
    if record is None:
        return jsonify({"error": "PNR not found."}), 404
    return jsonify(record)


@api_bp.route("/cancel/<pnr>", methods=["POST"])
def cancel(pnr):
    denied = _require_token()
    if denied:
        return denied
    data = _payload()
    passenger_ids = data.get("passenger_ids")
    with db() as conn:
        try:
            if passenger_ids:
                result = cancel_passengers(conn, pnr, passenger_ids)
                return jsonify({"pnr": pnr, "partial": True, **result})
            result = cancel_booking(conn, pnr)
        except BookingError as error:
            return jsonify({"error": str(error)}), 400
    return jsonify(
        {"pnr": pnr, "cancelled": True, "refund": result["refund"], "promoted": result["promoted"]}
    )


@api_bp.route("/reschedule/<pnr>", methods=["POST"])
def reschedule(pnr):
    denied = _require_token()
    if denied:
        return denied
    data = _payload()
    if not data.get("date"):
        return jsonify({"error": "'date' is required."}), 400
    with db() as conn:
        try:
            result = reschedule_booking(
                conn, pnr, data["date"], data.get("from_seq"), data.get("to_seq")
            )
        except BookingError as error:
            return jsonify({"error": str(error)}), 400
    return jsonify({"pnr": pnr, **result})
