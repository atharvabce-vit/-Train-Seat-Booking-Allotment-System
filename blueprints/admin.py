import csv
import io
from datetime import datetime

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from blueprints import db
from config import ADMIN_KEY, DB_PATH
from models import audit, notifications, reports
from models import trains as trains_model

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

CLASS_OPTIONS = ["SL", "3A", "2A", "1A"]


def _authorised():
    return request.args.get("key") == ADMIN_KEY or request.form.get("key") == ADMIN_KEY


def _csv_response(filename, header, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@admin_bp.route("/")
def dashboard():
    if not _authorised():
        flash("Admin key required.")
        return redirect(url_for("main.index"))

    travel_date = request.args.get("date", reports.today())
    with db() as conn:
        data = {
            "summary": reports.summary(conn),
            "classes": reports.class_breakdown(conn),
            "quota": reports.quota_breakdown(conn),
            "routes": reports.top_routes(conn),
            "train_load": reports.train_load(conn, travel_date),
            "queue": reports.queue_snapshot(conn),
            "revenue": reports.revenue_by_day(conn),
            "concessions": reports.concession_totals(conn),
            "occupancy": reports.class_occupancy(conn, travel_date),
            "audit": audit.recent(conn, limit=15),
        }
    return render_template(
        "admin.html",
        key=ADMIN_KEY,
        travel_date=travel_date,
        data=data,
        class_options=CLASS_OPTIONS,
    )


@admin_bp.route("/notifications")
def outbox():
    if not _authorised():
        flash("Admin key required.")
        return redirect(url_for("main.index"))
    with db() as conn:
        rows = [dict(row) for row in notifications.recent(conn, limit=50)]
    return render_template("notifications.html", key=ADMIN_KEY, notifications=rows)


@admin_bp.route("/audit")
def audit_log():
    if not _authorised():
        flash("Admin key required.")
        return redirect(url_for("main.index"))
    with db() as conn:
        rows = audit.recent(conn, limit=200)
    return render_template("audit.html", key=ADMIN_KEY, entries=rows)


@admin_bp.route("/trains")
def trains():
    if not _authorised():
        flash("Admin key required.")
        return redirect(url_for("main.index"))
    with db() as conn:
        rows = conn.execute(
            """
            SELECT t.id, t.train_number, t.train_name, t.runs_on,
                   COUNT(DISTINCT c.id) AS coaches,
                   COALESCE(SUM(c.seat_count), 0) AS seats,
                   (SELECT COUNT(*) FROM train_stops s WHERE s.train_id = t.id) AS stops
            FROM trains t
            LEFT JOIN coaches c ON c.train_id = t.id
            GROUP BY t.id
            ORDER BY t.train_number
            """
        ).fetchall()
    return render_template("admin_trains.html", key=ADMIN_KEY, trains=[dict(r) for r in rows])


@admin_bp.route("/trains", methods=["POST"])
def create_train():
    if not _authorised():
        flash("Admin key required.")
        return redirect(url_for("main.index"))
    number = request.form.get("train_number", "").strip()
    name = request.form.get("train_name", "").strip()
    runs_on = request.form.get("runs_on", "Daily").strip() or "Daily"
    if not number or not name:
        flash("Train number and name are required.")
        return redirect(url_for("admin.trains", key=ADMIN_KEY))
    with db() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO trains (train_number, train_name, runs_on) VALUES (?, ?, ?)",
                (number, name, runs_on),
            )
            audit.log(conn, "train_create", "train", cursor.lastrowid, f"{number} {name}")
        except Exception as error:
            flash(f"Could not create train: {error}")
            return redirect(url_for("admin.trains", key=ADMIN_KEY))
    flash(f"Train {number} added. Now add its halts and coaches.")
    return redirect(url_for("admin.train_detail", train_id=cursor.lastrowid, key=ADMIN_KEY))


