# Train Seat Booking & Seat Allotment System

A Flask + SQLite (stdlib `sqlite3`, no ORM) railway reservation system. Users
search a route by city, pick a class and quota, the engine **auto-allots** seats
(contiguous preferred, berth preference honoured), a **10-digit PNR** is issued,
and a printable **PDF + QR e-ticket** is generated. Bookings can be looked up by
PNR or e-mail, cancelled (fully or per passenger) with an automatic **refund**, or
rescheduled to a new date. Round trips, age-based concessions, a 30-day fare
calendar and an interactive seat map are all supported, and the whole thing is
also exposed over a **JSON REST API** (token-protected, documented with OpenAPI)
with an **admin dashboard**.

Deliberately out of scope: a real payment gateway (payments are mocked),
login/auth (a name + e-mail identifies the booker), real chart preparation, and
distributed locks — concurrency is handled by SQLite write transactions.

## 1. Feature overview

| Area | What it does |
| --- | --- |
| Part-route booking | Seats are tracked per *leg* `[from_seq, to_seq)`, so the same physical seat can be sold to different passengers on non-overlapping segments. |
| Station search | 26 stations; search any city/station pair that a train actually halts at, not just the endpoints. |
| Distance-based fare | `base(class) + per_km(class) × km` over the travelled leg, with a Tatkal premium. |
| Concessions & child fares | Age-based discount: infant (≤4) 100%, child (≤11) 50%, senior (≥58) 30% — applied per passenger. |
| Round-trip booking | Book outbound + return in one go; both share a `group_id` and the return leg gets a 5% discount. Outbound auto-cancels if the return fails. |
| Partial cancellation | Cancel individual passengers on a PNR; only their share is refunded and the queue is promoted. |
| Reschedule / date change | Move a confirmed booking to a new date/leg for a tiered change fee. |
| Quotas | Every coach is split into **Tatkal (TQ)** and **General (GN)** seat ranges; Tatkal opens 24 h before departure. |
| Seat preference | LB / MB / UB / SL / SU / no preference, plus an automatic **lower berth for seniors (58+)** when no preference is set. |
| Seat holds | Checking out reserves seats for `HOLD_TTL_SECONDS` (10 min) before payment; expired holds are released automatically. |
| Waiting list + RAC | When a class is full the booking joins the **RAC** queue, then the **waiting list**; cancelled seats **promote** the queue FIFO. |
| Refund engine | Cancellation refund is tiered on hours left before departure. |
| Interactive seat map | Per-coach visual grid on the booking page, showing free vs. booked seats for the selected leg/date/quota. |
| 30-day fare calendar | Per-day fare + availability for the whole booking window on the booking page. |
| Checkout stepper | 3-step progress bar (Choose seats → Review & pay → Ticket) across the flow. |
| Wallet pass / `.ics` | Download an `.ics` calendar invite for any ticket (hand-built, no extra dependency). |
| PDF + QR ticket | `reportlab` PDF with a `qrcode` QR pointing at the public verify URL. |
| My Bookings | Every booking for an e-mail address in one list. |
| Notifications outbox | Mocked e-mail/SMS rows are queued for every confirm/cancel/promote. |
| REST API | JSON search / availability / seatmap / book / round-trip / reschedule / PNR / cancel under `/api`, protected by API tokens + rate limiting. |
| OpenAPI / Swagger | Machine-readable OpenAPI 3.0 spec served at `/api/openapi.json`. |
| Admin dashboard | Counts, revenue, refunds, class/quota split, top routes, occupancy (with bar charts), concessions, recent activity, queue snapshot. |
| Admin CRUD | Create/edit trains, halts and coaches from the dashboard. |
| CSV exports | Bookings, refunds and a boarding manifest can be downloaded as CSV. |
| Audit log | Every booking-changing action is recorded and browsable; DB snapshots downloadable as a backup. |
| Migrations | Forward-only migration runner (`migrate.py`) tracking applied versions in `schema_migrations`. |
| Logging + `/healthz` | Structured request logging and a health-check endpoint. |
| Docker + CI | `Dockerfile` and a GitHub Actions workflow running `pytest` + a Docker build. |

## 2. Project layout

