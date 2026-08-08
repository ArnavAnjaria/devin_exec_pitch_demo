"""The Python replacement for PROMELIG.cbl, held to the COBOL golden.

The migration contract is byte-for-byte parity with the engine being replaced,
defects included, so the assertions here are the same ones
``test_cobol_batch.py`` makes -- plus a direct comparison against the recorded
COBOL golden and, where GnuCOBOL is available, against a live COBOL run.
"""

from __future__ import annotations

import datetime as dt

import pytest
from promelig import batch, cobol_rules as eligibility
from promelig.cobol_rules import MarineRecord

from harness.golden import compare, describe_difference, golden_path
from harness.marrec import encode
from harness.model import Corpus
from harness.normalize import GRADE_REQUIREMENTS, read_rows


def row_for(corpus: Corpus, rows, scenario_id: str):
    edipi = corpus.by_id(scenario_id).edipi
    return next((r for r in rows if r.edipi == edipi), None)


def record_for(corpus: Corpus, scenario_id: str) -> MarineRecord:
    return batch.decode_master_record(encode(corpus.by_id(scenario_id)))


def test_matches_golden(python_rows):
    expected, actual = compare("python_batch", python_rows)
    assert expected == actual, ("Python behavior changed:\n"
                                + describe_difference(expected, actual))


def test_reproduces_the_cobol_golden(python_rows):
    """The point of the migration: the same answers as the program it replaces."""
    expected = read_rows(golden_path("cobol"))
    assert expected == sorted(python_rows), (
        "Python diverges from the COBOL board slate:\n"
        + describe_difference(expected, sorted(python_rows)))


@pytest.mark.cobol
def test_matches_a_live_cobol_run(cobol_rows, python_rows):
    assert sorted(cobol_rows) == sorted(python_rows)


@pytest.mark.cobol
def test_the_run_summary_matches_the_cobol_report(cobol_run, python_run):
    """Including DEF-5: the counters are packed decimal in a character record."""
    _, cobol_report = cobol_run
    _, python_report = python_run
    # The COBOL harness reads RPTOUT as text with replacement characters,
    # because the packed counters are not valid UTF-8; decode ours the same way.
    assert python_report.decode("utf-8", errors="replace").rstrip() == cobol_report.rstrip()


@pytest.mark.cobol
def test_the_extract_records_are_byte_for_byte_identical(corpus: Corpus, tmp_path):
    """Not just the normalized rows: the 60-byte ELIGOUT records themselves.

    The trailing FILLER is excluded. PROMELIG only moves spaces into the record
    area *after* the first WRITE, so under GnuCOBOL the first record's filler is
    low-values -- an artifact of the runtime's record area, not of the program.
    """
    from harness.engines import cobol as cobol_engine
    from harness.marrec import DECLARED_RECORD_LEN, write_master_file

    scenarios = sorted(corpus.scenarios, key=lambda s: s.edipi)
    cobol_engine.run(corpus, tmp_path / "cobol")
    master = tmp_path / "master.dat"
    elig = tmp_path / "elig.dat"
    write_master_file(master, scenarios, record_len=DECLARED_RECORD_LEN)
    batch.run(master, elig, None, corpus.as_of)

    def data_only(raw: bytes) -> list[bytes]:
        return [raw[i:i + 35] for i in range(0, len(raw), batch.ELIG_RECORD_LEN)]

    expected = data_only((tmp_path / "cobol" / "elig.dat").read_bytes())
    assert data_only(elig.read_bytes()) == expected


def test_writes_one_record_per_input_except_bypasses(corpus: Corpus, python_rows):
    bypassed = [s for s in corpus.scenarios if s.grade_num >= 9]
    assert len(python_rows) == len(corpus.scenarios) - len(bypassed)


def test_top_grade_is_bypassed_with_no_output_record(corpus: Corpus, python_rows):
    assert row_for(corpus, python_rows, "grade-09-bypass") is None
    assert eligibility.evaluate(record_for(corpus, "grade-09-bypass"), corpus.as_of) is None


def test_run_date_is_stamped_on_every_record(corpus: Corpus, tmp_path):
    from harness.marrec import parse_elig_file, write_master_file

    master = tmp_path / "master.dat"
    elig = tmp_path / "elig.dat"
    write_master_file(master, corpus.scenarios[:5])
    batch.run(master, elig, tmp_path / "rpt.txt", corpus.as_of)

    records = parse_elig_file(elig)
    assert records
    assert all(r["run_dt"] == corpus.as_of_yyyymmdd for r in records)


@pytest.mark.parametrize("target_grade,requirement", sorted(GRADE_REQUIREMENTS.items()))
def test_time_in_grade_threshold(corpus, python_rows, target_grade, requirement):
    min_tig = requirement[0]
    below = row_for(corpus, python_rows, f"tig-{target_grade:02d}-below")
    at = row_for(corpus, python_rows, f"tig-{target_grade:02d}-at")
    above = row_for(corpus, python_rows, f"tig-{target_grade:02d}-above")

    assert (below.tig_mos, below.elig_ind, below.deny_rsn) == (min_tig - 1, "N", "TIG")
    assert (at.tig_mos, at.elig_ind) == (min_tig, "Y")
    assert (above.tig_mos, above.elig_ind) == (min_tig + 1, "Y")


@pytest.mark.parametrize("target_grade,requirement", sorted(GRADE_REQUIREMENTS.items()))
def test_time_in_service_threshold(corpus, python_rows, target_grade, requirement):
    min_tis = requirement[1]
    below = row_for(corpus, python_rows, f"tis-{target_grade:02d}-below")
    at = row_for(corpus, python_rows, f"tis-{target_grade:02d}-at")

    assert (below.tis_mos, below.elig_ind, below.deny_rsn) == (min_tis - 1, "N", "TIS")
    assert (at.tis_mos, at.elig_ind) == (min_tis, "Y")


