from datetime import date, datetime, timedelta, timezone

DATE_FORMAT = "%Y-%m-%d"
STAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def now_utc():
    return datetime.now(timezone.utc)


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
    today = date.today()
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
