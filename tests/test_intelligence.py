import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db as db_module
from models import intelligence
from models.booking import book_seats, confirmation_probability
from models.trains import search_stations, search_trains
from seed import create_sample_data

TRAVEL_DATE = (date.today() + timedelta(days=1)).isoformat()


@pytest.fixture
def conn(tmp_path):
    connection = db_module.get_connection(str(tmp_path / "intel.db"))
    db_module.create_tables(connection)
    create_sample_data(connection)
    yield connection
    connection.close()


def test_station_search_tolerates_typos(conn):
    assert search_stations(conn, "Mu")  # exact LIKE still works
    hits = search_stations(conn, "mumbay")
    assert any(row["city"] == "Mumbai" for row in hits)
    assert search_stations(conn, "zzzzzz") == []


def test_surge_multiplier_and_dynamic_fare():
    assert intelligence.surge_multiplier(0.0) == 1.0
    assert intelligence.surge_multiplier(0.5) == 1.0
    assert intelligence.surge_multiplier(0.75) == 1.05
    assert intelligence.surge_multiplier(0.9) == 1.15
    assert intelligence.surge_multiplier(1.0) == 1.25
    assert intelligence.dynamic_fare(1000, 0.1) == 1000
    assert intelligence.dynamic_fare(1000, 1.0) == 1250


def test_demand_index_rises_with_bookings(conn):
    trip = search_trains(conn, "Mumbai", "Delhi")[0]
    args = (trip["id"], "SL", TRAVEL_DATE, trip["from_seq"], trip["to_seq"])
    assert intelligence.demand_index(conn, *args) == 0.0
    assert intelligence.demand_label(0.0) == "Available"

    conn.execute("INSERT INTO users (name, email) VALUES ('A', 'a@example.com')")
    book_seats(
        conn, 1, trip["id"], "SL", TRAVEL_DATE, trip["from_seq"], trip["to_seq"],
        [{"name": "A", "age": 30, "gender": "M"}],
    )
    assert intelligence.demand_index(conn, *args) > 0


def test_waitlist_confidence_favours_rac_and_time():
    confirmed = {"status": "confirmed", "queue_position": None}
    cancelled = {"status": "cancelled", "queue_position": None}
    rac = {"status": "rac", "queue_position": 3}
    waiting = {"status": "waiting", "queue_position": 3}

    assert intelligence.waitlist_confidence(confirmed) == 100
    assert intelligence.waitlist_confidence(cancelled) == 0
    assert intelligence.waitlist_confidence(rac) > intelligence.waitlist_confidence(waiting)
    # More days before departure is a tailwind, a departure tomorrow a headwind.
    assert intelligence.waitlist_confidence(waiting, days_left=10) > intelligence.waitlist_confidence(waiting)
    assert intelligence.waitlist_confidence(waiting, days_left=1) < intelligence.waitlist_confidence(waiting)
    assert confirmation_probability(rac) == intelligence.waitlist_confidence(rac)