def test_deny_reason_precedence(corpus, python_rows):
    assert row_for(corpus, python_rows, "stat-beats-everything").deny_rsn == "STAT"
    assert row_for(corpus, python_rows, "advm-beats-tig").deny_rsn == "ADVM"
    assert row_for(corpus, python_rows, "tig-beats-tis").deny_rsn == "TIG"
    assert row_for(corpus, python_rows, "tis-beats-dril").deny_rsn == "TIS"


@pytest.mark.parametrize("months,expected", [
    (0, "ADVM"), (11, "ADVM"), (12, "ADVM"), (23, "ADVM"), (24, ""), (25, ""),
])
def test_adverse_material_lookback_is_24_months(corpus, python_rows, months, expected):
    assert row_for(corpus, python_rows, f"advm-{months:02d}mo").deny_rsn == expected


def test_reduction_accrues_time_in_grade_from_the_original_promotion(corpus, python_rows):
    # REV 02 2001, and DIV-3: unresolved, so the COBOL base date is kept.
    reduced = row_for(corpus, python_rows, "reduced-with-orig-promo")
    assert (reduced.tig_mos, reduced.elig_ind) == (60, "Y")


def test_reduction_without_an_original_promotion_falls_back_to_enlistment(corpus, python_rows):
    row = row_for(corpus, python_rows, "reduced-without-orig-promo")
    assert corpus.by_id("reduced-without-orig-promo").dt_orig_promo == 0
    assert row.tig_mos == row.tis_mos


def test_grade_effective_date_is_not_read_by_the_batch(corpus, python_rows):
    # DIV-3: the web tier would report 6 months here; the batch reads DT-LAST-PROMO.
    assert row_for(corpus, python_rows, "grade-eff-dt-diverges").tig_mos == 60


@pytest.mark.parametrize("scenario_id,expected_tig", [
    ("brk-svc-zero", 60), ("brk-svc-partial", 54), ("brk-svc-exceeds-tig", 0),
])
def test_break_in_service_is_subtracted_and_floored(corpus, python_rows,
                                                    scenario_id, expected_tig):
    assert row_for(corpus, python_rows, scenario_id).tig_mos == expected_tig


def test_partial_months_are_truncated(corpus, python_rows):
    assert row_for(corpus, python_rows, "anniversary-day-before-run-day").tig_mos == 36
    assert row_for(corpus, python_rows, "anniversary-day-after-run-day").tig_mos == 35


def test_future_dates_floor_at_zero(corpus, python_rows):
    assert row_for(corpus, python_rows, "promotion-in-the-future").tig_mos == 0
    assert row_for(corpus, python_rows, "pebd-after-run-date").tis_mos == 0


@pytest.mark.parametrize("scenario_id,expected", [
    ("comp-a-drill-s", ""), ("comp-a-drill-n", ""), ("comp-a-drill-blank", ""),
    ("comp-r-drill-s", ""), ("comp-r-drill-n", "DRIL"), ("comp-r-drill-blank", "DRIL"),
])
def test_drill_status_only_applies_to_the_reserve_component(corpus, python_rows,
                                                            scenario_id, expected):
    assert row_for(corpus, python_rows, scenario_id).deny_rsn == expected


def test_grade_without_a_requirement_row_is_denied_for_time_in_grade(corpus, python_rows):
    # DIV-5: a missing requirement row defaults the minimums to 999 and denies.
    row = row_for(corpus, python_rows, "grade-00-unset")
    assert (row.tgt_grade, row.elig_ind, row.deny_rsn) == (1, "N", "TIG")
    assert eligibility.lookup_minimums(1) == eligibility.NO_REQUIREMENT


def test_requirement_table_matches_the_working_storage_table():
    assert eligibility.GRADE_REQUIREMENTS == GRADE_REQUIREMENTS


def test_deny_reasons_are_four_bytes_space_padded(corpus, tmp_path):
    from harness.marrec import write_master_file

    scenario = corpus.by_id("tig-beats-tis")
    master = tmp_path / "master.dat"
    elig = tmp_path / "elig.dat"
    write_master_file(master, [scenario])
    batch.run(master, elig, None, corpus.as_of)

    record = elig.read_bytes()
    assert len(record) == batch.ELIG_RECORD_LEN
    assert record[23:27] == b"TIG "


def test_month_counters_are_truncated_on_output():
    """DEF-4: PIC S9(05) counters written into PIC 9(03)/9(04) output fields."""
    decision = eligibility.Decision(edipi=1234567890, grade="SGT", tgt_grade=2,
                                    tig_mos=24361, tis_mos=24361, eligible=True)
    record = batch.encode_elig_record(decision, dt.date(2026, 6, 15))
    assert record[15:18] == b"361"
    assert record[18:22] == b"4361"


def test_a_missing_master_file_is_an_open_failure(tmp_path):
    result = batch.run(tmp_path / "absent.dat", tmp_path / "elig.dat", None,
                       dt.date(2026, 6, 15))
    assert result.return_code == batch.OPEN_FAILED_RC
    assert result.decisions == []


def test_master_records_are_decoded_through_the_copybook(corpus):
    scenario = corpus.by_id("stat-beats-everything")
    record = record_for(corpus, "stat-beats-everything")
    assert record.edipi == scenario.edipi
    assert record.duty_stat == scenario.duty_stat
    assert record.adv_matl_mos == scenario.adv_matl_mos
    assert record.brk_svc_mos == scenario.brk_svc_mos
    assert record.non_promotable
