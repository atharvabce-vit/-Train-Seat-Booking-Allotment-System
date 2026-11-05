import sqlite3

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    email      TEXT    NOT NULL UNIQUE,
    phone      TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS stations (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    zone TEXT
);

CREATE TABLE IF NOT EXISTS trains (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    train_number TEXT    NOT NULL UNIQUE,
    train_name   TEXT    NOT NULL,
    runs_on      TEXT    NOT NULL DEFAULT 'Daily',
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Ordered halt list of a train. seq 1 is the origin, the last seq is the
-- terminus. Distances are measured from the origin and drive the fare.
CREATE TABLE IF NOT EXISTS train_stops (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    train_id             INTEGER NOT NULL REFERENCES trains(id) ON DELETE CASCADE,
    station_code         TEXT    NOT NULL REFERENCES stations(code) ON DELETE CASCADE,
    seq                  INTEGER NOT NULL CHECK (seq >= 1),
    arrival_time         TEXT,
    departure_time       TEXT,
    day_offset           INTEGER NOT NULL DEFAULT 0 CHECK (day_offset >= 0),
    distance_from_source INTEGER NOT NULL DEFAULT 0 CHECK (distance_from_source >= 0),
    UNIQUE (train_id, seq),
    UNIQUE (train_id, station_code)
);

CREATE TABLE IF NOT EXISTS coaches (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    train_id     INTEGER NOT NULL REFERENCES trains(id) ON DELETE CASCADE,
    coach_name   TEXT    NOT NULL,
    class_code   TEXT    NOT NULL CHECK (class_code IN ('SL', '3A', '2A', '1A')),
    seat_count   INTEGER NOT NULL CHECK (seat_count > 0),
    -- The first `tatkal_seats` seat numbers of the coach form the Tatkal
    -- quota; the rest are General quota.
    tatkal_seats INTEGER NOT NULL DEFAULT 0 CHECK (tatkal_seats >= 0),
    position     INTEGER NOT NULL DEFAULT 0,
    UNIQUE (train_id, coach_name),
    CHECK (tatkal_seats <= seat_count)
);

CREATE TABLE IF NOT EXISTS seats (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    coach_id    INTEGER NOT NULL REFERENCES coaches(id) ON DELETE CASCADE,
    seat_number INTEGER NOT NULL CHECK (seat_number > 0),
    berth_type  TEXT    NOT NULL CHECK (berth_type IN ('LB', 'MB', 'UB', 'SL', 'SU')),
    UNIQUE (coach_id, seat_number)
);

CREATE TABLE IF NOT EXISTS seat_holds (
    token       TEXT    PRIMARY KEY,
    train_id    INTEGER NOT NULL REFERENCES trains(id) ON DELETE CASCADE,
    class_code  TEXT    NOT NULL CHECK (class_code IN ('SL', '3A', '2A', '1A')),
    travel_date TEXT    NOT NULL,
    from_seq    INTEGER NOT NULL,
    to_seq      INTEGER NOT NULL,
    quota       TEXT    NOT NULL CHECK (quota IN ('GN', 'TQ')),
    expires_at  TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (to_seq > from_seq)
);

CREATE TABLE IF NOT EXISTS bookings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    pnr            TEXT    NOT NULL UNIQUE CHECK (length(pnr) = 10),
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    train_id       INTEGER NOT NULL REFERENCES trains(id) ON DELETE CASCADE,
    class_code     TEXT    NOT NULL CHECK (class_code IN ('SL', '3A', '2A', '1A')),
    travel_date    TEXT    NOT NULL,
    from_seq       INTEGER NOT NULL,
    to_seq         INTEGER NOT NULL,
    quota          TEXT    NOT NULL DEFAULT 'GN' CHECK (quota IN ('GN', 'TQ')),
    status         TEXT    NOT NULL DEFAULT 'confirmed'
                   CHECK (status IN ('confirmed', 'rac', 'waiting', 'cancelled')),
    queue_position INTEGER,
    distance_km    INTEGER NOT NULL DEFAULT 0 CHECK (distance_km >= 0),
    total_fare     INTEGER NOT NULL CHECK (total_fare >= 0),
    -- Concession amount already waived off total_fare.
    concession_amount INTEGER NOT NULL DEFAULT 0 CHECK (concession_amount >= 0),
    -- Round-trip legs share a group_id so they can be shown as one journey.
    group_id       TEXT,
    trip_type      TEXT    NOT NULL DEFAULT 'ONE_WAY'
                   CHECK (trip_type IN ('ONE_WAY', 'ROUND_TRIP')),
    change_count   INTEGER NOT NULL DEFAULT 0 CHECK (change_count >= 0),
    booked_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    cancelled_at   TEXT,
    CHECK (to_seq > from_seq)
);

-- One row per occupied seat for one travel date, over the leg
-- [from_seq, to_seq). Two rows for the same seat and date conflict only when
-- their legs overlap, which is what makes part-route booking possible.
CREATE TABLE IF NOT EXISTS seat_inventory (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    seat_id         INTEGER NOT NULL REFERENCES seats(id) ON DELETE CASCADE,
    travel_date     TEXT    NOT NULL,
    from_seq        INTEGER NOT NULL,
    to_seq          INTEGER NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'booked'
                    CHECK (status IN ('held', 'booked', 'cancelled')),
    booking_id      INTEGER REFERENCES bookings(id) ON DELETE SET NULL,
    hold_token      TEXT    REFERENCES seat_holds(token) ON DELETE SET NULL,
    hold_expires_at TEXT,
    CHECK (to_seq > from_seq)
);

