"""A tiny in-process metrics registry for the ops endpoint.

Deliberately dependency-free: counts are held in memory and reset when the
process restarts. That is plenty for a single-node demo deployment and keeps
the ``/metrics`` payload cheap to build.
"""
import time
from collections import Counter

_STARTED_AT = time.time()
_REQUESTS = Counter()
_ERRORS = Counter()
_LATENCY_MS = Counter()


def record(path, status, latency_ms=0):
    """Record one served request."""
    key = f"{status} {path}"
    _REQUESTS[key] += 1
    if status >= 500:
        _ERRORS[key] += 1
    if latency_ms:
        _LATENCY_MS[key] += latency_ms


def reset():
    """Clear every counter - used by tests to get a clean slate."""
    _REQUESTS.clear()
    _ERRORS.clear()
    _LATENCY_MS.clear()


def snapshot():
    total = sum(_REQUESTS.values())
    errors = sum(_ERRORS.values())
    return {
        "uptime_seconds": int(time.time() - _STARTED_AT),
        "requests_total": total,
        "errors_total": errors,
        "error_rate": round(errors / total, 4) if total else 0.0,
        "requests_by_route": dict(_REQUESTS.most_common(25)),
    }
