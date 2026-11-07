from datetime import datetime, timedelta

from config import (
    BOOKING_WINDOW_DAYS,
    QUOTA_POOL,
    TATKAL_OPEN_HOUR_AC,
    TATKAL_OPEN_HOUR_NON_AC,
)
from models.util import (
    IST,
    booking_dates,
    describe_time,
    format_duration,
    journey_minutes,
    now_ist,
    now_str,
    parse_date,
    parse_time,
    today_ist,
)

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Cycling berth layout per class, used whenever a coach is created.
BERTH_PATTERNS = {
    "SL": ["LB", "MB", "UB", "LB", "MB", "UB", "SL", "SU"],
    "3A": ["LB", "MB", "UB", "LB", "MB", "UB", "SL", "SU"],
    "2A": ["LB", "UB", "LB", "UB", "SL", "SU"],
    "1A": ["LB", "UB", "SL", "SU"],
}

COACH_PREFIX = {"SL": "S", "3A": "B", "2A": "A", "1A": "H"}


def create_coach(conn, train_id, coach_name, class_code, seat_count, tatkal_seats=0, position=0):
    """Insert a coach and its seats, returning the new coach id."""
    cursor = conn.execute(
        """
        INSERT INTO coaches
            (train_id, coach_name, class_code, seat_count, tatkal_seats, position)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (train_id, coach_name, class_code, seat_count, tatkal_seats, position),
    )
    coach_id = cursor.lastrowid
    pattern = BERTH_PATTERNS.get(class_code, BERTH_PATTERNS["SL"])
    for seat_number in range(1, seat_count + 1):
        berth = pattern[(seat_number - 1) % len(pattern)]
        conn.execute(
            "INSERT INTO seats (coach_id, seat_number, berth_type) VALUES (?, ?, ?)",
            (coach_id, seat_number, berth),
        )
    return coach_id


def next_coach_name(conn, train_id, class_code):
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM coaches WHERE train_id = ? AND class_code = ?",
        (train_id, class_code),
    ).fetchone()["c"]
    return f"{COACH_PREFIX.get(class_code, 'X')}{count + 1}"



def get_train(conn, train_id):
    if not train_id:
        return None
    return conn.execute("SELECT * FROM trains WHERE id = ?", (train_id,)).fetchone()


def get_stops(conn, train_id):
    return conn.execute(
        """
        SELECT ts.seq, ts.station_code, st.name AS station_name, st.city,
               ts.arrival_time, ts.departure_time, ts.day_offset,
               ts.distance_from_source
        FROM train_stops ts
        JOIN stations st ON st.code = ts.station_code
        WHERE ts.train_id = ?
        ORDER BY ts.seq
        """,
        (train_id,),
    ).fetchall()


def get_stop(conn, train_id, seq):
    return conn.execute(
        """
        SELECT ts.seq, ts.station_code, st.name AS station_name, st.city,
               ts.arrival_time, ts.departure_time, ts.day_offset,
               ts.distance_from_source
        FROM train_stops ts
        JOIN stations st ON st.code = ts.station_code
        WHERE ts.train_id = ? AND ts.seq = ?
        """,
        (train_id, seq),
    ).fetchone()


def train_endpoints(conn, train_id):
    stops = get_stops(conn, train_id)
    if not stops:
        return None, None
    return stops[0], stops[-1]


def segment_distance(conn, train_id, from_seq, to_seq):
    start = get_stop(conn, train_id, from_seq)
    end = get_stop(conn, train_id, to_seq)
    if start is None or end is None:
        return 0
    return max(0, end["distance_from_source"] - start["distance_from_source"])


def search_stations(conn, query, limit=10):
    pattern = f"%{(query or '').strip()}%"
    return conn.execute(
        """
        SELECT code, name, city FROM stations
        WHERE city LIKE ? OR name LIKE ? OR code LIKE ?
        ORDER BY city, name
        LIMIT ?
        """,
        (pattern, pattern, pattern, limit),
    ).fetchall()


def search_trains(conn, from_query, to_query):
    rows = conn.execute(
        """
        SELECT t.id, t.train_number, t.train_name, t.runs_on,
               fs.seq AS from_seq, fst.code AS from_code, fst.name AS from_name,
               fst.city AS from_city, fs.departure_time AS from_time,
               fs.day_offset AS from_day,
               ts.seq AS to_seq, tst.code AS to_code, tst.name AS to_name,
               tst.city AS to_city, ts.arrival_time AS to_time,
               ts.day_offset AS to_day,
               (ts.distance_from_source - fs.distance_from_source) AS distance_km
        FROM trains t
        JOIN train_stops fs  ON fs.train_id = t.id
        JOIN stations   fst  ON fst.code = fs.station_code
        JOIN train_stops ts  ON ts.train_id = t.id AND ts.seq > fs.seq
        JOIN stations   tst  ON tst.code = ts.station_code
        WHERE (fst.city = ? COLLATE NOCASE
               OR fst.name = ? COLLATE NOCASE
               OR fst.code = ? COLLATE NOCASE)
          AND (tst.city = ? COLLATE NOCASE
               OR tst.name = ? COLLATE NOCASE
               OR tst.code = ? COLLATE NOCASE)
        ORDER BY t.train_number, fs.seq, ts.seq
        """,
        (
            from_query.strip(), from_query.strip(), from_query.strip(),
            to_query.strip(), to_query.strip(), to_query.strip(),
        ),
    ).fetchall()

    results = []
    seen = set()
    for row in rows:
        key = (row["id"], row["from_seq"], row["to_seq"])
        if key in seen:
            continue
        seen.add(key)
        item = dict(row)
        item["duration"] = format_duration(
            journey_minutes(row["from_day"], row["from_time"], row["to_day"], row["to_time"])
        )
        item["duration_minutes"] = journey_minutes(
            row["from_day"], row["from_time"], row["to_day"], row["to_time"]
        )
        item["depart_label"] = describe_time(row["from_day"], row["from_time"])
        item["arrive_label"] = describe_time(row["to_day"], row["to_time"])
        results.append(item)
    return results


def classes_for_train(conn, train_id):
    rows = conn.execute(
        "SELECT DISTINCT class_code FROM coaches WHERE train_id = ? ORDER BY class_code",
        (train_id,),
    ).fetchall()
    return [row["class_code"] for row in rows]


def quota_seat_count(conn, train_id, class_code, quota="GN"):
    pool = QUOTA_POOL.get(quota, "GN")
    row = conn.execute(
        """
        SELECT COALESCE(SUM(
                   CASE WHEN ? = 'TQ' THEN tatkal_seats
                        ELSE seat_count - tatkal_seats END), 0) AS total
        FROM coaches
        WHERE train_id = ? AND class_code = ?
        """,
        (pool, train_id, class_code),
    ).fetchone()
    return row["total"]


def occupied_seat_ids(conn, train_id, class_code, travel_date, from_seq, to_seq, quota="GN", now=None):
    """Seats already taken on this date for a leg that overlaps [from_seq, to_seq)."""
    now = now or now_str()
    pool = QUOTA_POOL.get(quota, "GN")
    rows = conn.execute(
        """
        SELECT DISTINCT si.seat_id
        FROM seat_inventory si
        JOIN seats   s ON s.id = si.seat_id
        JOIN coaches c ON c.id = s.coach_id
        WHERE c.train_id = ?
          AND c.class_code = ?
          AND si.travel_date = ?
          AND si.from_seq < ?
          AND ? < si.to_seq
          AND (si.status = 'booked'
               OR (si.status = 'held' AND si.hold_expires_at > ?))
          AND ((? = 'TQ' AND s.seat_number <= c.tatkal_seats)
               OR (? = 'GN' AND s.seat_number > c.tatkal_seats))
        """,
        (train_id, class_code, travel_date, to_seq, from_seq, now, pool, pool),
    ).fetchall()
    return {row["seat_id"] for row in rows}


def available_seats(conn, train_id, class_code, travel_date, from_seq, to_seq, quota="GN", now=None):
    taken = occupied_seat_ids(
        conn, train_id, class_code, travel_date, from_seq, to_seq, quota, now
    )
    pool = QUOTA_POOL.get(quota, "GN")
    rows = conn.execute(
        """
        SELECT s.id AS seat_id, s.seat_number, s.berth_type,
               c.id AS coach_id, c.coach_name, c.position
        FROM seats s
        JOIN coaches c ON c.id = s.coach_id
        WHERE c.train_id = ?
          AND c.class_code = ?
          AND ((? = 'TQ' AND s.seat_number <= c.tatkal_seats)
               OR (? = 'GN' AND s.seat_number > c.tatkal_seats))
        ORDER BY c.position, c.coach_name, s.seat_number
        """,
        (train_id, class_code, pool, pool),
    ).fetchall()
    return [dict(row) for row in rows if row["seat_id"] not in taken]


def available_count(conn, train_id, class_code, travel_date, from_seq, to_seq, quota="GN", now=None):
    total = quota_seat_count(conn, train_id, class_code, quota)
    taken = occupied_seat_ids(
        conn, train_id, class_code, travel_date, from_seq, to_seq, quota, now
    )
    return max(0, total - len(taken))


def departure_datetime(conn, train_id, travel_date, from_seq):
    """The IST-aware instant this train leaves the boarding station."""
    stop = get_stop(conn, train_id, from_seq)
    day = parse_date(travel_date)
    if stop is None or day is None:
        return None
    clock = parse_time(stop["departure_time"] or stop["arrival_time"])
    if clock is None:
        return None
    return datetime.combine(day, clock).replace(tzinfo=IST)


def hours_before_departure(conn, train_id, travel_date, from_seq):
    departure = departure_datetime(conn, train_id, travel_date, from_seq)
    if departure is None:
        return 0.0
    return (departure - now_ist()).total_seconds() / 3600


def tatkal_open(conn, train_id, travel_date, from_seq, class_code="SL"):
    """Tatkal opens at 10:00 IST the previous day for AC classes and 11:00 IST
    for the rest, and closes when the train departs."""
    departure = departure_datetime(conn, train_id, travel_date, from_seq)
    if departure is None:
        return False
    now = now_ist()
    if departure <= now:
        return False
    hour = TATKAL_OPEN_HOUR_AC if class_code in ("3A", "2A", "1A") else TATKAL_OPEN_HOUR_NON_AC
    opens_at = (departure - timedelta(days=1)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    return now >= opens_at


def runs_on_days(runs_on):
    """Weekday indexes (Mon=0) a train runs on, or None when it runs daily."""
    text = (runs_on or "Daily").strip()
    lowered = text.lower()
    if lowered.startswith("daily except"):
        tail = lowered.split("except", 1)[1]
        excluded = {WEEKDAYS.index(day) for day in WEEKDAYS if day.lower() in tail}
        return {index for index in range(7) if index not in excluded}
    if lowered.startswith("daily"):
        return None
    days = set()
    for part in text.replace("/", ",").replace(" ", ",").split(","):
        token = part.strip()[:3].title()
        if token in WEEKDAYS:
            days.add(WEEKDAYS.index(token))
    return days or None


def runs_on_date(runs_on, travel_date):
    day = parse_date(travel_date) if isinstance(travel_date, str) else travel_date
    if day is None:
        return False
    days = runs_on_days(runs_on)
    return True if days is None else day.weekday() in days


def is_bookable_date(travel_date):
    day = parse_date(travel_date) if isinstance(travel_date, str) else travel_date
    if day is None:
        return False
    days_ahead = (day - today_ist()).days
    return 0 <= days_ahead <= BOOKING_WINDOW_DAYS


def availability_calendar(conn, train_id, class_code, from_seq, to_seq, quota="GN", days=BOOKING_WINDOW_DAYS):
    calendar = []
    for day in booking_dates(days):
        travel_date = day.isoformat()
        calendar.append(
            {
                "date": travel_date,
                "available": available_count(
                    conn, train_id, class_code, travel_date, from_seq, to_seq, quota
                ),
                "tatkal_open": tatkal_open(conn, train_id, travel_date, from_seq, class_code),
            }
        )
    return calendar
