import secrets
from datetime import timedelta

from config import (
    DEFAULT_PAYMENT_METHOD,
    HOLD_TTL_SECONDS,
    MAX_PASSENGERS_PER_PNR,
    RAC_LIMIT,
    RESCHEDULE_FEE_MIN,
    RESCHEDULE_FEE_PCT,
    ROUND_TRIP_DISCOUNT_PCT,
    SENIOR_AGE,
)
from models import audit, notifications
from models.fare import (
    calculate_fare_with_concessions,
    fare_per_passenger,
    refund_amount,
)
from models.pnr import generate_pnr
from models.trains import (
    available_seats,
    hours_before_departure,
    is_bookable_date,
    quota_seat_count,
    segment_distance,
    tatkal_open,
)
from models.util import STAMP_FORMAT, now_str, now_utc


class BookingError(Exception):
    pass


class NoSeatsError(BookingError):
    pass


def effective_preference(passenger):
    preference = (passenger.get("preference") or "ANY").upper()
    if preference == "ANY" and int(passenger.get("age") or 0) >= SENIOR_AGE:
        return "LB"
    return preference


def _contiguous_blocks(seats, length):
    blocks = []
    by_coach = {}
    for seat in seats:
        by_coach.setdefault(seat["coach_name"], []).append(seat)
    for ordered in by_coach.values():
        ordered = sorted(ordered, key=lambda s: s["seat_number"])
        run = []
        for seat in ordered:
            if run and seat["seat_number"] == run[-1]["seat_number"] + 1:
                run.append(seat)
            else:
                run = [seat]
            if len(run) == length:
                blocks.append(list(run))
                run = run[1:]
    return blocks


def _assign_preferences(pool, preferences):
    remaining = list(pool)
    chosen = []
    for preference in preferences:
        picked = None
        if preference != "ANY":
            picked = next((s for s in remaining if s["berth_type"] == preference), None)
        if picked is None and remaining:
            picked = remaining[0]
        if picked is None:
            return []
        remaining.remove(picked)
        chosen.append(picked)
    return chosen


def allot_seats(available, passengers):
    """Pick seats for the party: one coach and consecutive numbers when
    possible, otherwise honour berth preferences, otherwise whatever is free."""
    needed = len(passengers)
    if needed == 0 or len(available) < needed:
        return []

    preferences = [effective_preference(p) for p in passengers]
    lower_berths_wanted = sum(1 for p in preferences if p == "LB")
    blocks = _contiguous_blocks(available, needed)

    if lower_berths_wanted == 0:
        if blocks:
            return list(blocks[0])
    else:
        for block in blocks:
            if sum(1 for s in block if s["berth_type"] == "LB") >= lower_berths_wanted:
                return _assign_preferences(block, preferences)

    if any(preference != "ANY" for preference in preferences):
        chosen = _assign_preferences(available, preferences)
        if len(chosen) == needed:
            return chosen

    if blocks:
        return _assign_preferences(blocks[0], preferences)
    return available[:needed]


def cleanup_expired_holds(conn):
    now = now_str()
    conn.execute(
        "DELETE FROM seat_inventory WHERE status = 'held' AND (hold_expires_at IS NULL OR hold_expires_at <= ?)",
        (now,),
    )
    conn.execute("DELETE FROM seat_holds WHERE expires_at <= ?", (now,))


def _normalise_passengers(passengers):
    cleaned = []
    for passenger in passengers:
        name = (passenger.get("name") or "").strip()
        if not name:
            continue
        try:
            age = int(passenger.get("age"))
        except (TypeError, ValueError):
            age = 0
        cleaned.append(
            {
                "name": name,
                "age": age,
                "gender": (passenger.get("gender") or "M").upper(),
                "preference": effective_preference({**passenger, "age": age}),
            }
        )
    return cleaned


