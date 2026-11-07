import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db as db_module
from config import DEFAULT_API_TOKEN
from models.payments import PaymentError, charge
from seed import create_sample_data

TRAVEL_DATE = (date.today() + timedelta(days=1)).isoformat()
TOKEN = {"X-API-Token": DEFAULT_API_TOKEN}


@pytest.fixture
def conn(tmp_path):
    connection = db_module.get_connection(str(tmp_path / "pay.db"))
    db_module.create_tables(connection)
    yield connection
    connection.close()


def make_booking(connection):
    connection.execute("INSERT INTO users (name, email) VALUES ('U', 'u@example.com')")
    connection.execute("INSERT INTO trains (train_number, train_name) VALUES ('1', 'T')")
    connection.execute(
        """
        INSERT INTO bookings
            (pnr, user_id, train_id, class_code, travel_date, from_seq, to_seq, total_fare)
        VALUES ('1234567890', 1, 1, 'SL', '2026-01-01', 1, 2, 500)
        """
    )
    return 1


def test_charge_is_idempotent(conn):
    booking_id = make_booking(conn)

    first = charge(conn, booking_id, 500, "UPI", idempotency_key="key-1")
    second = charge(conn, booking_id, 500, "UPI", idempotency_key="key-1")

    assert first["txn_ref"] == second["txn_ref"]
    count = conn.execute("SELECT COUNT(*) AS c FROM payments").fetchone()["c"]
    assert count == 1


def test_different_keys_charge_separately(conn):
    booking_id = make_booking(conn)
    charge(conn, booking_id, 100, "UPI", idempotency_key="a")
    charge(conn, booking_id, 200, "UPI", idempotency_key="b")
    count = conn.execute("SELECT COUNT(*) AS c FROM payments").fetchone()["c"]
    assert count == 2


def test_card_ending_in_0000_is_declined(conn):
    booking_id = make_booking(conn)
    with pytest.raises(PaymentError):
        charge(conn, booking_id, 500, "CARD", card_number="4111 1111 1111 0000")

    with pytest.raises(PaymentError):
        charge(conn, booking_id, -1, "UPI")

    assert conn.execute("SELECT COUNT(*) AS c FROM payments").fetchone()["c"] == 0


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "api.db"))
    from app import create_app

    app = create_app()
    app.config.update(TESTING=True)

    connection = db_module.get_connection()
    create_sample_data(connection)
    connection.close()

    with app.test_client() as test_client:
        yield test_client


def test_api_booking_is_idempotent(client):
    trip = client.get("/api/search?from=Mumbai&to=Delhi").get_json()["results"][0]
    payload = {
        "train_id": trip["id"], "class": "SL", "date": TRAVEL_DATE,
        "from_seq": trip["from_seq"], "to_seq": trip["to_seq"],
        "user": {"name": "Asha", "email": "asha@example.com"},
        "passengers": [{"name": "Asha", "age": 30, "gender": "F"}],
    }
    headers = {**TOKEN, "Idempotency-Key": "retry-me-123"}

    first = client.post("/api/book", json=payload, headers=headers)
    second = client.post("/api/book", json=payload, headers=headers)

    assert first.status_code == 201 and second.status_code == 201
    assert first.get_json()["pnr"] == second.get_json()["pnr"]

    connection = db_module.get_connection()
    count = connection.execute("SELECT COUNT(*) AS c FROM bookings").fetchone()["c"]
    connection.close()
    assert count == 1
