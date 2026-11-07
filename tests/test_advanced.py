import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import create_tables, get_connection
from models import audit
from models.booking import (
    book_round_trip,
    book_seats,
    cancel_passengers,
    reschedule_booking,
)
from models.fare import concession_percent, fare_per_passenger
from models.pnr import get_booking_by_pnr
from models.trains import available_count
from seed import create_train

TRAVEL_DATE = (date.today() + timedelta(days=1)).isoformat()
LATER_DATE = (date.today() + timedelta(days=5)).isoformat()


@pytest.fixture
def db(tmp_path):
    conn = get_connection(str(tmp_path / "advanced.db"))
    create_tables(conn)
    yield conn
    conn.close()


def make_user(conn, email="adv@example.com"):
    return conn.execute(
        "INSERT INTO users (name, email, phone) VALUES ('Adv User', ?, '9000000000')",
        (email,),
    ).lastrowid


def adult():
    return {"name": "Adult", "age": 30, "gender": "M", "preference": "ANY"}


def test_concession_percent_by_age():
    assert concession_percent(3) == 100
    assert concession_percent(8) == 50
    assert concession_percent(60) == 30
    assert concession_percent(30) == 0


def test_concessions_reduce_total_fare(db):
    train_id = create_train(db, "96001", "Family Express", "A", "B", "10:00", "18:00",
                            plan={"SL": (1, 20)}, tatkal_ratio=0)
    user_id = make_user(db)
    passengers = [
        {"name": "Adult", "age": 34, "gender": "M", "preference": "ANY"},
        {"name": "Child", "age": 9, "gender": "F", "preference": "ANY"},
        {"name": "Infant", "age": 3, "gender": "M", "preference": "ANY"},
    ]
    pnr = book_seats(db, user_id, train_id, "SL", TRAVEL_DATE, 1, 2, passengers)
    record = get_booking_by_pnr(db, pnr)
    booking = record["booking"]

    base = fare_per_passenger("SL", booking["distance_km"], "GN")
    full_base = base * 3
    assert booking["total_fare"] < full_base
    assert booking["concession_amount"] == full_base - booking["total_fare"]
    assert booking["concession_amount"] > 0
    percents = sorted(p["concession_percent"] for p in record["passengers"])
    assert percents == [0, 50, 100]
    fares = sorted(p["fare"] for p in record["passengers"])
    assert fares[0] == 0
    assert fares[1] < base


def test_partial_cancellation_refunds_share(db):
    train_id = create_train(db, "96002", "Partial Express", "A", "B", "10:00", "18:00",
                            plan={"SL": (2, 20)}, tatkal_ratio=0)
    user_id = make_user(db)
    passengers = [adult() for _ in range(3)]
    pnr = book_seats(db, user_id, train_id, "SL", LATER_DATE, 1, 2, passengers)

    record = get_booking_by_pnr(db, pnr)
    victim = record["passengers"][0]["id"]
    before = available_count(db, train_id, "SL", LATER_DATE, 1, 2)

    result = cancel_passengers(db, pnr, [victim])
    assert result["remaining"] == 2
    assert result["refund"]["amount"] > 0
    assert available_count(db, train_id, "SL", LATER_DATE, 1, 2) == before + 1

    record = get_booking_by_pnr(db, pnr)
    statuses = sorted(p["status"] for p in record["passengers"])
    assert statuses == ["cancelled", "confirmed", "confirmed"]
    assert record["booking"]["status"] == "confirmed"


def test_reschedule_moves_booking_and_charges_fee(db):
    train_id = create_train(db, "96003", "Change Express", "A", "B", "10:00", "18:00",
                            plan={"SL": (2, 20)}, tatkal_ratio=0)
    user_id = make_user(db)
    pnr = book_seats(db, user_id, train_id, "SL", TRAVEL_DATE, 1, 2, [adult()])

    result = reschedule_booking(db, pnr, LATER_DATE)
    assert result["new_date"] == LATER_DATE
    assert result["fee"] > 0

    record = get_booking_by_pnr(db, pnr)
    assert record["booking"]["travel_date"] == LATER_DATE
    assert record["booking"]["change_count"] == 1
    assert record["changes"][0]["old_date"] == TRAVEL_DATE
    assert record["changes"][0]["new_date"] == LATER_DATE


def test_round_trip_shares_group_and_discounts_return(db):
    outbound_id = create_train(db, "96004", "Outbound Express", "A", "B", "10:00", "18:00",
                               plan={"SL": (2, 20)}, tatkal_ratio=0)
    inbound_id = create_train(db, "96005", "Inbound Express", "B", "A", "10:00", "18:00",
                              plan={"SL": (2, 20)}, tatkal_ratio=0)
    user_id = make_user(db)

    result = book_round_trip(
        db,
        user_id,
        {"train_id": outbound_id, "class_code": "SL", "travel_date": TRAVEL_DATE,
         "from_seq": 1, "to_seq": 2, "passengers": [adult()]},
        {"train_id": inbound_id, "class_code": "SL", "travel_date": LATER_DATE,
         "from_seq": 1, "to_seq": 2, "passengers": [adult()]},
    )

    outbound = get_booking_by_pnr(db, result["outbound"])
    inbound = get_booking_by_pnr(db, result["return"])
    assert outbound["booking"]["group_id"] == inbound["booking"]["group_id"]
    assert outbound["booking"]["trip_type"] == "ROUND_TRIP"
    assert inbound["booking"]["total_fare"] < outbound["booking"]["total_fare"]


def test_audit_log_records_booking_actions(db):
    train_id = create_train(db, "96006", "Audit Express", "A", "B", "10:00", "18:00",
                            plan={"SL": (2, 20)}, tatkal_ratio=0)
    user_id = make_user(db)
    pnr = book_seats(db, user_id, train_id, "SL", TRAVEL_DATE, 1, 2, [adult()])

    entries = audit.recent(db, limit=50)
    actions = [entry["action"] for entry in entries]
    assert "book" in actions
    assert any(entry["entity_id"] == pnr for entry in entries)
