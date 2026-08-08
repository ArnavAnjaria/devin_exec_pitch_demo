---
name: testing-promelig-parity
description: How to run and adversarially test the PROMELIG legacy batch and its Python replacement, including live GnuCOBOL-vs-Python byte parity outside pytest.
---

# Testing PROMELIG (COBOL batch and its Python port)

This repo is a characterization harness for a COBOL/JCL/Java/Perl/SQL promotion
eligibility system being ported to Python one component at a time. The contract
is byte-for-byte parity with the legacy engine, **defects included** — never
"fix" behavior while testing.

## Running the suites

```
make test                    # pytest (all engine suites) + Maven
make test-fast               # skips the two slow tests
python3 -m flake8 tests python   # note: `python/` too, not just `tests/`
make equivalence             # cross-engine report from the recorded goldens
```

Toolchains: `cobc` (GnuCOBOL), JDK 17 + Maven, `perl` + DBD::SQLite, Docker.
Suites whose tool is missing **skip silently** (markers `cobol`, `perl`,
`docker` in `tests/conftest.py`). Always confirm the engine suite actually ran,
e.g. `python3 -m pytest tests -q -m cobol` — a green run with everything skipped
proves nothing.

## Driving the engines directly (outside pytest)

Live GnuCOBOL run — build with the two defect workaround patches, then bind DD
names and the clock through the environment:

```python
from harness.engines import cobol as cobol_engine   # sys.path must include tests/
exe = cobol_engine.build(workdir)                   # applies tests/cobol/patches/*
env = {"DD_MSTRIN": master, "DD_ELIGOUT": elig, "DD_RPTOUT": rpt,
       "COB_CURRENT_DATE": "2026/06/15 00:00:00"}   # PROMELIG uses ACCEPT FROM DATE
```

Python replacement:

```
PYTHONPATH=python python3 -m promelig.batch --master M --elig-out E --report-out R --run-date CCYYMMDD
PYTHONPATH=python python3 -m promelig.job   --master M --elig-out E --work-dir W --run-date CCYYMMDD [--extract-command CMD]
PROMELIG_MASTER=... PROMELIG_ELIG_OUT=... PROMELIG_REPORT_OUT=... \
PROMELIG_WORK_DIR=... PROMELIG_RUN_DATE=... [PROMELIG_EXTRACT_COMMAND=...] python/run_promelig.sh
```

Build master files with `harness.marrec.encode(scenario, 140)` /
`write_master_file`; never hand-count offsets — read them from
`harness.marrec.FIELDS` (`MM-GRADE` is at offset 57, `MM-DT-LAST-PROMO` at 66,
`MM-PEBD` at 90). Hand-typed offsets are the easiest way to produce a bogus
"divergence".

Compare ELIGOUT at the byte level but ignore the trailing filler: only bytes
`[0:35]` of each 60-byte record are data (edipi 0:10, grade 10:13, tgt 13:15,
tig 15:18, tis 18:22, elig ind 22, deny 23:27, run date 27:35). Under GnuCOBOL
the first record's filler is low-values, not spaces.

## Adversarial angles that actually find things

- Re-run the same master under several run dates (`COB_CURRENT_DATE` vs
  `--run-date`) and assert the extracts differ between dates — otherwise a
  parity test can pass while the date is ignored.
- Feed malformed numeric DISPLAY fields: blanks, alphabetic bytes, and
  **numerically valid but calendar-invalid dates** (`00000101`, `20241332`,
  `20101300`). The Python port may raise an unhandled `ValueError` from
  `copybook.to_date` and abort the whole run while COBOL completes with RC=0 —
  check this whenever `to_date`/date decoding changes.
- Masters whose length is not a multiple of 140, and absent masters (batch must
  exit 16, job must stop after STEP020 per `COND=(0,NE)`).
- Mutation check: temporarily flip a constant (e.g. `ADV_LOOKBACK_MOS` 24→12)
  and confirm the parity comparison fails, proving the harness can detect
  breakage. **After reverting, delete `__pycache__`** — a same-second edit and
  `git checkout` can leave a stale `.pyc` that keeps the mutation live and
  produces phantom test failures:
  `find . -name __pycache__ -type d -exec rm -rf {} +`

## Devin Secrets Needed

None — everything runs locally.
