from config import (
    CHILD_CONCESSION_PCT,
    CHILD_MAX_AGE,
    DISTANCE_SLABS,
    FARE_TABLE,
    GST_PCT,
    INFANT_CONCESSION_PCT,
    INFANT_MAX_AGE,
    PER_KM_RATE,
    PREMIUM_TATKAL_PREMIUM_PCT,
    REFUND_RULES,
    RESERVATION_CHARGE,
    SENIOR_AGE,
    SENIOR_CONCESSION_PCT,
    SUPERFAST_CHARGE,
    TATKAL_PREMIUM_PCT,
)

# Quota premium over the normal fare, applied on the whole ticket.
QUOTA_PREMIUM_PCT = {"TQ": TATKAL_PREMIUM_PCT, "PT": PREMIUM_TATKAL_PREMIUM_PCT}


def distance_charge(class_code, distance_km):
    """Telescopic slab charge, the way real fare tables work: the first 100 km
    cost the full per-km rate, the next slab a little less, and so on, so the
    marginal cost of an extra kilometre falls as the journey gets longer."""
    rate = PER_KM_RATE[class_code]
    charge = 0.0
    covered = 0
    remaining = max(0, distance_km)
    for cap, factor in DISTANCE_SLABS:
        span = min(remaining, cap - covered)
        if span <= 0:
            break
        charge += span * rate * factor
        remaining -= span
        covered = cap
        if remaining <= 0:
            break
    return charge


def base_fare(class_code, distance_km):
    """Class base fare plus the flat reservation and superfast charges, before
    GST and any quota premium."""
    return (
        FARE_TABLE[class_code]
        + distance_charge(class_code, distance_km)
        + RESERVATION_CHARGE[class_code]
        + SUPERFAST_CHARGE[class_code]
    )


def fare_per_passenger(class_code, distance_km, quota="GN"):
    amount = base_fare(class_code, distance_km)
    amount += amount * GST_PCT.get(class_code, 0) / 100
    premium = QUOTA_PREMIUM_PCT.get(quota, 0)
    if premium:
        amount *= 1 + premium / 100
    return int(round(amount))


def concession_percent(age):
    """How much of the base fare an age group is exempt from."""
    try:
        age = int(age)
    except (TypeError, ValueError):
        return 0
    if age <= INFANT_MAX_AGE:
        return INFANT_CONCESSION_PCT
    if age <= CHILD_MAX_AGE:
        return CHILD_CONCESSION_PCT
    if age >= SENIOR_AGE:
        return SENIOR_CONCESSION_PCT
    return 0


def passenger_fare(class_code, distance_km, quota, age):
    """Return (fare_after_concession, concession_percent) for one passenger."""
    base = fare_per_passenger(class_code, distance_km, quota)
    percent = concession_percent(age)
    return int(round(base * (100 - percent) / 100)), percent


def calculate_fare(class_code, distance_km, num_passengers, quota="GN"):
    return fare_per_passenger(class_code, distance_km, quota) * num_passengers


def calculate_fare_with_concessions(class_code, distance_km, quota, ages):
    """Total fare plus the amount waived, honouring age-based concessions."""
    base = fare_per_passenger(class_code, distance_km, quota)
    total = 0
    waived = 0
    breakdown = []
    for age in ages:
        fare, percent = passenger_fare(class_code, distance_km, quota, age)
        total += fare
        waived += base - fare
        breakdown.append({"fare": fare, "concession_percent": percent})
    return total, waived, breakdown


def refund_percent(hours_before_departure):
    for threshold, percent in REFUND_RULES:
        if hours_before_departure > threshold:
            return percent
    return 0


def refund_amount(total_fare, hours_before_departure):
    percent = refund_percent(hours_before_departure)
    return int(round(total_fare * percent / 100)), percent
