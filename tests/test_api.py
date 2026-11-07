import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db as db_module
from config import ADMIN_KEY, DEFAULT_API_TOKEN
from seed import create_sample_data

TRAVEL_DATE = (date.today() + timedelta(days=1)).isoformat()
TOKEN = {"X-API-Token": DEFAULT_API_TOKEN}


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


def test_journeys_endpoint_returns_connection(client):
    # No direct Kolkata -> Chennai train exists, so this must be a connection.
    assert client.get("/api/search?from=Kolkata&to=Chennai").get_json()["total"] == 0

    response = client.get("/api/journeys?from=Kolkata&to=Chennai")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total"] >= 1
    journey = payload["journeys"][0]
    assert journey["changes"] == 1
    assert len(journey["legs"]) == 2
    assert journey["fares"]


def test_journeys_requires_both_cities(client):
    assert client.get("/api/journeys?from=Kolkata").status_code == 400


def test_search_page_shows_connecting_journeys(client):
    response = client.get("/search?source=Kolkata&destination=Chennai")
    assert response.status_code == 200
    assert b"Connecting journeys" in response.data


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
    response = client.post("/api/book", json=booking, headers=TOKEN)
    assert response.status_code == 201
    pnr = response.get_json()["pnr"]
    assert len(pnr) == 10

    status = client.get(f"/api/pnr/{pnr}")
    assert status.status_code == 200
    assert status.get_json()["booking"]["status"] == "confirmed"

    cancelled = client.post(f"/api/cancel/{pnr}", headers=TOKEN)
    assert cancelled.status_code == 200
    assert cancelled.get_json()["cancelled"] is True


def test_writes_require_api_token(client):
    trip = find_trip(client)
    booking = {
        "train_id": trip["id"], "class": "SL", "date": TRAVEL_DATE,
        "from_seq": trip["from_seq"], "to_seq": trip["to_seq"],
        "user": {"name": "No Token", "email": "notoken@example.com"},
        "passengers": [{"name": "No Token", "age": 30, "gender": "M"}],
    }
    assert client.post("/api/book", json=booking).status_code == 401


def test_openapi_and_health(client):
    assert client.get("/api/openapi.json").status_code == 200
    assert client.get("/healthz").get_json()["status"] == "ok"


def test_seatmap_endpoint(client):
    trip = find_trip(client)
    response = client.get(
        "/api/seatmap",
        query_string={
            "train_id": trip["id"], "cls": "SL", "date": TRAVEL_DATE,
            "from_seq": trip["from_seq"], "to_seq": trip["to_seq"],
        },
    )
    assert response.status_code == 200
    assert response.get_json()["coaches"]


def test_round_trip_and_reschedule(client):
    outbound = find_trip(client)
    return_leg = find_trip(client, source="Delhi", destination="Mumbai")

    payload = {
        "user": {"name": "Trip User", "email": "trip@example.com"},
        "outbound": {
            "train_id": outbound["id"], "class": "SL", "date": TRAVEL_DATE,
            "from_seq": outbound["from_seq"], "to_seq": outbound["to_seq"],
            "passengers": [{"name": "Trip User", "age": 40, "gender": "M"}],
        },
        "return": {
            "train_id": return_leg["id"], "class": "SL",
            "date": (date.today() + timedelta(days=5)).isoformat(),
            "from_seq": return_leg["from_seq"], "to_seq": return_leg["to_seq"],
            "passengers": [{"name": "Trip User", "age": 40, "gender": "M"}],
        },
    }
    response = client.post("/api/book-round-trip", json=payload, headers=TOKEN)
    assert response.status_code == 201
    outbound_pnr = response.get_json()["outbound"]

    rescheduled = client.post(
        f"/api/reschedule/{outbound_pnr}",
        json={"date": (date.today() + timedelta(days=6)).isoformat()},
        headers=TOKEN,
    )
    assert rescheduled.status_code == 200
    assert rescheduled.get_json()["fee"] > 0


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
