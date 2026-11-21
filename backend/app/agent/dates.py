"""Spoken date phrases -> a timezone-aware datetime (pure, deterministic).

Never guesses: if no date phrase is present, returns None so the assistant can ask.
Weekday names mean the next such day after today ("Friday" said on a Friday = next week's).
"""

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for m in names
}
_NUMBERS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
}
_NUM = r"(\d{1,2}|" + "|".join(_NUMBERS) + r")"
_MONTH = "(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")"


def _n(word: str) -> int:
    return int(word) if word.isdigit() else _NUMBERS[word]


def _next_weekday(today: date, weekday: int) -> date:
    ahead = (weekday - today.weekday()) % 7
    return today + timedelta(days=ahead or 7)


def parse_spoken_date(
    text: str, now: datetime, default_time: time = time(18, 0)
) -> datetime | None:
    """`now` must be timezone-aware (the organization's local time)."""
    t = re.sub(r"[^\w\s]", " ", text.lower())
    t = re.sub(r"\s+", " ", t)
    today = now.date()
    day: date | None = None

    if re.search(r"\bday after tomorrow\b", t):
        day = today + timedelta(days=2)
    elif re.search(r"\btomorrow\b", t):
        day = today + timedelta(days=1)
    elif re.search(r"\b(?:today|tonight|end of (?:the )?day)\b", t):
        day = today
    elif re.search(r"\bend of (?:the |this )?week\b", t):
        day = _next_weekday(today, 4) if today.weekday() != 4 else today
    elif re.search(r"\bnext week\b", t):
        day = today + timedelta(days=7)
    elif m := re.search(
        rf"\b(?:in )?{_NUM} (?:more |extra |additional )?(day|days|week|weeks)\b", t
    ):
        n = _n(m.group(1))
        day = today + timedelta(days=n * (7 if m.group(2).startswith("week") else 1))
    elif m := re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)? (?:of )?{_MONTH}\b", t):
        day = _month_day(today, _MONTHS[m.group(2)], int(m.group(1)))
    elif m := re.search(rf"\b{_MONTH} (\d{{1,2}})(?:st|nd|rd|th)?\b", t):
        day = _month_day(today, _MONTHS[m.group(1)], int(m.group(2)))
    else:
        for i, name in enumerate(_WEEKDAYS):
            if re.search(rf"\b{name}\b", t):
                day = _next_weekday(today, i)
                break
    if day is None:
        return None
    return datetime.combine(day, default_time, tzinfo=now.tzinfo)


def _month_day(today: date, month: int, dom: int) -> date | None:
    for year in (today.year, today.year + 1):
        try:
            d = date(year, month, dom)
        except ValueError:
            return None
        if d >= today:
            return d
    return None


def local_now(tz: str) -> datetime:
    return datetime.now(ZoneInfo(tz))


def spoken(dt: datetime, tz: str) -> str:
    """'Friday 27 November at 6 PM' in the given timezone."""
    local = dt.astimezone(ZoneInfo(tz))
    hour = local.strftime("%I:%M %p").lstrip("0").replace(":00", "")
    return f"{local.strftime('%A')} {local.day} {local.strftime('%B')} at {hour}"
