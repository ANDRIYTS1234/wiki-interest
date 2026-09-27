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
