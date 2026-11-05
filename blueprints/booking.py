from datetime import datetime

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from blueprints import db
from config import (
    BOOKING_WINDOW_DAYS,
    BERTH_NAMES,
    CLASS_NAMES,
    DEFAULT_PAYMENT_METHOD,
    PAYMENT_METHODS,
    QUOTA_NAMES,
)
from models import trains as trains_model
from models.booking import (
    BookingError,
    NoSeatsError,
    confirm_booking,
    create_hold,
    get_hold,
    hold_seats,
    join_queue,
    cancel_booking,
)
from models.fare import calculate_fare, fare_per_passenger
from models.pnr import bookings_for_email, get_booking_by_pnr
from models.trains import segment_distance
from models.util import STAMP_FORMAT, now_str, parse_date
from pdf_ticket import qr_data_uri, render_ticket_pdf

booking_bp = Blueprint("booking", __name__)


def get_or_create_user(conn, name, email, phone):
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if row is not None:
        return row["id"]
    cursor = conn.execute(
        "INSERT INTO users (name, email, phone) VALUES (?, ?, ?)", (name, email, phone)
    )
    return cursor.lastrowid


def _passengers_from_form(form):
    names = form.getlist("passenger_name")
    ages = form.getlist("passenger_age")
    genders = form.getlist("passenger_gender")
    preferences = form.getlist("passenger_preference") or ["ANY"] * len(names)
    passengers = []
    for name, age, gender, preference in zip(names, ages, genders, preferences):
        if not name.strip():
            continue
        try:
            age_value = int(age)
        except (TypeError, ValueError):
            age_value = 0
        passengers.append(
            {
                "name": name.strip(),
                "age": age_value,
                "gender": (gender or "M").upper(),
                "preference": (preference or "ANY").upper(),
            }
        )
    return passengers


def _seconds_left(expires_at):
    try:
        target = datetime.strptime(expires_at, STAMP_FORMAT)
    except (TypeError, ValueError):
        return 0
    return int((target - datetime.strptime(now_str(), STAMP_FORMAT)).total_seconds())


@booking_bp.route("/book")
def book():
    train_id = request.args.get("train_id", type=int)
    from_seq = request.args.get("from_seq", type=int)
    to_seq = request.args.get("to_seq", type=int)
    travel_date = request.args.get("date", "").strip()
    quota = request.args.get("quota", "GN").upper()
    selected_class = request.args.get("cls", "").strip()

    travel = parse_date(travel_date)
    if travel is None or not trains_model.is_bookable_date(travel_date):
        flash(f"Travel date must be today or within the next {BOOKING_WINDOW_DAYS} days.")
        return redirect(url_for("main.index"))

    with db() as conn:
        train = trains_model.get_train(conn, train_id) if train_id else None
        if train is None:
            abort(404)
        stops = [dict(s) for s in trains_model.get_stops(conn, train_id)]
        if not stops:
            abort(404)

        if from_seq is None or to_seq is None or to_seq <= from_seq:
            from_seq, to_seq = stops[0]["seq"], stops[-1]["seq"]

        from_stop = next((s for s in stops if s["seq"] == from_seq), stops[0])
        to_stop = next((s for s in stops if s["seq"] == to_seq), stops[-1])
        distance = segment_distance(conn, train_id, from_seq, to_seq)

        classes = []
        for class_code in trains_model.classes_for_train(conn, train_id):
            if class_code == "1A" and selected_class != "1A":
                pass
            classes.append(
                {
                    "code": class_code,
                    "name": CLASS_NAMES.get(class_code, class_code),
                    "capacity": trains_model.quota_seat_count(conn, train_id, class_code, quota),
                    "available": trains_model.available_count(
                        conn, train_id, class_code, travel_date, from_seq, to_seq, quota
                    ),
                    "fare": fare_per_passenger(class_code, distance, quota),
                }
            )

        if selected_class not in [c["code"] for c in classes]:
            selected_class = classes[0]["code"] if classes else ""

        tatkal_open = trains_model.tatkal_open(conn, train_id, travel_date, from_seq)

    if not CLASS_NAMES.get(selected_class):
        flash("This train has no bookable classes.")
        return redirect(url_for("main.index"))

    return render_template(
        "book.html",
        train=dict(train),
        stops=stops,
        from_stop=from_stop,
        to_stop=to_stop,
        from_seq=from_seq,
        to_seq=to_seq,
        travel_date=travel_date,
        quota=quota,
        distance=distance,
        classes=classes,
        selected_class=selected_class,
        tatkal_open=tatkal_open,
        payment_methods=PAYMENT_METHODS,
        default_method=DEFAULT_PAYMENT_METHOD,
        quota_names=QUOTA_NAMES,
        berth_names=BERTH_NAMES,
    )


