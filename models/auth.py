"""Account handling: registration, password hashing and authentication.

Passwords are stored as salted PBKDF2-SHA256 hashes; the plain password is
never persisted. Guests who book without an account keep a NULL hash, so they
cannot be signed in until they register.
"""
import hashlib
import hmac
import secrets

PBKDF2_ITERATIONS = 200_000
_ALGORITHM = "pbkdf2_sha256"
MIN_PASSWORD_LENGTH = 8


class AuthError(Exception):
    pass


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    )
    return f"{_ALGORITHM}${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password, stored):
    if not stored:
        return False
    try:
        algorithm, iterations, salt, digest = stored.split("$")
        if algorithm != _ALGORITHM:
            return False
        expected = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(expected.hex(), digest)


def get_user(conn, user_id):
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def register_user(conn, name, email, password, phone=None, role="passenger"):
    name = (name or "").strip()
    email = (email or "").strip().lower()
    if not name or not email or not password:
        raise AuthError("Name, e-mail and password are all required.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        raise AuthError("An account with this e-mail already exists.")

    cursor = conn.execute(
        """
        INSERT INTO users (name, email, phone, password_hash, role)
        VALUES (?, ?, ?, ?, ?)
        """,
        (name, email, phone or None, hash_password(password), role),
    )
    return cursor.lastrowid


def authenticate(conn, email, password):
    """Return the user row on success, or None when the credentials are wrong."""
    email = (email or "").strip().lower()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if row is None or not verify_password(password or "", row["password_hash"]):
        return None
    return row
