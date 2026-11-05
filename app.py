from datetime import date, datetime, timedelta

from flask import Flask, abort, flash, redirect, render_template, request, url_for

from config import BOOKING_WINDOW_DAYS, CLASS_NAMES
from db import create_tables, get_connection
from models import trains as trains_model
from models.booking import BookingError, book_seats, cancel_booking, seat_availability_count
from models.pnr import get_booking_by_pnr

app = Flask(__name__)
app.secret_key = "train-booking-dev-secret"


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def is_bookable_date(travel_date):
    today = date.today()
    return today <= travel_date <= today + timedelta(days=BOOKING_WINDOW_DAYS)


def get_or_create_user(conn, name, email, phone):
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if row is not None:
        return row["id"]
    cursor = conn.execute(
        "INSERT INTO users (name, email, phone) VALUES (?, ?, ?)",
        (name, email, phone),
    )
    return cursor.lastrowid


@app.route("/")
def index():
    return render_template("search.html", trains=None, source="", destination="", travel_date="")


@app.route("/search")
def search():
    source = request.args.get("source", "").strip()
    destination = request.args.get("destination", "").strip()
    travel_date = request.args.get("date", "").strip()

    results = None
    if source and destination:
        conn = get_connection()
        try:
            results = [dict(r) for r in trains_model.search_trains(conn, source, destination)]
        finally:
            conn.close()

    return render_template(
        "search.html",
        trains=results,
        source=source,
        destination=destination,
        travel_date=travel_date,
    )


@app.route("/book", methods=["GET", "POST"])
def book():
    if request.method == "POST":
        return _handle_booking()

    conn = get_connection()
    try:
        train_id = request.args.get("train_id", type=int)
        class_code = request.args.get("class_code", "")
        travel_date = request.args.get("date", "").strip()

        travel = parse_date(travel_date)
        train = trains_model.get_train(conn, train_id) if train_id else None
        if train is None:
            abort(404)
        if travel is None or not is_bookable_date(travel):
            flash(f"Travel date must be today or within the next {BOOKING_WINDOW_DAYS} days.")
            return redirect(url_for("index"))

        classes = trains_model.available_classes(conn, train_id)
        if class_code not in classes:
            class_code = classes[0] if classes else ""

        available = (
            seat_availability_count(conn, train_id, class_code, travel_date)
            if class_code
            else 0
        )
        return render_template(
            "book.html",
            train=dict(train),
            class_code=class_code,
            classes=classes,
            travel_date=travel_date,
            available=available,
            class_names=CLASS_NAMES,
        )
    finally:
        conn.close()


def _handle_booking():
    form = request.form
    train_id = form.get("train_id", type=int)
    class_code = form.get("class_code", "")
    travel_date = form.get("travel_date", "").strip()
    user_name = form.get("user_name", "").strip()
    user_email = form.get("user_email", "").strip()
    user_phone = form.get("user_phone", "").strip()

    names = form.getlist("passenger_name")
    ages = form.getlist("passenger_age")
    genders = form.getlist("passenger_gender")

    passengers = []
    for name, age, gender in zip(names, ages, genders):
        if not name.strip():
            continue
        try:
            age_value = int(age)
        except (TypeError, ValueError):
            age_value = 0
        passengers.append({"name": name.strip(), "age": age_value, "gender": gender})

    if not (train_id and class_code and user_name and user_email and passengers):
        flash("Please fill in your details and at least one passenger.")
        return redirect(url_for("index"))

    travel = parse_date(travel_date)
    if travel is None or not is_bookable_date(travel):
        flash(f"Travel date must be today or within the next {BOOKING_WINDOW_DAYS} days.")
        return redirect(url_for("index"))

    conn = get_connection()
    try:
        user_id = get_or_create_user(conn, user_name, user_email, user_phone)
        pnr = book_seats(conn, user_id, train_id, class_code, travel_date, passengers)
    except BookingError as error:
        flash(str(error))
        return redirect(
            url_for("book", train_id=train_id, class_code=class_code, date=travel_date)
        )
    except Exception as error:
        flash(f"Booking could not be completed: {error}")
        return redirect(url_for("index"))
    finally:
        conn.close()

    return redirect(url_for("ticket", pnr=pnr))


@app.route("/ticket/<pnr>")
def ticket(pnr):
    conn = get_connection()
    try:
        record = get_booking_by_pnr(conn, pnr)
    finally:
        conn.close()
    if record is None:
        abort(404)
    return render_template("ticket.html", record=record, class_names=CLASS_NAMES)


@app.route("/pnr")
def pnr_status():
    pnr = request.args.get("pnr", "").strip()
    record = None
    if pnr:
        conn = get_connection()
        try:
            record = get_booking_by_pnr(conn, pnr)
        finally:
            conn.close()
        if record is None:
            flash("No booking found for this PNR.")
    return render_template("pnr_status.html", record=record, pnr=pnr, class_names=CLASS_NAMES)


@app.route("/cancel/<pnr>", methods=["POST"])
def cancel(pnr):
    conn = get_connection()
    try:
        cancel_booking(conn, pnr)
        flash("Booking cancelled. Seats have been released.")
    except BookingError as error:
        flash(str(error))
    finally:
        conn.close()
    return redirect(url_for("pnr_status", pnr=pnr))


if __name__ == "__main__":
    connection = get_connection()
    create_tables(connection)
    connection.close()
    app.run(debug=True, port=5000)
