"""The corpus itself: reproducible, unique, and covering every rule branch."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "corpus"))

import build_corpus  # noqa: E402
from harness.model import CORPUS_PATH, Corpus, dump_corpus  # noqa: E402
from harness.model import DENY_REASONS  # noqa: E402
from harness.normalize import GRADE_REQUIREMENTS  # noqa: E402
from harness.scenario_csv import SCENARIO_COLUMNS, dump_scenario_csv  # noqa: E402


def test_checked_in_corpus_matches_the_builder(tmp_path):
    rebuilt = build_corpus.build()
    dump_corpus(rebuilt, tmp_path / "scenarios.yaml")
    assert (tmp_path / "scenarios.yaml").read_text() == CORPUS_PATH.read_text(), (
        "tests/corpus/scenarios.yaml is stale; rerun tests/corpus/build_corpus.py"
    )


def test_checked_in_scenario_csv_matches_the_builder(tmp_path):
    rebuilt = build_corpus.build()
    dump_scenario_csv(rebuilt, tmp_path)
    for name in ("scenarios.csv", "as_of.txt"):
        assert (tmp_path / name).read_text() == (CORPUS_PATH.parent / name).read_text(), (
            f"tests/corpus/{name} is stale; rerun tests/corpus/build_corpus.py"
        )


def test_scenario_ids_and_edipis_are_unique(corpus: Corpus):
    ids = [s.id for s in corpus.scenarios]
    edipis = [s.edipi for s in corpus.scenarios]
    assert len(set(ids)) == len(ids)
    assert len(set(edipis)) == len(edipis)


def test_every_scenario_is_documented(corpus: Corpus):
    for scenario in corpus.scenarios:
        assert scenario.note.strip(), f"{scenario.id} has no note"
        assert scenario.tags, f"{scenario.id} has no tags"


def test_no_free_text_field_needs_csv_quoting(corpus: Corpus):
    for scenario in corpus.scenarios:
        for column in SCENARIO_COLUMNS:
            value = getattr(scenario, column)
            if isinstance(value, str):
                assert "," not in value and '"' not in value


@pytest.mark.parametrize("target_grade", sorted(GRADE_REQUIREMENTS))
def test_every_grade_has_threshold_scenarios_on_both_axes(corpus: Corpus, target_grade: int):
    for axis in ("tig", "tis"):
        for label in ("below", "at", "above"):
            corpus.by_id(f"{axis}-{target_grade:02d}-{label}")


def test_every_deny_reason_is_exercised(corpus: Corpus, cobol_rows):
    produced = {row.deny_rsn for row in cobol_rows if row.deny_rsn}
    assert produced == set(DENY_REASONS)


def test_corpus_covers_the_documented_edge_categories(corpus: Corpus):
    tags = {tag for scenario in corpus.scenarios for tag in scenario.tags}
    assert {
        "threshold", "precedence", "adverse", "reduction", "break-in-service",
        "dates", "component", "grade-boundary", "divergence", "dirty", "fallback",
    } <= tags
