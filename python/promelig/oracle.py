"""Oracle date and NULL semantics, emulated exactly.

The reporting extract this package replaces is Oracle PL/SQL, and two of its
built-ins do not behave the way PostgreSQL or Python do. Both are reproduced
here, in one place, because every month count in the extract goes through them:

``MONTHS_BETWEEN``
    Whole months when the two dates share a day-of-month or are both the last
    day of their month; otherwise the remainder is expressed in 31ths of a
    month, regardless of the actual length of either month.

``GREATEST``
    Propagates NULL. The PostgreSQL built-in ignores NULL inputs and Python's
    ``max`` raises, so neither can stand in for it (DIV-6 depends on the NULL
    reaching the output).

``ROUND``
    Oracle rounds halves away from zero. Python's ``round`` is round-half-even,
    so ``Decimal`` quantization is used instead.

The same emulation is written in PL/pgSQL in
``tests/sql/sp_promotion_eligibility_pg.sql`` as ``ORACLE_MONTHS_BETWEEN`` and
``ORACLE_GREATEST``; the two are checked against each other by
``tests/test_python_sql_extract.py``.
"""

from __future__ import annotations

import calendar
import datetime as dt
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

DAYS_PER_ORACLE_MONTH = Decimal(31)


def is_last_day_of_month(value: dt.date) -> bool:
    return value.day == calendar.monthrange(value.year, value.month)[1]


def months_between(d1: dt.date, d2: dt.date) -> Decimal:
    """Oracle ``MONTHS_BETWEEN(d1, d2)``: signed, fractional months in 31ths."""
    whole = Decimal((d1.year - d2.year) * 12 + (d1.month - d2.month))
    if d1.day == d2.day or (is_last_day_of_month(d1) and is_last_day_of_month(d2)):
        return whole
    return whole + Decimal(d1.day - d2.day) / DAYS_PER_ORACLE_MONTH


def round_half_away_from_zero(value: Decimal) -> int:
    """Oracle ``ROUND(value)`` to whole units."""
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def greatest(a: Optional[int], b: Optional[int]) -> Optional[int]:
    """Oracle ``GREATEST``: NULL in, NULL out."""
    if a is None or b is None:
        return None
    return max(a, b)


def months_between_rounded(d1: Optional[dt.date], d2: Optional[dt.date]) -> Optional[int]:
    """``ROUND(MONTHS_BETWEEN(d1, d2))``, NULL-propagating like the SQL it replaces."""
    if d1 is None or d2 is None:
        return None
    return round_half_away_from_zero(months_between(d1, d2))
