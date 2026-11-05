import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import create_tables, get_connection
from models.fare import calculate_fare, fare_per_passenger, refund_amount, refund_percent
from models.trains import segment_distance
from seed import create_train


def test_fare_grows_with_distance():
    short = fare_per_passenger("SL", 100)
    long = fare_per_passenger("SL", 1000)
    assert long > short


def test_fare_multiplies_per_passenger():
    each = fare_per_passenger("3A", 500)
    assert calculate_fare("3A", 500, 4) == each * 4


def test_tatkal_adds_premium():
    from config import TATKAL_PREMIUM_PCT

    general = fare_per_passenger("SL", 400, "GN")
    tatkal = fare_per_passenger("SL", 400, "TQ")
    assert tatkal == int(round(general * (1 + TATKAL_PREMIUM_PCT / 100)))


def test_higher_class_costs_more():
    assert fare_per_passenger("1A", 600) > fare_per_passenger("2A", 600) > fare_per_passenger("3A", 600)


def test_refund_tiers():
    assert refund_percent(100) == 90
    assert refund_percent(30) == 75
    assert refund_percent(20) == 50
    assert refund_percent(6) == 25
    assert refund_percent(1) == 0


def test_refund_amount_matches_percent():
    amount, percent = refund_amount(1000, 30)
    assert percent == 75
    assert amount == 750


def test_segment_distance_from_stops(tmp_path):
    conn = get_connection(str(tmp_path / "fare.db"))
    create_tables(conn)
    stops = [
        {"station": "A", "arrival": None, "departure": "06:00", "day": 0, "distance": 0},
        {"station": "B", "arrival": "10:00", "departure": "10:10", "day": 0, "distance": 250},
        {"station": "C", "arrival": "15:00", "departure": None, "day": 0, "distance": 700},
    ]
    train_id = create_train(conn, "96001", "Distance Express", None, None, None, None, stops=stops)

    assert segment_distance(conn, train_id, 1, 3) == 700
    assert segment_distance(conn, train_id, 2, 3) == 450
    conn.close()
