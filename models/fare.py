from config import (
    CHILD_CONCESSION_PCT,
    CHILD_MAX_AGE,
    FARE_TABLE,
    INFANT_CONCESSION_PCT,
    INFANT_MAX_AGE,
    PER_KM_RATE,
    REFUND_RULES,
    SENIOR_AGE,
    SENIOR_CONCESSION_PCT,
    TATKAL_PREMIUM_PCT,
)


def fare_per_passenger(class_code, distance_km, quota="GN"):
    amount = FARE_TABLE[class_code] + PER_KM_RATE[class_code] * max(0, distance_km)
    if quota == "TQ":
        amount *= 1 + TATKAL_PREMIUM_PCT / 100
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

