from db import create_tables, get_connection
from models.api_auth import ensure_default_token
from models.trains import COACH_PREFIX, create_coach

DEFAULT_PLAN = {
    "SL": (3, 72),
    "3A": (2, 64),
    "2A": (1, 46),
    "1A": (1, 24),
}

SHORT_PLAN = {
    "SL": (2, 72),
    "3A": (1, 64),
    "2A": (1, 46),
    "1A": (1, 24),
}

TATKAL_RATIO = 0.25

STATIONS = [
    ("NDLS", "New Delhi", "Delhi", "NR"),
    ("BCT", "Mumbai Central", "Mumbai", "WR"),
    ("CSMT", "Mumbai CSMT", "Mumbai", "CR"),
    ("MAS", "Chennai Central", "Chennai", "SR"),
    ("HWH", "Howrah Jn", "Kolkata", "ER"),
    ("SBC", "KSR Bengaluru", "Bengaluru", "SWR"),
    ("SC", "Secunderabad Jn", "Hyderabad", "SCR"),
    ("TVC", "Thiruvananthapuram Central", "Trivandrum", "SR"),
    ("ADI", "Ahmedabad Jn", "Ahmedabad", "WR"),
    ("BPL", "Bhopal Jn", "Bhopal", "WCR"),
    ("LKO", "Lucknow Charbagh", "Lucknow", "NR"),
    ("BRC", "Vadodara Jn", "Vadodara", "WR"),
    ("ST", "Surat", "Surat", "WR"),
    ("KOTA", "Kota Jn", "Kota", "WCR"),
    ("AGC", "Agra Cantt", "Agra", "NCR"),
    ("GWL", "Gwalior Jn", "Gwalior", "NCR"),
    ("JHS", "Jhansi Jn", "Jhansi", "NCR"),
    ("CNB", "Kanpur Central", "Kanpur", "NCR"),
    ("GAYA", "Gaya Jn", "Gaya", "ECR"),
    ("DDU", "Pt. DDU Jn", "Mughalsarai", "ECR"),
    ("NGP", "Nagpur Jn", "Nagpur", "CR"),
    ("BZA", "Vijayawada Jn", "Vijayawada", "SCR"),
    ("CBE", "Coimbatore Jn", "Coimbatore", "SR"),
    ("PUNE", "Pune Jn", "Pune", "CR"),
    ("BSB", "Varanasi Jn", "Varanasi", "NER"),
    ("SBC", "KSR Bengaluru", "Bengaluru", "SWR"),
]


def stop(code, arrival, departure, day, distance):
    return {
        "station": code,
        "arrival": arrival,
        "departure": departure,
        "day": day,
        "distance": distance,
    }


ROUTES = [
    ("12951", "Mumbai Rajdhani Express", DEFAULT_PLAN, [
        stop("BCT", None, "17:00", 0, 0),
        stop("BRC", "19:38", "19:48", 0, 392),
        stop("KOTA", "01:05", "01:15", 1, 788),
        stop("NDLS", "08:35", None, 1, 1386),
    ]),
    ("12952", "Mumbai Rajdhani Express", DEFAULT_PLAN, [
        stop("NDLS", None, "16:25", 0, 0),
        stop("KOTA", "23:35", "23:45", 0, 598),
        stop("BRC", "05:05", "05:15", 1, 994),
        stop("BCT", "08:15", None, 1, 1386),
    ]),
    ("12621", "Tamil Nadu Express", DEFAULT_PLAN, [
        stop("MAS", None, "22:30", 0, 0),
        stop("BZA", "04:20", "04:30", 1, 431),
        stop("NGP", "14:15", "14:25", 1, 1090),
        stop("BPL", "20:35", "20:45", 1, 1612),
        stop("AGC", "03:10", "03:15", 2, 1910),
        stop("NDLS", "07:40", None, 2, 2182),
    ]),
    ("12622", "Tamil Nadu Express", DEFAULT_PLAN, [
        stop("NDLS", None, "22:30", 0, 0),
        stop("AGC", "01:20", "01:25", 1, 272),
        stop("BPL", "07:35", "07:45", 1, 570),
        stop("NGP", "13:50", "14:00", 1, 1092),
        stop("BZA", "23:40", "23:50", 1, 1751),
        stop("MAS", "07:05", None, 2, 2182),
    ]),
    ("12302", "Howrah Rajdhani Express", DEFAULT_PLAN, [
        stop("HWH", None, "16:55", 0, 0),
        stop("GAYA", "21:35", "21:40", 0, 458),
        stop("DDU", "00:55", "01:05", 1, 807),
        stop("CNB", "05:00", "05:05", 1, 1099),
        stop("NDLS", "10:00", None, 1, 1451),
    ]),
    ("12626", "Kerala Express", DEFAULT_PLAN, [
        stop("TVC", None, "11:15", 0, 0),
        stop("CBE", "17:35", "17:45", 0, 413),
        stop("BZA", "06:00", "06:10", 1, 1263),
        stop("NGP", "16:30", "16:40", 1, 1961),
        stop("BPL", "23:05", "23:15", 1, 2483),
        stop("NDLS", "12:45", None, 2, 3036),
    ]),
    ("12723", "Telangana Express", DEFAULT_PLAN, [
        stop("SC", None, "06:25", 0, 0),
        stop("NGP", "12:30", "12:40", 0, 581),
        stop("BPL", "18:50", "19:00", 0, 1087),
        stop("AGC", "00:15", "00:20", 1, 1599),
        stop("NDLS", "08:10", None, 1, 1780),
    ]),
    ("12009", "Shatabdi Express", SHORT_PLAN, [
        stop("BCT", None, "06:25", 0, 0),
        stop("ST", "09:10", "09:13", 0, 263),
        stop("BRC", "10:22", "10:30", 0, 392),
        stop("ADI", "13:05", None, 0, 493),
    ]),
    ("12002", "Bhopal Shatabdi Express", SHORT_PLAN, [
        stop("NDLS", None, "06:00", 0, 0),
        stop("AGC", "07:57", "07:59", 0, 195),
        stop("GWL", "09:12", "09:14", 0, 313),
        stop("JHS", "10:11", "10:16", 0, 415),
        stop("BPL", "14:05", None, 0, 707),
    ]),
    ("12230", "Lucknow Mail", SHORT_PLAN, [
        stop("LKO", None, "22:00", 0, 0),
        stop("CNB", "23:25", "23:35", 0, 74),
        stop("NDLS", "06:45", None, 1, 493),
    ]),
]


