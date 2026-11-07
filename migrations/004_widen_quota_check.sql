-- Widen the quota CHECK so the logical quotas (Premium Tatkal, Ladies, Senior
-- Citizen, Divyangjan, Duty Pass) can be stored. SQLite cannot alter a CHECK
-- in place, so the two affected tables are rebuilt with the standard
-- create/copy/drop/rename sequence with foreign keys temporarily off.

PRAGMA foreign_keys = OFF;

CREATE TABLE bookings_new (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    pnr            TEXT    NOT NULL UNIQUE CHECK (length(pnr) = 10),
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    train_id       INTEGER NOT NULL REFERENCES trains(id) ON DELETE CASCADE,
    class_code     TEXT    NOT NULL CHECK (class_code IN ('SL', '3A', '2A', '1A')),
    travel_date    TEXT    NOT NULL,
    from_seq       INTEGER NOT NULL,
    to_seq         INTEGER NOT NULL,
    quota          TEXT    NOT NULL DEFAULT 'GN'
                   CHECK (quota IN ('GN', 'TQ', 'PT', 'LD', 'SS', 'DF', 'DP')),
    status         TEXT    NOT NULL DEFAULT 'confirmed'
                   CHECK (status IN ('confirmed', 'rac', 'waiting', 'cancelled')),
    queue_position INTEGER,
    distance_km    INTEGER NOT NULL DEFAULT 0 CHECK (distance_km >= 0),
    total_fare     INTEGER NOT NULL CHECK (total_fare >= 0),
    concession_amount INTEGER NOT NULL DEFAULT 0 CHECK (concession_amount >= 0),
    group_id       TEXT,
    trip_type      TEXT    NOT NULL DEFAULT 'ONE_WAY'
                   CHECK (trip_type IN ('ONE_WAY', 'ROUND_TRIP')),
    change_count   INTEGER NOT NULL DEFAULT 0 CHECK (change_count >= 0),
    idempotency_key TEXT,
    booked_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    cancelled_at   TEXT,
    CHECK (to_seq > from_seq)
);

INSERT INTO bookings_new (
    id, pnr, user_id, train_id, class_code, travel_date, from_seq, to_seq,
    quota, status, queue_position, distance_km, total_fare, concession_amount,
    group_id, trip_type, change_count, idempotency_key, booked_at, cancelled_at
) SELECT
    id, pnr, user_id, train_id, class_code, travel_date, from_seq, to_seq,
    quota, status, queue_position, distance_km, total_fare, concession_amount,
    group_id, trip_type, change_count, idempotency_key, booked_at, cancelled_at
FROM bookings;

DROP TABLE bookings;

ALTER TABLE bookings_new RENAME TO bookings;

CREATE INDEX IF NOT EXISTS idx_bookings_pnr   ON bookings(pnr);

CREATE INDEX IF NOT EXISTS idx_bookings_train ON bookings(train_id, class_code, travel_date, status);

CREATE TABLE seat_holds_new (
    token       TEXT    PRIMARY KEY,
    train_id    INTEGER NOT NULL REFERENCES trains(id) ON DELETE CASCADE,
    class_code  TEXT    NOT NULL CHECK (class_code IN ('SL', '3A', '2A', '1A')),
    travel_date TEXT    NOT NULL,
    from_seq    INTEGER NOT NULL,
    to_seq      INTEGER NOT NULL,
    quota       TEXT    NOT NULL CHECK (quota IN ('GN', 'TQ', 'PT', 'LD', 'SS', 'DF', 'DP')),
    expires_at  TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (to_seq > from_seq)
);

INSERT INTO seat_holds_new SELECT * FROM seat_holds;

DROP TABLE seat_holds;

ALTER TABLE seat_holds_new RENAME TO seat_holds;

PRAGMA foreign_keys = ON;
