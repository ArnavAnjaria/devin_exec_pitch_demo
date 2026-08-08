"""Characterization of PROMELIG.cbl, the authoritative board-slate batch.

Everything here describes what the program does today. Where behavior looks
wrong it is recorded, not corrected: see docs/defects.md and
docs/divergence-register.md.
"""

from __future__ import annotations

import pytest

from harness.golden import compare, describe_difference
from harness.marrec import FIELDS, decode, encode
from harness.model import Corpus
from harness.normalize import GRADE_REQUIREMENTS, Row

pytestmark = pytest.mark.cobol


def row_for(corpus: Corpus, rows: list[Row], scenario_id: str) -> Row | None:
    edipi = corpus.by_id(scenario_id).edipi
    return next((r for r in rows if r.edipi == edipi), None)


def test_matches_golden(cobol_rows):
    expected, actual = compare("cobol", cobol_rows)
    assert expected == actual, "COBOL behavior changed:\n" + describe_difference(expected, actual)


def test_writes_one_record_per_input_except_bypasses(corpus: Corpus, cobol_rows):
    bypassed = [s for s in corpus.scenarios if s.grade_num >= 9]
    assert len(cobol_rows) == len(corpus.scenarios) - len(bypassed)


def test_top_grade_is_bypassed_with_no_output_record(corpus: Corpus, cobol_rows):
    assert row_for(corpus, cobol_rows, "grade-09-bypass") is None


def test_run_date_is_stamped_on_every_record(corpus: Corpus, cobol_run, tmp_path):
    # Covered indirectly by the golden; asserted here against the raw records.
    from harness.engines import cobol as cobol_engine
    from harness.marrec import parse_elig_file, write_master_file

    workdir = tmp_path / "rundate"
    exe = cobol_engine.build(workdir)
    master = workdir / "master.dat"
    write_master_file(master, corpus.scenarios[:5])

    import os
    import subprocess

    env = dict(os.environ, DD_MSTRIN=str(master), DD_ELIGOUT=str(workdir / "elig.dat"),
               DD_RPTOUT=str(workdir / "rpt.txt"),
               COB_CURRENT_DATE=corpus.as_of.strftime("%Y/%m/%d 00:00:00"))
    subprocess.run([str(exe)], env=env, cwd=workdir, check=True, capture_output=True, timeout=60)

    records = parse_elig_file(workdir / "elig.dat")
    assert records
    assert all(r["run_dt"] == corpus.as_of_yyyymmdd for r in records)


@pytest.mark.parametrize("target_grade,requirement", sorted(GRADE_REQUIREMENTS.items()))
def test_time_in_grade_threshold(corpus, cobol_rows, target_grade, requirement):
    min_tig = requirement[0]
    below = row_for(corpus, cobol_rows, f"tig-{target_grade:02d}-below")
    at = row_for(corpus, cobol_rows, f"tig-{target_grade:02d}-at")
    above = row_for(corpus, cobol_rows, f"tig-{target_grade:02d}-above")

    assert (below.tig_mos, below.elig_ind, below.deny_rsn) == (min_tig - 1, "N", "TIG")
    assert (at.tig_mos, at.elig_ind) == (min_tig, "Y")
    assert (above.tig_mos, above.elig_ind) == (min_tig + 1, "Y")


@pytest.mark.parametrize("target_grade,requirement", sorted(GRADE_REQUIREMENTS.items()))
def test_time_in_service_threshold(corpus, cobol_rows, target_grade, requirement):
    min_tis = requirement[1]
    below = row_for(corpus, cobol_rows, f"tis-{target_grade:02d}-below")
    at = row_for(corpus, cobol_rows, f"tis-{target_grade:02d}-at")

    assert (below.tis_mos, below.elig_ind, below.deny_rsn) == (min_tis - 1, "N", "TIS")
    assert (at.tis_mos, at.elig_ind) == (min_tis, "Y")


@pytest.mark.parametrize("scenario_id", ["stat-ps", "stat-cf", "stat-aw"])
def test_non_promotable_duty_status(corpus, cobol_rows, scenario_id):
    assert row_for(corpus, cobol_rows, scenario_id).deny_rsn == "STAT"


def test_deny_reason_precedence(corpus, cobol_rows):
    assert row_for(corpus, cobol_rows, "stat-beats-everything").deny_rsn == "STAT"
    assert row_for(corpus, cobol_rows, "advm-beats-tig").deny_rsn == "ADVM"
    assert row_for(corpus, cobol_rows, "tig-beats-tis").deny_rsn == "TIG"
    assert row_for(corpus, cobol_rows, "tis-beats-dril").deny_rsn == "TIS"


@pytest.mark.parametrize("months,expected", [
    (0, "ADVM"), (11, "ADVM"), (12, "ADVM"), (23, "ADVM"), (24, ""), (25, ""),
])
def test_adverse_material_lookback_is_24_months(corpus, cobol_rows, months, expected):
    assert row_for(corpus, cobol_rows, f"advm-{months:02d}mo").deny_rsn == expected


