"""Characterization of python/promelig/unit_diary.py, the loader rewrite.

The first class mirrors ``tests/test_perl_loader.py`` one test at a time, so the
Python loader is held to the behavior that suite pins. The second runs both
loaders over the same fixtures and compares the resulting master table row for
row -- that is the parity proof, and it is the test that fails if the rewrite
starts to drift. The last class covers the parsing in isolation, with no file and
no database.
"""

from __future__ import annotations

import pytest

from harness.engines import perl_loader, python_loader, python_loader_pg
from harness.marrec import FIELDS, feed_line
from harness.model import Corpus
from promelig import copybook, unit_diary


@pytest.fixture(scope="module")
def pg_container():
    """A PostgreSQL container with tests/sql/schema.sql loaded."""
    try:
        python_loader_pg.require_driver()
    except python_loader_pg.DriverUnavailable as exc:
        pytest.skip(str(exc))
    with python_loader_pg.database() as name:
        yield name


@pytest.fixture
def load(tmp_path, corpus):
    def _load(scenarios=None, lines=None, seed=()):
        feed = tmp_path / "unitdiary.dat"
        if lines is not None:
            python_loader.write_feed(feed, lines)
        else:
            python_loader.feed_from_scenarios(feed, scenarios or corpus.scenarios)
        return python_loader.run(tmp_path, feed, seed=seed)
    return _load


class TestLoaderBehavior:
    """One test per test in tests/test_perl_loader.py."""

    def test_loads_the_whole_corpus(self, load, corpus: Corpus):
        run = load()
        assert run.returncode == 0, run.stderr
        assert run.loaded == len(corpus.scenarios)
        assert len(run.rows()) == len(corpus.scenarios)

    def test_every_field_lands_on_its_copybook_offset(self, load, corpus: Corpus):
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

    def test_only_the_display_fields_before_the_packed_area_are_loaded(
            self, load, corpus: Corpus):
        row = load([corpus.by_id("stat-beats-everything")]).rows()[0]
        assert set(row) == set(unit_diary.LOADED_COLUMNS)

    def test_zero_filled_grade_effective_date_becomes_null(self, load, corpus: Corpus):
        scenario = corpus.by_id("grade-eff-dt-absent")
        assert scenario.grade_eff_dt == 0
        assert load([scenario]).row(scenario.edipi)["grade_eff_dt"] is None

    def test_populated_grade_effective_date_is_kept(self, load, corpus: Corpus):
        scenario = corpus.by_id("grade-eff-dt-diverges")
        row = load([scenario]).row(scenario.edipi)
        assert int(row["grade_eff_dt"]) == scenario.grade_eff_dt

    def test_reduction_without_an_original_promotion_date_is_carried_forward(
            self, load, corpus: Corpus):
        """The column is omitted from the UPDATE so the master keeps its value."""
        scenario = corpus.by_id("reduced-without-orig-promo")
        seed = [{"edipi": str(scenario.edipi), "dt_orig_promo": "19990101"}]

        run = load([scenario], seed=seed)

        assert run.carried_forward == 1
        assert run.row(scenario.edipi)["dt_orig_promo"] == "19990101"

    def test_carry_forward_on_an_unknown_edipi_inserts_a_row_without_the_column(
            self, load, corpus: Corpus):
        """DEF-7: nothing to carry forward, so the value is lost on the insert."""
        scenario = corpus.by_id("reduced-without-orig-promo")
        run = load([scenario])
        assert run.carried_forward == 1
        assert run.row(scenario.edipi)["dt_orig_promo"] is None

    def test_existing_records_are_updated_rather_than_duplicated(
            self, load, corpus: Corpus):
        scenario = corpus.by_id("tig-05-at")
        seed = [{"edipi": str(scenario.edipi), "grade": "PVT", "grade_num": "01"}]

        run = load([scenario], seed=seed)

        rows = run.rows()
        assert len(rows) == 1
        assert rows[0]["grade"] == scenario.grade
        assert int(rows[0]["grade_num"]) == scenario.grade_num

    def test_a_repeated_edipi_in_one_feed_collapses_to_the_last_record(
            self, load, corpus: Corpus):
        first = corpus.by_id("tig-05-at")
        second_line = feed_line(corpus.by_id("tig-05-above")).replace(
            str(corpus.by_id("tig-05-above").edipi), str(first.edipi), 1)

        run = load(lines=[feed_line(first), second_line])

        assert run.loaded == 2
        assert len(run.rows()) == 1

    def test_blank_lines_are_skipped(self, load, corpus: Corpus):
        scenario = corpus.by_id("tig-05-at")
        run = load(lines=["", "   ", feed_line(scenario), ""])
        assert run.loaded == 1

    def test_trailing_whitespace_is_stripped_from_every_field(
            self, load, corpus: Corpus):
        scenario = corpus.by_id("tig-05-at")
        run = load(lines=[feed_line(scenario) + "          "])
        assert run.row(scenario.edipi)["grade"] == scenario.grade

    def test_a_short_record_is_loaded_with_missing_trailing_fields(
            self, load, corpus: Corpus):
        """DEF-6: there is no length validation, so a truncated line still loads."""
        scenario = corpus.by_id("tig-05-at")
        cutoff = FIELDS["MM-PEBD"].offset
        run = load(lines=[feed_line(scenario)[:cutoff]])

        assert run.returncode == 0
        row = run.row(scenario.edipi)
        assert row is not None
        assert row["pebd"] in (None, "")
        assert row["dt_enlist"] in (None, "")
        assert "outside of string" in run.stderr

    def test_a_non_numeric_edipi_is_accepted(self, load, corpus: Corpus):
        """The feed is not validated, so junk propagates into the master table."""
        scenario = corpus.by_id("tig-05-at")
        line = "ABCDEFGHIJ" + feed_line(scenario)[10:]
        run = load(lines=[line])
        assert run.returncode == 0
        assert run.rows()[0]["edipi"] == "ABCDEFGHIJ"

    @pytest.mark.slow
    def test_commit_batching_does_not_lose_records_at_the_boundary(
            self, load, corpus: Corpus):
        """The loader commits every 5000 rows; 5001 exercises the boundary."""
        template = feed_line(corpus.by_id("tig-05-at"))
        lines = [str(2000000000 + i).zfill(10) + template[10:] for i in range(5001)]

        run = load(lines=lines)

        assert run.loaded == 5001
        assert len(run.rows()) == 5001


