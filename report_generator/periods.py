"""
Resolves --period (month|quarter|year) plus a reference date into a
[start_ms, stop_ms) epoch-millisecond window for the *previous complete*
calendar period — e.g. --period month on any day in October returns all of
September.
"""

import calendar
from datetime import datetime, timezone
from typing import Tuple

from dateutil.relativedelta import relativedelta


def _to_ms(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def resolve_period(period: str, reference: datetime = None) -> Tuple[int, int, str]:
    """Returns (start_ms, stop_ms, label) for the previous complete period."""
    ref = reference or datetime.utcnow()

    if period == "month":
        first_of_this_month = ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start = first_of_this_month - relativedelta(months=1)
        stop = first_of_this_month
        label = start.strftime("%Y-%m")

    elif period == "quarter":
        current_quarter = (ref.month - 1) // 3
        first_of_this_quarter = ref.replace(
            month=current_quarter * 3 + 1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
        start = first_of_this_quarter - relativedelta(months=3)
        stop = first_of_this_quarter
        q = (start.month - 1) // 3 + 1
        label = f"{start.year}-Q{q}"

    elif period == "year":
        first_of_this_year = ref.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        start = first_of_this_year - relativedelta(years=1)
        stop = first_of_this_year
        label = str(start.year)

    else:
        raise ValueError(f"Unknown period: {period!r} (expected month, quarter, or year)")

    return _to_ms(start), _to_ms(stop), label