@booking_bp.route("/book", methods=["POST"])
def create_booking_hold():
    form = request.form
    train_id = form.get("train_id", type=int)
    class_code = form.get("class_code", "").strip()
    travel_date = form.get("travel_date", "").strip()
    from_seq = form.get("from_seq", type=int)
    to_seq = form.get("to_seq", type=int)
    quota = form.get("quota", "GN").upper()
    method = form.get("payment_method", DEFAULT_PAYMENT_METHOD)
    user_name = form.get("user_name", "").strip()
    user_email = form.get("user_email", "").strip()
    user_phone = form.get("user_phone", "").strip()
    passengers = _passengers_from_form(form)

    back = url_for(
        "booking.book",
        train_id=train_id,
        cls=class_code,
        date=travel_date,
        from_seq=from_seq,
        to_seq=to_seq,
        quota=quota,
    )

    if not (train_id and class_code and user_name and user_email and passengers):
        flash("Please fill in your details and at least one passenger.")
        return redirect(back)

    with db() as conn:
        user_id = get_or_create_user(conn, user_name, user_email, user_phone)
        try:
            hold = create_hold(
                conn, train_id, class_code, travel_date, from_seq, to_seq, quota, passengers
            )
        except NoSeatsError:
            pnr, status, position = join_queue(
                conn, user_id, train_id, class_code, travel_date, from_seq, to_seq, quota, passengers
            )
            label = "RAC" if status == "rac" else "waitlist"
            flash(f"No confirmed seats free. You are on the {label} list at position {position}.")
            return redirect(url_for("booking.ticket", pnr=pnr))
        except BookingError as error:
            flash(str(error))
            return redirect(back)

    session["hold_token"] = hold["token"]
    session["hold_passengers"] = passengers
    session["hold_user"] = user_id
    session["hold_method"] = method
    return redirect(url_for("booking.confirm", token=hold["token"]))


@booking_bp.route("/confirm/<token>")
def confirm(token):
    if session.get("hold_token") != token:
        flash("Your seat hold has expired. Please choose seats again.")
        return redirect(url_for("main.index"))

    with db() as conn:
        hold = get_hold(conn, token)
        if hold is None:
            flash("Your seat hold has expired. Please choose seats again.")
            return redirect(url_for("main.index"))
        seats = hold_seats(conn, token)
        if len(seats) != len(session.get("hold_passengers", [])):
            flash("Your seat hold has expired. Please choose seats again.")
            return redirect(url_for("main.index"))
        train = trains_model.get_train(conn, hold["train_id"])
        distance = segment_distance(conn, hold["train_id"], hold["from_seq"], hold["to_seq"])
        fare = calculate_fare(hold["class_code"], distance, len(seats), hold["quota"])
        user = conn.execute(
            "SELECT name, email, phone FROM users WHERE id = ?", (session["hold_user"],)
        ).fetchone()
        from_stop = trains_model.get_stop(conn, hold["train_id"], hold["from_seq"])
        to_stop = trains_model.get_stop(conn, hold["train_id"], hold["to_seq"])

    return render_template(
        "confirm.html",
        token=token,
        hold=dict(hold),
        seats=seats,
        train=dict(train),
        distance=distance,
        fare=fare,
        user=dict(user),
        passengers=session.get("hold_passengers", []),
        from_stop=dict(from_stop),
        to_stop=dict(to_stop),
        seconds_left=_seconds_left(hold["expires_at"]),
        method=session.get("hold_method", DEFAULT_PAYMENT_METHOD),
        payment_methods=PAYMENT_METHODS,
    )