@pytest.mark.perl
class TestParityWithPerl:
    """Both loaders, same feed, same seed rows, same master table afterwards."""

    @pytest.fixture(autouse=True)
    def _require_perl(self):
        try:
            perl_loader.require_perl()
        except perl_loader.PerlUnavailable as exc:
            pytest.skip(str(exc))

    @staticmethod
    def _both(tmp_path, lines, seed=()):
        feed = perl_loader.write_feed(tmp_path / "unitdiary.dat", lines)
        seed = list(seed)
        runs = {}
        for name, engine in (("perl", perl_loader), ("python", python_loader)):
            workdir = tmp_path / name
            workdir.mkdir()
            runs[name] = engine.run(workdir, feed, seed=seed)
        return runs["perl"], runs["python"]

    def test_the_whole_corpus_lands_identically(self, tmp_path, corpus: Corpus):
        perl, python = self._both(tmp_path, [feed_line(s) for s in corpus.scenarios])

        assert python.returncode == perl.returncode == 0
        assert python.stdout == perl.stdout
        assert python.rows() == perl.rows()

    def test_the_carry_forward_paths_land_identically(self, tmp_path, corpus: Corpus):
        scenario = corpus.by_id("reduced-without-orig-promo")
        known = corpus.by_id("reduced-with-orig-promo")
        seed = [{"edipi": str(known.edipi), "dt_orig_promo": "19990101",
                 "grade_eff_dt": "20200101"}]
        lines = [feed_line(scenario), feed_line(known)]

        perl, python = self._both(tmp_path, lines, seed)

        assert python.stdout == perl.stdout
        assert python.rows() == perl.rows()

    def test_the_edge_cases_land_identically(self, tmp_path, corpus: Corpus):
        scenario = corpus.by_id("tig-05-at")
        line = feed_line(scenario)
        lines = [
            "",
            "   ",
            line + "          ",
            line[:FIELDS["MM-PEBD"].offset],
            line[:FIELDS["MM-GRADE-EFF-DT"].offset],
            "ABCDEFGHIJ" + line[10:],
            feed_line(corpus.by_id("grade-eff-dt-absent")),
        ]

        perl, python = self._both(tmp_path, lines)

        assert python.returncode == perl.returncode == 0
        assert python.stdout == perl.stdout
        assert python.rows() == perl.rows()

    def test_a_feed_of_only_blank_lines_lands_identically(self, tmp_path):
        perl, python = self._both(tmp_path, ["", "  ", "\t"])

        assert python.stdout == perl.stdout
        assert python.rows() == perl.rows() == []


