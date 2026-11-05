from flask import Blueprint, flash, redirect, render_template, request, url_for

from blueprints import db
from config import ADMIN_KEY
from models import notifications, reports

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _authorised():
    return request.args.get("key") == ADMIN_KEY or request.form.get("key") == ADMIN_KEY


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
        }
    return render_template("admin.html", key=ADMIN_KEY, travel_date=travel_date, data=data)


@admin_bp.route("/notifications")
def outbox():
    if not _authorised():
        flash("Admin key required.")
        return redirect(url_for("main.index"))
    with db() as conn:
        rows = [dict(row) for row in notifications.recent(conn, limit=50)]
    return render_template("notifications.html", key=ADMIN_KEY, notifications=rows)
