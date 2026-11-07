import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import create_tables, get_connection
from models.booking import BookingError, book_seats, join_queue
from models.chart import prepare_chart
from models.pnr import get_booking_by_pnr
from models.trains import is_chart_prepared
from seed import create_train

TRAVEL_DATE = (date.today() + timedelta(days=1)).isoformat()


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "chart.db")
    conn = get_connection(db_path)
    create_tables(conn)
    yield conn
    conn.close()


def make_user(conn):
    cursor = conn.execute(
        "INSERT INTO users (name, email) VALUES ('Test User', 'test@example.com')"
    )
    return cursor.lastrowid


def make_train(conn, train_number, plan):
    return create_train(
        conn, train_number, "Test Express", "A", "B", "10:00", "18:00",
        plan=plan, tatkal_ratio=0,
    )


def occupy_seats(conn, train_id, class_code, seat_numbers, from_seq=1, to_seq=2):
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
            (row["id"], TRAVEL_DATE, from_seq, to_seq),
        )


def passengers(count, age=30):
    return [
        {"name": f"Passenger {i}", "age": age, "gender": "M", "preference": "ANY"}
        for i in range(1, count + 1)
    ]


def test_chart_preparation_confirms_queued_bookings(db):
    train_id = make_train(db, "91001", {"SL": (1, 2)})
    user_id = make_user(db)

    occupy_seats(db, train_id, "SL", [1, 2])
    pnr, status, _ = join_queue(db, user_id, train_id, "SL", TRAVEL_DATE, 1, 2, "GN", passengers(1))
    assert status == "rac"

    # Seats are released but no cancellation runs promote_queue, so the RAC
    # booking is still queued when the chart is prepared.
    db.execute("DELETE FROM seat_inventory WHERE travel_date = ?", (TRAVEL_DATE,))

    promoted = prepare_chart(db, train_id, TRAVEL_DATE)

    assert pnr in promoted
    record = get_booking_by_pnr(db, pnr)
    assert record["booking"]["status"] == "confirmed"
    assert record["passengers"][0]["seat_number"] is not None
    assert is_chart_prepared(db, train_id, TRAVEL_DATE)


def test_chart_blocks_new_bookings(db):
    train_id = make_train(db, "91002", {"SL": (1, 10)})
    user_id = make_user(db)

    prepare_chart(db, train_id, TRAVEL_DATE)

    with pytest.raises(BookingError):
        book_seats(db, user_id, train_id, "SL", TRAVEL_DATE, 1, 2, passengers(1))


def test_prepare_chart_is_idempotent(db):
    train_id = make_train(db, "91003", {"SL": (1, 10)})

    prepare_chart(db, train_id, TRAVEL_DATE)

    with pytest.raises(BookingError):
        prepare_chart(db, train_id, TRAVEL_DATE)
