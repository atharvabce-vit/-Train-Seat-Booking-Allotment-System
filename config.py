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

MAX_PASSENGERS_PER_PNR = 6

BOOKING_WINDOW_DAYS = 30

TATKAL_PREMIUM_PCT = 30

TATKAL_WINDOW_HOURS = 24

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

ADMIN_KEY = "railyatra-admin"

DEFAULT_PAYMENT_METHOD = "MOCK"

PAYMENT_METHODS = ["MOCK", "UPI", "CARD", "NETBANKING"]
