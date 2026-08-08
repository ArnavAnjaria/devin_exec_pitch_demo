"""Month arithmetic as the web tier does it.

``EligibilityService.monthsBetween`` counts whole months and then rounds any
partial month up, so a Marine one week short of an anniversary is credited with
the month they are about to complete. The COBOL batch truncates and the Oracle
extract rounds to nearest; that three-way split is DIV-2 and is preserved here,
not reconciled.
"""

from __future__ import annotations

import calendar
import datetime as dt


def add_months(base: dt.date, months: int) -> dt.date:
    """``base`` shifted by ``months``, clamping the day to the target month.

    Matches ``java.time.LocalDate.plusMonths``, which resolves 31 January plus
    one month to 28 (or 29) February rather than overflowing into March.
    """
    total = base.year * 12 + (base.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    return dt.date(year, month, min(base.day, calendar.monthrange(year, month)[1]))


def whole_months_between(start: dt.date, end: dt.date) -> int:
    """Whole months between two dates, truncated toward zero.

    ``ChronoUnit.MONTHS.between`` packs the day of month into the low bits and
    divides, which truncates rather than floors; a start date after the end date
    therefore counts down toward zero instead of away from it.
    """
    packed_start = (start.year * 12 + start.month) * 32 + start.day
    packed_end = (end.year * 12 + end.month) * 32 + end.day
    delta = packed_end - packed_start
    return -(-delta // 32) if delta < 0 else delta // 32


def months_between_rounded_up(start: dt.date, end: dt.date) -> int:
    """Whole months between two dates with any partial month rounded up (DIV-2)."""
    months = whole_months_between(start, end)
    if add_months(start, months) < end:
        months += 1
    return months
