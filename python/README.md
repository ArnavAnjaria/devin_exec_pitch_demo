# `promelig`

Python replacements for the legacy promotion eligibility components, migrated
one at a time. Standard library only.

| Module | Replaces |
| --- | --- |
| `promelig/eligibility.py` | `java/.../EligibilityService.java` — the web tier's real-time single-record determination |
| `promelig/model.py` | `MarineMaster`, `EligibilityResult`, `GradeRequirement` |
| `promelig/monthmath.py` | `EligibilityService.monthsBetween` |
| `promelig/marrec.py` | reads the fixed-width master file, offsets parsed from `cobol/copybook/MARREC.cpy` |
| `promelig/cli_web.py` | `promelig-eligibility --master …`, the batch-shaped entry point the Java service never had |

Each replacement reproduces its engine's current behavior, including the
defects in [`docs/defects.md`](../docs/defects.md) and the divergences in
[the register](../docs/divergence-register.md). It is pinned to that engine's
golden file: `tests/test_python_web.py` asserts the web-tier rewrite produces
`tests/golden/java.csv` byte for byte, and `python_web` is compared against
every other engine by `tests/test_equivalence.py`.

```
python3 -m promelig.cli_web --master MASTER.DAT --as-of 2026-06-15
python3 -m promelig.cli_web --master MASTER.DAT --as-of 2026-06-15 --edipi 1000000003
```

The package is not installed by the test suite; `tests/conftest.py` puts this
directory on `sys.path`.
