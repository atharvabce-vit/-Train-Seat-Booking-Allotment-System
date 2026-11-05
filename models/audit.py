def log(conn, action, entity, entity_id=None, detail=None):
    conn.execute(
        "INSERT INTO audit_log (action, entity, entity_id, detail) VALUES (?, ?, ?, ?)",
        (action, entity, None if entity_id is None else str(entity_id), detail),
    )


def recent(conn, limit=100):
    rows = conn.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(row) for row in rows]
