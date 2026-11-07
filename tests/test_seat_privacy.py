import os
import re
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db as db_module
from seed import create_sample_data

TRAVEL_DATE = (date.today() + timedelta(days=1)).isoformat()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "privacy.db"))

    from app import create_app

    app = create_app()
    app.config.update(TESTING=True)

    connection = db_module.get_connection()
    create_sample_data(connection)
    connection.close()

    with app.test_client() as test_client:
        yield test_client


def csrf(test_client, path):
    html = test_client.get(path).get_data(as_text=True)
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def book_url():
    return f"/book?train_id=1&cls=SL&date={TRAVEL_DATE}&from_seq=1&to_seq=4&quota=GN"


def hold_a_seat(test_client):
    response = test_client.post(
        "/book",
        data={
            "csrf_token": csrf(test_client, book_url()),
            "train_id": 1, "class_code": "SL", "travel_date": TRAVEL_DATE,
            "from_seq": 1, "to_seq": 4, "quota": "GN", "payment_method": "MOCK",
            "user_name": "Guest", "user_email": "guest@example.com",
            "passenger_name": "Asha", "passenger_age": 30, "passenger_gender": "F",
        },
    )
    assert response.status_code == 302
    return response.headers["Location"]


def test_berth_is_hidden_until_payment(client):
    location = hold_a_seat(client)

    # The confirm (pre-payment) page must not disclose the berth, so a booker
    # cannot cancel at the payment step and re-hold to map the allotment.
    confirm = client.get(location)
    assert confirm.status_code == 200
    assert b"Allotted seats" not in confirm.data
    assert b"after payment is confirmed" in confirm.data

    # Paying reveals the berth on the e-ticket.
    paid = client.post(
        location,
        data={"csrf_token": csrf(client, location), "payment_method": "MOCK"},
        follow_redirects=True,
    )
    assert paid.status_code == 200

    pnr = re.search(r"E-Ticket (\d{10})", paid.get_data(as_text=True))
    assert pnr is not None

    connection = db_module.get_connection()
    try:
        seat = connection.execute(
            """
            SELECT p.seat_number FROM passengers p
            JOIN bookings b ON b.id = p.booking_id
            WHERE b.pnr = ?
            """,
            (pnr.group(1),),
        ).fetchone()
    finally:
        connection.close()

    assert seat["seat_number"] is not None
    assert f"<td>{seat['seat_number']}</td>".encode() in paid.data


def test_cancelling_and_reholding_does_not_leak_the_berth(client):
    # Two successive holds must never print a coach/seat on the confirm page.
    for _ in range(2):
        confirm = client.get(hold_a_seat(client)).get_data(as_text=True)
        assert "Allotted seats" not in confirm
        assert not re.search(r"[A-Z]\d+ / \d+", confirm)
        assert "after payment is confirmed" in confirm
