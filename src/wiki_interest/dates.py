"""Month/day helpers. Months are "YYYY-MM" strings, days are datetime.date or "YYYY-MM-DD"."""

from __future__ import annotations

import calendar
import datetime as dt
import re

MONTH_RE = re.compile(r"(\d{4})-(0[1-9]|1[0-2])")


def parse_month(s: str) -> tuple[int, int]:
    m = MONTH_RE.fullmatch(s)
    if not m:
        raise ValueError(f"not a YYYY-MM month: {s!r}")
    return int(m.group(1)), int(m.group(2))


def month_str(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def add_months(month: str, n: int) -> str:
    y, m = parse_month(month)
    idx = y * 12 + (m - 1) + n
    return month_str(idx // 12, idx % 12 + 1)


def first_day(month: str) -> dt.date:
    y, m = parse_month(month)
    return dt.date(y, m, 1)


def last_day(month: str) -> dt.date:
    y, m = parse_month(month)
    return dt.date(y, m, calendar.monthrange(y, m)[1])


def window_shift_years(months: int) -> int:
    """Whole years between a window and its base: at least the window's length, so the base never
    overlaps the window (a 24-month window a year back would share a year with it and understate the
    change), and a multiple of 12 months, so the same calendar months are compared (no seasonality)."""
    return -(-months // 12)


def window_label(months: int, shift_years: int, lang: str) -> str:
    """"last 24 months vs the previous 24" / "last 18 months vs the same months 2 years earlier"."""
    if shift_years * 12 == months:
        return {"en": f"last {months} months vs the previous {months}",
                "uk": f"останні {months} міс. проти попередніх {months}"}[lang]
    return {"en": f"last {months} months vs the same months {shift_years} year{'s' if shift_years > 1 else ''} earlier",
            "uk": f"останні {months} міс. проти тих самих місяців {shift_years} р. тому"}[lang]


def iso(d: dt.date) -> str:
    return d.isoformat()


def day(s: str) -> dt.date:
    return dt.date.fromisoformat(s[:10])


def gaps(want: tuple[dt.date, dt.date], covered: list[tuple[dt.date, dt.date]]) -> list[tuple[dt.date, dt.date]]:
    """Sub-ranges of `want` (inclusive) not covered by any of `covered` (inclusive)."""
    start, end = want
    out: list[tuple[dt.date, dt.date]] = []
    cursor = start
    for s, e in sorted(covered):
        if e < cursor or s > end:
            continue
        if s > cursor:
            out.append((cursor, min(end, s - dt.timedelta(days=1))))
        cursor = max(cursor, e + dt.timedelta(days=1))
        if cursor > end:
            break
    if cursor <= end:
        out.append((cursor, end))
    return out
