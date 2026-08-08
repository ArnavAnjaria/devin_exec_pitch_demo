"""Records the web-tier determination reads and writes.

The Java originals (``MarineMaster``, ``EligibilityResult``, ``GradeRequirement``)
were reconstructed from call sites, so this is a redesign rather than a
transliteration: immutable dataclasses instead of builders, an enum outcome, and
``None`` for the dates the feed leaves unpopulated.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum
from typing import Optional

# MM-NON-PROMOTABLE in cobol/copybook/MARREC.cpy: pending separation, confined, AWOL.
NON_PROMOTABLE_DUTY_STATUSES = frozenset({"PS", "CF", "AW"})

RESERVE_COMPONENT = "R"

# The only Reserve drill status that permits promotion.
DRILLING_STATUS = "S"


class Outcome(Enum):
    ELIGIBLE = "ELIGIBLE"
    DENIED = "DENIED"
    BYPASS = "BYPASS"
    NOT_FOUND = "NOT_FOUND"


@dataclass(frozen=True)
class GradeRequirement:
    """Minimum time in grade and time in service for a target grade.

    Mirrors REF_GRADE_REQUIREMENTS, duplicated in PROMELIG.cbl WORKING-STORAGE
    (WS-GRADE-TBL) and in the web tier's own lookup.
    """

    grade_num: int
    min_tig_mos: int
    min_tis_mos: int


@dataclass(frozen=True)
class MarineMaster:
    """One MARINE_MASTER record as the web tier sees it."""

    edipi: int
    grade: str = ""
    grade_num: int = 0
    date_of_last_promotion: Optional[dt.date] = None
    date_of_original_promotion: Optional[dt.date] = None
    grade_effective_date: Optional[dt.date] = None
    pebd: Optional[dt.date] = None
    date_of_enlistment: Optional[dt.date] = None
    reduced_in_grade: bool = False
    break_in_service_months: int = 0
    adverse_material: bool = False
    adverse_material_months: int = 0
    duty_status: str = "AC"
    component: str = "A"
    drill_status: Optional[str] = None

    @property
    def non_promotable(self) -> bool:
        return self.duty_status in NON_PROMOTABLE_DUTY_STATUSES

    @property
    def reserve_component(self) -> bool:
        return self.component == RESERVE_COMPONENT


@dataclass(frozen=True)
class EligibilityResult:
    """Outcome of one determination.

    ``target_grade``, ``tig_months`` and ``tis_months`` are zero for the
    outcomes the service reaches before computing them (bypass, not found).
    """

    edipi: int
    outcome: Outcome
    target_grade: int = 0
    tig_months: int = 0
    tis_months: int = 0
    deny_reason: Optional[str] = None

    @property
    def eligible(self) -> bool:
        return self.outcome is Outcome.ELIGIBLE

    @classmethod
    def not_found(cls, edipi: int) -> "EligibilityResult":
        return cls(edipi=edipi, outcome=Outcome.NOT_FOUND)

    @classmethod
    def bypass(cls, edipi: int, reason: str) -> "EligibilityResult":
        return cls(edipi=edipi, outcome=Outcome.BYPASS, deny_reason=reason)

    @classmethod
    def denied(cls, edipi: int, target_grade: int, tig_months: int,
               tis_months: int, deny_reason: str) -> "EligibilityResult":
        return cls(edipi=edipi, outcome=Outcome.DENIED, target_grade=target_grade,
                   tig_months=tig_months, tis_months=tis_months, deny_reason=deny_reason)

    @classmethod
    def eligible_for(cls, edipi: int, target_grade: int, tig_months: int,
                     tis_months: int) -> "EligibilityResult":
        return cls(edipi=edipi, outcome=Outcome.ELIGIBLE, target_grade=target_grade,
                   tig_months=tig_months, tis_months=tis_months)