def ensure_station(conn, code, name=None, city=None, zone=None):
    existing = conn.execute("SELECT 1 FROM stations WHERE code = ?", (code,)).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO stations (code, name, city, zone) VALUES (?, ?, ?, ?)",
            (code, name or code, city or name or code, zone),
        )
    return code


def seed_stations(conn):
    for code, name, city, zone in STATIONS:
        conn.execute(
            "INSERT OR IGNORE INTO stations (code, name, city, zone) VALUES (?, ?, ?, ?)",
            (code, name, city, zone),
        )


def create_train(conn, train_number, train_name, source, destination,
                 depart_time, arrive_time, plan=None, stops=None,
                 distance_km=500, tatkal_ratio=TATKAL_RATIO):
    plan = plan or DEFAULT_PLAN
    cursor = conn.execute(
        "INSERT INTO trains (train_number, train_name, runs_on) VALUES (?, ?, 'Daily')",
        (train_number, train_name),
    )
    train_id = cursor.lastrowid

    if stops is None:
        source_code = ensure_station(conn, source, source, source)
        dest_code = ensure_station(conn, destination, destination, destination)
        stops = [
            stop(source_code, None, depart_time, 0, 0),
            stop(dest_code, arrive_time, None, 0, distance_km),
        ]

    for index, halt in enumerate(stops, start=1):
        ensure_station(conn, halt["station"], halt["station"], halt["station"])
        conn.execute(
            """
            INSERT INTO train_stops
                (train_id, station_code, seq, arrival_time, departure_time,
                 day_offset, distance_from_source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                train_id, halt["station"], index, halt["arrival"], halt["departure"],
                halt["day"], halt["distance"],
            ),
        )

    for class_code, (num_coaches, seat_count) in plan.items():
        tatkal_seats = int(seat_count * tatkal_ratio)
        for index in range(1, num_coaches + 1):
            coach_name = f"{COACH_PREFIX[class_code]}{index}"
            create_coach(conn, train_id, coach_name, class_code, seat_count, tatkal_seats, index)
    return train_id


def create_sample_data(conn):
    seed_stations(conn)
    ensure_default_token(conn)

    users = [
        ("Aarav Sharma", "aarav@example.com", "9876543210"),
        ("Priya Nair", "priya@example.com", "9876500000"),
        ("Rahul Verma", "rahul@example.com", "9812300000"),
    ]
    for name, email, phone in users:
        conn.execute(
            "INSERT OR IGNORE INTO users (name, email, phone) VALUES (?, ?, ?)",
            (name, email, phone),
        )

    for train_number, train_name, plan, stops in ROUTES:
        existing = conn.execute(
            "SELECT 1 FROM trains WHERE train_number = ?", (train_number,)
        ).fetchone()
        if existing is None:
            create_train(conn, train_number, train_name, None, None, None, None,
                         plan=plan, stops=stops)


if __name__ == "__main__":
    connection = get_connection()
    create_tables(connection)
    create_sample_data(connection)
    train_count = connection.execute("SELECT COUNT(*) AS c FROM trains").fetchone()["c"]
    stop_count = connection.execute("SELECT COUNT(*) AS c FROM train_stops").fetchone()["c"]
    seat_count = connection.execute("SELECT COUNT(*) AS c FROM seats").fetchone()["c"]
    print(f"Seeded {train_count} trains, {stop_count} stops and {seat_count} seats.")
    connection.close()