@booking_bp.route("/confirm/<token>", methods=["POST"])
def confirm_payment(token):
    if session.get("hold_token") != token:
        flash("Your seat hold has expired. Please choose seats again.")
        return redirect(url_for("main.index"))

    method = request.form.get("payment_method", DEFAULT_PAYMENT_METHOD)
    passengers = session.get("hold_passengers", [])
    user_id = session.get("hold_user")

    with db() as conn:
        try:
            pnr = confirm_booking(conn, user_id, token, passengers, method)
        except BookingError as error:
            flash(str(error))
            return redirect(url_for("main.index"))

    session.pop("hold_token", None)
    session.pop("hold_passengers", None)
    session.pop("hold_user", None)
    session.pop("hold_method", None)
    flash("Payment successful. Your ticket is confirmed.")
    return redirect(url_for("booking.ticket", pnr=pnr))


@booking_bp.route("/ticket/<pnr>")
def ticket(pnr):
    with db() as conn:
        record = get_booking_by_pnr(conn, pnr)
    if record is None:
        abort(404)
    verify_url = url_for("booking.verify", pnr=pnr, _external=True)
    return render_template(
        "ticket.html",
        record=record,
        verify_url=verify_url,
        qr=qr_data_uri(verify_url),
        class_names=CLASS_NAMES,
        berth_names=BERTH_NAMES,
        quota_names=QUOTA_NAMES,
    )


@booking_bp.route("/ticket/<pnr>/pdf")
def ticket_pdf(pnr):
    with db() as conn:
        record = get_booking_by_pnr(conn, pnr)
    if record is None:
        abort(404)
    verify_url = url_for("booking.verify", pnr=pnr, _external=True)
    buffer = render_ticket_pdf(record, verify_url, CLASS_NAMES, BERTH_NAMES)
    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"ticket-{pnr}.pdf",
    )


@booking_bp.route("/pnr")
def pnr_status():
    pnr = request.args.get("pnr", "").strip()
    record = None
    if pnr:
        with db() as conn:
            record = get_booking_by_pnr(conn, pnr)
        if record is None:
            flash("No booking found for this PNR.")
    return render_template(
        "pnr_status.html",
        record=record,
        pnr=pnr,
        class_names=CLASS_NAMES,
        berth_names=BERTH_NAMES,
        quota_names=QUOTA_NAMES,
    )


@booking_bp.route("/verify/<pnr>")
def verify(pnr):
    with db() as conn:
        record = get_booking_by_pnr(conn, pnr)
    return render_template(
        "verify.html",
        record=record,
        pnr=pnr,
        class_names=CLASS_NAMES,
        berth_names=BERTH_NAMES,
        quota_names=QUOTA_NAMES,
    )


@booking_bp.route("/my-bookings")
def my_bookings():
    email = request.args.get("email", "").strip()
    bookings = None
    if email:
        with db() as conn:
            bookings = bookings_for_email(conn, email)
        if not bookings:
            flash("No bookings found for this e-mail.")
    return render_template(
        "my_bookings.html", email=email, bookings=bookings, class_names=CLASS_NAMES
    )


@booking_bp.route("/cancel/<pnr>", methods=["POST"])
def cancel(pnr):
    with db() as conn:
        try:
            result = cancel_booking(conn, pnr)
            refund = result["refund"]
            promoted = result["promoted"]
            message = "Booking cancelled. Seats have been released."
            if refund:
                message += f" Refund: INR {refund['amount']} ({refund['percent']}%)."
            if promoted:
                message += f" {len(promoted)} waiting passenger(s) confirmed."
            flash(message)
        except BookingError as error:
            flash(str(error))
    return redirect(url_for("booking.pnr_status", pnr=pnr))