```
train-booking-system/
├── config.py               # DB path, fares, quotas, refund rules, limits
├── db.py                   # get_connection() + full SQL schema (create_tables)
├── migrate.py              # forward-only migration runner (schema_migrations)
├── openapi.py              # OpenAPI 3.0 spec served at /api/openapi.json
├── seed.py                 # stations, 10 realistic multi-stop trains, coaches/seats
├── app.py                  # create_app() app factory + logging + /healthz
├── pdf_ticket.py           # reportlab PDF + QR rendering
├── blueprints/
│   ├── main.py             # /, /search, /stations, /schedule/<id>
│   ├── booking.py          # /book, /confirm, /ticket(+.ics), /pnr, /my-bookings,
│   │                       # /cancel, /cancel-passengers, /reschedule, /round-trip
│   ├── api.py              # /api/... JSON endpoints + /api/docs
│   └── admin.py            # /admin dashboard, CRUD, audit log, CSV exports, backup
├── models/
│   ├── trains.py           # search, stops, segment distance, availability
│   ├── booking.py          # hold / allot / confirm / queue / cancel / round-trip / reschedule
│   ├── fare.py             # fare, concessions, refund + reschedule maths
│   ├── pnr.py              # PNR generation + joined lookups
│   ├── reports.py          # admin aggregates (occupancy, concessions)
│   ├── audit.py            # audit-log writes + recent()
│   ├── api_auth.py         # API tokens + sliding-window rate limit
│   ├── cache.py            # small TTL response cache
│   ├── notifications.py    # mocked e-mail/SMS outbox
│   └── util.py             # date/time helpers
├── templates/              # Jinja2 pages (search, book, confirm, ticket, admin…)
├── static/                 # style.css (incl. print styles) + app.js
├── tests/                  # allotment, concurrency, booking flow, fare, API, advanced
├── Dockerfile / .dockerignore / .github/workflows/ci.yml
└── requirements.txt
```

## 3. Setup

```bash
cd train-booking-system
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python db.py      # create train_booking.db + schema
python seed.py    # seed 26 stations, 10 trains, coaches and seats
python app.py     # http://localhost:5000  (override with PORT)
```

Run the tests:

```bash
pytest -q
```

Run in Docker:

```bash
docker build -t railyatra .
docker run -p 5000:5000 railyatra
```

## 4. Database schema

Full `CREATE TABLE` statements live in `create_tables(conn)` in `db.py`.
Tables: `users`, `stations`, `trains`, `train_stops`, `coaches`, `seats`,
`seat_holds`, `bookings`, `seat_inventory`, `passengers`, `payments`,
`refunds`, `notifications`, `audit_log`, `api_tokens`, `booking_changes`,
`schema_migrations`.

Key rules:

- `coaches.class_code` / `bookings.class_code` are constrained to `('SL','3A','2A','1A')`.
- `bookings.status ∈ ('confirmed','rac','waiting','cancelled')`,
  `seat_inventory.status ∈ ('held','booked','cancelled')`, `quota ∈ ('GN','TQ')`.
- `passengers.age` is `1–120`; `gender ∈ ('M','F','O')`; `berth_type ∈ ('LB','MB','UB','SL','SU')`;
  `bookings.trip_type ∈ ('ONE_WAY','ROUND_TRIP')`.
- `bookings.pnr` must be exactly 10 chars and is UNIQUE.
- `train_stops` has `UNIQUE (train_id, seq)` and `UNIQUE (train_id, station_code)`, so a
  halt list is an ordered, gap-checked route.
- `schema_migrations` tracks applied migration versions for the forward-only runner.
- Foreign keys use `ON DELETE CASCADE` (coaches → trains, seats → coaches,
  stops/holds → trains, bookings → users/trains, passengers/payments/refunds →
  bookings, seat_inventory → seats); `seat_inventory.booking_id` and
  `hold_token` use `ON DELETE SET NULL`. `PRAGMA foreign_keys = ON` is set on every
  connection in `get_connection()`.

### Why seats are tracked per leg, not per date

Originally `seat_inventory` had `UNIQUE (seat_id, travel_date)` — one seat, one
date. To sell **part-route** journeys (e.g. Mumbai→Vadodara vs Vadodara→Delhi on
the same coach) each row now stores the leg it covers, and two rows for the same
seat/date conflict **only when their legs overlap**:

```
  si.from_seq < requested_to_seq   AND   requested_from_seq < si.to_seq
```

This is the standard half-open-interval overlap test. A seat is free when no
overlapping `booked` row (or un-expired `held` row) exists for that leg.

### Denormalized columns (and why)

`passengers.coach_name`, `passengers.seat_number` and `passengers.berth_type`
are **copies** of the allotted seat, written at booking time instead of being
joined live from `seats`/`coaches`.

**Why:** a ticket must be immutable. If coach/seat layout changes, a seat is
renumbered, or the booking is later cancelled, an already-issued ticket must
still show exactly what was allotted. Copying the values freezes the ticket;
joining live tables would silently rewrite history.

## 5. Seat allotment logic

For a `(train, class, travel_date, leg, quota)` the engine loads every free seat
in that quota, ordered by coach then seat number, then (`models/booking.py`):

