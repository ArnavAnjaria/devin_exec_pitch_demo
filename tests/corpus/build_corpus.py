#!/usr/bin/env python3
"""Generate tests/corpus/scenarios.yaml.

The corpus is generated rather than hand-written so the threshold cases stay in
step with the grade requirement table, and is checked in so that a change to it
shows up as a reviewable diff. ``test_corpus.py`` fails if the checked-in file
does not match a fresh generation.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.model import (  # noqa: E402
    CORPUS_PATH, Corpus, Scenario, as_yyyymmdd, dump_corpus, shift_months)
from harness.normalize import GRADE_REQUIREMENTS  # noqa: E402
from harness.scenario_csv import dump_scenario_csv  # noqa: E402

AS_OF = dt.date(2026, 6, 15)

GRADE_NAMES = {
    1: "PVT", 2: "PFC", 3: "LCP", 4: "CPL", 5: "SGT",
    6: "SSG", 7: "GYS", 8: "MSG", 9: "MGY",
}

# Comfortably above every minimum, so the axis under test is the only binding one.
SLACK_MOS = 400


class EdipiAllocator:
    def __init__(self, start: int = 1000000000) -> None:
        self._next = start

    def __call__(self) -> int:
        self._next += 1
        return self._next


def _promo_date(months_ago: int, day: int | None = None) -> int:
    return as_yyyymmdd(shift_months(AS_OF, -months_ago, day))


def make(alloc: EdipiAllocator, scenario_id: str, note: str, grade_num: int,
         tig_mos: int, tis_mos: int, tags: list[str], **overrides) -> Scenario:
    """Build a scenario whose truncated TIG/TIS are exactly the values given.

    Anniversary day equals the run day, so truncating (COBOL) and rounding up
    (Java) agree; scenarios that target that divergence set the day explicitly.
    """
    last_promo = _promo_date(tig_mos)
    pebd = _promo_date(tis_mos)
    defaults = dict(
        grade=GRADE_NAMES[grade_num],
        grade_num=grade_num,
        dt_last_promo=last_promo,
        grade_eff_dt=last_promo,
        pebd=pebd,
        dt_enlist=pebd,
    )
    defaults.update(overrides)
    return Scenario(id=scenario_id, note=note, edipi=alloc(), tags=tags, **defaults)


def threshold_scenarios(alloc: EdipiAllocator) -> list[Scenario]:
    """min-1 / min / min+1 on each axis, for every target grade."""
    out: list[Scenario] = []
    for target_grade, (min_tig, min_tis) in sorted(GRADE_REQUIREMENTS.items()):
        current = target_grade - 1
        if current not in GRADE_NAMES:
            continue
        for delta, label in ((-1, "below"), (0, "at"), (1, "above")):
            out.append(make(
                alloc, f"tig-{target_grade:02d}-{label}",
                f"target grade {target_grade}: TIG {min_tig + delta} vs minimum {min_tig}",
                current, min_tig + delta, SLACK_MOS, ["threshold", "tig"],
            ))
            out.append(make(
                alloc, f"tis-{target_grade:02d}-{label}",
                f"target grade {target_grade}: TIS {min_tis + delta} vs minimum {min_tis}",
                current, SLACK_MOS, min_tis + delta, ["threshold", "tis"],
            ))
    return out


def precedence_scenarios(alloc: EdipiAllocator) -> list[Scenario]:
    """Deny-reason precedence: STAT > ADVM > TIG > TIS > DRIL."""
    out = []
    for duty in ("PS", "CF", "AW"):
        out.append(make(
            alloc, f"stat-{duty.lower()}", f"non-promotable duty status {duty}",
            5, 400, 400, ["precedence", "stat"], duty_stat=duty,
        ))
    out.append(make(
        alloc, "stat-beats-everything",
        "trips STAT, ADVM, TIG, TIS and DRIL at once",
        5, 0, 0, ["precedence"],
        duty_stat="AW", adv_matl_ind="Y", adv_matl_mos=1,
        component="R", rc_drill_stat="N",
    ))
    out.append(make(
        alloc, "advm-beats-tig", "adverse material and short TIG",
        5, 0, 400, ["precedence"], adv_matl_ind="Y", adv_matl_mos=3,
    ))
    out.append(make(
        alloc, "tig-beats-tis", "short on both TIG and TIS",
        5, 0, 0, ["precedence"],
    ))
    out.append(make(
        alloc, "tis-beats-dril", "reserve, not drilling, and short TIS",
        5, 400, 0, ["precedence"], component="R", rc_drill_stat="N",
    ))
    return out


def adverse_scenarios(alloc: EdipiAllocator) -> list[Scenario]:
    """Straddles the COBOL/Java 24-month lookback and the SQL 12-month one."""
    out = []
    for months in (0, 11, 12, 23, 24, 25):
        out.append(make(
            alloc, f"advm-{months:02d}mo",
            f"adverse material {months} months old (SQL lookback 12, COBOL/Java 24)",
            5, 400, 400, ["adverse"], adv_matl_ind="Y", adv_matl_mos=months,
        ))
    out.append(make(
        alloc, "advm-indicator-off",
        "adverse material months populated but indicator not set",
        5, 400, 400, ["adverse"], adv_matl_ind="N", adv_matl_mos=1,
    ))
    return out


def reduction_scenarios(alloc: EdipiAllocator) -> list[Scenario]:
    """The COBOL reduction rule vs the Java grade-effective-date rule."""
    out = []
    out.append(make(
        alloc, "reduced-with-orig-promo",
        "reduced then restored: COBOL accrues TIG from the original promotion, "
        "Java from the grade effective date",
        5, 6, 400, ["reduction", "divergence"],
        red_in_grade_ind="Y", dt_orig_promo=_promo_date(60),
    ))
    out.append(make(
        alloc, "reduced-without-orig-promo",
        "reduced but the feed never restated the original promotion date "
        "(load_unit_diary.pl carry-forward path)",
        5, 6, 400, ["reduction", "divergence"],
        red_in_grade_ind="Y", dt_orig_promo=0,
    ))
    out.append(make(
        alloc, "not-reduced-with-orig-promo",
        "original promotion date present but the record was never reduced",
        5, 6, 400, ["reduction"], red_in_grade_ind="N", dt_orig_promo=_promo_date(60),
    ))
    out.append(make(
        alloc, "grade-eff-dt-diverges",
        "grade effective date is newer than last promotion: web tier reports "
        "less TIG than the batch",
        5, 60, 400, ["divergence"], grade_eff_dt=_promo_date(6),
    ))
    out.append(make(
        alloc, "grade-eff-dt-absent",
        "pre-2003 record with no grade effective date: Java falls back to last promotion",
        5, 60, 400, ["divergence"], grade_eff_dt=0,
    ))
    out.append(make(
        alloc, "no-promo-dates-at-all",
        "no promotion dates: TIG falls back to the enlistment date",
        5, 0, 400, ["fallback"],
        dt_last_promo=0, grade_eff_dt=0, dt_orig_promo=0,
        dt_enlist=_promo_date(90),
    ))
    return out


def break_in_service_scenarios(alloc: EdipiAllocator) -> list[Scenario]:
    out = []
    for months, label in ((0, "zero"), (6, "partial"), (999, "exceeds-tig")):
        out.append(make(
            alloc, f"brk-svc-{label}", f"break in service of {months} months",
            5, 60, 400, ["break-in-service"], brk_svc_mos=months,
        ))
    return out


def date_edge_scenarios(alloc: EdipiAllocator) -> list[Scenario]:
    """Where truncation (COBOL), round-up (Java) and ROUND (SQL) part ways."""
    out = []
    out.append(make(
        alloc, "anniversary-day-before-run-day",
        "promoted on the 1st, run on the 15th: partial month in progress",
        5, 36, 400, ["dates", "divergence"],
        dt_last_promo=_promo_date(36, day=1), grade_eff_dt=_promo_date(36, day=1),
    ))
    out.append(make(
        alloc, "anniversary-day-after-run-day",
        "promoted on the 28th: anniversary not yet reached this month",
        5, 36, 400, ["dates", "divergence"],
        dt_last_promo=_promo_date(36, day=28), grade_eff_dt=_promo_date(36, day=28),
    ))
    out.append(make(
        alloc, "month-end-promotion",
        "promoted on the 31st, base month shorter than the anniversary day",
        5, 36, 400, ["dates"],
        dt_last_promo=20230131, grade_eff_dt=20230131,
    ))
    out.append(make(
        alloc, "leap-day-promotion", "promoted on 29 Feb of a leap year",
        5, 36, 400, ["dates"], dt_last_promo=20240229, grade_eff_dt=20240229,
    ))
    out.append(make(
        alloc, "promotion-today", "promoted on the run date: zero months in grade",
        5, 0, 400, ["dates"],
    ))
    out.append(make(
        alloc, "promotion-in-the-future",
        "promotion date after the run date: negative raw month difference",
        5, 0, 400, ["dates", "dirty"],
        dt_last_promo=as_yyyymmdd(shift_months(AS_OF, 6)),
        grade_eff_dt=as_yyyymmdd(shift_months(AS_OF, 6)),
    ))
    out.append(make(
        alloc, "pebd-after-run-date", "PEBD after the run date",
        5, 400, 0, ["dates", "dirty"], pebd=as_yyyymmdd(shift_months(AS_OF, 3)),
    ))
    return out


def component_scenarios(alloc: EdipiAllocator) -> list[Scenario]:
    out = []
    for component in ("A", "R"):
        for drill in ("S", "N", " "):
            out.append(make(
                alloc, f"comp-{component.lower()}-drill-{drill.strip().lower() or 'blank'}",
                f"component {component}, drill status {drill!r}",
                5, 400, 400, ["component"], component=component, rc_drill_stat=drill,
            ))
    return out


def grade_boundary_scenarios(alloc: EdipiAllocator) -> list[Scenario]:
    out = []
    out.append(make(
        alloc, "grade-01-no-requirement-row",
        "grade 1: no REF_GRADE_REQUIREMENTS row for target grade 2? (there is one) "
        "-- lowest promotable grade",
        1, 400, 400, ["grade-boundary"],
    ))
    out.append(make(
        alloc, "grade-08-highest-promotable", "grade 8: target grade 9 is the last row",
        8, 400, 400, ["grade-boundary"],
    ))
    out.append(make(
        alloc, "grade-09-bypass",
        "grade 9: bypassed by the batch, MAXG in the web tier, filtered from the extract",
        9, 400, 400, ["grade-boundary", "divergence"],
    ))
    zero_grade = make(
        alloc, "grade-00-unset",
        "grade number never populated: no requirement row for target grade 1",
        1, 400, 400, ["grade-boundary", "dirty", "divergence"],
    )
    out.append(Scenario(**{**zero_grade.to_dict(), "grade_num": 0, "grade": "UNK"}))
    return out


def build() -> Corpus:
    alloc = EdipiAllocator()
    scenarios: list[Scenario] = []
    for group in (
        threshold_scenarios,
        precedence_scenarios,
        adverse_scenarios,
        reduction_scenarios,
        break_in_service_scenarios,
        date_edge_scenarios,
        component_scenarios,
        grade_boundary_scenarios,
    ):
        scenarios.extend(group(alloc))
    seen = [s.id for s in scenarios]
    duplicates = {i for i in seen if seen.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate scenario ids: {sorted(duplicates)}")
    return Corpus(as_of=AS_OF, scenarios=scenarios)


if __name__ == "__main__":
    corpus = build()
    dump_corpus(corpus)
    # The Java suite reads a flat CSV rather than YAML so it needs no extra
    # dependency; both files are generated from the same corpus.
    dump_scenario_csv(corpus, CORPUS_PATH.parent)
    print(f"wrote {len(corpus.scenarios)} scenarios as of {corpus.as_of}")
