"""Characterization of the Python reporting extract (``promelig.sql_extract``).

The Python replacement for ``SP_PROMOTION_ELIGIBILITY`` has to reproduce the
legacy extract exactly, so the first test here is the one that matters: the same
88 scenarios, normalized to the same six columns, compared against
``tests/golden/sql.csv``. The rest pin the individual quirks -- the 12-month
adverse lookback (DEF-9 / DIV-1), the silent inner join (DIV-5), the NULL month
count (DIV-6) -- so a regression says which one broke.

The month arithmetic is unit-tested without a database at the bottom of the
file; only the tests that need PostgreSQL carry the ``docker`` marker.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from harness.engines import postgres, python_sql
from harness.golden import compare, describe_difference, golden_path
from harness.model import REPO_ROOT, Corpus
from harness.normalize import Row, read_rows

from promelig import cli, oracle
from promelig.sql_extract import (ADV_LOOKBACK_MOS, Candidate, ComponentError, MAX_GRADE_NUM,
                                  candidate_sql, determine, run_extract)

ENGINE = "python_sql"


@pytest.fixture(scope="module")
def python_rows(pg_database, corpus):
    postgres.load_corpus(pg_database, corpus)
    return python_sql.run_extract(pg_database, corpus)


def row_for(corpus: Corpus, rows: list[Row], scenario_id: str):
    edipi = corpus.by_id(scenario_id).edipi
    return next((r for r in rows if r.edipi == edipi), None)


@pytest.mark.docker
def test_reproduces_the_legacy_extract_row_for_row(python_rows):
    """The migration gate: byte-for-byte agreement with the recorded extract."""
    expected = read_rows(golden_path("sql"))
    assert expected == sorted(python_rows), (
        "the Python extract no longer matches tests/golden/sql.csv:\n"
        + describe_difference(expected, sorted(python_rows)))


@pytest.mark.docker
def test_matches_golden(python_rows):
    expected, actual = compare(ENGINE, python_rows)
    assert expected == actual, "extract behavior changed:\n" + describe_difference(expected, actual)


@pytest.mark.docker
def test_the_rows_written_to_the_report_table_are_the_rows_returned(pg_database, python_rows):
    assert python_sql.read_report(pg_database) == sorted(python_rows)


@pytest.mark.docker
def test_grade_nine_is_filtered_out(corpus, python_rows):
    # DIV-4: no row at all, rather than the web service's MAXG bypass.
    assert row_for(corpus, python_rows, "grade-09-bypass") is None


@pytest.mark.docker
def test_a_grade_with_no_requirement_row_is_dropped_by_the_inner_join(corpus, python_rows):
    # DIV-5: no row, no denial, no trace.
    assert row_for(corpus, python_rows, "grade-00-unset") is None


@pytest.mark.docker
@pytest.mark.parametrize("months,expected", [
    (0, "ADVM"), (11, "ADVM"), (12, ""), (23, ""), (24, ""), (25, ""),
])
def test_adverse_material_lookback_is_still_twelve_months(corpus, python_rows, months, expected):
    # DEF-9 / DIV-1: preserved, not fixed.
    assert row_for(corpus, python_rows, f"advm-{months:02d}mo").deny_rsn == expected


@pytest.mark.docker
def test_time_in_grade_always_accrues_from_the_last_promotion(corpus, python_rows):
    # DIV-3: neither the reduction indicator nor the grade effective date is read.
    assert row_for(corpus, python_rows, "reduced-with-orig-promo").tig_mos == 6
    assert row_for(corpus, python_rows, "grade-eff-dt-diverges").tig_mos == 60


@pytest.mark.docker
def test_partial_months_are_rounded_to_nearest(corpus, python_rows):
    # DIV-2: 36 months and 14 days rounds down, 35 months and 18 days rounds up.
    assert row_for(corpus, python_rows, "anniversary-day-before-run-day").tig_mos == 36
    assert row_for(corpus, python_rows, "anniversary-day-after-run-day").tig_mos == 36


@pytest.mark.docker
def test_missing_promotion_date_yields_a_null_month_count(corpus, python_rows):
    # DIV-6: NULL propagates through GREATEST, so every threshold test is unknown
    # and the record falls through to eligible.
    row = row_for(corpus, python_rows, "no-promo-dates-at-all")
    assert row.tig_mos == postgres.NULL_MONTHS
    assert row.elig_ind == "Y"


@pytest.mark.docker
def test_break_in_service_is_subtracted_and_floored(corpus, python_rows):
    assert row_for(corpus, python_rows, "brk-svc-partial").tig_mos == 54
    assert row_for(corpus, python_rows, "brk-svc-exceeds-tig").tig_mos == 0


@pytest.mark.docker
@pytest.mark.parametrize("scenario_id,expected", [
    ("comp-a-drill-n", ""), ("comp-r-drill-s", ""),
    ("comp-r-drill-n", "DRIL"), ("comp-r-drill-blank", "DRIL"),
])
def test_drill_status_only_applies_to_the_reserve_component(corpus, python_rows,
                                                            scenario_id, expected):
    assert row_for(corpus, python_rows, scenario_id).deny_rsn == expected


@pytest.mark.docker
def test_component_parameter_filters_the_extract(pg_database, corpus):
    postgres.load_corpus(pg_database, corpus)
    reserve = python_sql.run_extract(pg_database, corpus, component="R")
    reserve_edipis = {s.edipi for s in corpus.scenarios if s.component == "R"}
    assert reserve
    assert {r.edipi for r in reserve} <= reserve_edipis


@pytest.mark.docker
def test_rerunning_the_same_run_date_replaces_rather_than_duplicates(pg_database, corpus):
    postgres.load_corpus(pg_database, corpus)
    first = python_sql.run_extract(pg_database, corpus)
    second = python_sql.run_extract(pg_database, corpus)
    assert first == second
    assert python_sql.read_report(pg_database) == sorted(second)


@pytest.mark.docker
@pytest.mark.parametrize("d1,d2", [
    ("2026-06-15", "2023-06-15"), ("2026-06-15", "2023-06-01"),
    ("2026-06-15", "2023-06-28"), ("2026-02-28", "2026-01-31"),
    ("2026-06-30", "2026-05-31"), ("2024-02-29", "2023-02-28"),
    ("2026-01-31", "2026-02-28"), ("2026-06-15", "2027-01-04"),
])
def test_python_months_between_agrees_with_the_plpgsql_emulation(pg_database, d1, d2):
    """The Python and PL/pgSQL emulations of Oracle MONTHS_BETWEEN cannot drift."""
    out = postgres._psql(
        pg_database, f"SELECT ORACLE_MONTHS_BETWEEN(DATE '{d1}', DATE '{d2}');",
        expect_csv=True)
    expected = Decimal(out.strip())
    actual = oracle.months_between(dt.date.fromisoformat(d1), dt.date.fromisoformat(d2))
    assert actual == pytest.approx(expected, abs=Decimal("1e-12"))


# --- the month arithmetic, without a database --------------------------------


@pytest.mark.parametrize("d1,d2,expected", [
    # Oracle MONTHS_BETWEEN reference values.
    ("2026-06-15", "2023-06-15", Decimal(36)),
    ("2026-06-15", "2023-06-01", 36 + Decimal(14) / 31),
    ("2026-06-15", "2023-06-28", 36 - Decimal(13) / 31),
    # Both dates month-end: whole months, even though the days differ.
    ("2026-02-28", "2026-01-31", Decimal(1)),
    ("2026-06-30", "2026-05-31", Decimal(1)),
    ("2024-02-29", "2024-01-31", Decimal(1)),
    # One date month-end, the other not: 31ths again, not the real month length.
    ("2026-03-31", "2026-02-15", 1 + Decimal(16) / 31),
    # Negative when the second date is later.
    ("2026-06-15", "2026-08-15", Decimal(-2)),
    ("2026-06-15", "2026-08-20", -2 - Decimal(5) / 31),
])
def test_oracle_months_between(d1, d2, expected):
    assert oracle.months_between(dt.date.fromisoformat(d1),
                                 dt.date.fromisoformat(d2)) == expected


@pytest.mark.parametrize("value,expected", [
    ("36.4838709677", 36), ("35.5806451613", 36),
    # Oracle rounds halves away from zero; Python's round() would give 2 and -2.
    ("2.5", 3), ("-2.5", -3), ("3.5", 4), ("-0.5", -1),
])
def test_round_is_half_away_from_zero(value, expected):
    assert oracle.round_half_away_from_zero(Decimal(value)) == expected


@pytest.mark.parametrize("a,b,expected", [
    (5, 0, 5), (-5, 0, 0), (None, 0, None), (0, None, None), (None, None, None),
])
def test_oracle_greatest_propagates_null(a, b, expected):
    assert oracle.greatest(a, b) == expected


def test_months_between_rounded_is_null_when_either_date_is_missing():
    assert oracle.months_between_rounded(dt.date(2026, 6, 15), None) is None
    assert oracle.months_between_rounded(None, dt.date(2026, 6, 15)) is None


# --- the denial rules, without a database ------------------------------------

RUN_DT = dt.date(2026, 6, 15)


def candidate(**overrides) -> Candidate:
    defaults = dict(
        edipi=1, grade="SSG", grade_num=5,
        dt_last_promo=dt.date(2020, 6, 15), pebd=dt.date(2010, 6, 15),
        brk_svc_mos=0, adv_matl_ind="N", adv_matl_mos=0,
        duty_stat="AC", component="A", rc_drill_stat=None,
        min_tig=36, min_tis=48,
    )
    defaults.update(overrides)
    return Candidate(**defaults)


def test_an_eligible_candidate_has_no_denial_reason():
    row = determine(RUN_DT, candidate())
    assert (row.elig_ind, row.deny_rsn, row.tig_mos, row.tis_mos) == ("Y", None, 72, 192)


def test_the_target_grade_is_the_current_grade_plus_one():
    assert determine(RUN_DT, candidate(grade_num=5)).tgt_grade_num == 6


@pytest.mark.parametrize("overrides,expected", [
    (dict(duty_stat="PS"), "STAT"),
    (dict(duty_stat="CF"), "STAT"),
    (dict(duty_stat="AW"), "STAT"),
    (dict(adv_matl_ind="Y", adv_matl_mos=ADV_LOOKBACK_MOS - 1), "ADVM"),
    (dict(min_tig=96), "TIG"),
    (dict(min_tis=240), "TIS"),
    (dict(component="R"), "DRIL"),
    (dict(component="R", rc_drill_stat="N"), "DRIL"),
])
def test_each_denial_reason(overrides, expected):
    row = determine(RUN_DT, candidate(**overrides))
    assert (row.elig_ind, row.deny_rsn) == ("N", expected)


@pytest.mark.parametrize("overrides", [
    dict(adv_matl_ind="Y", adv_matl_mos=ADV_LOOKBACK_MOS),
    dict(component="R", rc_drill_stat="S"),
    dict(component="A", rc_drill_stat="N"),
])
def test_predicates_that_do_not_deny(overrides):
    assert determine(RUN_DT, candidate(**overrides)).elig_ind == "Y"


@pytest.mark.parametrize("overrides,expected", [
    # STAT outranks everything, ADVM outranks the thresholds, TIG outranks TIS,
    # and DRIL is last -- the order of the legacy CASE expression.
    (dict(duty_stat="PS", adv_matl_ind="Y", adv_matl_mos=0, min_tig=96), "STAT"),
    (dict(adv_matl_ind="Y", adv_matl_mos=0, min_tig=96, min_tis=240), "ADVM"),
    (dict(min_tig=96, min_tis=240), "TIG"),
    (dict(min_tis=240, component="R"), "TIS"),
])
def test_denial_reason_precedence(overrides, expected):
    assert determine(RUN_DT, candidate(**overrides)).deny_rsn == expected


def test_a_missing_promotion_date_falls_through_every_comparison():
    # DIV-6 again, at the unit level: NULL is unknown, not zero.
    row = determine(RUN_DT, candidate(dt_last_promo=None, min_tig=96))
    assert (row.tig_mos, row.elig_ind, row.deny_rsn) == (None, "Y", None)


def test_a_missing_pebd_does_not_stop_a_time_in_grade_denial():
    row = determine(RUN_DT, candidate(pebd=None, min_tig=96))
    assert (row.tis_mos, row.deny_rsn) == (None, "TIG")


def test_a_null_adverse_month_count_is_not_a_denial():
    row = determine(RUN_DT, candidate(adv_matl_ind="Y", adv_matl_mos=None))
    assert row.elig_ind == "Y"


def test_break_in_service_is_subtracted_then_floored_at_zero():
    assert determine(RUN_DT, candidate(brk_svc_mos=6)).tig_mos == 66
    assert determine(RUN_DT, candidate(brk_svc_mos=999)).tig_mos == 0


def test_a_promotion_in_the_future_floors_at_zero():
    assert determine(RUN_DT, candidate(dt_last_promo=dt.date(2027, 1, 4))).tig_mos == 0


# --- the row-producing query -------------------------------------------------


def test_the_query_keeps_the_inner_join_and_the_grade_filter():
    sql = candidate_sql()
    assert "JOIN REF_GRADE_REQUIREMENTS" in sql and "LEFT JOIN" not in sql
    assert f"m.GRADE_NUM < {MAX_GRADE_NUM}" in sql
    assert "m.COMPONENT =" not in sql


def test_the_component_filter_is_added_only_when_asked_for():
    assert "m.COMPONENT = 'R'" in candidate_sql("R")


@pytest.mark.parametrize("component", ["R'; DROP TABLE MARINE_MASTER; --", "RR", "1", ""])
def test_an_implausible_component_is_rejected_rather_than_interpolated(component):
    with pytest.raises(ComponentError):
        candidate_sql(component)


class FakeDatabase:
    """A :class:`promelig.db.Database` that records what it was asked to do."""

    def __init__(self, records: list[list[str]]) -> None:
        self.records = records
        self.queried: list[str] = []
        self.executed: list[str] = []

    def query(self, sql: str) -> list[list[str]]:
        self.queried.append(sql)
        return self.records

    def execute(self, sql: str) -> None:
        self.executed.append(sql)


RECORD = ["1000000001", "SGT", "5", "2020-06-15", "2010-06-15", "0",
          "N", "0", "AC", "A", None, "36", "48"]


def test_the_run_deletes_the_run_date_before_inserting():
    db = FakeDatabase([RECORD])
    rows = run_extract(db, RUN_DT)
    assert [(r.edipi, r.elig_ind, r.tig_mos, r.tis_mos) for r in rows] == [
        (1000000001, "Y", 72, 192)]
    written = db.executed[0]
    assert written.index("DELETE FROM RPT_PROMOTION_ELIGIBILITY") < written.index("INSERT INTO")
    assert "WHERE RUN_DT = DATE '2026-06-15'" in written
    assert "(1000000001, 'SGT', 6, 72, 192, 'Y', NULL, DATE '2026-06-15')" in written


def test_a_run_with_no_candidates_still_clears_the_run_date():
    db = FakeDatabase([])
    assert run_extract(db, RUN_DT) == []
    assert "INSERT INTO" not in db.executed[0]
    assert "DELETE FROM RPT_PROMOTION_ELIGIBILITY" in db.executed[0]


def test_null_month_counts_are_written_as_null_not_zero():
    record = list(RECORD)
    record[3] = None          # DT_LAST_PROMO
    db = FakeDatabase([record])
    run_extract(db, RUN_DT)
    assert "(1000000001, 'SGT', 6, NULL, 192, 'Y', NULL, DATE '2026-06-15')" in db.executed[0]


def test_the_cli_writes_the_rows_it_is_asked_for(tmp_path):
    db = FakeDatabase([RECORD])
    destination = tmp_path / "extract.csv"
    cli.write_csv(run_extract(db, RUN_DT), destination)
    assert destination.read_text().splitlines() == [
        "edipi,grade,tgt_grade_num,tig_mos,tis_mos,elig_ind,deny_rsn,run_dt",
        "1000000001,SGT,6,72,192,Y,,2026-06-15",
    ]


def test_the_cli_defaults_to_the_whole_extract_for_today():
    args = cli.build_parser().parse_args(["--dsn", "postgresql:///promelig"])
    assert (args.component, args.run_date) == (None, dt.date.today())


def test_the_lookback_still_matches_the_legacy_source():
    """DEF-9: 12 months in the extract, 24 in the batch and the web service."""
    oracle_sql = (REPO_ROOT / "sql" / "promotion_eligibility.sql").read_text()
    assert "V_ADV_LOOKBACK_MOS  NUMBER := 12;" in oracle_sql
    assert ADV_LOOKBACK_MOS == 12
