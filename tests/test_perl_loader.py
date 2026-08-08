"""Characterization of perl/load_unit_diary.pl, the unit diary feed loader.

Driven from Python so the fixed-width fixtures come from the same corpus and
copybook parser every other engine uses.
"""

from __future__ import annotations

import pytest

from harness.engines import perl_loader
from harness.marrec import FIELDS, feed_line
from harness.model import Corpus

pytestmark = pytest.mark.perl


@pytest.fixture(autouse=True)
def _require_perl():
    try:
        perl_loader.require_perl()
    except perl_loader.PerlUnavailable as exc:
        pytest.skip(str(exc))


@pytest.fixture
def load(tmp_path, corpus):
    def _load(scenarios=None, lines=None, seed=()):
        feed = tmp_path / "unitdiary.dat"
        if lines is not None:
            perl_loader.write_feed(feed, lines)
        else:
            perl_loader.feed_from_scenarios(feed, scenarios or corpus.scenarios)
        return perl_loader.run(tmp_path, feed, seed=seed)
    return _load


def test_loads_the_whole_corpus(load, corpus: Corpus):
    run = load()
    assert run.returncode == 0
    assert run.loaded == len(corpus.scenarios)
    assert len(run.rows()) == len(corpus.scenarios)


def test_every_field_lands_on_its_copybook_offset(load, corpus: Corpus):
    scenario = corpus.by_id("stat-beats-everything")
    row = load([scenario]).row(scenario.edipi)

    assert row["last_nm"] == scenario.last_nm
    assert row["first_nm"] == scenario.first_nm
    assert row["middle_init"] == scenario.middle_init
    assert row["grade"] == scenario.grade
    assert int(row["grade_num"]) == scenario.grade_num
    assert row["pmos"] == scenario.pmos
    assert int(row["dt_last_promo"]) == scenario.dt_last_promo
    assert int(row["pebd"]) == scenario.pebd
    assert int(row["dt_enlist"]) == scenario.dt_enlist
    assert row["red_in_grade_ind"] == scenario.red_in_grade_ind


def test_only_the_display_fields_before_the_packed_area_are_loaded(load, corpus: Corpus):
    row = load([corpus.by_id("stat-beats-everything")]).rows()[0]
    assert set(row) == set(perl_loader.LOADED_COLUMNS)


def test_zero_filled_grade_effective_date_becomes_null(load, corpus: Corpus):
    scenario = corpus.by_id("grade-eff-dt-absent")
    assert scenario.grade_eff_dt == 0
    assert load([scenario]).row(scenario.edipi)["grade_eff_dt"] is None


def test_populated_grade_effective_date_is_kept(load, corpus: Corpus):
    scenario = corpus.by_id("grade-eff-dt-diverges")
    row = load([scenario]).row(scenario.edipi)
    assert int(row["grade_eff_dt"]) == scenario.grade_eff_dt


def test_reduction_without_an_original_promotion_date_is_carried_forward(load, corpus: Corpus):
    """The column is omitted from the UPDATE so the master keeps its old value."""
    scenario = corpus.by_id("reduced-without-orig-promo")
    seed = [{"edipi": str(scenario.edipi), "dt_orig_promo": "19990101"}]

    run = load([scenario], seed=seed)

    assert run.carried_forward == 1
    assert run.row(scenario.edipi)["dt_orig_promo"] == "19990101"


def test_carry_forward_on_an_unknown_edipi_inserts_a_row_without_the_column(load, corpus):
    """There is no row to carry anything forward from, so the value is lost."""
    scenario = corpus.by_id("reduced-without-orig-promo")
    run = load([scenario])
    assert run.carried_forward == 1
    assert run.row(scenario.edipi)["dt_orig_promo"] is None


def test_existing_records_are_updated_rather_than_duplicated(load, corpus: Corpus):
    scenario = corpus.by_id("tig-05-at")
    seed = [{"edipi": str(scenario.edipi), "grade": "PVT", "grade_num": "01"}]

    run = load([scenario], seed=seed)

    rows = run.rows()
    assert len(rows) == 1
    assert rows[0]["grade"] == scenario.grade
    assert int(rows[0]["grade_num"]) == scenario.grade_num


def test_a_repeated_edipi_in_one_feed_collapses_to_the_last_record(load, corpus: Corpus):
    first = corpus.by_id("tig-05-at")
    second_line = feed_line(corpus.by_id("tig-05-above")).replace(
        str(corpus.by_id("tig-05-above").edipi), str(first.edipi), 1)

    run = load(lines=[feed_line(first), second_line])

    assert run.loaded == 2
    assert len(run.rows()) == 1


def test_blank_lines_are_skipped(load, corpus: Corpus):
    scenario = corpus.by_id("tig-05-at")
    run = load(lines=["", "   ", feed_line(scenario), ""])
    assert run.loaded == 1


def test_trailing_whitespace_is_stripped_from_every_field(load, corpus: Corpus):
    scenario = corpus.by_id("tig-05-at")
    run = load(lines=[feed_line(scenario) + "          "])
    assert run.row(scenario.edipi)["grade"] == scenario.grade


def test_a_short_record_is_loaded_with_missing_trailing_fields(load, corpus: Corpus):
    """DEF-6: there is no length validation, so a truncated line still loads."""
    scenario = corpus.by_id("tig-05-at")
    cutoff = FIELDS["MM-PEBD"].offset
    run = load(lines=[feed_line(scenario)[:cutoff]])

    assert run.returncode == 0
    row = run.row(scenario.edipi)
    assert row is not None
    assert row["pebd"] in (None, "")
    assert row["dt_enlist"] in (None, "")
    assert "uninitialized" in run.stderr or "outside of string" in run.stderr


def test_a_non_numeric_edipi_is_accepted(load, corpus: Corpus):
    """The feed is not validated, so junk propagates into the master table."""
    scenario = corpus.by_id("tig-05-at")
    line = "ABCDEFGHIJ" + feed_line(scenario)[10:]
    run = load(lines=[line])
    assert run.returncode == 0
    assert run.rows()[0]["edipi"] == "ABCDEFGHIJ"


@pytest.mark.slow
def test_commit_batching_does_not_lose_records_at_the_boundary(load, corpus: Corpus):
    """The loader commits every 5000 rows; 5001 exercises the boundary."""
    template = feed_line(corpus.by_id("tig-05-at"))
    lines = [str(2000000000 + i).zfill(10) + template[10:] for i in range(5001)]

    run = load(lines=lines)

    assert run.loaded == 5001
    assert len(run.rows()) == 5001
