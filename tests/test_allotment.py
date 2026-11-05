import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import create_tables, get_connection
from models.booking import BookingError, book_seats, cancel_booking
from models.pnr import get_booking_by_pnr
from models.trains import available_count, available_seats, quota_seat_count
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


def make_train(conn, train_number, plan=PLAN_ONE_COACH, tatkal_ratio=0, stops=None):
    return create_train(
        conn, train_number, "Test Express", "A", "B", "10:00", "18:00",
        plan=plan, tatkal_ratio=tatkal_ratio, stops=stops,
    )


THREE_STOPS = [
    {"station": "A", "arrival": None, "departure": "10:00", "day": 0, "distance": 0},
    {"station": "B", "arrival": "14:00", "departure": "14:10", "day": 0, "distance": 300},
    {"station": "C", "arrival": "18:00", "departure": None, "day": 0, "distance": 600},
]


def occupy_seats(conn, train_id, class_code, seat_numbers, from_seq=1, to_seq=2, travel_date=TRAVEL_DATE):
    seat_numbers = list(seat_numbers)
    if not seat_numbers:
        return
    placeholders = ", ".join("?" for _ in seat_numbers)
    rows = conn.execute(
        f"""
        SELECT s.id FROM seats s
        JOIN coaches c ON c.id = s.coach_id
        WHERE c.train_id = ? AND c.class_code = ? AND s.seat_number IN ({placeholders})
        """,
        (train_id, class_code, *seat_numbers),
    ).fetchall()
    for row in rows:
        conn.execute(
            """
            INSERT INTO seat_inventory (seat_id, travel_date, from_seq, to_seq, status)
            VALUES (?, ?, ?, ?, 'booked')
            """,
            (row["id"], travel_date, from_seq, to_seq),
        )


def passengers(count, age=30, preference="ANY"):
    return [
        {"name": f"Passenger {i}", "age": age, "gender": "M", "preference": preference}
        for i in range(1, count + 1)
    ]


def test_contiguous_seats_are_allotted_first(db):
    train_id = make_train(db, "90001")
    user_id = make_user(db)

    pnr = book_seats(db, user_id, train_id, "SL", TRAVEL_DATE, 1, 2, passengers(3))

    record = get_booking_by_pnr(db, pnr)
    seat_numbers = sorted(p["seat_number"] for p in record["passengers"])
    coaches = {p["coach_name"] for p in record["passengers"]}

    assert seat_numbers == [1, 2, 3]
    assert len(coaches) == 1
    assert len(record["passengers"]) == 3


def test_contiguous_block_avoiding_booked_seats(db):
    train_id = make_train(db, "90002")
    user_id = make_user(db)
    occupy_seats(db, train_id, "SL", [1, 2, 3, 7, 8, 9, 10])

    pnr = book_seats(db, user_id, train_id, "SL", TRAVEL_DATE, 1, 2, passengers(3))

    record = get_booking_by_pnr(db, pnr)
    seat_numbers = sorted(p["seat_number"] for p in record["passengers"])
    assert seat_numbers == [4, 5, 6]


def test_fallback_to_any_available_seat(db):
    train_id = make_train(db, "90003")
    user_id = make_user(db)
    occupy_seats(db, train_id, "SL", [2, 4, 6, 8, 10])

    pnr = book_seats(db, user_id, train_id, "SL", TRAVEL_DATE, 1, 2, passengers(2))

    record = get_booking_by_pnr(db, pnr)
    seat_numbers = sorted(p["seat_number"] for p in record["passengers"])
    assert seat_numbers == [1, 3]


def test_allotment_stays_within_one_coach(db):
    train_id = make_train(db, "90004", plan=PLAN_TWO_COACHES)
    user_id = make_user(db)

    pnr = book_seats(db, user_id, train_id, "SL", TRAVEL_DATE, 1, 2, passengers(4))

    record = get_booking_by_pnr(db, pnr)
    coaches = {p["coach_name"] for p in record["passengers"]}
    assert len(coaches) == 1


