-- History of date/leg changes (reschedules) made against a booking.
CREATE TABLE IF NOT EXISTS booking_changes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id   INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    old_date     TEXT    NOT NULL,
    new_date     TEXT    NOT NULL,
    old_from_seq INTEGER,
    old_to_seq   INTEGER,
    new_from_seq INTEGER,
    new_to_seq   INTEGER,
    fee          INTEGER NOT NULL DEFAULT 0 CHECK (fee >= 0),
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_changes_booking ON booking_changes(booking_id);
