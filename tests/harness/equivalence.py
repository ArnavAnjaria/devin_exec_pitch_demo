"""Cross-engine comparison of the three eligibility determinations.

The COBOL batch, the Java web service and the SQL reporting extract each decide
promotion eligibility independently. This compares them scenario by scenario and
reports where they disagree, so modernization work can be gated on "no new
disagreements" rather than on any one engine being right.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Optional

import yaml

from .golden import golden_path
from .model import REPO_ROOT, Corpus
from .normalize import Row, read_rows

ENGINES = ("cobol", "java", "sql")
REGISTER_PATH = REPO_ROOT / "tests" / "divergences.yaml"
MISSING = "no row"


@dataclass(frozen=True)
class Disagreement:
    scenario_id: str
    engine_a: str
    engine_b: str
    detail: str

    @property
    def pair(self) -> tuple[str, str]:
        return (self.engine_a, self.engine_b)


def load_golden(engine: str) -> dict[int, Row]:
    return {row.edipi: row for row in read_rows(golden_path(engine))}


def _describe(row: Optional[Row]) -> str:
    if row is None:
        return MISSING
    return (f"tgt={row.tgt_grade} tig={row.tig_mos} tis={row.tis_mos} "
            f"elig={row.elig_ind} deny={row.deny_rsn or '-'}")


def compare_engines(corpus: Corpus,
                    goldens: Optional[dict[str, dict[int, Row]]] = None) -> list[Disagreement]:
    goldens = goldens or {engine: load_golden(engine) for engine in ENGINES}
    out: list[Disagreement] = []
    for scenario in corpus.scenarios:
        for a, b in combinations(ENGINES, 2):
            row_a = goldens[a].get(scenario.edipi)
            row_b = goldens[b].get(scenario.edipi)
            if row_a == row_b:
                continue
            out.append(Disagreement(scenario.id, a, b,
                                    f"{a}: {_describe(row_a)} | {b}: {_describe(row_b)}"))
    return out


def load_register(path: Path = REGISTER_PATH) -> dict:
    return yaml.safe_load(path.read_text())


def registered_scenarios(register: Optional[dict] = None) -> dict[str, str]:
    """scenario id -> divergence register entry id."""
    register = register or load_register()
    out = {}
    for entry in register["divergences"]:
        for scenario_id in entry["scenarios"]:
            out[scenario_id] = entry["id"]
    return out


def report(corpus: Corpus) -> str:
    disagreements = compare_engines(corpus)
    known = registered_scenarios()
    by_scenario: dict[str, list[Disagreement]] = {}
    for item in disagreements:
        by_scenario.setdefault(item.scenario_id, []).append(item)

    lines = [
        "Cross-engine equivalence report",
        "=" * 31,
        f"scenarios: {len(corpus.scenarios)}   as of: {corpus.as_of}",
        f"scenarios where all three engines agree: "
        f"{len(corpus.scenarios) - len(by_scenario)}",
        f"scenarios with a disagreement: {len(by_scenario)}",
        "",
    ]
    for scenario_id in sorted(by_scenario):
        entry = known.get(scenario_id, "UNREGISTERED")
        lines.append(f"[{entry}] {scenario_id}")
        lines.append(f"    {corpus.by_id(scenario_id).note}")
        for item in by_scenario[scenario_id]:
            lines.append(f"    {item.engine_a} vs {item.engine_b}: {item.detail}")
        lines.append("")
    return "\n".join(lines)


REGISTER_DOC = REPO_ROOT / "docs" / "divergence-register.md"


def render_register(register: Optional[dict] = None) -> str:
    """docs/divergence-register.md, generated from tests/divergences.yaml."""
    register = register or load_register()
    lines = [
        "# Divergence register",
        "",
        "Where the COBOL batch, the Java web service and the SQL reporting extract",
        "disagree about the same Marine. Generated from `tests/divergences.yaml` by",
        "`make docs`; edit the YAML, not this file.",
        "",
        "`tests/test_equivalence.py` fails if the engines disagree anywhere that is not",
        "listed below, and fails if a listed divergence stops reproducing.",
        "",
        "| ID | Divergence | Target behavior | Scenarios |",
        "| --- | --- | --- | --- |",
    ]
    for entry in register["divergences"]:
        scenarios = ", ".join(f"`{s}`" for s in entry["scenarios"])
        lines.append(f"| {entry['id']} | {entry['title']} | {entry['target']} | {scenarios} |")
    lines.append("")

    for entry in register["divergences"]:
        lines += [
            f"## {entry['id']}: {entry['title']}",
            "",
            f"**Engines:** {', '.join(entry['engines'])}  ",
            f"**Target behavior:** {entry['target']}",
            "",
            f"**Cause.** {entry['cause'].strip()}",
            "",
            f"**Impact.** {entry['impact'].strip()}",
            "",
        ]
        if entry.get("review"):
            lines += [f"**Needs review.** {entry['review'].strip()}", ""]
        lines += ["**Scenarios.** " + ", ".join(f"`{s}`" for s in entry["scenarios"]), ""]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    from .model import load_corpus

    if "--write-doc" in sys.argv:
        REGISTER_DOC.parent.mkdir(exist_ok=True)
        REGISTER_DOC.write_text(render_register())
        print(f"wrote {REGISTER_DOC.relative_to(REPO_ROOT)}")
    else:
        print(report(load_corpus()))
