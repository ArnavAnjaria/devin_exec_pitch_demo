# Testing

The suite here is a characterization harness: it records what the legacy system
does today so each component can be replaced with something that behaves the
same. It is not a specification. Where the current behavior is wrong it is
pinned anyway and written down in [`defects.md`](defects.md); where the engines
disagree with each other it is pinned three times and written down in
[the divergence register](divergence-register.md).

## Running it

```
make test          # everything
make test-fast     # skips the suites marked slow
make test-python   # COBOL, Perl, SQL, JCL, corpus, equivalence
make test-java     # web tier
make equivalence   # print the cross-engine comparison
```

Requirements:

| Suite | Needs |
| --- | --- |
| COBOL | GnuCOBOL (`apt install gnucobol`) |
| Java | JDK 17, Maven |
| Perl | `perl`, DBD::SQLite (`apt install libdbd-sqlite3-perl`) |
| SQL | Docker (`postgres:16-alpine`) |
| JCL, corpus, equivalence | Python 3 only |

Suites whose tooling is missing skip rather than fail, so a partial environment
still gives useful signal. CI installs all of it.

## How it fits together

```
tests/corpus/build_corpus.py
        │  one scenario list, expressed in copybook terms
        ▼
tests/corpus/scenarios.yaml ──► scenarios.csv (for the Java suite)
        │
        ├─► marrec.encode()      ──► 140-byte master file  ──► PROMELIG (GnuCOBOL)
        ├─► Corpus.load()        ──► MarineMaster objects  ──► EligibilityService
        ├─► postgres.load_corpus ──► MARINE_MASTER rows     ──► SP_PROMOTION_ELIGIBILITY
        └─► marrec.feed_line()   ──► unit diary feed        ──► load_unit_diary.pl
                                                │
                                                ▼
                        normalized rows: edipi,tgt_grade,tig_mos,tis_mos,elig_ind,deny_rsn
                                                │
                        tests/golden/*.csv ─────┴───► tests/test_equivalence.py
```

Every engine gets the same 88 scenarios, and every engine's answer is reduced to
the same six columns. Normalization happens only at the comparison boundary:
`'TIG '` from COBOL and `"TIG"` from Java compare equal, but a different *answer*
never does.

### The corpus

`tests/corpus/scenarios.yaml` is generated, not hand-edited — run `make corpus`
after changing `build_corpus.py`, and a test fails if the two drift apart. Each
scenario has a stable id, a stable EDIPI, a note explaining what it is for, and
tags. Dates are computed backwards from a fixed as-of date (`2026-06-15`) so the
suite does not rot.

Coverage is deliberate rather than random: both thresholds at minus-one, exactly,
and plus-one for all eight grades; every denial reason and every precedence pair;
the adverse lookback at 0, 11, 12, 23, 24 and 25 months; reduction with and
without an original promotion date; break in service at 0, 6 and beyond the
accrued time; month-end, leap-day, exact-anniversary and future dates; both
components against all three drill statuses; and the grade boundaries at 0 and 9.

### Golden files

`tests/golden/*.csv` are the recorded answers. To change them:

```
make golden        # regenerates the corpus, then rewrites every golden
git diff tests/golden
```

The diff is the review artifact. A golden change in a PR that was not supposed to
change behavior is the bug.

### The COBOL patches

`PROMELIG.cbl` cannot run to completion as written (DEF-1) and cannot read a
correctly sized record (DEF-2). Rather than edit the source, the harness copies
it into a build directory and applies `tests/cobol/patches/*.patch` there. The
production source stays untouched, the patches document exactly what is broken,
and `tests/test_defects.py` builds *without* each patch to prove the defect still
reproduces. When a defect is fixed for real, its patch stops applying and is
deleted.

### The PostgreSQL translation

Oracle is not available, so `tests/sql/sp_promotion_eligibility_pg.sql` is a port
of the extract, and `TestTranslationFidelity` compares it against the Oracle
original: predicate order, the 12-month lookback, the inner join, the grade
filter, the month arithmetic. `ORACLE_MONTHS_BETWEEN` and `ORACLE_GREATEST`
reproduce the two Oracle semantics that PostgreSQL does not share (fractional
months in 31ths, and NULL propagation through `GREATEST`), and both are tested
against known Oracle values.

## Modernization workflow

Each component is migrated in its own session. The rules are the same for all of
them:

1. **Do not touch the corpus or the goldens.** A rewrite proves itself by
   reproducing `tests/golden/<engine>.csv`, so a session that edits the goldens
   has proved nothing. Add scenarios freely; changing existing ones needs review.
2. **Register the engine.** A Python replacement produces the same six normalized
   columns, gets a golden of its own, and joins `ENGINES` in
   `tests/harness/equivalence.py`. `test_no_unregistered_disagreements` then holds
   it to the same standard as the legacy engines.
3. **Reproduce, do not improve.** Bugs stay bugs until their ticket is worked. A
   rewrite that quietly fixes the truncation in DEF-4 is indistinguishable, in the
   diff, from one that broke it.
4. **Divergences resolve toward Java** (program decision, 2026-08), but not in the
   migration PR. Land the like-for-like rewrite green, then change the behavior in
   a separate PR whose whole diff is the divergence being closed, so the roster
   change has something to point at. DIV-3 and DIV-5 need an owner ruling first.
5. **Defects are separate tickets.** `docs/defects.md` lists them with their
   reproductions.

The suites are independent, so the COBOL, Perl, SQL and web-tier migrations can
run in parallel. `tests/test_equivalence.py` is the join point: it is what
catches a rewrite that is self-consistent but no longer agrees with the systems
it has to live alongside.
