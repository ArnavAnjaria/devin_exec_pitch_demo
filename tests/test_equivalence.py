"""Cross-engine equivalence.

This is the gate for modernization work: a rewritten component must keep the
engines disagreeing in exactly the places tests/divergences.yaml already
describes, and nowhere else.
"""

from __future__ import annotations

import pytest

from harness import equivalence
from harness.model import Corpus


@pytest.fixture(scope="module")
def disagreements(corpus):
    return equivalence.compare_engines(corpus)


@pytest.fixture(scope="module")
def register():
    return equivalence.load_register()


def test_no_unregistered_disagreements(disagreements, register):
    known = equivalence.registered_scenarios(register)
    unexpected = sorted({d.scenario_id for d in disagreements} - set(known))
    detail = "\n".join(
        f"  {d.scenario_id}: {d.detail}" for d in disagreements
        if d.scenario_id in unexpected)
    assert not unexpected, (
        "engines disagree on scenarios that are not in tests/divergences.yaml:\n" + detail)


def test_every_registered_divergence_still_reproduces(disagreements, register):
    observed = {d.scenario_id for d in disagreements}
    known = equivalence.registered_scenarios(register)
    resolved = sorted(set(known) - observed)
    assert not resolved, (
        "these scenarios no longer diverge; remove them from tests/divergences.yaml: "
        + ", ".join(f"{s} ({known[s]})" for s in resolved))


def test_the_engines_agree_on_everything_else(corpus: Corpus, disagreements, register):
    known = equivalence.registered_scenarios(register)
    agreeing = len(corpus.scenarios) - len({d.scenario_id for d in disagreements})
    assert agreeing == len(corpus.scenarios) - len(known)
    assert agreeing > 0.8 * len(corpus.scenarios), (
        "the engines now agree on less than 80% of the corpus")


def test_register_entries_are_complete(register):
    ids = set()
    for entry in register["divergences"]:
        for field in ("id", "title", "engines", "target", "cause", "impact", "scenarios"):
            assert entry.get(field), f"{entry.get('id')} is missing {field}"
        assert entry["target"] in (*equivalence.ENGINES, "undecided")
        assert set(entry["engines"]) <= set(equivalence.ENGINES)
        ids.add(entry["id"])
    assert len(ids) == len(register["divergences"])


def test_register_scenarios_exist_in_the_corpus(corpus: Corpus, register):
    for scenario_id in equivalence.registered_scenarios(register):
        corpus.by_id(scenario_id)


def test_a_scenario_appears_in_at_most_one_register_entry(register):
    seen = []
    for entry in register["divergences"]:
        seen.extend(entry["scenarios"])
    assert len(seen) == len(set(seen))


def test_generated_register_document_is_current(register):
    assert equivalence.REGISTER_DOC.read_text() == equivalence.render_register(register), (
        "docs/divergence-register.md is stale; run make docs")


def test_report_renders(corpus: Corpus, capsys):
    text = equivalence.report(corpus)
    assert "UNREGISTERED" not in text
    for entry_id in {e["id"] for e in equivalence.load_register()["divergences"]}:
        assert entry_id in text
