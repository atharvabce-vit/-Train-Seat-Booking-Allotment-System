import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import create_tables, get_connection
from models.booking import (
    BookingError,
    cleanup_expired_holds,
    confirm_booking,
    create_hold,
    book_seats,
    cancel_booking,
    join_queue,
)
from models.pnr import get_booking_by_pnr
from models.trains import available_count
from models.util import STAMP_FORMAT, now_utc
from seed import create_train

TRAVEL_DATE = date.today().isoformat()


@pytest.fixture
def db(tmp_path):
    conn = get_connection(str(tmp_path / "flow.db"))
    create_tables(conn)
    yield conn
    conn.close()


def make_user(conn):
    return conn.execute(
        "INSERT INTO users (name, email, phone) VALUES ('Flow User', 'flow@example.com', '9000000000')"
    ).lastrowid


def passengers(count):
    return [{"name": f"P{i}", "age": 30, "gender": "M", "preference": "ANY"} for i in range(count)]


def test_hold_then_confirm_issues_pnr(db):
    train_id = create_train(db, "95001", "Hold Express", "A", "B", "10:00", "18:00",
                            plan={"SL": (1, 10)}, tatkal_ratio=0)
    user_id = make_user(db)

    hold = create_hold(db, train_id, "SL", TRAVEL_DATE, 1, 2, "GN", passengers(2))
    assert available_count(db, train_id, "SL", TRAVEL_DATE, 1, 2) == 8

    pnr = confirm_booking(db, user_id, hold["token"], passengers(2))
    record = get_booking_by_pnr(db, pnr)

    assert record["booking"]["status"] == "confirmed"
    assert record["payments"][0]["amount"] == record["booking"]["total_fare"]
    assert available_count(db, train_id, "SL", TRAVEL_DATE, 1, 2) == 8


def test_expired_hold_releases_seats_and_cannot_be_confirmed(db):
    train_id = create_train(db, "95002", "Hold Express", "A", "B", "10:00", "18:00",
                            plan={"SL": (1, 10)}, tatkal_ratio=0)
    user_id = make_user(db)

    hold = create_hold(db, train_id, "SL", TRAVEL_DATE, 1, 2, "GN", passengers(1))
    assert available_count(db, train_id, "SL", TRAVEL_DATE, 1, 2) == 9

    past = (now_utc() - timedelta(hours=1)).strftime(STAMP_FORMAT)
    db.execute("UPDATE seat_holds SET expires_at = ? WHERE token = ?", (past, hold["token"]))
    db.execute("UPDATE seat_inventory SET hold_expires_at = ? WHERE hold_token = ?", (past, hold["token"]))

    cleanup_expired_holds(db)
    assert available_count(db, train_id, "SL", TRAVEL_DATE, 1, 2) == 10

    with pytest.raises(BookingError):
        confirm_booking(db, user_id, hold["token"], passengers(1))


def test_waitlist_is_promoted_on_cancellation(db):
    train_id = create_train(db, "95003", "Tiny Express", "A", "B", "10:00", "18:00",
                            plan={"SL": (1, 2)}, tatkal_ratio=0)
    user_id = make_user(db)

    full = book_seats(db, user_id, train_id, "SL", TRAVEL_DATE, 1, 2, passengers(2))
    assert available_count(db, train_id, "SL", TRAVEL_DATE, 1, 2) == 0

    queued, status, position = join_queue(
        db, user_id, train_id, "SL", TRAVEL_DATE, 1, 2, "GN", passengers(1)
    )
    assert status == "rac"
    assert position == 1

    result = cancel_booking(db, full)
    assert queued in result["promoted"]

    record = get_booking_by_pnr(db, queued)
    assert record["booking"]["status"] == "confirmed"
    assert record["passengers"][0]["seat_number"] is not None


def test_waitlist_when_rac_is_full(db):
    from config import RAC_LIMIT

    train_id = create_train(db, "95004", "Tiny Express", "A", "B", "10:00", "18:00",
                            plan={"SL": (1, 1)}, tatkal_ratio=0)
    user_id = make_user(db)
    book_seats(db, user_id, train_id, "SL", TRAVEL_DATE, 1, 2, passengers(1))

    statuses = []
    for _ in range(RAC_LIMIT + 1):
        _, status, _ = join_queue(db, user_id, train_id, "SL", TRAVEL_DATE, 1, 2, "GN", passengers(1))
        statuses.append(status)

    assert statuses[:RAC_LIMIT] == ["rac"] * RAC_LIMIT
    assert statuses[-1] == "waiting"


def test_early_cancellation_refunds_ninety_percent(db):
    far_date = (date.today() + timedelta(days=10)).isoformat()
    train_id = create_train(db, "95005", "Refund Express", "A", "B", "10:00", "18:00",
                            plan={"SL": (1, 10)}, tatkal_ratio=0)
    user_id = make_user(db)

    pnr = book_seats(db, user_id, train_id, "SL", far_date, 1, 2, passengers(2))
    record = get_booking_by_pnr(db, pnr)
    total = record["booking"]["total_fare"]

    result = cancel_booking(db, pnr)
    assert result["refund"]["percent"] == 90
    assert result["refund"]["amount"] == int(round(total * 0.9))
