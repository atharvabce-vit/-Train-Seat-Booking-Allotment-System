import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db as db_module
import metrics
from seed import create_sample_data

TRAVEL_DATE = (date.today() + timedelta(days=1)).isoformat()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "ops.db"))
    metrics.reset()

    from app import create_app

    app = create_app()
    app.config.update(TESTING=True)

    connection = db_module.get_connection()
    create_sample_data(connection)
    connection.close()

    with app.test_client() as test_client:
        yield test_client


def trip(client):
    return client.get("/api/search?from=Mumbai&to=Delhi").get_json()["results"][0]


def test_metrics_endpoint_reports_counts(client):
    client.get("/api/trains")
    payload = client.get("/metrics").get_json()

    assert payload["requests_total"] >= 1
    assert payload["uptime_seconds"] >= 0
    assert payload["database"]["trains"] >= 10
    assert "bookings" in payload["database"]


def test_typo_tolerant_station_api(client):
    stations = client.get("/api/stations?q=mumbay").get_json()["stations"]
    assert any("Mumbai" in station["city"] for station in stations)


def test_demand_endpoint(client):
    found = trip(client)
    response = client.get(
        "/api/demand",
        query_string={
            "train_id": found["id"], "cls": "SL", "date": TRAVEL_DATE,
            "from_seq": found["from_seq"], "to_seq": found["to_seq"],
        },
    )
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["demand_label"] == "Available"
    assert payload["surge_multiplier"] == 1.0
    assert payload["dynamic_fare"] == payload["base_fare"]


def test_availability_stream_pushes_frames(client):
    found = trip(client)
    response = client.get(
        "/api/availability/stream",
        query_string={
            "train_id": found["id"], "cls": "SL", "date": TRAVEL_DATE,
            "from_seq": found["from_seq"], "to_seq": found["to_seq"],
            "interval": 0, "frames": 2,
        },
    )
    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    assert response.data.count(b"data: ") == 2
