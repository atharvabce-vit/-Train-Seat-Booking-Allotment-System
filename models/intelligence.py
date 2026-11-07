"""Decision helpers that make the app feel smarter than a plain CRUD screen.

Three small models live here, each kept pure and cheap so they are trivial to
test:

* :func:`demand_index` / :func:`surge_multiplier` / :func:`dynamic_fare` - how
  full a leg is, and the surge that occupancy justifies. Premium Tatkal is the
  natural place for it, but the numbers are exposed for every quota.
* :func:`waitlist_confidence` - a sharper play on the old ad-hoc
  ``confirmation_probability``: it factors in RAC vs waitlist, the queue
  position *and* how many days are still left before departure.

Typo-tolerant station lookup lives next to the other station helpers in
``models.trains``; it is pure string work, so it does not belong here.
"""
from models.trains import available_count, quota_seat_count

# (occupancy ceiling, surge percent). The first ceiling the index clears wins,
# so a half-empty train is never surcharged.
SURGE_STEPS = [
    (0.50, 0),
    (0.75, 5),
    (0.90, 15),
    (1.00, 25),
]


def demand_index(conn, train_id, class_code, travel_date, from_seq, to_seq, quota="GN"):
    """Fraction of the quota's seats already taken on this leg, 0.0 - 1.0."""
    total = quota_seat_count(conn, train_id, class_code, quota)
    if total <= 0:
        return 0.0
    free = available_count(conn, train_id, class_code, travel_date, from_seq, to_seq, quota)
    taken = max(0, total - free)
    return round(taken / total, 4)


def surge_multiplier(index):
    """Price multiplier (1.0 = no surge) that this occupancy justifies."""
    for ceiling, percent in SURGE_STEPS:
        if index <= ceiling:
            return 1 + percent / 100
    return 1 + SURGE_STEPS[-1][1] / 100


def dynamic_fare(base_fare, index):
    """The base fare nudged by the demand surge, rounded to whole rupees."""
    return int(round(base_fare * surge_multiplier(index)))


def demand_label(index):
    if index >= 0.90:
        return "Very high demand"
    if index >= 0.75:
        return "High demand"
    if index >= 0.50:
        return "Filling fast"
    return "Available"


def demand_summary(conn, train_id, class_code, travel_date, from_seq, to_seq, quota="GN", base_fare=0):
    index = demand_index(conn, train_id, class_code, travel_date, from_seq, to_seq, quota)
    return {
        "demand_index": index,
        "demand_label": demand_label(index),
        "surge_multiplier": surge_multiplier(index),
        "base_fare": base_fare,
        "dynamic_fare": dynamic_fare(base_fare, index),
    }


def waitlist_confidence(booking, days_left=None):
    """A 0-100 chance that an RAC/waitlisted booking ends up confirmed.

    RAC tickets almost always get a berth and only taper as the RAC position
    grows; waitlisted tickets lean far more on other passengers cancelling, so
    their odds fall away much faster with the queue position. When ``days_left``
    is known, plenty of time left is a small tailwind (more cancellations can
    still free a seat) and a departure tomorrow is a headwind.
    """
    status = booking["status"]
    if status == "confirmed":
        return 100
    if status == "cancelled":
        return 0

    position = booking["queue_position"] or 1
    if status == "rac":
        base = max(55, 97 - (position - 1) * 3)
    else:
        base = max(1, 72 - position * 4)

    if days_left is not None:
        if days_left >= 7:
            base += 8
        elif days_left >= 3:
            base += 4
        elif days_left <= 1:
            base -= 10
    return max(0, min(99, int(round(base))))
