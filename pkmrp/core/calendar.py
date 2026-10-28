"""Working-day arithmetic. MAX lead times (PURLT_01, MFGLT_01) are working
days, Mon-Fri; plant holidays are passed in when known."""

from datetime import date, datetime, timedelta


def _is_workday(d, holidays):
    return d.weekday() < 5 and d not in holidays


def minus_workdays(d, n, holidays=frozenset()):
    """`d` less `n` working days. n <= 0 returns d unchanged."""
    n = int(round(n or 0))
    while n > 0:
        d -= timedelta(days=1)
        if _is_workday(d, holidays):
            n -= 1
    return d


def plus_workdays(d, n, holidays=frozenset()):
    n = int(round(n or 0))
    while n > 0:
        d += timedelta(days=1)
        if _is_workday(d, holidays):
            n -= 1
    return d


def workdays_between(a, b, holidays=frozenset()):
    """Working days from a (exclusive) to b (inclusive); negative if b < a."""
    if b < a:
        return -workdays_between(b, a, holidays)
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if _is_workday(d, holidays):
            n += 1
    return n


def week_start(d):
    """The Monday of d's week."""
    return d - timedelta(days=d.weekday())


def as_date(v):
    """A date from a date, datetime, pandas Timestamp, or None/NaT/NaN."""
    if v is None:
        return None
    try:
        if v != v:  # NaN and NaT are the only values not equal to themselves
            return None
    except (TypeError, ValueError):
        return None
    if isinstance(v, datetime):  # includes pandas Timestamp
        return v.date()
    if isinstance(v, date):
        return v
    return None
