from datetime import date, datetime, timedelta, timezone

DATE_FORMAT = "%Y-%m-%d"
STAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

# Indian Standard Time never observes daylight saving, so a fixed UTC+5:30
# offset is exact and avoids depending on a system tz database (which Windows
# does not ship).
IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def now_utc():
    """Current instant in UTC - used for every stored timestamp."""
    return datetime.now(timezone.utc)


def now_ist():
    """Current instant in IST - used for journey and booking-window rules."""
    return datetime.now(IST)


def today_ist():
    """The current calendar date in India, which is what a rail booking cares
    about (a train that departs at 00:30 IST belongs to an IST day)."""
    return now_ist().date()


def now_str():
    return now_utc().strftime(STAMP_FORMAT)


def minutes_of(time_text):
    hours, minutes = time_text.split(":")
    return int(hours) * 60 + int(minutes)


def parse_date(value):
    try:
        return datetime.strptime(value, DATE_FORMAT).date()
    except (TypeError, ValueError):
        return None


def parse_time(value):
    try:
        return datetime.strptime(value, "%H:%M").time()
    except (TypeError, ValueError):
        return None


def booking_dates(days):
    today = today_ist()
    return [today + timedelta(days=offset) for offset in range(days + 1)]


def journey_minutes(from_day, from_time, to_day, to_time):
    start = from_day * 1440 + minutes_of(from_time)
    end = to_day * 1440 + minutes_of(to_time)
    return max(0, end - start)


def format_duration(total_minutes):
    return f"{total_minutes // 60}h {total_minutes % 60:02d}m"


def describe_time(day_offset, time_text):
    if not time_text:
        return "--"
    return f"{time_text} (+{day_offset}d)" if day_offset else time_text
