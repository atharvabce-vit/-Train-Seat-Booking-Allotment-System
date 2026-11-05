# Train Seat Booking & Seat Allotment System

A Flask + SQLite (stdlib `sqlite3`, no ORM) application where users search trains,
book N seats in a chosen class (SL / 3A / 2A / 1A), get an **auto-allotted** seat
(contiguous preferred, fallback to any available), receive a unique **10-digit PNR**
and a printable ticket, and can later check PNR status or cancel the booking.

**End-to-end flow:** Search trains → Results → pick Class (fare shown) → Fare
breakdown → Confirm (mock, no payment gateway) → PNR + printable ticket.

Deliberately out of scope: real payment gateway, login/auth (a simple name +
email field identifies the booker), chart preparation, and distributed locks —
concurrency is handled by a single SQLite transaction (`BEGIN IMMEDIATE`).

## 1. Folder / file tree

```
train-booking-system/
├── README.md                     # Project overview, setup and design notes
├── requirements.txt              # Python dependencies (Flask, pytest)
├── config.py                     # DB path, fare table, booking limits and window
├── db.py                         # Connection helper + full SQL schema (create_tables)
├── seed.py                       # Creates tables and seeds sample users/trains/coaches/seats
├── app.py                        # Flask app: search, book, ticket, PNR status, cancel
├── models/
│   ├── __init__.py               # Marks models as a package
│   ├── trains.py                 # Train/coach lookups and route search queries
│   ├── booking.py                # Seat allotment (contiguous + fallback) and booking/cancel
│   ├── pnr.py                    # Unique 10-digit PNR generation + PNR lookups
│   └── fare.py                   # Fare calculation from FARE_TABLE
├── templates/
│   ├── base.html                 # Shared layout, nav bar and flash messages
│   ├── search.html               # Source/destination/date search form and results
│   ├── book.html                 # Passenger entry form (max 6) and class selection
│   ├── ticket.html               # Printable e-ticket with allotted coach/seat/berth
│   └── pnr_status.html           # PNR status lookup, passenger list and cancel action
├── static/
│   └── style.css                 # Styling incl. print styles for the ticket
└── tests/
    ├── test_allotment.py         # Contiguous/fallback allotment, limits, cancellation
    └── test_concurrency.py       # Parallel bookings never double-book a seat
```

## 2. Setup

```bash
cd train-booking-system
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python db.py      # creates train_booking.db + schema
python seed.py    # seeds sample users, trains, coaches and seats
python app.py     # runs the app at http://localhost:5000
```

Run the tests:

```bash
pytest -v
```

## 3. Database schema

Full `CREATE TABLE` statements live in `create_tables(conn)` in `db.py`.

Tables: `users`, `trains`, `coaches`, `seats`, `bookings`, `seat_inventory`, `passengers`.

Key rules:

- `coaches.class_code` and `bookings.class_code` are constrained to `('SL','3A','2A','1A')`.
- `seat_inventory.status` is `('available','booked','cancelled')`.
- `bookings.status` is `('confirmed','cancelled')`.
- `passengers.age` must be between `1` and `120`; `gender` is `('M','F','O')`;
  `berth_type` is `('LB','MB','UB','SL','SU')`.
- `bookings.pnr` must be exactly 10 characters and is UNIQUE.
- `seat_inventory` has `UNIQUE (seat_id, travel_date)` — this is the hard guarantee
  that one physical seat cannot be sold twice on the same date.
- Foreign keys use `ON DELETE CASCADE` (coaches → trains, seats → coaches,
  bookings → users/trains, passengers → bookings, seat_inventory → seats) and
  `seat_inventory.booking_id` uses `ON DELETE SET NULL`.

### Denormalized columns (and why)

`passengers.coach_name`, `passengers.seat_number` and `passengers.berth_type` are
**copies** of the allotted seat, written at booking time instead of being joined
live from `seats`/`coaches`.

**Why:** a ticket must be immutable. If coach/seat layout changes, a seat is
renumbered, or the booking is later cancelled, an already-issued ticket for that
PNR must still show exactly what was allotted. Copying the values freezes the
ticket; joining live tables would silently rewrite history.

## 4. Seat allotment logic

For a `(train, class, travel_date)` the system loads every seat with no
`seat_inventory` row (or one whose status is `available`/`cancelled`), ordered by
coach then seat number:

1. **Contiguous preferred** — scan each coach for a run of consecutive seat
   numbers long enough for the group; the first such run wins, keeping the group
   in a single coach.
2. **Fallback** — if no contiguous run exists, allocate the next best available
   seats anywhere in the class.
3. If fewer seats exist than passengers, the booking is rejected.

## 5. Concurrency

Each booking runs inside `BEGIN IMMEDIATE` (a write lock is taken before the
availability read), with `PRAGMA foreign_keys = ON`, WAL journaling and a
`busy_timeout`. Combined with `UNIQUE (seat_id, travel_date)`, two simultaneous
requests for the same seat cannot both succeed — the loser re-reads and picks the
next free seat, or fails with "not enough seats". `tests/test_concurrency.py`
verifies this with parallel threads against a shared database file.

## 6. Formulas

### Availability

For a train `T`, class `C` and travel date `D`:

```
total_seats(T, C)   = SUM(coaches.seat_count)
                      WHERE train_id = T AND class_code = C

occupied(T, C, D)   = COUNT(seat_inventory)
                      JOIN seats   ON seats.id   = seat_inventory.seat_id
                      JOIN coaches ON coaches.id = seats.coach_id
                      WHERE coaches.train_id   = T
                        AND coaches.class_code = C
                        AND seat_inventory.travel_date = D
                        AND seat_inventory.status     = 'booked'

available(T, C, D)  = total_seats(T, C) - occupied(T, C, D)

occupancy_pct(T,C,D) = occupied(T, C, D) / total_seats(T, C) * 100
```

A seat counts as **free** when it has no `seat_inventory` row for `D` at all, or
when its row status is `available` / `cancelled`. Rows are written lazily on the
first booking, so a never-touched seat has no row and is implicitly free.
Cancelling only flips the row to `cancelled` (and clears `booking_id`), which is
exactly why those seats come back into the `available` count.

In code: `models.trains.total_seats()` gives `total_seats(T, C)` and
`models.booking.get_available_seats()` / `seat_availability_count()` give
`available(T, C, D)`. The booking page shows `available / total` and the free
percentage using this formula.

### Fare

```
base_fare(C)  = FARE_TABLE[C]
total_fare    = base_fare(C) * number_of_passengers
```

Flat, per-passenger and distance-independent: `SL = Rs 500`, `3A = Rs 1200`,
`2A = Rs 1800`, `1A = Rs 2500`. The same amount is shown on the booking page
before the user confirms and stored on `bookings.total_fare`. No payment gateway
is involved — the Confirm step is a mock confirmation that immediately issues the
PNR.

## 7. Configuration (`config.py`)

| Setting | Value |
| --- | --- |
| `DB_PATH` | `train_booking.db` |
| `FARE_TABLE` | `SL: 500, 3A: 1200, 2A: 1800, 1A: 2500` (per passenger) |
| `MAX_PASSENGERS_PER_PNR` | `6` |
| `BOOKING_WINDOW_DAYS` | `30` |

Run the server on a custom port with the `PORT` environment variable (default
`5000`), e.g. `set PORT=5001 && python app.py`.
