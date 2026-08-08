# Known defects

Defects found while building the characterization suite. None of them are fixed
here: the suite pins current behavior so the fixes can be reviewed one at a time
against a green baseline. Each has an executable reproduction in
`tests/test_defects.py`, which fails when the defect is fixed — that is the
signal to update the test and close the ticket.

Behavior that differs between the three engines but is not obviously a bug is in
[the divergence register](divergence-register.md) instead.

| ID | Component | Severity | Summary |
| --- | --- | --- | --- |
| DEF-1 | `cobol/PROMELIG.cbl` | critical | The batch never advances past the first record it evaluates |
| DEF-2 | `cobol/copybook/MARREC.cpy` | critical | Copybook is 137 bytes, the FD declares 140 |
| DEF-3 | `jcl/PROMELIG.jcl` | high | `INCLUDE COND` filters on the wrong bytes |
| DEF-4 | `cobol/PROMELIG.cbl` | medium | Month counters are truncated on output |
| DEF-5 | `cobol/PROMELIG.cbl` | medium | Report counters are written as packed decimal into a character report |
| DEF-6 | `perl/load_unit_diary.pl` | high | No record length validation |
| DEF-7 | `perl/load_unit_diary.pl` | medium | Carry-forward silently loses the original promotion date on an insert |
| DEF-8 | `perl/load_unit_diary.pl` | medium | The loader never maintains six of the fields the batch reads |
| DEF-9 | `sql/promotion_eligibility.sql` | high | Adverse material lookback was never updated to 24 months (also DIV-1) |

## DEF-1 — the batch never advances past the first record it evaluates

`2400-APPLY-RULES` ends every branch with `GO TO 2490-EXIT`, but `2000-PROCESS`
performs it as a single paragraph, so `2490-EXIT` is outside the performed
range. Control falls out of the `PERFORM` and runs straight into `2500-WRITE-ELIG`
and then `9000-TERM`, which closes all three files. `2900-NEXT` — the only place
the next master record is read — is reached only on the grade ≥ 9 bypass path.

Observed with a two-record master:

- both records denied: the job ends with `RC=0` after writing **one** record.
  The board slate is silently short and nothing reports an error.
- first record eligible: the loop never terminates. Locally it wrote 4 GB to
  `ELIGOUT` before being killed.

Which of the two happens depends on the first record in the sorted master, so in
production this presents as an intermittent overnight failure.

Reproduced by `test_def1_unpatched_batch_drops_every_record_after_the_first_denial`
and `test_def1_unpatched_batch_loops_forever_on_an_eligible_record`.
Worked around for testing by `tests/cobol/patches/0001-def1-control-flow.patch`.

**Fix.** `PERFORM 2400-APPLY-RULES THRU 2490-EXIT`, and perform `2900-NEXT` on
both the bypass and the evaluated path.

## DEF-2 — copybook is 137 bytes, the FD declares 140

`MARREC.cpy` fields total 137 bytes; `FD MASTER-FILE` declares
`RECORD CONTAINS 140 CHARACTERS`. On the mainframe the record area is padded and
the discrepancy is invisible; anywhere else the reader takes the file as variable
length and every field after the first record is offset.

Reproduced by `test_def2_copybook_is_shorter_than_the_declared_record_length` and
`test_def2_record_length_mismatch_shifts_every_field`. Worked around for testing
by `tests/cobol/patches/0002-def2-record-length.patch`, which widens the trailing
`FILLER` from 21 to 24 bytes.

**Fix.** Widen the copybook filler. Do not shrink the FD: the master dataset is
allocated `LRECL=140`.

## DEF-3 — `INCLUDE COND` filters on the wrong bytes

`INCLUDE COND=(58,2,ZD,LT,09)` is meant to drop grade 9 before the batch runs.
Position 58 is the start of `MM-GRADE` (`SGT`, `CPL`, …), not `MM-GRADE-NUM`,
which starts at position 61. The filter compares two alphabetic bytes as zoned
decimal, so its result is whatever the collating sequence produces.

