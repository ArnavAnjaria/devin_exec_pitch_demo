"""Normalized result rows.

Every engine emits the same six columns so that goldens and the cross-engine
equivalence report compare like with like. Engine-specific formatting quirks
(COBOL's 4-byte padded deny reasons, the SQL extract's NULL deny reason) are
normalized here; behavioral differences are deliberately preserved.
"""

from __future__ import annotations

import csv
from dataclasses import astuple, dataclass
from pathlib import Path
from typing import Iterable, Optional

COLUMNS = ("edipi", "tgt_grade", "tig_mos", "tis_mos", "elig_ind", "deny_rsn")

# Minimum time in grade / time in service by target grade. Duplicated today in
# PROMELIG.cbl WORKING-STORAGE and in REF_GRADE_REQUIREMENTS; the harness keeps
# one copy and asserts the others match it.
GRADE_REQUIREMENTS = {
    2: (6, 12),
    3: (12, 24),
    4: (24, 36),
    5: (36, 48),
    6: (48, 72),
    7: (72, 120),
    8: (96, 168),
    9: (120, 216),
}


@dataclass(frozen=True, order=True)
class Row:
    edipi: int
    tgt_grade: int
    tig_mos: int
    tis_mos: int
    elig_ind: str
    deny_rsn: str

    @staticmethod
    def make(edipi: int, tgt_grade: int, tig_mos: int, tis_mos: int,
             elig_ind: str, deny_rsn: Optional[str]) -> "Row":
        return Row(
            edipi=int(edipi),
            tgt_grade=int(tgt_grade),
            tig_mos=int(tig_mos),
            tis_mos=int(tis_mos),
            elig_ind=elig_ind.strip().upper(),
            deny_rsn=(deny_rsn or "").strip().upper(),
        )


def write_rows(path: Path, rows: Iterable[Row]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(COLUMNS)
        for row in sorted(rows):
            writer.writerow(astuple(row))


def read_rows(path: Path) -> list[Row]:
    with path.open(newline="") as fh:
        return sorted(
            Row.make(r["edipi"], r["tgt_grade"], r["tig_mos"], r["tis_mos"],
                     r["elig_ind"], r["deny_rsn"])
            for r in csv.DictReader(fh)
        )