def test_adverse_months_are_ignored_without_the_indicator(corpus, cobol_rows):
    assert row_for(corpus, cobol_rows, "advm-indicator-off").elig_ind == "Y"


def test_reduction_accrues_time_in_grade_from_the_original_promotion(corpus, cobol_rows):
    # REV 02 2001: directed behavior, not a defect.
    reduced = row_for(corpus, cobol_rows, "reduced-with-orig-promo")
    assert reduced.tig_mos == 60
    assert reduced.elig_ind == "Y"


def test_reduction_without_an_original_promotion_falls_back_to_enlistment(corpus, cobol_rows):
    # DT-ORIG-PROMO is zero, so 2100-COMPUTE-TIG uses the enlistment date and
    # the Marine is credited with their entire career as time in grade.
    scenario = corpus.by_id("reduced-without-orig-promo")
    row = row_for(corpus, cobol_rows, "reduced-without-orig-promo")
    assert scenario.dt_orig_promo == 0
    assert row.tig_mos == row.tis_mos


def test_grade_effective_date_is_not_read_by_the_batch(corpus, cobol_rows):
    # The web tier would report 6 months here; the batch reads DT-LAST-PROMO.
    assert row_for(corpus, cobol_rows, "grade-eff-dt-diverges").tig_mos == 60


def test_missing_promotion_dates_fall_back_to_enlistment(corpus, cobol_rows):
    assert row_for(corpus, cobol_rows, "no-promo-dates-at-all").tig_mos == 90


@pytest.mark.parametrize("scenario_id,expected_tig", [
    ("brk-svc-zero", 60), ("brk-svc-partial", 54), ("brk-svc-exceeds-tig", 0),
])
def test_break_in_service_is_subtracted_and_floored(corpus, cobol_rows,
                                                    scenario_id, expected_tig):
    assert row_for(corpus, cobol_rows, scenario_id).tig_mos == expected_tig


def test_partial_months_are_truncated(corpus, cobol_rows):
    # Promoted on the 1st, run on the 15th: the in-progress month is credited
    # because the anniversary day has passed.
    assert row_for(corpus, cobol_rows, "anniversary-day-before-run-day").tig_mos == 36
    # Promoted on the 28th: the anniversary has not been reached this month.
    assert row_for(corpus, cobol_rows, "anniversary-day-after-run-day").tig_mos == 35


def test_future_dates_floor_at_zero(corpus, cobol_rows):
    assert row_for(corpus, cobol_rows, "promotion-in-the-future").tig_mos == 0
    assert row_for(corpus, cobol_rows, "pebd-after-run-date").tis_mos == 0


@pytest.mark.parametrize("scenario_id,expected", [
    ("comp-a-drill-s", ""), ("comp-a-drill-n", ""), ("comp-a-drill-blank", ""),
    ("comp-r-drill-s", ""), ("comp-r-drill-n", "DRIL"), ("comp-r-drill-blank", "DRIL"),
])
def test_drill_status_only_applies_to_the_reserve_component(corpus, cobol_rows,
                                                            scenario_id, expected):
    assert row_for(corpus, cobol_rows, scenario_id).deny_rsn == expected


def test_grade_without_a_requirement_row_is_denied_for_time_in_grade(corpus, cobol_rows):
    # 2300-LOOKUP-MINIMUMS leaves the minimums at 999 when SEARCH finds nothing.
    row = row_for(corpus, cobol_rows, "grade-00-unset")
    assert (row.tgt_grade, row.elig_ind, row.deny_rsn) == (1, "N", "TIG")


def test_working_storage_table_matches_the_reference_table():
    from harness.model import REPO_ROOT

    source = (REPO_ROOT / "cobol" / "PROMELIG.cbl").read_text()
    entries = {}
    for line in source.splitlines():
        if "05  FILLER  PIC X(09) VALUE" in line:
            literal = line.split("'")[1]
            entries[int(literal[0:2])] = (int(literal[2:5]), int(literal[5:8]))
    assert entries == GRADE_REQUIREMENTS


def test_master_records_round_trip_through_the_copybook_layout(corpus):
    scenario = corpus.by_id("stat-beats-everything")
    decoded = decode(encode(scenario))
    assert int(decoded["MM-EDIPI"]) == scenario.edipi
    assert decoded["MM-DUTY-STAT"].strip() == scenario.duty_stat
    assert decoded["MM-ADV-MATL-MOS"] == scenario.adv_matl_mos
    assert decoded["MM-BRK-SVC-MOS"] == scenario.brk_svc_mos


def test_copybook_field_offsets_are_stable():
    # Pinning the layout: the Perl loader and the JCL both index into it.
    assert FIELDS["MM-EDIPI"].offset == 0
    assert FIELDS["MM-GRADE"].offset == 57
    assert FIELDS["MM-GRADE-NUM"].offset == 60
    assert FIELDS["MM-DT-LAST-PROMO"].offset == 66
    assert FIELDS["MM-RED-IN-GRADE-IND"].offset == 106
