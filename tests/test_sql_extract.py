"""Characterization of the reporting extract (SP_PROMOTION_ELIGIBILITY).

Runs the PostgreSQL translation in tests/sql/; test_translation_matches_oracle
keeps that translation honest against the Oracle original.
"""

from __future__ import annotations

import re

import pytest

from harness.engines import postgres
from harness.golden import compare, describe_difference
from harness.model import REPO_ROOT, Corpus
from harness.normalize import Row

pytestmark = pytest.mark.docker

ORACLE = (REPO_ROOT / "sql" / "promotion_eligibility.sql").read_text()
TRANSLATION = (REPO_ROOT / "tests" / "sql" / "sp_promotion_eligibility_pg.sql").read_text()


def row_for(corpus: Corpus, rows: list[Row], scenario_id: str) -> Row | None:
    edipi = corpus.by_id(scenario_id).edipi
    return next((r for r in rows if r.edipi == edipi), None)


def test_matches_golden(sql_rows):
    expected, actual = compare("sql", sql_rows)
    assert expected == actual, "extract behavior changed:\n" + describe_difference(expected, actual)


def test_grade_nine_is_filtered_out(corpus, sql_rows):
    assert row_for(corpus, sql_rows, "grade-09-bypass") is None


def test_a_grade_with_no_requirement_row_is_dropped_by_the_inner_join(corpus, sql_rows):
    """No row, no denial, no trace: the Marine simply is not in the report."""
    assert row_for(corpus, sql_rows, "grade-00-unset") is None


@pytest.mark.parametrize("months,expected", [
    (0, "ADVM"), (11, "ADVM"), (12, ""), (23, ""), (24, ""), (25, ""),
])
def test_adverse_material_lookback_is_still_twelve_months(corpus, sql_rows, months, expected):
    """The 2011 change to 24 months was never applied here."""
    assert row_for(corpus, sql_rows, f"advm-{months:02d}mo").deny_rsn == expected


def test_time_in_grade_always_accrues_from_the_last_promotion(corpus, sql_rows):
    # Neither the reduction indicator nor the grade effective date is read.
    assert row_for(corpus, sql_rows, "reduced-with-orig-promo").tig_mos == 6
    assert row_for(corpus, sql_rows, "grade-eff-dt-diverges").tig_mos == 60


def test_partial_months_are_rounded_to_nearest(corpus, sql_rows):
    # ROUND(MONTHS_BETWEEN(...)): 36 months and 14 days rounds down, 35 months
    # and 18 days rounds up.
    assert row_for(corpus, sql_rows, "anniversary-day-before-run-day").tig_mos == 36
    assert row_for(corpus, sql_rows, "anniversary-day-after-run-day").tig_mos == 36


def test_missing_promotion_date_yields_a_null_month_count(corpus, sql_rows):
    """Oracle GREATEST propagates NULL, so the comparisons fall through to 'Y'."""
    row = row_for(corpus, sql_rows, "no-promo-dates-at-all")
    assert row.tig_mos == postgres.NULL_MONTHS
    assert row.elig_ind == "Y"


def test_break_in_service_is_subtracted_and_floored(corpus, sql_rows):
    assert row_for(corpus, sql_rows, "brk-svc-partial").tig_mos == 54
    assert row_for(corpus, sql_rows, "brk-svc-exceeds-tig").tig_mos == 0


@pytest.mark.parametrize("scenario_id,expected", [
    ("comp-a-drill-n", ""), ("comp-r-drill-s", ""),
    ("comp-r-drill-n", "DRIL"), ("comp-r-drill-blank", "DRIL"),
])
def test_drill_status_only_applies_to_the_reserve_component(corpus, sql_rows,
                                                            scenario_id, expected):
    assert row_for(corpus, sql_rows, scenario_id).deny_rsn == expected


def test_component_parameter_filters_the_extract(pg_database, corpus):
    postgres.load_corpus(pg_database, corpus)
    reserve = postgres.run_extract(pg_database, corpus, component="R")
    reserve_edipis = {s.edipi for s in corpus.scenarios if s.component == "R"}
    assert {r.edipi for r in reserve} <= reserve_edipis
    assert reserve


def test_rerunning_the_same_run_date_replaces_rather_than_duplicates(pg_database, corpus):
    postgres.load_corpus(pg_database, corpus)
    first = postgres.run_extract(pg_database, corpus)
    second = postgres.run_extract(pg_database, corpus)
    assert first == second


def test_reference_table_matches_the_documented_values():
    documented = {
        int(grade): (int(tig), int(tis))
        for grade, tig, tis in re.findall(r"^--\s+(\d)\s+(\d+)\s+(\d+)\s*$",
                                          ORACLE, re.MULTILINE)
    }
    schema = (REPO_ROOT / "tests" / "sql" / "schema.sql").read_text()
    seeded = {
        int(grade): (int(tig), int(tis))
        for grade, tig, tis in re.findall(r"\(\s*(\d),\s*(\d+),\s*(\d+)\)", schema)
    }
    assert documented == seeded


class TestTranslationFidelity:
    """The PostgreSQL port must keep the behavior of the Oracle original."""

    def test_adverse_lookback_is_carried_over_unchanged(self):
        oracle = re.search(r"V_ADV_LOOKBACK_MOS\s+NUMBER := (\d+)", ORACLE).group(1)
        ported = re.search(r"V_ADV_LOOKBACK_MOS\s+INTEGER := (\d+)", TRANSLATION).group(1)
        assert oracle == ported == "12"

    def test_predicate_order_is_identical(self):
        def predicates(sql: str) -> list[str]:
            return re.findall(r"THEN '(STAT|ADVM|TIG|TIS|DRIL)'", sql)

        assert predicates(ORACLE) == predicates(TRANSLATION)

    def test_join_to_the_requirement_table_stays_an_inner_join(self):
        for sql in (ORACLE, TRANSLATION):
            assert re.search(r"\n\s+JOIN REF_GRADE_REQUIREMENTS", sql)
            assert "LEFT JOIN REF_GRADE_REQUIREMENTS" not in sql

    def test_grade_filter_and_component_filter_are_carried_over(self):
        for sql in (ORACLE, TRANSLATION):
            assert "m.GRADE_NUM < 9" in sql
            assert "P_COMPONENT IS NULL OR m.COMPONENT = P_COMPONENT" in sql

    def test_month_arithmetic_is_round_of_months_between(self):
        assert "ROUND(MONTHS_BETWEEN(P_RUN_DT, m.DT_LAST_PROMO))" in ORACLE
        assert "ROUND(ORACLE_MONTHS_BETWEEN(P_RUN_DT, m.DT_LAST_PROMO))" in TRANSLATION


@pytest.mark.parametrize("d1,d2,expected", [
    # Oracle MONTHS_BETWEEN reference values.
    ("2026-06-15", "2023-06-15", 36.0),
    ("2026-06-15", "2023-06-01", 36 + 14 / 31),
    ("2026-06-15", "2023-06-28", 36 - 13 / 31),
    ("2026-02-28", "2026-01-31", 1.0),
    ("2026-06-30", "2026-05-31", 1.0),
])
def test_oracle_months_between_translation(pg_database, d1, d2, expected):
    out = postgres._psql(
        pg_database, f"SELECT ORACLE_MONTHS_BETWEEN(DATE '{d1}', DATE '{d2}');",
        expect_csv=True)
    assert float(out.strip()) == pytest.approx(expected, abs=1e-9)
