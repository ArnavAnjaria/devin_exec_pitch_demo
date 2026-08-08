# Promotion Eligibility Determination

Batch and service components supporting promotion eligibility determination for enlisted
personnel records.

## Components

| Path | What it is |
|---|---|
| `cobol/PROMELIG.cbl` | Nightly batch eligibility determination. Authoritative for the board slate. |
| `cobol/copybook/MARREC.cpy` | Master record layout. Shared with the unit diary feed. |
| `jcl/PROMELIG.jcl` | Job control for the nightly run. |
| `sql/promotion_eligibility.sql` | Stored procedure backing the reporting extract. |
| `perl/load_unit_diary.pl` | Fixed-width unit diary feed loader. |
| `java/src/main/java/mil/usmc/manpower/promotion/` | Eligibility lookup for the self-service web front end. |
| `tests/` | Characterization suite covering all five components. |

## Run order

The nightly cycle runs `load_unit_diary.pl`, then `PROMELIG.jcl`, then refreshes the reporting
extract. `EligibilityService` reads the same master table but computes independently so the
web tier does not depend on batch completion.

## Notes

- Grade tables are maintained in `sql/ref_grade_requirements.sql` and are read by the stored
  procedure. The COBOL carries its own copy in WORKING-STORAGE.
- Reserve component records were folded into the same layout in the 1994 revision. Some fields
  are only populated for one component.
- The web tier was added in 2003. The original intent was to retire the batch determination
  once the service reached parity. That did not happen.

## Tests

```
make test        # every suite (GnuCOBOL, JDK 17, perl + DBD::SQLite, Docker)
make test-fast   # skips the slow suites
```

The suite records current behavior so components can be replaced one at a time.
Start with [`docs/testing.md`](docs/testing.md); the behavior that differs
between the three implementations is catalogued in
[`docs/divergence-register.md`](docs/divergence-register.md) and the bugs found
along the way are in [`docs/defects.md`](docs/defects.md).

The Java sources moved into a Maven layout under `java/` so the service can be
compiled and tested; `MarineMaster`, `EligibilityResult`, `GradeRequirement` and
the two repository interfaces were reconstructed from their call sites, since
they were not in the original drop.

## Ownership

Original authors are no longer with the program. Change requests route through the
sustainment queue.
