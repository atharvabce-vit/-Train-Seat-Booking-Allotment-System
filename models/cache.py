import time

_cache = {}


def remember(key, builder, ttl_seconds=30):
    """Return a cached value for key, rebuilding it when the TTL has lapsed."""
    entry = _cache.get(key)
    now = time.time()
    if entry is not None and now - entry[0] < ttl_seconds:
        return entry[1]
    value = builder()
    _cache[key] = (now, value)
    return value


def clear():
    _cache.clear()
