def queue_email(conn, booking_id, recipient, subject, body):
    conn.execute(
        "INSERT INTO notifications (booking_id, channel, recipient, subject, body) VALUES (?, 'email', ?, ?, ?)",
        (booking_id, recipient, subject, body),
    )


def queue_sms(conn, booking_id, recipient, body):
    conn.execute(
        "INSERT INTO notifications (booking_id, channel, recipient, subject, body) VALUES (?, 'sms', ?, 'Booking update', ?)",
        (booking_id, recipient or "", body),
    )


def recent(conn, limit=25):
    return conn.execute(
        """
        SELECT n.*, b.pnr
        FROM notifications n
        LEFT JOIN bookings b ON b.id = n.booking_id
        ORDER BY n.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
