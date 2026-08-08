"""Promotion eligibility decision logic.

A like-for-like port of the PROCEDURE DIVISION of ``cobol/PROMELIG.cbl``
(paragraphs 2000-PROCESS through 2500-WRITE-ELIG). It is pure: no files, no
clock, no database, so the rules can be exercised directly.

Where the COBOL is wrong the port is wrong the same way; every such place names
its DEF/DIV id. Nothing here may be "corrected" outside a behavior-change PR --
see docs/testing.md.

This deliberately duplicates :mod:`promelig.eligibility`, the port of the Java
web tier: the two engines do not agree today (DIV-2 truncation vs rounding,
DIV-3 TIG base date, DIV-5 missing requirement), so one module cannot serve both
without picking a winner. Collapsing them into one is the whole point of the
divergence-resolution PR, and until then a shared module would silently decide
the question.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

from .cobol_copybook import MasterDate

# WS-GRADE-TBL: minimum time in grade / time in service by target grade.
# Duplicated in REF_GRADE_REQUIREMENTS; the two are expected to agree.
GRADE_REQUIREMENTS: dict[int, tuple[int, int]] = {
    2: (6, 12),
    3: (12, 24),
    4: (24, 36),
    5: (36, 48),
    6: (48, 72),
    7: (72, 120),
    8: (96, 168),
    9: (120, 216),
}

# 2300-LOOKUP-MINIMUMS primes the minimums with 999 and leaves them there when
# SEARCH finds no row, so a target grade with no requirement is always denied
# for time in grade (DIV-5: the web tier treats a missing row as no minimum).
NO_REQUIREMENT = (999, 999)

# WS-ADV-LOOKBACK-MOS. Raised from 12 to 24 in 2011; the reporting extract was
# not updated at the time (DIV-1 / DEF-9).
ADV_LOOKBACK_MOS = 24

# WS-MAX-GRADE. A Marine already at or above this grade is bypassed entirely --
# no eligibility record is written for them at all (DIV-4).
MAX_GRADE = 9

NON_PROMOTABLE_DUTY_STATUS = frozenset({"PS", "CF", "AW"})
RESERVE_COMPONENT = "R"
DRILLING_STATUS = "S"


@dataclass(frozen=True)
class MarineRecord:
    """One MARINE-MASTER record, in copybook terms.

    Dates are ``None`` when the underlying CCYYMMDD field is unpopulated, which
    the fixed-width feed represents as zeros.
    """

    edipi: int
    grade: str
    grade_num: int
    dt_last_promo: Optional[MasterDate] = None
    dt_orig_promo: Optional[MasterDate] = None
    grade_eff_dt: Optional[MasterDate] = None
    pebd: Optional[MasterDate] = None
    dt_enlist: Optional[MasterDate] = None
    red_in_grade_ind: str = "N"
    brk_svc_mos: int = 0
    adv_matl_ind: str = "N"
    adv_matl_mos: int = 0
    duty_stat: str = "AC"
    component: str = "A"
    rc_drill_stat: str = " "

    @property
    def was_reduced(self) -> bool:
        return self.red_in_grade_ind == "Y"

    @property
    def non_promotable(self) -> bool:
        return self.duty_stat in NON_PROMOTABLE_DUTY_STATUS

    @property
    def has_adverse_material(self) -> bool:
        return self.adv_matl_ind == "Y"

    @property
    def is_reserve(self) -> bool:
        return self.component == RESERVE_COMPONENT


@dataclass(frozen=True)
class Decision:
    """One ELIG-REC, before it is rendered to the fixed-width output."""

    edipi: int
    grade: str
    tgt_grade: int
    tig_mos: int
    tis_mos: int
    eligible: bool
    deny_reason: str = ""

    @property
    def elig_ind(self) -> str:
        return "Y" if self.eligible else "N"


def month_difference(run_date: dt.date, base: Optional[MasterDate]) -> int:
    """2150-MONTH-DIFF: whole months from ``base`` to ``run_date``.

    Partial months truncate -- a Marine whose anniversary day has not been
    reached in the current month does not get credit for it -- and a base date
    in the future floors at zero (DIV-2: the web tier rounds any partial month
    up, the extract rounds to nearest).

    The base date is not validated, because the COBOL does not validate it: it
    redefines eight digits into CCYY/MM/DD and computes on whatever they hold.
    An unpopulated field is year 0 month 0; a corrupt one such as ``20241332``
    is month 13 day 32. Either yields a month count -- reported as its low-order
    digits (DEF-4) -- rather than an error that would end the run.
    """
    base_year, base_month, base_day = (base.year, base.month, base.day) if base else (0, 0, 0)
    months = ((run_date.year * 12) + run_date.month) - ((base_year * 12) + base_month)
    if run_date.day < base_day:
        months -= 1
    return max(months, 0)


def compute_time_in_grade(record: MarineRecord, run_date: dt.date) -> int:
    """2100-COMPUTE-TIG.

    REV 02 2001: a Marine who was reduced in grade and subsequently restored
    accrues time in grade from the original promotion date, not the restoration
    date. Directed behavior, not a defect. When that date is missing the COBOL
    falls through to the enlistment date and credits the Marine with their
    entire career (DIV-3, unresolved -- do not adopt the web tier's
    MM-GRADE-EFF-DT here).
    """
    base = record.dt_orig_promo if record.was_reduced else record.dt_last_promo
    if base is None:
        base = record.dt_enlist

    tig_mos = month_difference(run_date, base)
    if record.brk_svc_mos > 0:
        tig_mos -= record.brk_svc_mos
    return max(tig_mos, 0)


def compute_time_in_service(record: MarineRecord, run_date: dt.date) -> int:
    """2200-COMPUTE-TIS: months since the pay entry base date."""
    return month_difference(run_date, record.pebd)


def lookup_minimums(target_grade: int) -> tuple[int, int]:
    """2300-LOOKUP-MINIMUMS: (minimum TIG, minimum TIS) for the target grade."""
    return GRADE_REQUIREMENTS.get(target_grade, NO_REQUIREMENT)


def apply_rules(record: MarineRecord, tig_mos: int, tis_mos: int,
                min_tig: int, min_tis: int) -> str:
    """2400-APPLY-RULES: the first failing rule wins; '' means eligible.

    The order is the precedence: status, adverse material, time in grade, time
    in service, drill status.
    """
    if record.non_promotable:
        return "STAT"
    if record.has_adverse_material and record.adv_matl_mos < ADV_LOOKBACK_MOS:
        return "ADVM"
    if tig_mos < min_tig:
        return "TIG"
    if tis_mos < min_tis:
        return "TIS"
    # Reserve drill status check. Active component bypasses.
    if record.is_reserve and record.rc_drill_stat != DRILLING_STATUS:
        return "DRIL"
    return ""


def evaluate(record: MarineRecord, run_date: dt.date) -> Optional[Decision]:
    """2000-PROCESS for one record; ``None`` is the grade >= 9 bypass.

    The bypass writes no eligibility record at all, so the top grade is simply
    absent from the board slate rather than reported as ineligible (DIV-4).
    """
    if record.grade_num >= MAX_GRADE:
        return None

    target_grade = record.grade_num + 1
    tig_mos = compute_time_in_grade(record, run_date)
    tis_mos = compute_time_in_service(record, run_date)
    min_tig, min_tis = lookup_minimums(target_grade)
    deny_reason = apply_rules(record, tig_mos, tis_mos, min_tig, min_tis)

    return Decision(
        edipi=record.edipi,
        grade=record.grade,
        tgt_grade=target_grade,
        tig_mos=tig_mos,
        tis_mos=tis_mos,
        eligible=not deny_reason,
        deny_reason=deny_reason,
    )
