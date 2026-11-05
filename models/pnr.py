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
        SELECT b.*, t.train_number, t.train_name, t.source, t.destination,
               t.depart_time, t.arrive_time, u.name AS user_name, u.email, u.phone
        FROM bookings b
        JOIN trains t ON t.id = b.train_id
        JOIN users  u ON u.id = b.user_id
        WHERE b.pnr = ?
        """,
        (pnr,),
    ).fetchone()
    if booking is None:
        return None

    passengers = conn.execute(
        """
        SELECT name, age, gender, coach_name, seat_number, berth_type
        FROM passengers
        WHERE booking_id = ?
        ORDER BY id
        """,
        (booking["id"],),
    ).fetchall()

    return {"booking": dict(booking), "passengers": [dict(p) for p in passengers]}
