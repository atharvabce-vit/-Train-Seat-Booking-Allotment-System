from models.util import now_str, today_ist


def summary(conn):
    counts = conn.execute(
        """
        SELECT status, COUNT(*) AS c
        FROM bookings
        GROUP BY status
        """
    ).fetchall()
    by_status = {row["status"]: row["c"] for row in counts}

    revenue = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM payments WHERE status = 'success'"
    ).fetchone()["total"]
    refunded = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM refunds"
    ).fetchone()["total"]
    passengers = conn.execute("SELECT COUNT(*) AS c FROM passengers").fetchone()["c"]
    trains = conn.execute("SELECT COUNT(*) AS c FROM trains").fetchone()["c"]
    stations = conn.execute("SELECT COUNT(*) AS c FROM stations").fetchone()["c"]
    holds = conn.execute(
        "SELECT COUNT(*) AS c FROM seat_holds WHERE expires_at > ?", (now_str(),)
    ).fetchone()["c"]

    return {
        "bookings": sum(by_status.values()),
        "confirmed": by_status.get("confirmed", 0),
        "rac": by_status.get("rac", 0),
        "waiting": by_status.get("waiting", 0),
        "cancelled": by_status.get("cancelled", 0),
        "revenue": revenue,
        "refunded": refunded,
        "net_revenue": revenue - refunded,
        "passengers": passengers,
        "trains": trains,
        "stations": stations,
        "active_holds": holds,
        "generated_at": now_str(),
    }


def class_breakdown(conn):
    rows = conn.execute(
        """
        SELECT class_code,
               COUNT(*) AS bookings,
               COALESCE(SUM(CASE WHEN status = 'confirmed' THEN total_fare ELSE 0 END), 0) AS fare
        FROM bookings
        GROUP BY class_code
        ORDER BY class_code
        """
    ).fetchall()
    return [dict(row) for row in rows]


def quota_breakdown(conn):
    rows = conn.execute(
        """
        SELECT quota, status, COUNT(*) AS c
        FROM bookings
        GROUP BY quota, status
        ORDER BY quota, status
        """
    ).fetchall()
    return [dict(row) for row in rows]


def top_routes(conn, limit=5):
    rows = conn.execute(
        """
        SELECT fst.city AS from_city, tst.city AS to_city, COUNT(*) AS bookings,
               COALESCE(SUM(b.total_fare), 0) AS fare
        FROM bookings b
        JOIN train_stops fs ON fs.train_id = b.train_id AND fs.seq = b.from_seq
        JOIN stations fst ON fst.code = fs.station_code
        JOIN train_stops ts ON ts.train_id = b.train_id AND ts.seq = b.to_seq
        JOIN stations tst ON tst.code = ts.station_code
        GROUP BY fst.city, tst.city
        ORDER BY bookings DESC, fare DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def occupancy(conn, train_id, class_code, from_seq, to_seq, quota="GN"):
    from config import QUOTA_POOL
    from models.trains import quota_seat_count

    pool = QUOTA_POOL.get(quota, "GN")
    total = quota_seat_count(conn, train_id, class_code, quota)
    occupied = conn.execute(
        """
        SELECT COUNT(DISTINCT si.seat_id) AS c
        FROM seat_inventory si
        JOIN seats s ON s.id = si.seat_id
        JOIN coaches c ON c.id = s.coach_id
        WHERE c.train_id = ? AND c.class_code = ?
          AND si.from_seq < ? AND ? < si.to_seq
          AND si.status = 'booked'
          AND ((? = 'TQ' AND s.seat_number <= c.tatkal_seats)
               OR (? = 'GN' AND s.seat_number > c.tatkal_seats))
        """,
        (train_id, class_code, to_seq, from_seq, pool, pool),
    ).fetchone()["c"]
    percent = round(occupied / total * 100, 1) if total else 0.0
    return {"total": total, "occupied": occupied, "percent": percent}


def train_load(conn, travel_date):
    rows = conn.execute(
        """
        SELECT t.id, t.train_number, t.train_name,
               COUNT(b.id) AS bookings,
               COALESCE(SUM(b.total_fare), 0) AS fare
        FROM trains t
        LEFT JOIN bookings b
               ON b.train_id = t.id AND b.travel_date = ? AND b.status = 'confirmed'
        GROUP BY t.id
        ORDER BY bookings DESC, t.train_number
        """,
        (travel_date,),
    ).fetchall()
    return [dict(row) for row in rows]


def queue_snapshot(conn, limit=20):
    rows = conn.execute(
        """
        SELECT b.pnr, b.class_code, b.travel_date, b.status, b.queue_position,
               b.quota, t.train_number, t.train_name
        FROM bookings b
        JOIN trains t ON t.id = b.train_id
        WHERE b.status IN ('rac', 'waiting')
        ORDER BY b.travel_date, b.status DESC, b.queue_position
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def revenue_by_day(conn, days=7):
    rows = conn.execute(
        """
        SELECT date(paid_at) AS day, COALESCE(SUM(amount), 0) AS amount
        FROM payments
        WHERE status = 'success' AND date(paid_at) >= date('now', ?)
        GROUP BY date(paid_at)
        ORDER BY day
        """,
        (f"-{days - 1} days",),
    ).fetchall()
    return [dict(row) for row in rows]


def concession_totals(conn):
    row = conn.execute(
        """
        SELECT COALESCE(SUM(concession_amount), 0) AS waived,
               COALESCE(SUM(total_fare), 0) AS collected
        FROM bookings WHERE status != 'cancelled'
        """
    ).fetchone()
    by_type = conn.execute(
        """
        SELECT CASE
                   WHEN concession_percent = 100 THEN 'Infant'
                   WHEN concession_percent = 50 THEN 'Child'
                   WHEN concession_percent = 30 THEN 'Senior'
                   ELSE 'Adult'
               END AS passenger_type,
               COUNT(*) AS passengers,
               COALESCE(SUM(fare), 0) AS fare
        FROM passengers
        GROUP BY passenger_type
        ORDER BY passengers DESC
        """
    ).fetchall()
    return {"waived": row["waived"], "collected": row["collected"],
            "by_type": [dict(r) for r in by_type]}


def class_occupancy(conn, travel_date):
    """Seats booked per class on a date, for the dashboard heatmap."""
    rows = conn.execute(
        """
        SELECT c.class_code,
               COUNT(*) AS coaches,
               COALESCE(SUM(c.seat_count), 0) AS seats,
               (
                   SELECT COUNT(DISTINCT si.seat_id)
                   FROM seats s
                   JOIN coaches cc ON cc.id = s.coach_id
                   JOIN seat_inventory si ON si.seat_id = s.id
                   WHERE cc.class_code = c.class_code
                     AND si.travel_date = ?
                     AND si.status = 'booked'
               ) AS booked
        FROM coaches c
        GROUP BY c.class_code
        ORDER BY c.class_code
        """,
        (travel_date,),
    ).fetchall()
    return [dict(row) for row in rows]


def today():
    return today_ist().isoformat()
