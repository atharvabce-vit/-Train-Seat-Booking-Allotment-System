from config import MAX_PASSENGERS_PER_PNR
from models.fare import calculate_fare
from models.pnr import generate_pnr


class BookingError(Exception):
    pass


def get_available_seats(conn, train_id, class_code, travel_date):
    rows = conn.execute(
        """
        SELECT s.id AS seat_id, s.seat_number, s.berth_type,
               c.coach_name, c.id AS coach_id
        FROM seats s
        JOIN coaches c ON c.id = s.coach_id
        LEFT JOIN seat_inventory si
               ON si.seat_id = s.id AND si.travel_date = ?
        WHERE c.train_id = ?
          AND c.class_code = ?
          AND (si.id IS NULL OR si.status IN ('available', 'cancelled'))
        ORDER BY c.coach_name, s.seat_number
        """,
        (travel_date, train_id, class_code),
    ).fetchall()
    return [dict(r) for r in rows]


def _pick_seats(available, count):
    by_coach = {}
    for seat in available:
        by_coach.setdefault(seat["coach_name"], []).append(seat)

    for coach_name in sorted(by_coach):
        seats = sorted(by_coach[coach_name], key=lambda s: s["seat_number"])
        run = []
        for seat in seats:
            if run and seat["seat_number"] == run[-1]["seat_number"] + 1:
                run.append(seat)
            else:
                run = [seat]
            if len(run) == count:
                return run

    if len(available) >= count:
        return available[:count]
    return []


def book_seats(conn, user_id, train_id, class_code, travel_date, passengers):
    if not passengers:
        raise BookingError("At least one passenger is required.")
    if len(passengers) > MAX_PASSENGERS_PER_PNR:
        raise BookingError(f"A single PNR can hold at most {MAX_PASSENGERS_PER_PNR} passengers.")

    conn.execute("BEGIN IMMEDIATE")
    try:
        available = get_available_seats(conn, train_id, class_code, travel_date)
        seats = _pick_seats(available, len(passengers))
        if len(seats) < len(passengers):
            raise BookingError("Not enough seats available in the selected class.")

        pnr = generate_pnr(conn)
        total_fare = calculate_fare(class_code, len(passengers))
        cursor = conn.execute(
            """
            INSERT INTO bookings (pnr, user_id, train_id, class_code, travel_date, status, total_fare)
            VALUES (?, ?, ?, ?, ?, 'confirmed', ?)
            """,
            (pnr, user_id, train_id, class_code, travel_date, total_fare),
        )
        booking_id = cursor.lastrowid

        for passenger, seat in zip(passengers, seats):
            conn.execute(
                """
                INSERT INTO seat_inventory (seat_id, travel_date, status, booking_id)
                VALUES (?, ?, 'booked', ?)
                ON CONFLICT (seat_id, travel_date)
                DO UPDATE SET status = 'booked', booking_id = excluded.booking_id
                """,
                (seat["seat_id"], travel_date, booking_id),
            )
            conn.execute(
                """
                INSERT INTO passengers
                    (booking_id, name, age, gender, coach_name, seat_number, berth_type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    booking_id,
                    passenger["name"],
                    passenger["age"],
                    passenger["gender"],
                    seat["coach_name"],
                    seat["seat_number"],
                    seat["berth_type"],
                ),
            )

        conn.execute("COMMIT")
        return pnr
    except Exception:
        conn.execute("ROLLBACK")
        raise


def cancel_booking(conn, pnr):
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT id, status FROM bookings WHERE pnr = ?", (pnr,)).fetchone()
        if row is None:
            raise BookingError("PNR not found.")
        if row["status"] == "cancelled":
            raise BookingError("This booking is already cancelled.")

        conn.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (row["id"],))
        conn.execute(
            "UPDATE seat_inventory SET status = 'cancelled', booking_id = NULL WHERE booking_id = ?",
            (row["id"],),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def seat_availability_count(conn, train_id, class_code, travel_date):
    return len(get_available_seats(conn, train_id, class_code, travel_date))