@admin_bp.route("/trains/<int:train_id>")
def train_detail(train_id):
    if not _authorised():
        flash("Admin key required.")
        return redirect(url_for("main.index"))
    with db() as conn:
        train = trains_model.get_train(conn, train_id)
        if train is None:
            abort(404)
        stops = [dict(s) for s in trains_model.get_stops(conn, train_id)]
        coaches = conn.execute(
            """
            SELECT c.id, c.coach_name, c.class_code, c.seat_count, c.tatkal_seats,
                   c.position, COUNT(s.id) AS seats
            FROM coaches c
            LEFT JOIN seats s ON s.coach_id = c.id
            WHERE c.train_id = ?
            GROUP BY c.id
            ORDER BY c.position, c.coach_name
            """,
            (train_id,),
        ).fetchall()
        stations = conn.execute(
            "SELECT code, name, city FROM stations ORDER BY city"
        ).fetchall()
    return render_template(
        "admin_train_detail.html",
        key=ADMIN_KEY,
        train=dict(train),
        stops=stops,
        coaches=[dict(c) for c in coaches],
        stations=[dict(s) for s in stations],
        class_options=CLASS_OPTIONS,
    )


@admin_bp.route("/trains/<int:train_id>/edit", methods=["POST"])
def edit_train(train_id):
    if not _authorised():
        flash("Admin key required.")
        return redirect(url_for("main.index"))
    name = request.form.get("train_name", "").strip()
    runs_on = request.form.get("runs_on", "Daily").strip() or "Daily"
    with db() as conn:
        if name:
            conn.execute(
                "UPDATE trains SET train_name = ?, runs_on = ? WHERE id = ?",
                (name, runs_on, train_id),
            )
            audit.log(conn, "train_update", "train", train_id, name)
            flash("Train updated.")
    return redirect(url_for("admin.train_detail", train_id=train_id, key=ADMIN_KEY))


@admin_bp.route("/trains/<int:train_id>/coaches", methods=["POST"])
def add_coach(train_id):
    if not _authorised():
        flash("Admin key required.")
        return redirect(url_for("main.index"))
    class_code = request.form.get("class_code", "SL").strip().upper()
    seat_count = request.form.get("seat_count", type=int) or 0
    tatkal_seats = request.form.get("tatkal_seats", type=int) or 0
    if class_code not in CLASS_OPTIONS or seat_count <= 0:
        flash("Pick a valid class and seat count.")
        return redirect(url_for("admin.train_detail", train_id=train_id, key=ADMIN_KEY))
    tatkal_seats = min(tatkal_seats, seat_count)
    with db() as conn:
        coach_name = request.form.get("coach_name", "").strip() or trains_model.next_coach_name(
            conn, train_id, class_code
        )
        try:
            trains_model.create_coach(
                conn, train_id, coach_name, class_code, seat_count, tatkal_seats,
                position=seat_count,
            )
        except Exception as error:
            flash(f"Could not add coach: {error}")
            return redirect(url_for("admin.train_detail", train_id=train_id, key=ADMIN_KEY))
        audit.log(conn, "coach_create", "train", train_id, f"{coach_name} {class_code} {seat_count}")
    flash(f"Coach {coach_name} added with {seat_count} seats.")
    return redirect(url_for("admin.train_detail", train_id=train_id, key=ADMIN_KEY))


@admin_bp.route("/coaches/<int:coach_id>/delete", methods=["POST"])
def delete_coach(coach_id):
    if not _authorised():
        flash("Admin key required.")
        return redirect(url_for("main.index"))
    with db() as conn:
        coach = conn.execute(
            "SELECT train_id, coach_name FROM coaches WHERE id = ?", (coach_id,)
        ).fetchone()
        if coach is None:
            abort(404)
        conn.execute("DELETE FROM coaches WHERE id = ?", (coach_id,))
        audit.log(conn, "coach_delete", "train", coach["train_id"], coach["coach_name"])
    flash("Coach removed.")
    return redirect(url_for("admin.train_detail", train_id=coach["train_id"], key=ADMIN_KEY))


