from config import FARE_TABLE, PER_KM_RATE, REFUND_RULES, TATKAL_PREMIUM_PCT


def fare_per_passenger(class_code, distance_km, quota="GN"):
    amount = FARE_TABLE[class_code] + PER_KM_RATE[class_code] * max(0, distance_km)
    if quota == "TQ":
        amount *= 1 + TATKAL_PREMIUM_PCT / 100
    return int(round(amount))


def calculate_fare(class_code, distance_km, num_passengers, quota="GN"):
    return fare_per_passenger(class_code, distance_km, quota) * num_passengers


def refund_percent(hours_before_departure):
    for threshold, percent in REFUND_RULES:
        if hours_before_departure > threshold:
            return percent
    return 0


def refund_amount(total_fare, hours_before_departure):
    percent = refund_percent(hours_before_departure)
    return int(round(total_fare * percent / 100)), percent
