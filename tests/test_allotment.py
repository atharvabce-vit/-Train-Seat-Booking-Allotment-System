import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import create_tables, get_connection
from models.booking import BookingError, book_seats, cancel_booking, get_available_seats
from models.pnr import get_booking_by_pnr
from seed import create_train

TRAVEL_DATE = date.today().isoformat()
PLAN_ONE_COACH = {"SL": (1, 10)}
PLAN_TWO_COACHES = {"SL": (2, 6)}


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "allotment.db")
    conn = get_connection(db_path)
    create_tables(conn)
    yield conn
    conn.close()


def make_user(conn):
    cursor = conn.execute(
        "INSERT INTO users (name, email) VALUES ('Test User', 'test@example.com')"
    )
    return cursor.lastrowid


def occupy_seats(conn, train_id, class_code, seat_numbers, travel_date=TRAVEL_DATE, coach_name=None):
    seat_numbers = list(seat_numbers)
    if not seat_numbers:
        return
    placeholders = ", ".join("?" for _ in seat_numbers)
    coach_clause = "AND c.coach_name = ?" if coach_name else ""
    params = (train_id, class_code, *seat_numbers)
    if coach_name:
        params = (train_id, class_code, coach_name, *seat_numbers)
    rows = conn.execute(
        f"""
        SELECT s.id FROM seats s
        JOIN coaches c ON c.id = s.coach_id
        WHERE c.train_id = ? AND c.class_code = ?
          {coach_clause}
          AND s.seat_number IN ({placeholders})
        """,
        params,
    ).fetchall()
    for row in rows:
        conn.execute(
            "INSERT INTO seat_inventory (seat_id, travel_date, status) VALUES (?, ?, 'booked')",
            (row["id"], travel_date),
        )


def passengers(count):
    return [
        {"name": f"Passenger {i}", "age": 30, "gender": "M"}
        for i in range(1, count + 1)
    ]


def test_contiguous_seats_are_allotted_first(db):
    train_id = create_train(db, "90001", "Test Express", "A", "B", "10:00", "18:00", plan=PLAN_ONE_COACH)
    user_id = make_user(db)

    pnr = book_seats(db, user_id, train_id, "SL", TRAVEL_DATE, passengers(3))

    record = get_booking_by_pnr(db, pnr)
    seat_numbers = sorted(p["seat_number"] for p in record["passengers"])
    coaches = {p["coach_name"] for p in record["passengers"]}

    assert seat_numbers == [1, 2, 3]
    assert len(coaches) == 1
    assert len(record["passengers"]) == 3


def test_contiguous_block_avoiding_booked_seats(db):
    train_id = create_train(db, "90002", "Test Express", "A", "B", "10:00", "18:00", plan=PLAN_ONE_COACH)
    user_id = make_user(db)
    occupy_seats(db, train_id, "SL", [1, 2, 3, 7, 8, 9, 10])

    pnr = book_seats(db, user_id, train_id, "SL", TRAVEL_DATE, passengers(3))

    record = get_booking_by_pnr(db, pnr)
    seat_numbers = sorted(p["seat_number"] for p in record["passengers"])
    assert seat_numbers == [4, 5, 6]


def test_fallback_to_any_available_seat(db):
    train_id = create_train(db, "90003", "Test Express", "A", "B", "10:00", "18:00", plan=PLAN_ONE_COACH)
    user_id = make_user(db)
    occupy_seats(db, train_id, "SL", [2, 4, 6, 8, 10])

    pnr = book_seats(db, user_id, train_id, "SL", TRAVEL_DATE, passengers(2))

    record = get_booking_by_pnr(db, pnr)
    seat_numbers = sorted(p["seat_number"] for p in record["passengers"])
    assert seat_numbers == [1, 3]
    assert seat_numbers[1] - seat_numbers[0] != 1


def test_allotment_stays_within_one_coach(db):
    train_id = create_train(db, "90004", "Test Express", "A", "B", "10:00", "18:00", plan=PLAN_TWO_COACHES)
    user_id = make_user(db)
    occupy_seats(db, train_id, "SL", [1, 2, 3, 4, 5, 6], coach_name="S1")

    pnr = book_seats(db, user_id, train_id, "SL", TRAVEL_DATE, passengers(3))

    record = get_booking_by_pnr(db, pnr)
    coaches = {p["coach_name"] for p in record["passengers"]}
    assert len(coaches) == 1
    assert sorted(p["seat_number"] for p in record["passengers"]) == [1, 2, 3]


def test_booking_fails_when_not_enough_seats(db):
    train_id = create_train(db, "90005", "Test Express", "A", "B", "10:00", "18:00", plan=PLAN_ONE_COACH)
    user_id = make_user(db)
    occupy_seats(db, train_id, "SL", [1, 2, 3, 4, 5, 6, 7, 8])

    with pytest.raises(BookingError):
        book_seats(db, user_id, train_id, "SL", TRAVEL_DATE, passengers(3))


def test_cancellation_releases_seats(db):
    train_id = create_train(db, "90006", "Test Express", "A", "B", "10:00", "18:00", plan=PLAN_ONE_COACH)
    user_id = make_user(db)

    pnr = book_seats(db, user_id, train_id, "SL", TRAVEL_DATE, passengers(2))
    assert len(get_available_seats(db, train_id, "SL", TRAVEL_DATE)) == 8

    cancel_booking(db, pnr)
    assert len(get_available_seats(db, train_id, "SL", TRAVEL_DATE)) == 10

    record = get_booking_by_pnr(db, pnr)
    assert record["booking"]["status"] == "cancelled"


def test_passenger_limit_enforced(db):
    train_id = create_train(db, "90007", "Test Express", "A", "B", "10:00", "18:00", plan=PLAN_ONE_COACH)
    user_id = make_user(db)

    with pytest.raises(BookingError):
        book_seats(db, user_id, train_id, "SL", TRAVEL_DATE, passengers(7))
