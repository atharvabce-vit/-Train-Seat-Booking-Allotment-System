DB_PATH = "train_booking.db"

CLASS_NAMES = {
    "SL": "Sleeper",
    "3A": "AC 3 Tier",
    "2A": "AC 2 Tier",
    "1A": "AC First Class",
}

QUOTA_NAMES = {
    "GN": "General",
    "TQ": "Tatkal",
    "PT": "Premium Tatkal",
    "LD": "Ladies",
    "SS": "Senior Citizen",
    "DF": "Divyangjan",
    "DP": "Duty Pass",
}

# Every quota draws its seats from one of the two physical pools a coach
# carries: the General pool (every seat that is not a Tatkal seat) or the
# Tatkal pool (the first `tatkal_seats` numbers of the coach). Keeping the
# mapping in one place lets the like-named logical quotas (Ladies, Senior
# Citizen, Premium Tatkal) reuse the existing seat inventory untouched.
QUOTA_POOL = {
    "GN": "GN",
    "LD": "GN",
    "SS": "GN",
    "DF": "GN",
    "DP": "GN",
    "TQ": "TQ",
    "PT": "TQ",
}

BERTH_NAMES = {
    "LB": "Lower",
    "MB": "Middle",
    "UB": "Upper",
    "SL": "Side Lower",
    "SU": "Side Upper",
    "ANY": "No preference",
}

# Fare is charged per passenger and has two parts:
#   fixed base fare for the class + a per-kilometre charge for the distance
#   actually travelled, so a short leg costs less than the full run.
FARE_TABLE = {
    "SL": 300,
    "3A": 700,
    "2A": 1000,
    "1A": 1500,
}

PER_KM_RATE = {
    "SL": 0.35,
    "3A": 0.85,
    "2A": 1.20,
    "1A": 1.90,
}

# Distance is charged through telescopic slabs, the way the real fare tables
# work: the first 100 km cost the full per-km rate, the next slab a little
# less, and so on, so the marginal cost of a kilometre falls with distance.
DISTANCE_SLABS = [
    (100, 1.00),
    (300, 0.85),
    (500, 0.70),
    (1000, 0.55),
    (float("inf"), 0.45),
]

# Flat charges added to every ticket, per class.
RESERVATION_CHARGE = {"SL": 20, "3A": 40, "2A": 50, "1A": 60}
SUPERFAST_CHARGE = {"SL": 30, "3A": 45, "2A": 45, "1A": 45}

# GST is levied on air-conditioned classes only (sleeper is exempt).
GST_PCT = {"SL": 0, "3A": 5, "2A": 5, "1A": 5}

MAX_PASSENGERS_PER_PNR = 6

# Advance Reservation Period - how far ahead a journey can be booked.
BOOKING_WINDOW_DAYS = 60

TATKAL_PREMIUM_PCT = 30

# Premium Tatkal is priced dynamically and carries a steeper premium.
PREMIUM_TATKAL_PREMIUM_PCT = 50

# Tatkal booking opens on the previous day at 10:00 IST for AC classes and
# 11:00 IST for non-AC classes, and stays open until the train departs.
TATKAL_OPEN_HOUR_AC = 10
TATKAL_OPEN_HOUR_NON_AC = 11

SENIOR_AGE = 58

# Concession: percentage of the base fare waived, picked by passenger age.
INFANT_MAX_AGE = 4
INFANT_CONCESSION_PCT = 100
CHILD_MAX_AGE = 11
CHILD_CONCESSION_PCT = 50
SENIOR_CONCESSION_PCT = 30

# Reschedule / date change fee (percentage of the paid fare, with a floor).
RESCHEDULE_FEE_PCT = 10
RESCHEDULE_FEE_MIN = 50

# Round-trip bookings get this discount off the return leg.
ROUND_TRIP_DISCOUNT_PCT = 5

RAC_LIMIT = 10

HOLD_TTL_SECONDS = 600

# A train's chart is prepared this many hours before departure: RAC and
# waitlisted bookings are finalised and online booking closes.
CHART_LEAD_HOURS = 4

# REST API guard: token required for writes, N requests per window per token.
API_RATE_LIMIT = 60
API_RATE_WINDOW = 60
DEFAULT_API_TOKEN = "demo-token-123"

LOG_LEVEL = "INFO"

# (hours still left before departure, refund percent). The first rule whose
# threshold the booking still clears is the one that applies.
REFUND_RULES = [
    (48, 90),
    (24, 75),
    (12, 50),
    (4, 25),
    (0, 0),
]

# Flat clerkage retained per passenger when an RAC or waitlisted ticket is
# cancelled - these never had a confirmed seat, so the fare is refunded in
# full minus this charge instead of the percentage ladder above.
CLERKAGE_PER_PASSENGER = 60

ADMIN_KEY = "railyatra-admin"

DEFAULT_PAYMENT_METHOD = "MOCK"

PAYMENT_METHODS = ["MOCK", "UPI", "CARD", "NETBANKING"]

# Typo-tolerant station search kicks in only after the exact query finds
# nothing; 0.6 tolerates a transposition or a missing vowel (mumbay -> Mumbai).
FUZZY_STATION_THRESHOLD = 0.6

# The exact berth is withheld from the booker until the booking is paid for.
# Showing it at the payment step lets someone cancel and re-hold repeatedly to
# map out (and game) the seat-allotment pattern, so we keep it hidden there and
# reveal it only on the confirmed e-ticket.
REVEAL_SEATS_BEFORE_PAYMENT = False
