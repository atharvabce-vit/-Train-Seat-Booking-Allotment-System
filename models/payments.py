"""Sandbox payment gateway.

No real money moves: a charge is just a row in the ``payments`` table. The
gateway is small but behaves like a real one in the two ways that matter for a
booking site:

* every charge can carry an idempotency key, so a retried request returns the
  original payment instead of charging a second time;
* card numbers ending in ``0000`` are declined, so the failure path can be
  exercised end to end.
"""
import secrets

GATEWAY_NAME = "RAILYATRA-SANDBOX"
DECLINE_SUFFIX = "0000"
VALID_METHODS = ("MOCK", "UPI", "CARD", "NETBANKING")


class PaymentError(Exception):
    pass


def _txn_ref():
    return f"TXN{secrets.token_hex(6).upper()}"


def find_by_key(conn, idempotency_key):
    if not idempotency_key:
        return None
    return conn.execute(
        "SELECT * FROM payments WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()


def charge(conn, booking_id, amount, method="MOCK", card_number=None, idempotency_key=None):
    """Charge ``amount`` for ``booking_id`` exactly once.

    Repeating the call with the same ``idempotency_key`` returns the payment
    already recorded rather than making a second charge.
    """
    existing = find_by_key(conn, idempotency_key)
    if existing is not None:
        return existing
    if amount < 0:
        raise PaymentError("The payable amount cannot be negative.")
    if method not in VALID_METHODS:
        raise PaymentError("Unsupported payment method.")
    if method == "CARD" and (card_number or "").replace(" ", "").endswith(DECLINE_SUFFIX):
        raise PaymentError("The card was declined by the issuing bank.")

    cursor = conn.execute(
        """
        INSERT INTO payments (booking_id, amount, method, status, txn_ref, idempotency_key)
        VALUES (?, ?, ?, 'success', ?, ?)
        """,
        (booking_id, amount, method, _txn_ref(), idempotency_key),
    )
    return conn.execute("SELECT * FROM payments WHERE id = ?", (cursor.lastrowid,)).fetchone()
