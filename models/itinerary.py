"""Multi-leg (connecting) journey search.

`search_trains` finds direct trains. This module walks the station graph to
find itineraries that need one change of train, which is how a large share of
real journeys are actually booked (e.g. Kolkata -> Chennai via Delhi).
"""
from models.fare import fare_per_passenger
from models.trains import classes_for_train, get_stop, journey_minutes, segment_distance
from models.util import describe_time, format_duration, minutes_of

# Minimum time a passenger needs to change trains at a junction.
MIN_TRANSFER_MINUTES = 60
# Longest wait, in minutes, that still counts as a usable connection. Trains
# run daily, so a departure that is earlier than the arrival is taken to be the
# next day's service; anything beyond a day is not offered.
MAX_TRANSFER_MINUTES = 24 * 60
MAX_LEGS = 2


def _match_station(conn, query):
    row = conn.execute(
        """
        SELECT code FROM stations
        WHERE city = ? COLLATE NOCASE OR name = ? COLLATE NOCASE OR code = ? COLLATE NOCASE
        LIMIT 1
        """,
        (query, query, query),
    ).fetchone()
    return row["code"] if row else None


def _direct_edges(conn):
    """Every (from, to) station pair reachable on a single train."""
    rows = conn.execute(
        """
        SELECT t.id AS train_id, fs.station_code AS from_code, fs.seq AS from_seq,
               ts.station_code AS to_code, ts.seq AS to_seq
        FROM trains t
        JOIN train_stops fs ON fs.train_id = t.id
        JOIN train_stops ts ON ts.train_id = t.id AND ts.seq > fs.seq
        """
    ).fetchall()
    edges = {}
    for row in rows:
        edges.setdefault(row["from_code"], []).append(dict(row))
    return edges


def _leg(conn, train_id, from_seq, to_seq):
    train = conn.execute(
        "SELECT train_number, train_name FROM trains WHERE id = ?", (train_id,)
    ).fetchone()
    origin = get_stop(conn, train_id, from_seq)
    dest = get_stop(conn, train_id, to_seq)
    if train is None or origin is None or dest is None:
        return None
    minutes = journey_minutes(
        origin["day_offset"], origin["departure_time"] or origin["arrival_time"],
        dest["day_offset"], dest["arrival_time"] or dest["departure_time"],
    )
    return {
        "train_id": train_id,
        "train_number": train["train_number"],
        "train_name": train["train_name"],
        "from_seq": from_seq,
        "to_seq": to_seq,
        "from_code": origin["station_code"],
        "from_name": origin["station_name"],
        "from_city": origin["city"],
        "to_code": dest["station_code"],
        "to_name": dest["station_name"],
        "to_city": dest["city"],
        "depart_label": describe_time(origin["day_offset"], origin["departure_time"]),
        "arrive_label": describe_time(dest["day_offset"], dest["arrival_time"]),
        "distance_km": segment_distance(conn, train_id, from_seq, to_seq),
        "duration": format_duration(minutes),
        "duration_minutes": minutes,
    }


def _abs_minutes(stop, key):
    clock = stop[key] or stop["arrival_time"] or stop["departure_time"] or "00:00"
    return stop["day_offset"] * 1440 + minutes_of(clock)


def _transfer_wait(conn, first, second):
    """Minutes spent waiting at the junction, or None when the connection is
    not usable. Since trains run daily, a second-leg departure that falls
    before the arrival is treated as the next day's service."""
    arrive = get_stop(conn, first["train_id"], first["to_seq"])
    depart = get_stop(conn, second["train_id"], second["from_seq"])
    if arrive is None or depart is None:
        return None
    gap = _abs_minutes(depart, "departure_time") - _abs_minutes(arrive, "arrival_time")
    if gap < 0:
        gap += 1440
    if gap < MIN_TRANSFER_MINUTES or gap > MAX_TRANSFER_MINUTES:
        return None
    return gap


def _fare_estimate(conn, legs):
    """Estimated total fare per class, summed across the legs of a journey."""
    common = None
    for leg in legs:
        classes = set(classes_for_train(conn, leg["train_id"]))
        common = classes if common is None else (common & classes)
    return {
        code: sum(fare_per_passenger(code, leg["distance_km"]) for leg in legs)
        for code in sorted(common or [])
    }


def find_journeys(conn, source, destination, limit=10):
    """Return one-change itineraries from source to destination, shortest total
    travel time first. Returns an empty list when no connection can be made."""
    start = _match_station(conn, source)
    end = _match_station(conn, destination)
    if not start or not end or start == end:
        return []

    edges = _direct_edges(conn)
    journeys = []
    seen = set()
    for first in edges.get(start, []):
        junction = first["to_code"]
        if junction == end:
            continue
        for second in edges.get(junction, []):
            if second["to_code"] != end or second["train_id"] == first["train_id"]:
                continue
            wait = _transfer_wait(conn, first, second)
            if wait is None:
                continue
            leg_one = _leg(conn, first["train_id"], first["from_seq"], first["to_seq"])
            leg_two = _leg(conn, second["train_id"], second["from_seq"], second["to_seq"])
            if leg_one is None or leg_two is None:
                continue
            key = (
                (leg_one["train_id"], leg_one["from_seq"], leg_one["to_seq"]),
                (leg_two["train_id"], leg_two["from_seq"], leg_two["to_seq"]),
            )
            if key in seen:
                continue
            seen.add(key)
            total_minutes = leg_one["duration_minutes"] + wait + leg_two["duration_minutes"]
            journeys.append(
                {
                    "changes": 1,
                    "legs": [leg_one, leg_two],
                    "transfer_at": leg_one["to_name"],
                    "transfer_wait_minutes": wait,
                    "transfer_wait": format_duration(wait),
                    "total_distance_km": leg_one["distance_km"] + leg_two["distance_km"],
                    "total_minutes": total_minutes,
                    "total_duration": format_duration(total_minutes),
                    "fares": _fare_estimate(conn, [leg_one, leg_two]),
                }
            )

    journeys.sort(key=lambda item: (item["total_minutes"], item["total_distance_km"]))
    return journeys[:limit]