def test_over_capacity_goes_to_queue(db):
    from models.booking import join_queue

    train_id = make_train(db, "90005")
    user_id = make_user(db)
    occupy_seats(db, train_id, "SL", range(1, 11))

    pnr, status, position = join_queue(db, user_id, train_id, "SL", TRAVEL_DATE, 1, 2, "GN", passengers(1))
    record = get_booking_by_pnr(db, pnr)

    assert status == "rac"
    assert position == 1
    assert record["booking"]["status"] == "rac"
    assert record["passengers"][0]["seat_number"] is None


def test_max_six_passengers_per_pnr(db):
    train_id = make_train(db, "90006")
    user_id = make_user(db)

    with pytest.raises(BookingError):
        book_seats(db, user_id, train_id, "SL", TRAVEL_DATE, 1, 2, passengers(7))


def test_booking_window_is_enforced(db):
    train_id = make_train(db, "90007")
    user_id = make_user(db)
    far_date = (date.today() + timedelta(days=60)).isoformat()

    with pytest.raises(BookingError):
        book_seats(db, user_id, train_id, "SL", far_date, 1, 2, passengers(1))


def test_cancellation_releases_seats(db):
    train_id = make_train(db, "90008")
    user_id = make_user(db)

    pnr = book_seats(db, user_id, train_id, "SL", TRAVEL_DATE, 1, 2, passengers(2))
    assert available_count(db, train_id, "SL", TRAVEL_DATE, 1, 2) == 8

    cancel_booking(db, pnr)
    assert available_count(db, train_id, "SL", TRAVEL_DATE, 1, 2) == 10


def test_berth_preference_is_honoured(db):
    train_id = make_train(db, "90009")
    user_id = make_user(db)

    pnr = book_seats(db, user_id, train_id, "SL", TRAVEL_DATE, 1, 2, passengers(2, preference="LB"))

    record = get_booking_by_pnr(db, pnr)
    berths = [p["berth_type"] for p in record["passengers"]]
    assert berths == ["LB", "LB"]


def test_senior_gets_lower_berth(db):
    train_id = make_train(db, "90010")
    user_id = make_user(db)

    pnr = book_seats(
        db, user_id, train_id, "SL", TRAVEL_DATE, 1, 2,
        [{"name": "Elder", "age": 65, "gender": "M", "preference": "ANY"}],
    )

    record = get_booking_by_pnr(db, pnr)
    assert record["passengers"][0]["berth_type"] == "LB"


def test_tatkal_quota_is_separate_from_general(db):
    train_id = make_train(db, "90011", tatkal_ratio=0.25)

    assert quota_seat_count(db, train_id, "SL", "GN") == 8
    assert quota_seat_count(db, train_id, "SL", "TQ") == 2

    tatkal_numbers = [seat["seat_number"] for seat in available_seats(db, train_id, "SL", TRAVEL_DATE, 1, 2, "TQ")]
    assert tatkal_numbers == [1, 2]


def test_part_route_booking_shares_a_seat(db):
    train_id = make_train(db, "90012", stops=THREE_STOPS)
    user_id = make_user(db)

    first = book_seats(db, user_id, train_id, "SL", TRAVEL_DATE, 1, 2, passengers(1))
    assert available_count(db, train_id, "SL", TRAVEL_DATE, 1, 2) == 9

    second = book_seats(db, user_id, train_id, "SL", TRAVEL_DATE, 2, 3, passengers(1))
    second_record = get_booking_by_pnr(db, second)
    first_record = get_booking_by_pnr(db, first)

    assert second_record["passengers"][0]["seat_number"] == first_record["passengers"][0]["seat_number"]


def test_duplicate_seats_are_never_issued(db):
    train_id = make_train(db, "90013")
    user_id = make_user(db)

    for _ in range(3):
        book_seats(db, user_id, train_id, "SL", TRAVEL_DATE, 1, 2, passengers(3))

    duplicates = db.execute(
        "SELECT seat_number FROM passengers GROUP BY coach_name, seat_number HAVING COUNT(*) > 1"
    ).fetchall()
    assert duplicates == []
