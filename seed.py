from db import create_tables, get_connection

BERTH_PATTERNS = {
    "SL": ["LB", "MB", "UB", "LB", "MB", "UB", "SL", "SU"],
    "3A": ["LB", "MB", "UB", "LB", "MB", "UB", "SL", "SU"],
    "2A": ["LB", "UB", "LB", "UB", "SL", "SU"],
    "1A": ["LB", "UB", "SL", "SU"],
}

COACH_PREFIX = {"SL": "S", "3A": "B", "2A": "A", "1A": "H"}

DEFAULT_PLAN = {
    "SL": (3, 72),
    "3A": (2, 64),
    "2A": (1, 46),
    "1A": (1, 24),
}


def create_train(conn, train_number, train_name, source, destination, depart_time, arrive_time, plan=None):
    plan = plan or DEFAULT_PLAN
    cursor = conn.execute(
        """
        INSERT INTO trains (train_number, train_name, source, destination, depart_time, arrive_time)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (train_number, train_name, source, destination, depart_time, arrive_time),
    )
    train_id = cursor.lastrowid

    for class_code, (num_coaches, seat_count) in plan.items():
        pattern = BERTH_PATTERNS[class_code]
        for index in range(1, num_coaches + 1):
            coach_name = f"{COACH_PREFIX[class_code]}{index}"
            coach_cursor = conn.execute(
                """
                INSERT INTO coaches (train_id, coach_name, class_code, seat_count)
                VALUES (?, ?, ?, ?)
                """,
                (train_id, coach_name, class_code, seat_count),
            )
            coach_id = coach_cursor.lastrowid
            for seat_number in range(1, seat_count + 1):
                berth = pattern[(seat_number - 1) % len(pattern)]
                conn.execute(
                    "INSERT INTO seats (coach_id, seat_number, berth_type) VALUES (?, ?, ?)",
                    (coach_id, seat_number, berth),
                )
    return train_id


def create_sample_data(conn):
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

    trains = [
        ("12951", "Mumbai Rajdhani Express", "Mumbai", "Delhi", "17:00", "08:35"),
        ("12621", "Tamil Nadu Express", "Chennai", "Delhi", "22:30", "07:40"),
        ("12009", "Shatabdi Express", "Mumbai", "Ahmedabad", "06:25", "13:05"),
        ("12626", "Kerala Express", "Trivandrum", "Delhi", "11:15", "12:45"),
        ("12302", "Howrah Rajdhani", "Kolkata", "Delhi", "16:55", "10:00"),
    ]
    for train in trains:
        existing = conn.execute(
            "SELECT 1 FROM trains WHERE train_number = ?", (train[0],)
        ).fetchone()
        if existing is None:
            create_train(conn, *train)


if __name__ == "__main__":
    connection = get_connection()
    create_tables(connection)
    create_sample_data(connection)
    train_count = connection.execute("SELECT COUNT(*) AS c FROM trains").fetchone()["c"]
    seat_count = connection.execute("SELECT COUNT(*) AS c FROM seats").fetchone()["c"]
    print(f"Seeded {train_count} trains and {seat_count} seats.")
    connection.close()
