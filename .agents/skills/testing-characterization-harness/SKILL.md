---
name: testing-characterization-harness
description: How to run, verify and adversarially probe the legacy promotion-eligibility characterization test harness (COBOL/Java/Perl/SQL/JCL) in this repo.
---

# Testing the characterization harness

## Running
- `make test` = `pytest tests -v` + `cd java && mvn -B test`. Whole thing is ~11-13s on a warm box.
- `make test-fast` (~3s) only deselects the 2 tests marked `slow`; it still needs cobc and docker.
- `make golden` regenerates the corpus and rewrites every golden. On an unmodified tree it must
  produce a zero `git diff` — that is the fastest honesty check of the goldens.
- CI equivalent of the "nothing drifted" gate: `git diff --exit-code tests/golden tests/corpus docs`
  and `python3 -m flake8 tests`.

## Toolchain
Needs `cobc` (GnuCOBOL), `docker` (pulls `postgres:16-alpine`), `perl` + DBD::SQLite, JDK 17 + Maven.
Pre-pull the postgres image; otherwise the first SQL run pays a ~294MB download that is easy to
mistake for a hang. The SQL engine starts a `promelig-test-<hex>` container with `--rm` and removes
it in a `finally`, so `docker ps -a` should be empty afterwards — check this after any interrupted run.

## How to test a tooling-gate claim ("suites skip when the tool is missing")
Do NOT build a small PATH directory with a handful of symlinks: `cobc` shells out to `gcc`/`as`/`ld`,
so a sparse PATH makes COBOL builds fail for the wrong reason and produces bogus failures. Instead
mirror the entire PATH and omit exactly one binary:

```
mkdir -p /tmp/noX
for d in $(echo $PATH | tr ':' ' '); do for f in "$d"/*; do b=$(basename "$f");
  [ "$b" = cobc ] && continue; [ -e /tmp/noX/$b ] || ln -s "$f" /tmp/noX/$b 2>/dev/null; done; done
PATH=/tmp/noX python3 -m pytest tests -q -rf
```

Skipping is driven by the `cobol`, `perl` and `docker` markers via `pytest_runtest_setup` in
`tests/conftest.py`, not by the fixtures — a test that drives an engine without the matching marker
will fail instead of skipping when its toolchain is absent. Expected counts with one tool hidden:
no `cobc` 92 passed / 55 skipped, no `docker` 117 / 30, no `perl` 133 / 14.

## Adversarial probes that actually distinguish working from broken
Each perturbation below must make a named test fail; revert with `git checkout <file>` afterwards
and confirm `git status --porcelain` is empty.

| Perturbation | Expected failure |
| --- | --- |
| `V_ADV_LOOKBACK_MOS INTEGER := 12` -> 24 in `tests/sql/sp_promotion_eligibility_pg.sql` | `test_sql_extract.py::test_matches_golden`, the two `..._still_twelve_months[12/23]` cases, and `TestTranslationFidelity::test_adverse_lookback_is_carried_over_unchanged` |
| `WS-ADV-LOOKBACK-MOS ... VALUE 024` -> 012 in `cobol/PROMELIG.cbl` | `test_cobol_batch.py::test_matches_golden` + `test_adverse_material_lookback_is_24_months[12/23]` |
| any value change in `tests/corpus/scenarios.yaml` | `test_corpus.py::test_checked_in_corpus_matches_the_builder` ("stale") |
| drop a scenario id from `tests/divergences.yaml` | `test_equivalence.py::test_no_unregistered_disagreements` |
| add a non-diverging scenario id to a register entry | `test_equivalence.py::test_every_registered_divergence_still_reproduces` ("no longer diverge") |

Edit `scenarios.yaml` by replacing a *value* substring; inserting a bare word before a quoted scalar
produces invalid YAML and makes 13 tests error at collection instead of the one staleness assertion.

## Important nuance about the equivalence gate
`tests/harness/equivalence.py::compare_engines` reads `tests/golden/*.csv`, not live engine output.
So `test_equivalence.py` alone will NOT notice an engine that has drifted — it only notices changes
to the goldens/register. The live-vs-golden check lives in each suite's `test_matches_golden`.
Always run the per-engine suites too when judging whether behavior changed.

## Devin Secrets Needed
None. The repo is public and every engine runs locally.
