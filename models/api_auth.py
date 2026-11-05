import threading
import time

from config import API_RATE_LIMIT, API_RATE_WINDOW, DEFAULT_API_TOKEN
from models.util import now_str

_window_lock = threading.Lock()
_windows = {}


def ensure_default_token(conn):
    exists = conn.execute("SELECT COUNT(*) AS c FROM api_tokens").fetchone()["c"]
    if not exists:
        conn.execute(
            "INSERT INTO api_tokens (token, label) VALUES (?, 'demo token')",
            (DEFAULT_API_TOKEN,),
        )


def validate_token(conn, token):
    if not token:
        return False
    row = conn.execute(
        "SELECT token FROM api_tokens WHERE token = ? AND active = 1", (token,)
    ).fetchone()
    if row is None:
        return False
    conn.execute(
        "UPDATE api_tokens SET request_count = request_count + 1, last_used_at = ? WHERE token = ?",
        (now_str(), token),
    )
    return True


def rate_limited(key):
    """Sliding-window limiter. Returns True when the caller is over the limit."""
    now = time.time()
    with _window_lock:
        hits = [stamp for stamp in _windows.get(key, []) if now - stamp < API_RATE_WINDOW]
        if len(hits) >= API_RATE_LIMIT:
            _windows[key] = hits
            return True
        hits.append(now)
        _windows[key] = hits
        return False
