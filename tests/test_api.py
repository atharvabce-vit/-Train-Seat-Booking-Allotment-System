import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db as db_module
from config import ADMIN_KEY
from seed import create_sample_data

TRAVEL_DATE = (date.today() + timedelta(days=1)).isoformat()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "api.db"))

    from app import create_app

    app = create_app()
    app.config.update(TESTING=True)

    conn = db_module.get_connection()
    create_sample_data(conn)
    conn.close()

    with app.test_client() as test_client:
        yield test_client


def find_trip(client, source="Mumbai", destination="Delhi"):
    response = client.get(f"/api/search?from={source}&to={destination}")
    return response.get_json()["results"][0]


def test_stations_endpoint(client):
    response = client.get("/api/stations?q=mum")
    assert response.status_code == 200
    assert any("Mumbai" in station["city"] for station in response.get_json()["stations"])


def test_trains_endpoint(client):
    response = client.get("/api/trains")
    assert response.status_code == 200
    assert len(response.get_json()["trains"]) >= 10


def test_search_requires_both_cities(client):
    assert client.get("/api/search?from=Mumbai").status_code == 400


def test_search_returns_route(client):
    trip = find_trip(client)
    assert trip["train_number"] == "12951"
    assert trip["distance_km"] > 0


def test_availability_endpoint(client):
    trip = find_trip(client)
    response = client.get(
        "/api/availability",
        query_string={
            "train_id": trip["id"], "class": "SL", "date": TRAVEL_DATE,
            "from_seq": trip["from_seq"], "to_seq": trip["to_seq"],
        },
    )
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["available"] > 0
    assert payload["fare_per_passenger"] > 0


def test_book_pnr_and_cancel(client):
    trip = find_trip(client)
    booking = {
        "train_id": trip["id"],
        "class": "SL",
        "date": TRAVEL_DATE,
        "from_seq": trip["from_seq"],
        "to_seq": trip["to_seq"],
        "quota": "GN",
        "user": {"name": "API User", "email": "api@example.com", "phone": "9000000001"},
        "passengers": [{"name": "API User", "age": 30, "gender": "M", "preference": "LB"}],
    }
    response = client.post("/api/book", json=booking)
    assert response.status_code == 201
    pnr = response.get_json()["pnr"]
    assert len(pnr) == 10

    status = client.get(f"/api/pnr/{pnr}")
    assert status.status_code == 200
    assert status.get_json()["booking"]["status"] == "confirmed"

    cancelled = client.post(f"/api/cancel/{pnr}")
    assert cancelled.status_code == 200
    assert cancelled.get_json()["cancelled"] is True


def test_unknown_pnr_returns_404(client):
    assert client.get("/api/pnr/0000000000").status_code == 404


def test_html_pages_render(client):
    assert client.get("/").status_code == 200
    assert client.get("/api/docs").status_code == 200
    trip = find_trip(client)
    book_page = client.get(
        f"/book?train_id={trip['id']}&from_seq={trip['from_seq']}&to_seq={trip['to_seq']}&date={TRAVEL_DATE}"
    )
    assert book_page.status_code == 200


def test_admin_dashboard_requires_key(client):
    assert client.get("/admin/").status_code == 302
    authorised = client.get(f"/admin/?key={ADMIN_KEY}")
    assert authorised.status_code == 200
