from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.agent.dates import parse_spoken_date, spoken

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 21, 10, 30, tzinfo=IST)  # a Saturday


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("until tomorrow", "2026-11-22"),
        ("by the day after tomorrow", "2026-11-23"),
        ("today", "2026-11-21"),
        ("until Friday", "2026-11-27"),
        ("till monday please", "2026-11-23"),
        ("by saturday", "2026-11-28"),  # today is Saturday: the next one
        ("next week", "2026-11-28"),
        ("end of the week", "2026-11-27"),
        ("in 3 days", "2026-11-24"),
        ("I need two more days", "2026-11-23"),
        ("one more week", "2026-11-28"),
        ("until 27 November", "2026-11-27"),
        ("by the 5th of December", "2026-12-05"),
        ("december 2nd", "2026-12-02"),
        ("by 10 January", "2027-01-10"),  # already past this year -> next year
    ],
)
def test_spoken_dates_resolve_in_local_time(said, expected):
    d = parse_spoken_date(said, NOW)
    assert d is not None, said
    assert d.date().isoformat() == expected
    assert d.tzinfo == IST and d.time() == time(18, 0)


@pytest.mark.parametrize("said", ["I need more time", "because the API is down", "", "31 February"])
def test_no_date_means_none_never_a_guess(said):
    assert parse_spoken_date(said, NOW) is None


def test_default_time_can_follow_the_current_due_time():
    assert parse_spoken_date("tomorrow", NOW, time(9, 30)).time() == time(9, 30)


def test_spoken_format():
    d = datetime(2026, 11, 27, 18, 0, tzinfo=IST)
    assert spoken(d, "Asia/Kolkata") == "Friday 27 November at 6 PM"