def validate_party(conn, train_id, class_code, travel_date, from_seq, to_seq, quota, passengers):
    if not passengers:
        raise BookingError("At least one passenger is required.")
    if len(passengers) > MAX_PASSENGERS_PER_PNR:
        raise BookingError(f"A single PNR can hold at most {MAX_PASSENGERS_PER_PNR} passengers.")
    for passenger in passengers:
        if not 1 <= passenger["age"] <= 120:
            raise BookingError("Passenger age must be between 1 and 120.")
    if from_seq is None or to_seq is None or to_seq <= from_seq:
        raise BookingError("Choose a valid boarding and destination station.")
    if not is_bookable_date(travel_date):
        raise BookingError("The travel date is outside the booking window.")
    if quota_seat_count(conn, train_id, class_code, quota) == 0:
        raise BookingError("This class is not available on the selected train.")
    if quota == "TQ" and not tatkal_open(conn, train_id, travel_date, from_seq):
        raise BookingError("Tatkal booking opens 24 hours before departure.")


def create_hold(conn, train_id, class_code, travel_date, from_seq, to_seq, quota, passengers):
    passengers = _normalise_passengers(passengers)
    conn.execute("BEGIN IMMEDIATE")
    try:
        cleanup_expired_holds(conn)
        validate_party(
            conn, train_id, class_code, travel_date, from_seq, to_seq, quota, passengers
        )
        seats = allot_seats(
            available_seats(conn, train_id, class_code, travel_date, from_seq, to_seq, quota),
            passengers,
        )
        if len(seats) < len(passengers):
            raise NoSeatsError("Not enough seats in this class for the whole party.")

        token = secrets.token_urlsafe(16)
        expires_at = (now_utc() + timedelta(seconds=HOLD_TTL_SECONDS)).strftime(STAMP_FORMAT)
        conn.execute(
            """
            INSERT INTO seat_holds
                (token, train_id, class_code, travel_date, from_seq, to_seq, quota, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (token, train_id, class_code, travel_date, from_seq, to_seq, quota, expires_at),
        )
        for seat in seats:
            conn.execute(
                """
                INSERT INTO seat_inventory
                    (seat_id, travel_date, from_seq, to_seq, status, hold_token, hold_expires_at)
                VALUES (?, ?, ?, ?, 'held', ?, ?)
                """,
                (seat["seat_id"], travel_date, from_seq, to_seq, token, expires_at),
            )
        conn.execute("COMMIT")
        return {"token": token, "seats": seats, "expires_at": expires_at}
    except Exception:
        conn.execute("ROLLBACK")
        raise


def get_hold(conn, token):
    return conn.execute("SELECT * FROM seat_holds WHERE token = ?", (token,)).fetchone()


def hold_seats(conn, token):
    rows = conn.execute(
        """
        SELECT si.seat_id, s.seat_number, s.berth_type, c.coach_name
        FROM seat_inventory si
        JOIN seats   s ON s.id = si.seat_id
        JOIN coaches c ON c.id = s.coach_id
        WHERE si.hold_token = ?
        ORDER BY c.position, c.coach_name, s.seat_number
        """,
        (token,),
    ).fetchall()
    return [dict(row) for row in rows]


def confirm_booking(conn, user_id, token, passengers, method=DEFAULT_PAYMENT_METHOD, discount_pct=0):
    passengers = _normalise_passengers(passengers)
    conn.execute("BEGIN IMMEDIATE")
    try:
        hold = get_hold(conn, token)
        if hold is None:
            raise BookingError("This seat hold has expired. Please choose seats again.")
        if hold["expires_at"] <= now_str():
            raise BookingError("This seat hold has expired. Please choose seats again.")

        seats = hold_seats(conn, token)
        if len(seats) != len(passengers):
            raise BookingError("The passenger list no longer matches the held seats.")

        train_id = hold["train_id"]
        class_code = hold["class_code"]
        quota = hold["quota"]
        distance = segment_distance(conn, train_id, hold["from_seq"], hold["to_seq"])

        ages = [passenger["age"] for passenger in passengers]
        base_total, _, breakdown = calculate_fare_with_concessions(
            class_code, distance, quota, ages
        )
        if discount_pct:
            for item in breakdown:
                item["fare"] = int(round(item["fare"] * (100 - discount_pct) / 100))
        total_fare = sum(item["fare"] for item in breakdown)
        full_base = fare_per_passenger(class_code, distance, quota) * len(passengers)
        concession_amount = max(0, full_base - total_fare)

        pnr = generate_pnr(conn)

        cursor = conn.execute(
            """
            INSERT INTO bookings
                (pnr, user_id, train_id, class_code, travel_date, from_seq, to_seq,
                 quota, status, distance_km, total_fare, concession_amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, ?, ?)
            """,
            (
                pnr, user_id, train_id, class_code, hold["travel_date"],
                hold["from_seq"], hold["to_seq"], quota, distance, total_fare,
                concession_amount,
            ),
        )
        booking_id = cursor.lastrowid

        for passenger, seat, priced in zip(passengers, seats, breakdown):
            conn.execute(
                """
                INSERT INTO passengers
                    (booking_id, name, age, gender, preference, status, seat_id,
                     coach_name, seat_number, berth_type, concession_percent, fare)
                VALUES (?, ?, ?, ?, ?, 'confirmed', ?, ?, ?, ?, ?, ?)
                """,
                (
                    booking_id, passenger["name"], passenger["age"], passenger["gender"],
                    passenger["preference"], seat["seat_id"], seat["coach_name"],
                    seat["seat_number"], seat["berth_type"],
                    priced["concession_percent"], priced["fare"],
                ),
            )

            conn.execute(
                "UPDATE seat_inventory SET status = 'booked', booking_id = ? WHERE hold_token = ? AND seat_id = ?",
                (booking_id, token, seat["seat_id"]),
            )

        conn.execute(
            """
            INSERT INTO payments (booking_id, amount, method, status, txn_ref)
            VALUES (?, ?, ?, 'success', ?)
            """,
            (booking_id, total_fare, method, f"TXN{secrets.token_hex(6).upper()}"),
        )

        contact = conn.execute("SELECT name, email, phone FROM users WHERE id = ?", (user_id,)).fetchone()
        notifications.queue_email(
            conn, booking_id, contact["email"],
            f"Booking confirmed - PNR {pnr}",
            f"Your booking {pnr} is confirmed. {len(passengers)} passenger(s), total fare INR {total_fare}.",
        )
        if contact["phone"]:
            notifications.queue_sms(conn, booking_id, contact["phone"], f"PNR {pnr} confirmed. Happy journey!")

        conn.execute("DELETE FROM seat_holds WHERE token = ?", (token,))
        audit.log(
            conn, "book", "booking", pnr,
            f"{class_code}/{quota} {hold['travel_date']} leg {hold['from_seq']}->{hold['to_seq']} "
            f"{len(passengers)} pax, fare {total_fare} (concession {concession_amount})",
        )
        conn.execute("COMMIT")
        return pnr
    except Exception:
        conn.execute("ROLLBACK")
        raise


def book_seats(conn, user_id, train_id, class_code, travel_date, from_seq, to_seq, passengers,
               quota="GN", discount_pct=0):
    hold = create_hold(conn, train_id, class_code, travel_date, from_seq, to_seq, quota, passengers)
    return confirm_booking(conn, user_id, hold["token"], passengers, discount_pct=discount_pct)



def join_queue(conn, user_id, train_id, class_code, travel_date, from_seq, to_seq, quota, passengers):
    passengers = _normalise_passengers(passengers)
    conn.execute("BEGIN IMMEDIATE")
    try:
        cleanup_expired_holds(conn)
        validate_party(
            conn, train_id, class_code, travel_date, from_seq, to_seq, quota, passengers
        )
        rac_ahead = conn.execute(
            """
            SELECT COUNT(*) AS c FROM bookings
            WHERE train_id = ? AND class_code = ? AND travel_date = ? AND quota = ?
              AND status = 'rac'
            """,
            (train_id, class_code, travel_date, quota),
        ).fetchone()["c"]
        status = "rac" if rac_ahead < RAC_LIMIT else "waiting"
        position = conn.execute(
            """
            SELECT COUNT(*) AS c FROM bookings
            WHERE train_id = ? AND class_code = ? AND travel_date = ? AND quota = ?
              AND status = ?
            """,
            (train_id, class_code, travel_date, quota, status),
        ).fetchone()["c"] + 1

        distance = segment_distance(conn, train_id, from_seq, to_seq)
        ages = [passenger["age"] for passenger in passengers]
        total_fare, _, breakdown = calculate_fare_with_concessions(
            class_code, distance, quota, ages
        )
        full_base = fare_per_passenger(class_code, distance, quota) * len(passengers)
        concession_amount = max(0, full_base - total_fare)
        pnr = generate_pnr(conn)
        cursor = conn.execute(
            """
            INSERT INTO bookings
                (pnr, user_id, train_id, class_code, travel_date, from_seq, to_seq,
                 quota, status, queue_position, distance_km, total_fare, concession_amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pnr, user_id, train_id, class_code, travel_date, from_seq, to_seq,
                quota, status, position, distance, total_fare, concession_amount,
            ),
        )
        booking_id = cursor.lastrowid
        for passenger, priced in zip(passengers, breakdown):
            conn.execute(
                """
                INSERT INTO passengers
                    (booking_id, name, age, gender, preference, status, concession_percent, fare)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    booking_id, passenger["name"], passenger["age"],
                    passenger["gender"], passenger["preference"], status,
                    priced["concession_percent"], priced["fare"],
                ),
            )
        contact = conn.execute("SELECT name, email, phone FROM users WHERE id = ?", (user_id,)).fetchone()
        label = "RAC" if status == "rac" else "Waitlist"
        notifications.queue_email(
            conn, booking_id, contact["email"],
            f"{label} {position} - PNR {pnr}",
            f"No confirmed seats were free, so booking {pnr} is on the {label} list at position {position}.",
        )
        audit.log(conn, "queue", "booking", pnr, f"{status} position {position} ({class_code}/{quota})")
        conn.execute("COMMIT")
        return pnr, status, position
    except Exception:
        conn.execute("ROLLBACK")
        raise



def _booking_passengers(conn, booking_id):
    rows = conn.execute(
        "SELECT name, age, gender, preference FROM passengers WHERE booking_id = ? ORDER BY id",
        (booking_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _renumber_queue(conn, train_id, class_code, travel_date, quota):
    for status in ("rac", "waiting"):
        rows = conn.execute(
            """
            SELECT id FROM bookings
            WHERE train_id = ? AND class_code = ? AND travel_date = ? AND quota = ?
              AND status = ?
            ORDER BY queue_position, booked_at
            """,
            (train_id, class_code, travel_date, quota, status),
        ).fetchall()
        for position, row in enumerate(rows, start=1):
            conn.execute("UPDATE bookings SET queue_position = ? WHERE id = ?", (position, row["id"]))


def promote_queue(conn, train_id, class_code, travel_date, quota):
    """Move RAC first, then waitlisted bookings, onto any seats that are free."""
    promoted = []
    queued = conn.execute(
        """
        SELECT * FROM bookings
        WHERE train_id = ? AND class_code = ? AND travel_date = ? AND quota = ?
          AND status IN ('rac', 'waiting')
        ORDER BY CASE status WHEN 'rac' THEN 0 ELSE 1 END, queue_position, booked_at
        """,
        (train_id, class_code, travel_date, quota),
    ).fetchall()

    for booking in queued:
        passengers = _booking_passengers(conn, booking["id"])
        free = available_seats(
            conn, train_id, class_code, travel_date,
            booking["from_seq"], booking["to_seq"], quota,
        )
        seats = allot_seats(free, passengers)
        if len(seats) < len(passengers):
            continue

        conn.execute(
            "UPDATE bookings SET status = 'confirmed', queue_position = NULL WHERE id = ?",
            (booking["id"],),
        )
        for passenger, seat in zip(passengers, seats):
            conn.execute(
                """
                UPDATE passengers
                SET status = 'confirmed', seat_id = ?, coach_name = ?,
                    seat_number = ?, berth_type = ?
                WHERE booking_id = ? AND name = ? AND age = ?
                """,
                (
                    seat["seat_id"], seat["coach_name"], seat["seat_number"],
                    seat["berth_type"], booking["id"], passenger["name"], passenger["age"],
                ),
            )
            conn.execute(
                """
                INSERT INTO seat_inventory
                    (seat_id, travel_date, from_seq, to_seq, status, booking_id)
                VALUES (?, ?, ?, ?, 'booked', ?)
                """,
                (
                    seat["seat_id"], travel_date, booking["from_seq"],
                    booking["to_seq"], booking["id"],
                ),
            )
        conn.execute(
            """
            INSERT INTO payments (booking_id, amount, method, status, txn_ref)
            VALUES (?, ?, 'MOCK', 'success', ?)
            """,
            (booking["id"], booking["total_fare"], f"TXN{secrets.token_hex(6).upper()}"),
        )
        contact = conn.execute(
            "SELECT email, phone FROM users WHERE id = ?", (booking["user_id"],)
        ).fetchone()
        notifications.queue_email(
            conn, booking["id"], contact["email"],
            f"Booking confirmed - PNR {booking['pnr']}",
            f"A seat was released, so PNR {booking['pnr']} is now confirmed.",
        )
        promoted.append(booking["pnr"])

    _renumber_queue(conn, train_id, class_code, travel_date, quota)
    return promoted


def cancel_booking(conn, pnr):
    conn.execute("BEGIN IMMEDIATE")
    try:
        booking = conn.execute("SELECT * FROM bookings WHERE pnr = ?", (pnr,)).fetchone()
        if booking is None:
            raise BookingError("PNR not found.")
        if booking["status"] == "cancelled":
            raise BookingError("This booking is already cancelled.")

        conn.execute(
            "UPDATE bookings SET status = 'cancelled', cancelled_at = ? WHERE id = ?",
            (now_str(), booking["id"]),
        )
        conn.execute("UPDATE passengers SET status = 'cancelled' WHERE booking_id = ?", (booking["id"],))
        conn.execute(
            "UPDATE seat_inventory SET status = 'cancelled' WHERE booking_id = ?", (booking["id"],)
        )

        refund = None
        if booking["status"] == "confirmed":
            hours = hours_before_departure(
                conn, booking["train_id"], booking["travel_date"], booking["from_seq"]
            )
            amount, percent = refund_amount(booking["total_fare"], hours)
            conn.execute(
                "INSERT INTO refunds (booking_id, percent, amount, reason) VALUES (?, ?, ?, ?)",
                (booking["id"], percent, amount, f"Cancelled {hours:.0f} hours before departure"),
            )
            refund = {"percent": percent, "amount": amount}

        contact = conn.execute(
            "SELECT email, phone FROM users WHERE id = ?", (booking["user_id"],)
        ).fetchone()
        notifications.queue_email(
            conn, booking["id"], contact["email"],
            f"Booking cancelled - PNR {pnr}",
            f"Booking {pnr} has been cancelled."
            + (f" Refund of INR {refund['amount']} ({refund['percent']}%) initiated." if refund else ""),
        )

        promoted = promote_queue(
            conn, booking["train_id"], booking["class_code"],
            booking["travel_date"], booking["quota"],
        )
        audit.log(
            conn, "cancel", "booking", pnr,
            f"fare {booking['total_fare']}, refund {refund['amount'] if refund else 0}, "
            f"promoted {len(promoted)}",
        )
        conn.execute("COMMIT")
        return {"refund": refund, "promoted": promoted}
    except Exception:
        conn.execute("ROLLBACK")
        raise


def cancel_passengers(conn, pnr, passenger_ids):
    """Cancel only the listed passengers on a PNR and refund their share."""
    passenger_ids = {int(pid) for pid in passenger_ids}
    conn.execute("BEGIN IMMEDIATE")
    try:
        booking = conn.execute("SELECT * FROM bookings WHERE pnr = ?", (pnr,)).fetchone()
        if booking is None:
            raise BookingError("PNR not found.")
        if booking["status"] == "cancelled":
            raise BookingError("This booking is already cancelled.")

        rows = conn.execute(
            "SELECT id, name, fare, seat_id FROM passengers WHERE booking_id = ? AND status != 'cancelled'",
            (booking["id"],),
        ).fetchall()
        target = [row for row in rows if row["id"] in passenger_ids]
        if not target:
            raise BookingError("Select at least one passenger to cancel.")
        remaining = [row for row in rows if row["id"] not in passenger_ids]

        for row in target:
            conn.execute("UPDATE passengers SET status = 'cancelled' WHERE id = ?", (row["id"],))
            if row["seat_id"]:
                conn.execute(
                    "UPDATE seat_inventory SET status = 'cancelled' WHERE booking_id = ? AND seat_id = ?",
                    (booking["id"], row["seat_id"]),
                )

        cancelled_fare = sum(row["fare"] for row in target)
        hours = hours_before_departure(
            conn, booking["train_id"], booking["travel_date"], booking["from_seq"]
        )
        amount, percent = refund_amount(cancelled_fare, hours)
        conn.execute(
            "INSERT INTO refunds (booking_id, percent, amount, reason) VALUES (?, ?, ?, ?)",
            (
                booking["id"], percent, amount,
                f"{len(target)} passenger(s) cancelled {hours:.0f} hours before departure",
            ),
        )

        fully_cancelled = not remaining
        if fully_cancelled:
            conn.execute(
                "UPDATE bookings SET status = 'cancelled', cancelled_at = ? WHERE id = ?",
                (now_str(), booking["id"]),
            )

        contact = conn.execute(
            "SELECT email, phone FROM users WHERE id = ?", (booking["user_id"],)
        ).fetchone()
        notifications.queue_email(
            conn, booking["id"], contact["email"],
            f"Partial cancellation - PNR {pnr}",
            f"{len(target)} passenger(s) cancelled on {pnr}. Refund of INR {amount} ({percent}%).",
        )

        promoted = []
        if remaining or fully_cancelled:
            promoted = promote_queue(
                conn, booking["train_id"], booking["class_code"],
                booking["travel_date"], booking["quota"],
            )
        audit.log(
            conn, "partial_cancel", "booking", pnr,
            f"cancelled {len(target)} of {len(rows)}, refund {amount} ({percent}%)",
        )
        conn.execute("COMMIT")
        return {
            "refund": {"percent": percent, "amount": amount},
            "promoted": promoted,
            "remaining": len(remaining),
        }
    except Exception:
        conn.execute("ROLLBACK")
        raise


def reschedule_booking(conn, pnr, new_date, new_from_seq=None, new_to_seq=None):
    """Move a confirmed booking to another date/leg, re-allotting seats and
    charging a change fee."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        booking = conn.execute("SELECT * FROM bookings WHERE pnr = ?", (pnr,)).fetchone()
        if booking is None:
            raise BookingError("PNR not found.")
        if booking["status"] != "confirmed":
            raise BookingError("Only confirmed bookings can be rescheduled.")

        from_seq = new_from_seq or booking["from_seq"]
        to_seq = new_to_seq or booking["to_seq"]
        if to_seq <= from_seq:
            raise BookingError("Choose a valid boarding and destination station.")
        if new_date == booking["travel_date"] and from_seq == booking["from_seq"] and to_seq == booking["to_seq"]:
            raise BookingError("The new journey is identical to the current one.")
        if not is_bookable_date(new_date):
            raise BookingError("The new travel date is outside the booking window.")

        passengers = conn.execute(
            "SELECT id, name, age, gender, preference FROM passengers "
            "WHERE booking_id = ? AND status != 'cancelled' ORDER BY id",
            (booking["id"],),
        ).fetchall()
        if not passengers:
            raise BookingError("This booking has no active passengers.")

        conn.execute(
            "UPDATE seat_inventory SET status = 'cancelled' WHERE booking_id = ?",
            (booking["id"],),
        )
        free = available_seats(
            conn, booking["train_id"], booking["class_code"], new_date,
            from_seq, to_seq, booking["quota"],
        )
        seats = allot_seats(free, [dict(p) for p in passengers])
        if len(seats) < len(passengers):
            raise BookingError("No seats available on the new date. Booking left unchanged.")

        for passenger, seat in zip(passengers, seats):
            conn.execute(
                """
                UPDATE passengers
                SET seat_id = ?, coach_name = ?, seat_number = ?, berth_type = ?
                WHERE id = ?
                """,
                (
                    seat["seat_id"], seat["coach_name"], seat["seat_number"],
                    seat["berth_type"], passenger["id"],
                ),
            )
            conn.execute(
                """
                INSERT INTO seat_inventory
                    (seat_id, travel_date, from_seq, to_seq, status, booking_id)
                VALUES (?, ?, ?, ?, 'booked', ?)
                """,
                (seat["seat_id"], new_date, from_seq, to_seq, booking["id"]),
            )

        distance = segment_distance(conn, booking["train_id"], from_seq, to_seq)
        fee = max(RESCHEDULE_FEE_MIN, int(round(booking["total_fare"] * RESCHEDULE_FEE_PCT / 100)))
        conn.execute(
            """
            UPDATE bookings
            SET travel_date = ?, from_seq = ?, to_seq = ?, distance_km = ?,
                change_count = change_count + 1
            WHERE id = ?
            """,
            (new_date, from_seq, to_seq, distance, booking["id"]),
        )
        conn.execute(
            """
            INSERT INTO booking_changes
                (booking_id, old_date, new_date, old_from_seq, old_to_seq,
                 new_from_seq, new_to_seq, fee)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                booking["id"], booking["travel_date"], new_date,
                booking["from_seq"], booking["to_seq"], from_seq, to_seq, fee,
            ),
        )
        conn.execute(
            "INSERT INTO payments (booking_id, amount, method, status, txn_ref) VALUES (?, ?, 'MOCK', 'success', ?)",
            (booking["id"], fee, f"TXN{secrets.token_hex(6).upper()}"),
        )
        contact = conn.execute(
            "SELECT email, phone FROM users WHERE id = ?", (booking["user_id"],)
        ).fetchone()
        notifications.queue_email(
            conn, booking["id"], contact["email"],
            f"Booking rescheduled - PNR {pnr}",
            f"Booking {pnr} moved to {new_date}. Change fee INR {fee}.",
        )
        audit.log(
            conn, "reschedule", "booking", pnr,
            f"{booking['travel_date']} -> {new_date}, fee {fee}",
        )
        conn.execute("COMMIT")
        return {"fee": fee, "new_date": new_date, "seats": seats}
    except Exception:
        conn.execute("ROLLBACK")
        raise


def book_round_trip(conn, user_id, outbound, inbound):
    """Book an outbound and a return leg, linked by a shared group id.

    Each leg is booked inside its own transaction; if the return leg fails the
    outbound is cancelled, so the user is never charged for half a trip.
    """
    group_id = secrets.token_hex(8)
    outbound_pnr = book_seats(
        conn, user_id, outbound["train_id"], outbound["class_code"],
        outbound["travel_date"], outbound["from_seq"], outbound["to_seq"],
        outbound["passengers"], outbound.get("quota", "GN"),
    )
    _assign_group(conn, outbound_pnr, group_id)
    try:
        inbound_pnr = book_seats(
            conn, user_id, inbound["train_id"], inbound["class_code"],
            inbound["travel_date"], inbound["from_seq"], inbound["to_seq"],
            inbound["passengers"], inbound.get("quota", "GN"),
            discount_pct=ROUND_TRIP_DISCOUNT_PCT,
        )
    except Exception:
        cancel_booking(conn, outbound_pnr)
        raise
    _assign_group(conn, inbound_pnr, group_id)
    audit.log(conn, "round_trip", "group", group_id, f"{outbound_pnr} + {inbound_pnr}")
    return {"group_id": group_id, "outbound": outbound_pnr, "return": inbound_pnr}


def _assign_group(conn, pnr, group_id):
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE bookings SET group_id = ?, trip_type = 'ROUND_TRIP' WHERE pnr = ?",
            (group_id, pnr),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def group_bookings(conn, group_id):
    rows = conn.execute(
        "SELECT pnr, travel_date, class_code, status, total_fare FROM bookings "
        "WHERE group_id = ? ORDER BY travel_date",
        (group_id,),
    ).fetchall()
    return [dict(row) for row in rows]