1. **Contiguous preferred** — scan each coach for a run of consecutive seat
   numbers long enough for the party; the first such run wins, keeping the group
   in a single coach.
2. **Berth preference** — if anyone asked for a berth type (or is a senior), look
   for a contiguous block that can satisfy all of them, else scan the whole class.
3. **Fallback** — otherwise allocate the next best free seats anywhere in the class.
4. If fewer seats exist than passengers, the class is full and the booking is
   offered **RAC** first (up to `RAC_LIMIT`), then the **waiting list**.

## 6. Concurrency

Every hold / confirm / cancel / queue action runs inside `BEGIN IMMEDIATE` (a
write lock is taken before the availability read), with `PRAGMA foreign_keys = ON`,
WAL journaling and a `busy_timeout`. Two simultaneous requests can therefore
never both take the same seat for overlapping legs — the loser re-reads and
picks the next free seat, or fails with "not enough seats".
`tests/test_concurrency.py` verifies this with parallel threads on a shared DB file.

## 7. Formulas

### Distance of a leg

```
leg_km(T, from_seq, to_seq) = distance_from_source(to_seq) - distance_from_source(from_seq)
```

### Fare

Charged **per passenger** over the distance actually travelled:

```
fare_per_passenger(class, km, quota)
    = ROUND( ( FARE_TABLE[class] + PER_KM_RATE[class] * km )
             * (1 + TATKAL_PREMIUM_PCT/100 if quota == 'TQ' else 1) )

total_fare = fare_per_passenger(...) * number_of_passengers
```

`FARE_TABLE`: SL 300, 3A 700, 2A 1000, 1A 1500.
`PER_KM_RATE`: SL 0.35, 3A 0.85, 2A 1.20, 1A 1.90. `TATKAL_PREMIUM_PCT = 30`.

### Availability

```
total_seats(T, C, quota) = SUM( CASE WHEN quota='TQ' THEN tatkal_seats
                                     ELSE seat_count - tatkal_seats END )
                           over coaches WHERE train_id = T AND class_code = C

occupied(T, C, D, leg, quota) = COUNT(DISTINCT seat) with a seat_inventory row
                                WHERE train = T, class = C, date = D, quota matches,
                                  legs overlap (si.from_seq < to_seq AND from_seq < si.to_seq),
                                  status = 'booked'
                                  OR (status = 'held' AND hold_expires_at > now)

available(T, C, D, leg, quota) = total_seats(T, C, quota) - occupied(...)
```

A seat counts as free when it has no overlapping `booked` row and no un-expired
`held` row. Cancelling flips rows to `cancelled` (auto-excluded), which is why
those seats reappear in the available count — and why the waiting list moves up.

In code: `models.trains.available_seats()` / `available_count()` implement this;
`models.trains.quota_seat_count()` gives the total.

### Refund

```
refund_percent(hours_left) = first pct in REFUND_RULES whose threshold hours_left clears
refund_amount(total_fare, hours_left) = ROUND(total_fare * refund_percent / 100)
```

`REFUND_RULES` (hours still left before departure → refund):

| Hours before departure | Refund |
| --- | --- |
| > 48 | 90% |
| > 24 | 75% |
| > 12 | 50% |
| > 4 | 25% |
| ≤ 4 | 0% |

### Concessions

```
concession_percent(age) = 100 if age ≤ 4   (infant)
                        = 50  if age ≤ 11  (child)
                        = 30  if age ≥ 58  (senior)
                        = 0   otherwise

passenger_fare(base, age) = ROUND(base * (100 - concession_percent(age)) / 100)
booking_total = Σ passenger_fare(base, age)
```

### Round-trip discount

```
return_leg_fare = ROUND(base_return * (100 - ROUND_TRIP_DISCOUNT_PCT) / 100)
```

Both legs share a `group_id`; the outbound is cancelled automatically if the
return leg fails.

### Reschedule fee

```
change_fee = MAX(RESCHEDULE_FEE_MIN, ROUND(paid_fare * RESCHEDULE_FEE_PCT / 100))
```

### Seat hold / RAC / waitlist

- A hold expires after `HOLD_TTL_SECONDS` (600 s); expired rows are swept away
  before every booking attempt.
- RAC status is given while fewer than `RAC_LIMIT` (10) RAC bookings exist for
  that train/class/date/quota; beyond that the booking is `waiting`.
- On cancellation seats free up and `promote_queue()` moves RAC first, then
  waitlisted bookings, onto them FIFO, renumbering the queue afterwards.

### Booking window & Tatkal

- Travel date must be within `BOOKING_WINDOW_DAYS` (30) days of today.
- Tatkal (`TQ`) bookings only open in the last `TATKAL_WINDOW_HOURS` (24) hours
  before departure; a coach's first `tatkal_seats` seat numbers are the TQ quota.

