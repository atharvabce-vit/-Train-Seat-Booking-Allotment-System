def search_trains(conn, source, destination):
    return conn.execute(
        """
        SELECT *
        FROM trains
        WHERE source = ? COLLATE NOCASE
          AND destination = ? COLLATE NOCASE
        ORDER BY depart_time
        """,
        (source.strip(), destination.strip()),
    ).fetchall()


def get_train(conn, train_id):
    return conn.execute("SELECT * FROM trains WHERE id = ?", (train_id,)).fetchone()


def get_coaches(conn, train_id, class_code=None):
    if class_code is None:
        return conn.execute(
            "SELECT * FROM coaches WHERE train_id = ? ORDER BY class_code, coach_name",
            (train_id,),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM coaches WHERE train_id = ? AND class_code = ? ORDER BY coach_name",
        (train_id, class_code),
    ).fetchall()


def available_classes(conn, train_id):
    rows = conn.execute(
        "SELECT DISTINCT class_code FROM coaches WHERE train_id = ? ORDER BY class_code",
        (train_id,),
    ).fetchall()
    return [r["class_code"] for r in rows]


def total_seats(conn, train_id, class_code):
    row = conn.execute(
        """
        SELECT COALESCE(SUM(seat_count), 0) AS total
        FROM coaches
        WHERE train_id = ? AND class_code = ?
        """,
        (train_id, class_code),
    ).fetchone()
    return row["total"]
