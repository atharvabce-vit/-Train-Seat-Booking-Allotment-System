import sqlite3

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    phone         TEXT,
    password_hash TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trains (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    train_number TEXT    NOT NULL UNIQUE,
    train_name   TEXT    NOT NULL,
    source       TEXT    NOT NULL,
    destination  TEXT    NOT NULL,
    depart_time  TEXT    NOT NULL,
    arrive_time  TEXT    NOT NULL,
    runs_on      TEXT    NOT NULL DEFAULT 'Daily',
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS coaches (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    train_id   INTEGER NOT NULL REFERENCES trains(id) ON DELETE CASCADE,
    coach_name TEXT    NOT NULL,
    class_code TEXT    NOT NULL CHECK (class_code IN ('SL', '3A', '2A', '1A')),
    seat_count INTEGER NOT NULL CHECK (seat_count > 0),
    UNIQUE (train_id, coach_name)
);

CREATE TABLE IF NOT EXISTS seats (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    coach_id    INTEGER NOT NULL REFERENCES coaches(id) ON DELETE CASCADE,
    seat_number INTEGER NOT NULL CHECK (seat_number > 0),
    berth_type  TEXT    NOT NULL CHECK (berth_type IN ('LB', 'MB', 'UB', 'SL', 'SU')),
    UNIQUE (coach_id, seat_number)
);

CREATE TABLE IF NOT EXISTS bookings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pnr         TEXT    NOT NULL UNIQUE CHECK (length(pnr) = 10),
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    train_id    INTEGER NOT NULL REFERENCES trains(id) ON DELETE CASCADE,
    class_code  TEXT    NOT NULL CHECK (class_code IN ('SL', '3A', '2A', '1A')),
    travel_date TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'confirmed' CHECK (status IN ('confirmed', 'cancelled')),
    total_fare  INTEGER NOT NULL CHECK (total_fare >= 0),
    booked_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS seat_inventory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    seat_id     INTEGER NOT NULL REFERENCES seats(id) ON DELETE CASCADE,
    travel_date TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'available' CHECK (status IN ('available', 'booked', 'cancelled')),
    booking_id  INTEGER REFERENCES bookings(id) ON DELETE SET NULL,
    UNIQUE (seat_id, travel_date)
);

-- passengers.coach_name, passengers.seat_number and passengers.berth_type are
-- DENORMALIZED copies of the allotted seat at the moment of booking.
-- WHY: a printed ticket must stay immutable. If the coach layout changes, a
-- seat is renumbered, or the booking is later cancelled, the ticket issued for
-- this PNR must still show exactly what was allotted. Joining live tables would
-- make an old ticket change retroactively; copying the values freezes them.
CREATE TABLE IF NOT EXISTS passengers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id  INTEGER NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,
    age         INTEGER NOT NULL CHECK (age BETWEEN 1 AND 120),
    gender      TEXT    NOT NULL CHECK (gender IN ('M', 'F', 'O')),
    coach_name  TEXT,
    seat_number INTEGER,
    berth_type  TEXT    CHECK (berth_type IN ('LB', 'MB', 'UB', 'SL', 'SU'))
);

CREATE INDEX IF NOT EXISTS idx_coaches_train    ON coaches(train_id, class_code);
CREATE INDEX IF NOT EXISTS idx_seats_coach      ON seats(coach_id, seat_number);
CREATE INDEX IF NOT EXISTS idx_inventory_date   ON seat_inventory(travel_date, status);
CREATE INDEX IF NOT EXISTS idx_bookings_pnr     ON bookings(pnr);
CREATE INDEX IF NOT EXISTS idx_passengers_book  ON passengers(booking_id);
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