## 8. Configuration (`config.py`)

| Setting | Value |
| --- | --- |
| `DB_PATH` | `train_booking.db` |
| `FARE_TABLE` | SL 300, 3A 700, 2A 1000, 1A 1500 |
| `PER_KM_RATE` | SL 0.35, 3A 0.85, 2A 1.20, 1A 1.90 |
| `MAX_PASSENGERS_PER_PNR` | 6 |
| `BOOKING_WINDOW_DAYS` | 30 |
| `TATKAL_PREMIUM_PCT` / `TATKAL_WINDOW_HOURS` | 30 / 24 |
| `SENIOR_AGE` | 58 (auto lower berth) |
| `INFANT_MAX_AGE` / `INFANT_CONCESSION_PCT` | 4 / 100 |
| `CHILD_MAX_AGE` / `CHILD_CONCESSION_PCT` | 11 / 50 |
| `SENIOR_CONCESSION_PCT` | 30 |
| `RESCHEDULE_FEE_PCT` / `RESCHEDULE_FEE_MIN` | 10 / 50 |
| `ROUND_TRIP_DISCOUNT_PCT` | 5 |
| `RAC_LIMIT` | 10 |
| `HOLD_TTL_SECONDS` | 600 |
| `REFUND_RULES` | 48→90, 24→75, 12→50, 4→25, 0→0 |
| `API_RATE_LIMIT` / `API_RATE_WINDOW` | 60 / 60 |
| `DEFAULT_API_TOKEN` | `demo-token-123` |
| `LOG_LEVEL` | `INFO` |
| `ADMIN_KEY` | `railyatra-admin` (admin dashboard `?key=`) |

Run on a custom port with the `PORT` environment variable (default `5000`), e.g.
`set PORT=5001 && python app.py`.

## 9. REST API

Writes require an `X-API-Token` header (default demo token `demo-token-123`);
requests are rate-limited to `API_RATE_LIMIT` per `API_RATE_WINDOW` seconds per
token. The full machine-readable spec is at `/api/openapi.json`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/stations?q=` | Station autocomplete |
| GET | `/api/trains` | All trains with endpoints |
| GET | `/api/search?from=&to=` | Trains between two cities |
| GET | `/api/availability?train_id=&cls=&date=&from_seq=&to_seq=&quota=` | Seat counts |
| GET | `/api/seatmap?train_id=&cls=&date=&from_seq=&to_seq=&quota=` | Per-seat map (free/booked) |
| POST | `/api/book` | Create a booking (JSON body) → 201 with `pnr`/`status` |
| POST | `/api/book-round-trip` | Book outbound + return together → 201 with both PNRs |
| POST | `/api/reschedule/<pnr>` | Move a confirmed booking to a new date/leg |
| GET | `/api/pnr/<pnr>` | PNR details (404 if unknown) |
| POST | `/api/cancel/<pnr>` | Cancel + refund → promoted PNRs |
| GET | `/api/openapi.json` | OpenAPI 3.0 document |
| GET | `/api/docs` | Human-readable API reference page |
| GET | `/healthz` | Health check |

Inside the JSON body the class field is named `"class"` (e.g. `{"class": "SL"}`),
while query strings use `cls=` (`class` is a Python reserved word).

## 10. Admin

`/admin/?key=railyatra-admin` shows bookings by status, net revenue, refunds,
class/quota splits, top routes, per-train load, occupancy (bar charts),
concessions and recent activity. From there you can also:

- manage trains (`/admin/trains`) — create/edit a train, its halts and coaches,
- browse the audit log (`/admin/audit`),
- view the notification outbox (`/admin/notifications`),
- download **CSV** exports (bookings, refunds, boarding manifest),
- download a database **backup**.

## 11. Tests

```
tests/test_allotment.py     # contiguous → fallback, berth preference, senior LB,
                            # max 6 pax, window, cancellation, tatkal separation,
                            # part-route sharing
tests/test_concurrency.py   # parallel threads never double-book a seat
tests/test_booking_flow.py  # hold→confirm, expired hold, waitlist promotion, refund
tests/test_fare.py          # distance fare, tatkal premium, refund tiers, segment km
tests/test_api.py           # JSON API + rendered pages + admin key + tokens + OpenAPI
tests/test_advanced.py      # concessions, partial cancel, reschedule, round-trip, audit
```

Run everything with `py -m pytest -q` (Windows) or `pytest -q`.

## 12. Migrations

`migrate.py` applies pending, forward-only migrations and records each version in
the `schema_migrations` table; it runs automatically on app start (`create_app()`),
so an existing database is upgraded in place without losing data.

```
py migrate.py      # apply pending migrations
```
