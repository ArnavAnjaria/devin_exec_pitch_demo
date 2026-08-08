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
| `java/EligibilityService.java` | Eligibility lookup for the self-service web front end. |

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

## Ownership

Original authors are no longer with the program. Change requests route through the
sustainment queue.
