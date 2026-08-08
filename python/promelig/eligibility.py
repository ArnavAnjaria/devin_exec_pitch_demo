"""Real-time promotion eligibility for the self-service web front end.

Python replacement for
``java/src/main/java/mil/usmc/manpower/promotion/EligibilityService.java``, the
single-record lookup the web tier calls. It computes independently of the
nightly batch, which is why it disagrees with it; the disagreements are recorded
in ``tests/divergences.yaml`` and are reproduced here rather than resolved.

Behavior deliberately preserved:

* DIV-2 -- partial months round up (``monthmath``), where the batch truncates.
* DIV-3 -- time in grade accrues from the grade effective date and the reduction
  indicator is never consulted.
* DIV-4 -- grade 9 is a ``MAXG`` bypass; the batch writes no record at all.
* DIV-5 -- a target grade with no requirement row fails the determination
  instead of denying or skipping. The Java service dereferences a null
  ``GradeRequirement``; this raises :class:`MissingGradeRequirementError`.

Nothing here reads a file or a database: the two repository ports are the only
way data gets in.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from .model import (DRILLING_STATUS, EligibilityResult, GradeRequirement,
                    MarineMaster)
from .monthmath import months_between_rounded_up
from .repositories import GradeRequirementRepository, MarineMasterRepository

MAX_GRADE = 9

#: Adverse material lookback, in months. 12 in the reporting extract (DIV-1).
ADV_LOOKBACK_MOS = 24


class EligibilityError(Exception):
    """A determination that cannot be completed from the data on hand."""


class MissingGradeRequirementError(EligibilityError):
    """No REF_GRADE_REQUIREMENTS row exists for the target grade (DIV-5).

    The Java service has no check here and dereferences null, so the web tier
    returns a 500. Raising a named exception at the same point keeps that
    observable outcome -- a failed determination, not a denial and not a
    silently dropped record -- without pretending the miss was anticipated.
    DIV-5 is unresolved, so choosing a deny reason here would be a behavior
    change smuggled into a migration.
    """

    def __init__(self, edipi: int, target_grade: int) -> None:
        super().__init__(
            f"no grade requirement for target grade {target_grade} (edipi {edipi})")
        self.edipi = edipi
        self.target_grade = target_grade


class MissingDateError(EligibilityError):
    """A date the determination has to have is not populated.

    Only reachable for MM-PEBD: every time-in-grade base date has a fallback.
    The Java service dereferences null here too.
    """

    def __init__(self, edipi: int, field: str) -> None:
        super().__init__(f"{field} is not populated (edipi {edipi})")
        self.edipi = edipi
        self.field = field


class EligibilityService:
    """The determination. Construct it with the two lookups it needs."""

    def __init__(self, grade_repo: GradeRequirementRepository,
                 master_repo: MarineMasterRepository) -> None:
        self._grade_repo = grade_repo
        self._master_repo = master_repo

    def determine(self, edipi: int, as_of: dt.date) -> EligibilityResult:
        master = self._master_repo.find_by_edipi(edipi)
        if master is None:
            return EligibilityResult.not_found(edipi)
        return self.evaluate(master, as_of)

    def evaluate(self, master: MarineMaster, as_of: dt.date) -> EligibilityResult:
        """Decide for a record already in hand. Pure: no lookups but the grade table."""
        edipi = master.edipi
        if master.grade_num >= MAX_GRADE:
            return EligibilityResult.bypass(edipi, "MAXG")

        target_grade = master.grade_num + 1
        requirement = self._grade_repo.for_grade(target_grade)

        tig_months = self._time_in_grade(master, as_of)
        tis_months = self._time_in_service(master, as_of)

        # Denial precedence: status, adverse material, TIG, TIS, drill status.
        if master.non_promotable:
            return EligibilityResult.denied(edipi, target_grade, tig_months, tis_months, "STAT")
        if master.adverse_material and master.adverse_material_months < ADV_LOOKBACK_MOS:
            return EligibilityResult.denied(edipi, target_grade, tig_months, tis_months, "ADVM")

        # The Java service dereferences the requirement here, which is why a
        # non-promotable Marine at an unknown grade is denied rather than 500ing.
        if requirement is None:
            raise MissingGradeRequirementError(edipi, target_grade)

        if tig_months < requirement.min_tig_mos:
            return EligibilityResult.denied(edipi, target_grade, tig_months, tis_months, "TIG")
        if tis_months < requirement.min_tis_mos:
            return EligibilityResult.denied(edipi, target_grade, tig_months, tis_months, "TIS")
        if master.reserve_component and master.drill_status != DRILLING_STATUS:
            return EligibilityResult.denied(edipi, target_grade, tig_months, tis_months, "DRIL")

        return EligibilityResult.eligible_for(edipi, target_grade, tig_months, tis_months)

    def requirement_for(self, target_grade: int) -> Optional[GradeRequirement]:
        return self._grade_repo.for_grade(target_grade)

    def _time_in_grade(self, master: MarineMaster, as_of: dt.date) -> int:
        """Time in grade, in whole months, net of any break in service.

        The base date is the grade effective date, which only the web feed
        maintains, falling back to the last promotion date and then to
        enlistment. The batch prefers the original promotion date for a
        reduced-then-restored Marine; this never looks at the reduction
        indicator (DIV-3).
        """
        base = (master.grade_effective_date
                or master.date_of_last_promotion
                or master.date_of_enlistment)
        if base is None:
            raise MissingDateError(master.edipi, "date of enlistment")
        months = months_between_rounded_up(base, as_of) - master.break_in_service_months
        return max(months, 0)

    def _time_in_service(self, master: MarineMaster, as_of: dt.date) -> int:
        if master.pebd is None:
            raise MissingDateError(master.edipi, "PEBD")
        return max(months_between_rounded_up(master.pebd, as_of), 0)