@pytest.mark.docker
class TestPostgresTarget:
    """The same loader against the production target: typed columns, real schema.

    Only the scenarios whose dates are all populated are loaded. A zero-filled
    date other than GRADE_EFF_DT is written through as ``'00000000'``, which a
    DATE column rejects -- the Perl loader issues the identical statement with
    the identical value, so this is the schema's behavior, not the rewrite's.
    """

    LOADABLE = ("reduced-with-orig-promo", "not-reduced-with-orig-promo",
                "reduced-without-orig-promo")

    @pytest.fixture
    def container(self, pg_container):
        return pg_container

    @pytest.fixture
    def feed(self, tmp_path, corpus: Corpus):
        return perl_loader.write_feed(
            tmp_path / "unitdiary.dat",
            [feed_line(corpus.by_id(i)) for i in self.LOADABLE])

    def test_the_feed_upserts_into_the_production_schema(
            self, container, feed, corpus: Corpus):
        first = python_loader_pg.run(container, feed)
        assert first.returncode == 0, first.stderr
        assert f"loaded {len(self.LOADABLE)} records, 1 carried forward" in first.stdout
        assert len(python_loader_pg.rows(container)) == len(self.LOADABLE)

        # Second pass over the same feed updates rather than duplicating.
        second = python_loader_pg.run(container, feed)
        assert second.returncode == 0, second.stderr
        assert len(python_loader_pg.rows(container)) == len(self.LOADABLE)

    def test_dates_and_the_carry_forward_column_land_as_they_do_on_sqlite(
            self, container, feed, corpus: Corpus):
        assert python_loader_pg.run(container, feed).returncode == 0
        rows = {row.split(",")[0]: row.split(",")
                for row in python_loader_pg.rows(container)}

        reduced = corpus.by_id("reduced-with-orig-promo")
        row = rows[str(reduced.edipi)]
        assert row[1].strip() == reduced.grade
        assert int(row[2]) == reduced.grade_num
        assert row[4].replace("-", "") == str(reduced.dt_orig_promo)

        # DEF-7: inserted on the carry-forward path, so there is no orig promo.
        assert rows[str(corpus.by_id("reduced-without-orig-promo").edipi)][4] == ""


class TestParsing:
    """The parsing is pure, so it needs neither a feed file nor a database."""

    def test_the_layout_comes_from_the_copybook(self):
        for column, name in unit_diary.COLUMN_FIELDS:
            field = FIELDS[name]
            layout = next(f for f in unit_diary.LAYOUT if f.column == column)
            assert (layout.offset, layout.length) == (field.offset, field.length)

    def test_the_package_and_the_harness_parse_the_copybook_the_same_way(self):
        mine = {name: (f.offset, f.length, f.packed)
                for name, f in copybook.FIELDS.items()}
        harness = {name: (f.offset, f.length, f.packed) for name, f in FIELDS.items()}
        assert mine == harness

    def test_def8_six_fields_the_batch_reads_are_never_loaded(self):
        """The rewrite maintains exactly the 13 columns the Perl loader does."""
        never_loaded = {"duty_stat", "component", "rc_drill_stat", "brk_svc_mos",
                        "adv_matl_ind", "adv_matl_mos"}
        assert not (set(unit_diary.LOADED_COLUMNS) & never_loaded)
        assert set(unit_diary.LOADED_COLUMNS) == set(perl_loader.LOADED_COLUMNS)

    def test_every_field_is_stripped(self, corpus: Corpus):
        scenario = corpus.by_id("tig-05-at")
        record = unit_diary.parse_line(feed_line(scenario)).record

        assert record.last_nm == scenario.last_nm
        assert record.grade == scenario.grade
        assert record.grade_num == str(scenario.grade_num).zfill(2)

    def test_a_zero_filled_grade_effective_date_is_dropped(self, corpus: Corpus):
        record = unit_diary.parse_line(
            feed_line(corpus.by_id("grade-eff-dt-absent"))).record
        assert record.grade_eff_dt is None
        assert "grade_eff_dt" not in record.columns()

    def test_a_reduction_without_an_original_promotion_date_drops_the_column(
            self, corpus: Corpus):
        parsed = unit_diary.parse_line(
            feed_line(corpus.by_id("reduced-without-orig-promo")))
        assert parsed.carried_forward
        assert "dt_orig_promo" not in parsed.record.columns()

    def test_a_reduction_with_an_original_promotion_date_keeps_the_column(
            self, corpus: Corpus):
        scenario = corpus.by_id("reduced-with-orig-promo")
        parsed = unit_diary.parse_line(feed_line(scenario))
        assert not parsed.carried_forward
        assert parsed.record.dt_orig_promo == str(scenario.dt_orig_promo)

    def test_a_short_line_warns_but_still_parses(self, corpus: Corpus):
        """DEF-6 again, without the database: no rejection, just NULL columns."""
        line = feed_line(corpus.by_id("tig-05-at"))[:FIELDS["MM-PEBD"].offset]
        parsed = unit_diary.parse_line(line)

        assert parsed.record.pebd == ""
        assert parsed.record.dt_enlist is None
        assert "dt_enlist" not in parsed.record.columns()
        assert any("outside of string" in w for w in parsed.warnings)

    def test_blank_lines_produce_no_records(self, corpus: Corpus):
        lines = ["", "   \n", feed_line(corpus.by_id("tig-05-at")) + "\n"]
        assert len(list(unit_diary.parse_feed(lines))) == 1

    def test_zero_filled_covers_absent_empty_and_all_zero(self):
        assert unit_diary.is_zero_filled(None)
        assert unit_diary.is_zero_filled("")
        assert unit_diary.is_zero_filled("00000000")
        assert not unit_diary.is_zero_filled("19990101")

    def test_substr_matches_perl_out_of_range_semantics(self):
        assert unit_diary.substr("abc", 0, 2) == "ab"
        assert unit_diary.substr("abc", 1, 8) == "bc"
        assert unit_diary.substr("abc", 3, 8) == ""
        assert unit_diary.substr("abc", 4, 8) is None