-- passengers.coach_name, passengers.seat_number and passengers.berth_type are
-- DENORMALIZED copies of the seat that was allotted when the booking was made.
-- WHY: a printed ticket has to stay immutable. If the coach layout is changed,
-- a seat is renumbered, or the booking is cancelled later, the ticket already
-- issued for this PNR must still show exactly what was allotted at that moment.
-- Reading the live seats table instead would let an old ticket silently change
-- under the passenger's feet, so the values are copied and frozen here.
CREATE TABLE IF NOT EXISTS passengers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id  INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,
    age         INTEGER NOT NULL CHECK (age BETWEEN 1 AND 120),
    gender      TEXT    NOT NULL CHECK (gender IN ('M', 'F', 'O')),
    preference  TEXT    NOT NULL DEFAULT 'ANY'
                CHECK (preference IN ('ANY', 'LB', 'MB', 'UB', 'SL', 'SU')),
    status      TEXT    NOT NULL DEFAULT 'confirmed'
                CHECK (status IN ('confirmed', 'rac', 'waiting', 'cancelled')),
    concession_percent INTEGER NOT NULL DEFAULT 0
                CHECK (concession_percent BETWEEN 0 AND 100),
    -- Fare actually charged for this passenger, after any concession.
    fare        INTEGER NOT NULL DEFAULT 0 CHECK (fare >= 0),
    seat_id     INTEGER REFERENCES seats(id) ON DELETE SET NULL,
    coach_name  TEXT,
    seat_number INTEGER,
    berth_type  TEXT CHECK (berth_type IN ('LB', 'MB', 'UB', 'SL', 'SU'))
);

-- Mock payment gateway: one row per confirmed booking, no real money moves.
CREATE TABLE IF NOT EXISTS payments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    amount     INTEGER NOT NULL CHECK (amount >= 0),
    method     TEXT    NOT NULL DEFAULT 'MOCK'
               CHECK (method IN ('MOCK', 'UPI', 'CARD', 'NETBANKING')),
    status     TEXT    NOT NULL DEFAULT 'success'
               CHECK (status IN ('pending', 'success', 'failed')),
    txn_ref    TEXT    NOT NULL UNIQUE,
    paid_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS refunds (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    percent    INTEGER NOT NULL CHECK (percent BETWEEN 0 AND 100),
    amount     INTEGER NOT NULL CHECK (amount >= 0),
    reason     TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Outbox for the mocked e-mail / SMS confirmations.
CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id INTEGER REFERENCES bookings(id) ON DELETE CASCADE,
    channel    TEXT    NOT NULL CHECK (channel IN ('email', 'sms')),
    recipient  TEXT    NOT NULL,
    subject    TEXT    NOT NULL,
    body       TEXT    NOT NULL,
    status     TEXT    NOT NULL DEFAULT 'sent'
               CHECK (status IN ('queued', 'sent', 'failed')),
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- History of date/leg changes (reschedules) made against a booking.
CREATE TABLE IF NOT EXISTS booking_changes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    old_date   TEXT    NOT NULL,
    new_date   TEXT    NOT NULL,
    old_from_seq INTEGER,
    old_to_seq   INTEGER,
    new_from_seq INTEGER,
    new_to_seq   INTEGER,
    fee        INTEGER NOT NULL DEFAULT 0 CHECK (fee >= 0),
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Simple audit trail for anything that moves money or seats.
CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    action     TEXT    NOT NULL,
    entity     TEXT    NOT NULL,
    entity_id  TEXT,
    detail     TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Tokens for the JSON REST API; writes need a valid active token.
CREATE TABLE IF NOT EXISTS api_tokens (
    token        TEXT PRIMARY KEY,
    label        TEXT NOT NULL,
    active       INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    request_count INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_stops_train        ON train_stops(train_id, seq);
CREATE INDEX IF NOT EXISTS idx_stops_station      ON train_stops(station_code);
CREATE INDEX IF NOT EXISTS idx_coaches_train      ON coaches(train_id, class_code);
CREATE INDEX IF NOT EXISTS idx_seats_coach        ON seats(coach_id, seat_number);
CREATE INDEX IF NOT EXISTS idx_inventory_lookup   ON seat_inventory(seat_id, travel_date, status);
CREATE INDEX IF NOT EXISTS idx_inventory_booking  ON seat_inventory(booking_id);
CREATE INDEX IF NOT EXISTS idx_inventory_hold     ON seat_inventory(hold_token);
CREATE INDEX IF NOT EXISTS idx_bookings_pnr       ON bookings(pnr);
CREATE INDEX IF NOT EXISTS idx_bookings_train     ON bookings(train_id, class_code, travel_date, status);
CREATE INDEX IF NOT EXISTS idx_passengers_book    ON passengers(booking_id);
CREATE INDEX IF NOT EXISTS idx_notifications_book ON notifications(booking_id);
CREATE INDEX IF NOT EXISTS idx_changes_booking    ON booking_changes(booking_id);
CREATE INDEX IF NOT EXISTS idx_audit_created      ON audit_log(created_at);
"""


def get_connection(db_path=None):
    path = db_path or DB_PATH
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def create_tables(conn):
    conn.executescript(SCHEMA)


if __name__ == "__main__":
    connection = get_connection()
    create_tables(connection)
    print(f"Database created at {DB_PATH}")
    connection.close()
