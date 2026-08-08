# Divergence register

Where the COBOL batch, the Java web service and the SQL reporting extract
disagree about the same Marine. Generated from `tests/divergences.yaml` by
`make docs`; edit the YAML, not this file.

`tests/test_equivalence.py` fails if the engines disagree anywhere that is not
listed below, and fails if a listed divergence stops reproducing.

| ID | Divergence | Target behavior | Scenarios |
| --- | --- | --- | --- |
| DIV-1 | Adverse material lookback is 12 months in the extract and 24 everywhere else | java | `advm-12mo`, `advm-23mo` |
| DIV-2 | Partial months are truncated, rounded up and rounded to nearest | java | `anniversary-day-before-run-day`, `anniversary-day-after-run-day`, `month-end-promotion`, `leap-day-promotion` |
| DIV-3 | Time in grade accrues from three different base dates | java | `reduced-with-orig-promo`, `reduced-without-orig-promo`, `grade-eff-dt-diverges` |
| DIV-4 | The top grade is represented three ways | java | `grade-09-bypass` |
| DIV-5 | A grade with no requirement row is denied, dropped, or throws | undecided | `grade-00-unset` |
| DIV-6 | A missing promotion date produces a NULL month count in the extract | java | `no-promo-dates-at-all` |

## DIV-1: Adverse material lookback is 12 months in the extract and 24 everywhere else

**Engines:** cobol, java, sql  
**Target behavior:** java

**Cause.** The 2011 change extending the lookback to 24 months updated PROMELIG.cbl (WS-ADV-LOOKBACK-MOS) and EligibilityService (ADV_LOOKBACK_MOS) but not SP_PROMOTION_ELIGIBILITY (V_ADV_LOOKBACK_MOS), which still reads 12.

**Impact.** A Marine with adverse material 12 to 23 months old is denied on the board slate and in the web tier, but shows as eligible on the roster report.

**Scenarios.** `advm-12mo`, `advm-23mo`

## DIV-2: Partial months are truncated, rounded up and rounded to nearest

**Engines:** cobol, java, sql  
**Target behavior:** java

**Cause.** 2150-MONTH-DIFF truncates; EligibilityService.monthsBetween rounds any partial month up; the extract uses ROUND(MONTHS_BETWEEN(...)), which is Oracle's fractional month rounded to nearest.

**Impact.** Every Marine within one month of a threshold can get three different answers. This is the most common source of the discrepancies that have been closed as "timing".

**Scenarios.** `anniversary-day-before-run-day`, `anniversary-day-after-run-day`, `month-end-promotion`, `leap-day-promotion`

## DIV-3: Time in grade accrues from three different base dates

**Engines:** cobol, java, sql  
**Target behavior:** java

**Cause.** The batch uses MM-DT-ORIG-PROMO for a reduced-then-restored Marine and MM-DT-LAST-PROMO otherwise (REV 02 2001, directed). The web tier uses MM-GRADE-EFF-DT, which only the web feed maintains, and never looks at the reduction indicator. The extract always uses DT_LAST_PROMO.

**Impact.** Reduced-then-restored Marines are eligible on the board slate and denied in the web tier. Adopting the Java behavior reverses a 2001 directive and needs a change request before it ships.

**Needs review.** Program decision selects the Java behavior, but REV 02 2001 was directed by message traffic; confirm the directive is superseded before migrating.

**Scenarios.** `reduced-with-orig-promo`, `reduced-without-orig-promo`, `grade-eff-dt-diverges`

## DIV-4: The top grade is represented three ways

**Engines:** cobol, java, sql  
**Target behavior:** java

**Cause.** The batch writes no record at all, the service returns a MAXG bypass result, and the extract filters the row out with GRADE_NUM < 9.

**Impact.** Reconciliation counts never line up, because "not eligible" and "not considered" are indistinguishable in two of the three outputs.

**Scenarios.** `grade-09-bypass`

## DIV-5: A grade with no requirement row is denied, dropped, or throws

**Engines:** cobol, java, sql  
**Target behavior:** undecided

**Cause.** 2300-LOOKUP-MINIMUMS leaves the minimums at 999 so the record is denied TIG; the extract's INNER JOIN removes the row silently; the service dereferences the missing GradeRequirement and throws.

**Impact.** A corrupt or unset GRADE_NUM disappears from the roster report with no error anywhere. The replacement needs one defined behavior; a rejected record with a reason code is the obvious candidate.

**Scenarios.** `grade-00-unset`

## DIV-6: A missing promotion date produces a NULL month count in the extract

**Engines:** cobol, java, sql  
**Target behavior:** java

**Cause.** Oracle GREATEST propagates NULL, so TIG_MOS is NULL when DT_LAST_PROMO is not populated. Every threshold comparison against NULL is unknown, so the CASE falls through to 'Y'. The batch and the service both fall back to the enlistment date instead.

**Impact.** A Marine with no promotion date on file is reported eligible with a blank time in grade, regardless of how long they have served.

**Scenarios.** `no-promo-dates-at-all`
