import random


def generate_pnr(conn):
    while True:
        pnr = "".join(random.choices("0123456789", k=10))
        if pnr[0] == "0":
            pnr = "9" + pnr[1:]
        exists = conn.execute("SELECT 1 FROM bookings WHERE pnr = ?", (pnr,)).fetchone()
        if exists is None:
            return pnr


def get_booking_by_pnr(conn, pnr):
    booking = conn.execute(
        """
        SELECT b.*,
               t.train_number, t.train_name, t.runs_on,
               fs.seq AS from_seq, fst.code AS from_code, fst.name AS from_name,
               fst.city AS from_city, fs.departure_time AS depart_time,
               fs.day_offset AS from_day,
               ts.seq AS to_seq, tst.code AS to_code, tst.name AS to_name,
               tst.city AS to_city, ts.arrival_time AS arrive_time,
               ts.day_offset AS to_day,
               u.name AS user_name, u.email, u.phone
        FROM bookings b
        JOIN trains t ON t.id = b.train_id
        JOIN train_stops fs ON fs.train_id = b.train_id AND fs.seq = b.from_seq
        JOIN stations fst ON fst.code = fs.station_code
        JOIN train_stops ts ON ts.train_id = b.train_id AND ts.seq = b.to_seq
        JOIN stations tst ON tst.code = ts.station_code
        JOIN users u ON u.id = b.user_id
        WHERE b.pnr = ?
        """,
        (pnr,),
    ).fetchone()
    if booking is None:
        return None

    passengers = conn.execute(
        """
        SELECT id, name, age, gender, preference, status,
               coach_name, seat_number, berth_type
        FROM passengers
        WHERE booking_id = ?
        ORDER BY id
        """,
        (booking["id"],),
    ).fetchall()

    refunds = conn.execute(
        "SELECT percent, amount, reason, created_at FROM refunds WHERE booking_id = ? ORDER BY id DESC",
        (booking["id"],),
    ).fetchall()

    payments = conn.execute(
        "SELECT amount, method, status, txn_ref, paid_at FROM payments WHERE booking_id = ? ORDER BY id DESC",
        (booking["id"],),
    ).fetchall()

    return {
        "booking": dict(booking),
        "passengers": [dict(p) for p in passengers],
        "refunds": [dict(r) for r in refunds],
        "payments": [dict(p) for p in payments],
    }


def bookings_for_email(conn, email):
    rows = conn.execute(
        """
        SELECT b.pnr, b.travel_date, b.class_code, b.status, b.quota,
               b.total_fare, b.booked_at, b.queue_position,
               t.train_number, t.train_name,
               fst.city AS from_city, tst.city AS to_city
        FROM bookings b
        JOIN users u ON u.id = b.user_id
        JOIN trains t ON t.id = b.train_id
        JOIN train_stops fs ON fs.train_id = b.train_id AND fs.seq = b.from_seq
        JOIN stations fst ON fst.code = fs.station_code
        JOIN train_stops ts ON ts.train_id = b.train_id AND ts.seq = b.to_seq
        JOIN stations tst ON tst.code = ts.station_code
        WHERE u.email = ? COLLATE NOCASE
        ORDER BY b.booked_at DESC, b.id DESC
        """,
        (email,),
    ).fetchall()
    return [dict(row) for row in rows]
