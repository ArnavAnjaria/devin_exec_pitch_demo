"""Python replacements for the legacy promotion eligibility components.

One module per legacy component, migrated one at a time against the
characterization suite in ``tests/``: each reproduces its engine's current
behavior, bugs and cross-engine divergences included. See ``docs/testing.md``.

* :mod:`promelig.eligibility` -- the web tier's real-time single-record
  determination, from
  ``java/src/main/java/mil/usmc/manpower/promotion/EligibilityService.java``.
* :mod:`promelig.sql_extract` -- ``sql/promotion_eligibility.sql``
  (``SP_PROMOTION_ELIGIBILITY``, the reporting extract).
* :mod:`promelig.unit_diary` -- ``perl/load_unit_diary.pl``.

:mod:`promelig.oracle` holds the Oracle date and NULL semantics the extract
depends on. The two database seams are separate on purpose: :mod:`promelig.db`
reaches PostgreSQL through the ``psql`` client for the extract, while
:mod:`promelig.dbapi` opens a DB-API connection for the loader, which must also
run against SQLite.
"""

from .eligibility import (ADV_LOOKBACK_MOS, MAX_GRADE, EligibilityError,
                          EligibilityService, MissingDateError,
                          MissingGradeRequirementError)
from .model import EligibilityResult, GradeRequirement, MarineMaster, Outcome
from .repositories import (GRADE_REQUIREMENTS, InMemoryGradeRequirementRepository,
                           InMemoryMarineMasterRepository)

__all__ = [
    "ADV_LOOKBACK_MOS",
    "MAX_GRADE",
    "EligibilityError",
    "EligibilityResult",
    "EligibilityService",
    "GRADE_REQUIREMENTS",
    "GradeRequirement",
    "InMemoryGradeRequirementRepository",
    "InMemoryMarineMasterRepository",
    "MarineMaster",
    "MissingDateError",
    "MissingGradeRequirementError",
    "Outcome",
    "copybook",
    "db",
    "dbapi",
    "oracle",
    "sql_extract",
    "unit_diary",
]
