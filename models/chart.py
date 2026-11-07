"""Chart preparation.

A few hours before a train departs, its chart is *prepared*: every RAC or
waitlisted booking that can now be given a berth is confirmed, and online
booking for that train and date is closed - mirroring the real cut-off after
which only the station's current-booking counter may sell tickets.
"""
from config import CHART_LEAD_HOURS
from models import audit
from models.booking import BookingError, promote_queue
from models.trains import get_stops, hours_before_departure, is_chart_prepared


def queued_pairs(conn, train_id, travel_date):
    """Distinct (class, quota) pairs that still hold RAC/waitlisted bookings."""
    rows = conn.execute(
        """
        SELECT DISTINCT class_code, quota FROM bookings
        WHERE train_id = ? AND travel_date = ? AND status IN ('rac', 'waiting')
        """,
        (train_id, travel_date),
    ).fetchall()
    return [(row["class_code"], row["quota"]) for row in rows]


def prepare_chart(conn, train_id, travel_date):
    """Finalise a train's chart, returning the PNRs that were confirmed."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        if is_chart_prepared(conn, train_id, travel_date):
            raise BookingError("The chart for this train and date is already prepared.")
        promoted = []
        for class_code, quota in queued_pairs(conn, train_id, travel_date):
            promoted.extend(promote_queue(conn, train_id, class_code, travel_date, quota))
        conn.execute(
            "INSERT INTO charts (train_id, travel_date) VALUES (?, ?)",
            (train_id, travel_date),
        )
        audit.log(
            conn, "chart_prepare", "train", str(train_id),
            f"{travel_date}: confirmed {len(promoted)} queued booking(s)",
        )
        conn.execute("COMMIT")
        return promoted
    except Exception:
        conn.execute("ROLLBACK")
        raise


def charts_due(conn, lead_hours=CHART_LEAD_HOURS):
    """Train/date pairs that are inside the chart cut-off but not yet prepared."""
    pairs = conn.execute(
        "SELECT DISTINCT train_id, travel_date FROM bookings WHERE status != 'cancelled'"
    ).fetchall()
    due = []
    for row in pairs:
        if is_chart_prepared(conn, row["train_id"], row["travel_date"]):
            continue
        stops = get_stops(conn, row["train_id"])
        if not stops:
            continue
        hours = hours_before_departure(conn, row["train_id"], row["travel_date"], stops[0]["seq"])
        if 0 < hours <= lead_hours:
            due.append((row["train_id"], row["travel_date"]))
    return due


def prepare_due_charts(conn):
    """Prepare every chart that has reached its cut-off. Safe to call often."""
    prepared = []
    for train_id, travel_date in charts_due(conn):
        prepare_chart(conn, train_id, travel_date)
        prepared.append((train_id, travel_date))
    return prepared
