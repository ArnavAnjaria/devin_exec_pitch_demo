"""Lookup ports for the determination, plus in-memory adapters.

The service depends on these protocols rather than on a database, which is what
keeps ``eligibility.py`` free of I/O.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Optional, Protocol

from .model import GradeRequirement, MarineMaster

# REF_GRADE_REQUIREMENTS, duplicated in PROMELIG.cbl WORKING-STORAGE.
# Grade 1 deliberately has no row: see DIV-5.
GRADE_REQUIREMENTS: Mapping[int, GradeRequirement] = {
    grade: GradeRequirement(grade, min_tig, min_tis)
    for grade, (min_tig, min_tis) in {
        2: (6, 12),
        3: (12, 24),
        4: (24, 36),
        5: (36, 48),
        6: (48, 72),
        7: (72, 120),
        8: (96, 168),
        9: (120, 216),
    }.items()
}


class GradeRequirementRepository(Protocol):
    def for_grade(self, grade_num: int) -> Optional[GradeRequirement]:
        """The requirement row for a target grade, or ``None`` when there is none."""


class MarineMasterRepository(Protocol):
    def find_by_edipi(self, edipi: int) -> Optional[MarineMaster]:
        """The master record for an EDIPI, or ``None`` when it is unknown."""


class InMemoryGradeRequirementRepository:
    """Backed by a mapping; a missing grade returns ``None``, as a single-row
    JDBC lookup does."""

    def __init__(self, requirements: Optional[Mapping[int, GradeRequirement]] = None) -> None:
        self._requirements = dict(GRADE_REQUIREMENTS if requirements is None else requirements)

    def for_grade(self, grade_num: int) -> Optional[GradeRequirement]:
        return self._requirements.get(grade_num)


class InMemoryMarineMasterRepository:
    def __init__(self, masters: Iterable[MarineMaster] = ()) -> None:
        self._by_edipi = {master.edipi: master for master in masters}

    def find_by_edipi(self, edipi: int) -> Optional[MarineMaster]:
        return self._by_edipi.get(edipi)

    def all_edipis(self) -> list[int]:
        return list(self._by_edipi)
