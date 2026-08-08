"""Flat CSV view of the corpus.

The Java suite reads this instead of the YAML so the Maven build needs no YAML
dependency. Free-text fields (note, tags) are deliberately excluded so the file
never needs quoting.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .model import Corpus

SCENARIO_COLUMNS = (
    "id", "edipi", "grade", "grade_num",
    "dt_last_promo", "dt_orig_promo", "grade_eff_dt", "pebd", "dt_enlist",
    "red_in_grade_ind", "brk_svc_mos", "adv_matl_ind", "adv_matl_mos",
    "duty_stat", "component", "rc_drill_stat",
)

CSV_NAME = "scenarios.csv"
AS_OF_NAME = "as_of.txt"


def dump_scenario_csv(corpus: Corpus, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / CSV_NAME
    with target.open("w", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(SCENARIO_COLUMNS)
        for scenario in corpus.scenarios:
            row = []
            for column in SCENARIO_COLUMNS:
                value = getattr(scenario, column)
                row.append(value.strip() if isinstance(value, str) else value)
            writer.writerow(row)
    (directory / AS_OF_NAME).write_text(corpus.as_of.isoformat() + "\n")
    return target
