"""Run the Python replacement for the web tier over the corpus.

``python/promelig`` is the rewrite of ``EligibilityService.java``. It is driven
here exactly as the Java suite drives the original -- one determination per
scenario, in EDIPI order -- and normalized the same way, so ``python_web.csv``
and ``java.csv`` are directly comparable.
"""

from __future__ import annotations

import sys

from ..model import REPO_ROOT, Corpus, Scenario, to_date
from ..normalize import Row

sys.path.insert(0, str(REPO_ROOT / "python"))

from promelig import (EligibilityError, EligibilityService,  # noqa: E402
                      InMemoryGradeRequirementRepository,
                      InMemoryMarineMasterRepository, MarineMaster, Outcome)

ELIG_INDICATOR = {
    Outcome.ELIGIBLE: "Y",
    Outcome.DENIED: "N",
    Outcome.BYPASS: "B",
    Outcome.NOT_FOUND: "X",
}


def to_master(scenario: Scenario) -> MarineMaster:
    """The scenario as the web tier's master record."""
    drill_status = scenario.rc_drill_stat.strip()
    return MarineMaster(
        edipi=scenario.edipi,
        grade=scenario.grade,
        grade_num=scenario.grade_num,
        date_of_last_promotion=to_date(scenario.dt_last_promo),
        date_of_original_promotion=to_date(scenario.dt_orig_promo),
        grade_effective_date=to_date(scenario.grade_eff_dt),
        pebd=to_date(scenario.pebd),
        date_of_enlistment=to_date(scenario.dt_enlist),
        reduced_in_grade=scenario.red_in_grade_ind == "Y",
        break_in_service_months=scenario.brk_svc_mos,
        adverse_material=scenario.adv_matl_ind == "Y",
        adverse_material_months=scenario.adv_matl_mos,
        duty_status=scenario.duty_stat.strip(),
        component=scenario.component.strip(),
        drill_status=drill_status or None,
    )


def service(corpus: Corpus) -> EligibilityService:
    return EligibilityService(
        InMemoryGradeRequirementRepository(),
        InMemoryMarineMasterRepository(to_master(s) for s in corpus.scenarios))


def to_row(result) -> Row:
    if result.outcome in (Outcome.BYPASS, Outcome.NOT_FOUND):
        # The bypass carries MAXG (DIV-4); an unknown EDIPI carries NOTF.
        reason = result.deny_reason or "NOTF"
        return Row.make(result.edipi, 0, 0, 0, ELIG_INDICATOR[result.outcome], reason)
    return Row.make(result.edipi, result.target_grade, result.tig_months,
                    result.tis_months, ELIG_INDICATOR[result.outcome], result.deny_reason)


def run(corpus: Corpus) -> list[Row]:
    determine = service(corpus).determine
    rows = []
    for scenario in corpus.scenarios:
        try:
            rows.append(to_row(determine(scenario.edipi, corpus.as_of)))
        except EligibilityError:
            # DIV-5: the Java service dereferences the missing GradeRequirement
            # and NormalizedRow records the NullPointerException as E/NPE. The
            # rewrite raises a named exception at the same point; both mean the
            # determination failed on absent reference data, so both normalize
            # to the same row.
            rows.append(Row.make(scenario.edipi, 0, 0, 0, "E", "NPE"))
        except Exception:
            # Mirrors NormalizedRow's catch of any other RuntimeException.
            rows.append(Row.make(scenario.edipi, 0, 0, 0, "E", "ERR"))
    return sorted(rows)
