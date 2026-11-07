import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import create_tables, get_connection
from models.itinerary import MIN_TRANSFER_MINUTES, find_journeys
from seed import create_train, ensure_station, stop

PLAN = {"SL": (1, 6)}


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "itinerary.db")
    conn = get_connection(db_path)
    create_tables(conn)
    yield conn
    conn.close()


def add_train(conn, number, name, segments):
    """segments: list of (code, arrival, departure, day, distance)."""
    stops = [stop(code, arr, dep, day, dist) for code, arr, dep, day, dist in segments]
    for code, *_ in segments:
        ensure_station(conn, code, code, code)
    return create_train(
        conn, number, name, segments[0][0], segments[-1][0],
        segments[0][2], segments[-1][1], plan=PLAN, stops=stops, tatkal_ratio=0,
    )


def test_finds_one_change_journey(db):
    add_train(db, "10001", "Alpha Express", [
        ("AAA", None, "06:00", 0, 0),
        ("BBB", "08:00", None, 0, 400),
    ])
    add_train(db, "10002", "Gamma Express", [
        ("BBB", None, "10:00", 0, 0),
        ("CCC", "14:00", None, 0, 600),
    ])

    journeys = find_journeys(db, "AAA", "CCC")

    assert len(journeys) == 1
    journey = journeys[0]
    assert journey["changes"] == 1
    assert journey["transfer_at"] == "BBB"
    assert journey["transfer_wait_minutes"] == 120
    assert [leg["train_number"] for leg in journey["legs"]] == ["10001", "10002"]
    assert journey["legs"][0]["distance_km"] == 400
    assert journey["legs"][1]["distance_km"] == 600
    assert journey["total_distance_km"] == 1000
    assert "SL" in journey["fares"] and journey["fares"]["SL"] > 0


def test_rejects_connection_shorter_than_minimum(db):
    add_train(db, "10003", "Alpha Express", [
        ("AAA", None, "06:00", 0, 0),
        ("BBB", "08:00", None, 0, 400),
    ])
    # Leaves just 30 minutes after arrival: below MIN_TRANSFER_MINUTES.
    add_train(db, "10004", "Gamma Express", [
        ("BBB", None, "08:30", 0, 0),
        ("CCC", "09:00", None, 0, 600),
    ])

    assert MIN_TRANSFER_MINUTES > 30
    assert find_journeys(db, "AAA", "CCC") == []


def test_rejects_connection_beyond_one_day(db):
    add_train(db, "10005", "Alpha Express", [
        ("AAA", None, "06:00", 0, 0),
        ("BBB", "08:00", None, 0, 400),
    ])
    # Departs two days later: outside the accepted waiting window.
    add_train(db, "10006", "Gamma Express", [
        ("BBB", None, "10:00", 2, 0),
        ("CCC", "14:00", None, 2, 600),
    ])

    assert find_journeys(db, "AAA", "CCC") == []


def test_returns_empty_for_unknown_or_same_station(db):
    add_train(db, "10007", "Alpha Express", [
        ("AAA", None, "06:00", 0, 0),
        ("BBB", "08:00", None, 0, 400),
    ])

    assert find_journeys(db, "Nowhere", "Elsewhere") == []
    assert find_journeys(db, "AAA", "AAA") == []


def test_limit_caps_results(db):
    add_train(db, "20001", "Alpha Express", [
        ("AAA", None, "06:00", 0, 0),
        ("BBB", "08:00", None, 0, 400),
    ])
    add_train(db, "20101", "First Gamma", [
        ("BBB", None, "10:00", 0, 0), ("CCC", "14:00", None, 0, 600),
    ])
    add_train(db, "20102", "Second Gamma", [
        ("BBB", None, "11:00", 0, 0), ("CCC", "15:00", None, 0, 600),
    ])

    assert len(find_journeys(db, "AAA", "CCC")) == 2
    journeys = find_journeys(db, "AAA", "CCC", limit=1)
    assert len(journeys) == 1
    # Shortest total time first: the 10:00 connection.
    assert journeys[0]["legs"][1]["train_number"] == "20101"
