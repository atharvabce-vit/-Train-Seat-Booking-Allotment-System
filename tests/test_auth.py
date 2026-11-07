import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db as db_module
from models.auth import AuthError, authenticate, hash_password, register_user, verify_password


@pytest.fixture
def conn(tmp_path):
    connection = db_module.get_connection(str(tmp_path / "auth.db"))
    db_module.create_tables(connection)
    yield connection
    connection.close()


def test_password_hash_round_trip():
    stored = hash_password("hunter2hunter2")
    assert stored != "hunter2hunter2"
    assert verify_password("hunter2hunter2", stored)
    assert not verify_password("wrong-password", stored)
    assert not verify_password("hunter2hunter2", None)


def test_register_and_authenticate(conn):
    user_id = register_user(conn, "Asha", "Asha@Example.com", "secret123")
    assert user_id

    # E-mail is normalised to lowercase, so sign-in is case-insensitive.
    user = authenticate(conn, "asha@example.com", "secret123")
    assert user is not None and user["id"] == user_id
    assert user["password_hash"] != "secret123"
    assert user["role"] == "passenger"

    assert authenticate(conn, "asha@example.com", "nope") is None
    assert authenticate(conn, "nobody@example.com", "secret123") is None


def test_register_rejects_bad_input(conn):
    with pytest.raises(AuthError):
        register_user(conn, "Asha", "asha@example.com", "short")
    with pytest.raises(AuthError):
        register_user(conn, "", "asha@example.com", "secret123")

    register_user(conn, "Asha", "asha@example.com", "secret123")
    with pytest.raises(AuthError):
        register_user(conn, "Asha Again", "ASHA@example.com", "secret123")


def test_guest_users_cannot_sign_in(conn):
    # A guest booking creates a user row with no password hash.
    conn.execute("INSERT INTO users (name, email) VALUES ('Guest', 'guest@example.com')")
    assert authenticate(conn, "guest@example.com", "anything") is None


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "web.db"))
    from app import create_app

    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def csrf(test_client, path):
    html = test_client.get(path).get_data(as_text=True)
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def test_register_login_logout_flow(client):
    response = client.post(
        "/register",
        data={
            "csrf_token": csrf(client, "/register"),
            "name": "Ravi", "email": "ravi@example.com", "password": "secret123",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Ravi" in response.data

    client.post("/logout", data={"csrf_token": csrf(client, "/")}, follow_redirects=True)

    bad = client.post(
        "/login",
        data={"csrf_token": csrf(client, "/login"), "email": "ravi@example.com", "password": "wrong"},
        follow_redirects=True,
    )
    assert b"Invalid" in bad.data

    good = client.post(
        "/login",
        data={"csrf_token": csrf(client, "/login"), "email": "ravi@example.com", "password": "secret123"},
        follow_redirects=True,
    )
    assert b"Welcome back" in good.data