The step is redundant anyway — `2000-PROCESS` applies the same rule — which is
why nobody has noticed.

Reproduced by `test_def3_jcl_include_filter_points_at_the_wrong_field` and
`test_the_include_filter_reads_non_numeric_data`.

**Fix.** `INCLUDE COND=(61,2,ZD,LT,09)`, or drop the filter and let the program
own the rule.

## DEF-4 — month counters are truncated on output

`WS-TIG-MOS`/`WS-TIS-MOS` are `PIC S9(05)`; `EL-TIG-MOS`/`EL-TIS-MOS` are
`PIC 9(03)`. A career of more than 83 years is not the concern — corrupt dates
are. A `MM-PEBD` of zeros yields a five-digit month count that is written as its
low three digits, so a data error is reported as a plausible number.

Reproduced by `test_def4_eligibility_record_truncates_the_computed_month_counters`.

**Fix.** Widen the output fields to `PIC 9(05)` (this changes `LRECL`, so the JCL
and every downstream reader change with it), or reject the record.

## DEF-5 — report counters are written as packed decimal

`9000-TERM` `STRING`s `WS-READ-CNT` and friends, which are `COMP-3`, directly into
a character report line. The nightly report line reads `PROMELIG READ=` followed
by packed bytes rather than digits.

Reproduced by `test_def5_report_counters_are_written_as_packed_decimal`.

**Fix.** `MOVE` each counter to a `PIC Z(7)9` display field before the `STRING`.

## DEF-6 — no record length validation in the loader

`load_unit_diary.pl` `substr`s a fixed layout out of every non-blank line without
checking its length. A truncated line loads with `undef` fields — `perl` warns to
stderr, the loader carries on, and the record reaches the master with NULLs where
`PEBD` and `DT_ENLIST` should be. The batch then computes a time in service from
a missing date.

Reproduced by `test_a_short_record_is_loaded_with_missing_trailing_fields`.

**Fix.** Reject any line that is not the expected record length to a reject file
and count it in the run summary.

## DEF-7 — carry-forward silently loses the original promotion date

When a record has `RED_IN_GRADE_IND = 'Y'` and a zero `DT_ORIG_PROMO`, the loader
omits the column so an existing master row keeps its value. If the EDIPI is *new*
the same path inserts a row with `DT_ORIG_PROMO` NULL, and the run summary still
counts it as carried forward. The batch then falls back to the enlistment date
and credits the Marine's whole career as time in grade.

Reproduced by `test_carry_forward_on_an_unknown_edipi_inserts_a_row_without_the_column`
and, on the batch side, by
`test_reduction_without_an_original_promotion_falls_back_to_enlistment`.

**Fix.** Treat an insert on the carry-forward path as a reject; there is nothing
to carry forward.

## DEF-8 — six fields the batch reads are never loaded

The loader maintains 13 of the copybook's fields. `DUTY_STAT`, `COMPONENT`,
`RC_DRILL_STAT`, `BRK_SVC_MOS`, `ADV_MATL_IND` and `ADV_MATL_MOS` are not in its
offset table, yet `2400-APPLY-RULES` denies on all six. They are maintained by
some other process, or not at all.

Reproduced by `test_def8_loader_ignores_every_field_after_the_reduction_indicator`.

**Fix.** Establish which feed owns these columns before the loader is migrated;
this is a prerequisite for the loader rewrite, not part of it.

## DEF-9 — stale adverse material lookback in the extract

`V_ADV_LOOKBACK_MOS` is 12; the batch and the web service both use 24. See DIV-1
for the behavioral consequence and the scenarios that pin it.

Reproduced by `test_def9_reporting_extract_uses_a_stale_adverse_lookback` and
`test_adverse_material_lookback_is_still_twelve_months`.

**Fix.** Set the lookback to 24 in the same change that migrates the extract, and
expect the roster report to lose rows the first night it runs.
