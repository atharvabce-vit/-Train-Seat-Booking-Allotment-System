import os
import sys
import threading
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import create_tables, get_connection
from models.booking import BookingError, book_seats, cancel_booking
from models.pnr import get_booking_by_pnr
from models.trains import available_count
from seed import create_train

TRAVEL_DATE = (date.today() + timedelta(days=1)).isoformat()
PLAN = {"SL": (1, 10)}
TOTAL_SEATS = 10
PASSENGERS_PER_THREAD = 2
NUM_THREADS = 10


def setup_db(db_path):
    conn = get_connection(db_path)
    create_tables(conn)
    train_id = create_train(
        conn, "98001", "Concurrency Express", "A", "B", "10:00", "18:00",
        plan=PLAN, tatkal_ratio=0,
    )
    cursor = conn.execute(
        "INSERT INTO users (name, email) VALUES ('Racer', 'racer@example.com')"
    )
    user_id = cursor.lastrowid
    conn.close()
    return train_id, user_id


def test_concurrent_bookings_never_double_book_seats(tmp_path):
    db_path = str(tmp_path / "concurrency.db")
    train_id, user_id = setup_db(db_path)

    successes = []
    failures = []
    lock = threading.Lock()
    barrier = threading.Barrier(NUM_THREADS)

    def worker():
        conn = get_connection(db_path)
        try:
            barrier.wait()
            passengers = [
                {"name": f"P{i}", "age": 25, "gender": "M"}
                for i in range(PASSENGERS_PER_THREAD)
            ]
            pnr = book_seats(conn, user_id, train_id, "SL", TRAVEL_DATE, 1, 2, passengers)
            with lock:
                successes.append(pnr)
        except BookingError:
            with lock:
                failures.append(1)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(NUM_THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(successes) + len(failures) == NUM_THREADS
    assert len(successes) == TOTAL_SEATS // PASSENGERS_PER_THREAD

    conn = get_connection(db_path)
    try:
        booked = conn.execute(
            "SELECT COUNT(*) AS c FROM seat_inventory WHERE travel_date = ? AND status = 'booked'",
            (TRAVEL_DATE,),
        ).fetchone()["c"]
        assert booked == TOTAL_SEATS

        duplicates = conn.execute(
            """
            SELECT seat_number FROM passengers
            GROUP BY coach_name, seat_number
            HAVING COUNT(*) > 1
            """
        ).fetchall()
        assert duplicates == []
        assert available_count(conn, train_id, "SL", TRAVEL_DATE, 1, 2) == 0
    finally:
        conn.close()


def test_cancelled_seats_can_be_reused_under_concurrency(tmp_path):
    db_path = str(tmp_path / "concurrency_cancel.db")
    train_id, user_id = setup_db(db_path)

    conn = get_connection(db_path)
    pnr = book_seats(
        conn, user_id, train_id, "SL", TRAVEL_DATE, 1, 2,
        [{"name": "A", "age": 30, "gender": "M"}, {"name": "B", "age": 28, "gender": "F"}],
    )

    cancel_booking(conn, pnr)
    assert available_count(conn, train_id, "SL", TRAVEL_DATE, 1, 2) == TOTAL_SEATS
    conn.close()

    conn = get_connection(db_path)
    try:
        new_pnr = book_seats(
            conn, user_id, train_id, "SL", TRAVEL_DATE, 1, 2,
            [{"name": "C", "age": 40, "gender": "M"}],
        )
        record = get_booking_by_pnr(conn, new_pnr)
        assert len(record["passengers"]) == 1
        assert available_count(conn, train_id, "SL", TRAVEL_DATE, 1, 2) == TOTAL_SEATS - 1
    finally:
        conn.close()