@admin_bp.route("/trains/<int:train_id>/stops", methods=["POST"])
def add_stop(train_id):
    if not _authorised():
        flash("Admin key required.")
        return redirect(url_for("main.index"))
    station_code = request.form.get("station_code", "").strip().upper()
    seq = request.form.get("seq", type=int)
    arrival = request.form.get("arrival_time", "").strip() or None
    departure = request.form.get("departure_time", "").strip() or None
    day_offset = request.form.get("day_offset", type=int) or 0
    distance = request.form.get("distance_from_source", type=int) or 0
    if not station_code or not seq:
        flash("Station and sequence are required.")
        return redirect(url_for("admin.train_detail", train_id=train_id, key=ADMIN_KEY))
    with db() as conn:
        try:
            conn.execute(
                """
                INSERT INTO train_stops
                    (train_id, station_code, seq, arrival_time, departure_time,
                     day_offset, distance_from_source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (train_id, station_code, seq, arrival, departure, day_offset, distance),
            )
            audit.log(conn, "stop_create", "train", train_id, f"seq {seq} {station_code}")
        except Exception as error:
            flash(f"Could not add halt: {error}")
            return redirect(url_for("admin.train_detail", train_id=train_id, key=ADMIN_KEY))
    flash("Halt added.")
    return redirect(url_for("admin.train_detail", train_id=train_id, key=ADMIN_KEY))


@admin_bp.route("/export/bookings.csv")
def export_bookings():
    if not _authorised():
        flash("Admin key required.")
        return redirect(url_for("main.index"))
    with db() as conn:
        rows = conn.execute(
            """
            SELECT b.pnr, t.train_number, b.class_code, b.quota, b.travel_date,
                   b.status, b.distance_km, b.total_fare, b.concession_amount,
                   b.booked_at, u.email
            FROM bookings b
            JOIN trains t ON t.id = b.train_id
            JOIN users u ON u.id = b.user_id
            ORDER BY b.id DESC
            """
        ).fetchall()
    header = ["pnr", "train_number", "class", "quota", "travel_date", "status",
              "distance_km", "total_fare", "concession_amount", "booked_at", "email"]
    return _csv_response("bookings.csv", header, [list(row) for row in rows])


@admin_bp.route("/export/refunds.csv")
def export_refunds():
    if not _authorised():
        flash("Admin key required.")
        return redirect(url_for("main.index"))
    with db() as conn:
        rows = conn.execute(
            """
            SELECT b.pnr, r.percent, r.amount, r.reason, r.created_at
            FROM refunds r JOIN bookings b ON b.id = r.booking_id
            ORDER BY r.id DESC
            """
        ).fetchall()
    header = ["pnr", "percent", "amount", "reason", "created_at"]
    return _csv_response("refunds.csv", header, [list(row) for row in rows])


@admin_bp.route("/export/manifest.csv")
def export_manifest():
    if not _authorised():
        flash("Admin key required.")
        return redirect(url_for("main.index"))
    train_id = request.args.get("train_id", type=int)
    travel_date = request.args.get("date", reports.today())
    query = """
        SELECT b.pnr, t.train_number, b.class_code, p.name, p.age, p.gender,
               p.coach_name, p.seat_number, p.berth_type, p.fare
        FROM passengers p
        JOIN bookings b ON b.id = p.booking_id
        JOIN trains t ON t.id = b.train_id
        WHERE b.travel_date = ? AND b.status = 'confirmed' AND p.status = 'confirmed'
    """
    params = [travel_date]
    if train_id:
        query += " AND b.train_id = ?"
        params.append(train_id)
    query += " ORDER BY t.train_number, p.coach_name, p.seat_number"
    with db() as conn:
        rows = conn.execute(query, params).fetchall()
    header = ["pnr", "train_number", "class", "name", "age", "gender",
              "coach", "seat", "berth", "fare"]
    return _csv_response(f"manifest-{travel_date}.csv", header, [list(row) for row in rows])


@admin_bp.route("/backup")
def backup():
    if not _authorised():
        flash("Admin key required.")
        return redirect(url_for("main.index"))
    with db() as conn:
        conn.execute("PRAGMA wal_checkpoint(FULL)")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return send_file(
        DB_PATH,
        mimetype="application/x-sqlite3",
        as_attachment=True,
        download_name=f"train_booking-{stamp}.db",
    )
