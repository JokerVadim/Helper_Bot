"""Time parsing utilities."""
import calendar
import re
from datetime import datetime, timedelta

REPEAT_LABELS = {
    "none": "одноразовое",
    "daily": "ежедневное",
    "monthly": "ежемесячное",
    "yearly": "ежегодное",
}
REPEAT_ICONS = {
    "none": "🔔",
    "daily": "🔁",
    "monthly": "📅",
    "yearly": "🎂",
}


def _repeat_label(repeat_type: str) -> str:
    return REPEAT_LABELS.get(repeat_type or "none", "одноразовое")


def _repeat_icon(repeat_type: str) -> str:
    return REPEAT_ICONS.get(repeat_type or "none", "🔔")


def _format_reminder_time(r: dict) -> str:
    if r.get("delivered"):
        return "сработало"
    t = r["time"]
    now = datetime.now()
    if t.date() == now.date():
        return t.strftime("%H:%M")
    elif t.date() == (now + timedelta(days=1)).date():
        return f"завтра {t.strftime('%H:%M')}"
    else:
        return t.strftime("%d.%m %H:%M")

TIME_RE = re.compile(r'^(\d{1,2}):(\d{2})$')
DELTA_RE = re.compile(r'^(?:(\d+)h)?(?:(\d+)m)?$', re.IGNORECASE)


def parse_duration_seconds(arg: str) -> int | None:
    arg = arg.strip().lower()
    if arg.isdigit():
        return int(arg)

    m = DELTA_RE.match(arg)
    if not m or not (m.group(1) or m.group(2)):
        return None

    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    seconds = hours * 3600 + minutes * 60
    return seconds if seconds > 0 else None


def _next_month(year: int, month: int) -> tuple[int, int]:
    month += 1
    if month > 12:
        return year + 1, 1
    return year, month


def _safe_datetime(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    day = min(day, calendar.monthrange(year, month)[1])
    return datetime(year, month, day, hour, minute)


def next_repeat_time(current: datetime, repeat_type: str, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now()
    repeat_type = repeat_type or "none"
    if repeat_type == "daily":
        nxt = current + timedelta(days=1)
        while nxt <= now:
            nxt += timedelta(days=1)
        return nxt
    if repeat_type == "monthly":
        year, month = current.year, current.month
        while True:
            year, month = _next_month(year, month)
            nxt = _safe_datetime(year, month, current.day, current.hour, current.minute)
            if nxt > now:
                return nxt
    if repeat_type == "yearly":
        year = current.year
        while True:
            year += 1
            nxt = _safe_datetime(year, current.month, current.day, current.hour, current.minute)
            if nxt > now:
                return nxt
    return None


def parse_reminder_time_arg(arg: str, repeat_type: str) -> datetime | None:
    now = datetime.now()
    arg = arg.strip().lower()
    repeat_type = repeat_type or "none"

    if repeat_type == "daily":
        m = re.search(r'(\d{1,2}):(\d{2})', arg)
        if not m:
            return None
        hour, minute = int(m.group(1)), int(m.group(2))
        if hour > 23 or minute > 59:
            return None
        dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return dt + timedelta(days=1) if dt <= now else dt

    if repeat_type == "monthly":
        m = re.search(r'(\d{1,2})(?:\s*числа)?\D+(\d{1,2}):(\d{2})', arg)
        if m:
            day, hour, minute = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if day < 1 or day > 31 or hour > 23 or minute > 59:
                return None
            dt = _safe_datetime(now.year, now.month, day, hour, minute)
            if dt <= now:
                year, month = _next_month(now.year, now.month)
                dt = _safe_datetime(year, month, day, hour, minute)
            return dt

    if repeat_type == "yearly":
        m = re.search(r'(\d{1,2})\.(\d{1,2}).*?(\d{1,2}):(\d{2})', arg)
        if m:
            day, month, hour, minute = map(int, m.groups())
            if month < 1 or month > 12 or day < 1 or day > 31 or hour > 23 or minute > 59:
                return None
            try:
                dt = _safe_datetime(now.year, month, day, hour, minute)
            except ValueError:
                return None
            if dt <= now:
                dt = _safe_datetime(now.year + 1, month, day, hour, minute)
            return dt

    return parse_time_arg(arg)


def parse_clock(text: str) -> tuple[int, int] | None:
    m = re.search(r'(\d{1,2}):(\d{2})', text.strip())
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def next_daily_at(hour: int, minute: int) -> datetime:
    now = datetime.now()
    dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return dt + timedelta(days=1) if dt <= now else dt


def next_monthly_at(day: int, hour: int, minute: int) -> datetime:
    now = datetime.now()
    dt = _safe_datetime(now.year, now.month, day, hour, minute)
    if dt <= now:
        year, month = _next_month(now.year, now.month)
        dt = _safe_datetime(year, month, day, hour, minute)
    return dt


def next_yearly_at(day: int, month: int, hour: int, minute: int) -> datetime:
    now = datetime.now()
    dt = _safe_datetime(now.year, month, day, hour, minute)
    if dt <= now:
        dt = _safe_datetime(now.year + 1, month, day, hour, minute)
    return dt


def describe_when(fire_at: datetime) -> str:
    now = datetime.now()
    if fire_at.date() == now.date():
        return fire_at.strftime("%H:%M")
    if fire_at.date() == (now + timedelta(days=1)).date():
        return f"завтра в {fire_at.strftime('%H:%M')}"
    return fire_at.strftime("%d.%m в %H:%M")


def parse_time_arg(arg: str) -> datetime | None:
    now = datetime.now()
    arg = arg.strip().lower()

    time_match = re.search(r'(\d{1,2}):(\d{2})', arg)
    if time_match:
        time_part = (int(time_match.group(1)), int(time_match.group(2)))
        arg_without_time = arg[:time_match.start()].strip()
    else:
        time_part = None
        arg_without_time = arg

    date_part = None
    date_match = re.search(r'(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?', arg_without_time)
    if date_match:
        day   = int(date_match.group(1))
        month = int(date_match.group(2))
        year  = int(date_match.group(3)) if date_match.group(3) else now.year
        try:
            date_part = now.replace(year=year, month=month, day=day)
        except ValueError:
            return None
    elif "послезавтра" in arg_without_time:
        date_part = now + timedelta(days=2)
    elif "завтра" in arg_without_time:
        date_part = now + timedelta(days=1)
    elif "сегодня" in arg_without_time:
        date_part = now

    if time_part:
        h, mn = time_part
        if h > 23 or mn > 59:
            return None
        base = date_part if date_part else now
        dt = base.replace(hour=h, minute=mn, second=0, microsecond=0)
        if dt <= now:
            dt += timedelta(days=1)
        return dt

    m = DELTA_RE.match(arg)
    if m and (m.group(1) or m.group(2)):
        hours   = int(m.group(1) or 0)
        minutes = int(m.group(2) or 0)
        if hours == 0 and minutes == 0:
            return None
        return now + timedelta(hours=hours, minutes=minutes)

    if arg.isdigit():
        return now + timedelta(seconds=int(arg))

    return None
