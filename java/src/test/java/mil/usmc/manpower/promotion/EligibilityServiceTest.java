package mil.usmc.manpower.promotion;

import java.time.LocalDate;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Behavior-level characterization of the web tier determination.
 *
 * These describe what the service does today, including the places where it
 * disagrees with PROMELIG.cbl. Nothing here asserts what it "should" do.
 */
class EligibilityServiceTest {

    private static final LocalDate AS_OF = LocalDate.of(2026, 6, 15);
    private static final long EDIPI = 1234567890L;

    private EligibilityResult determine(MarineMaster master) {
        EligibilityService service =
                new EligibilityService(Fakes.gradeRepo(), Fakes.masterRepo(master));
        return service.determine(master.getEdipi(), AS_OF);
    }

    private static MarineMaster.Builder sergeant() {
        return MarineMaster.builder()
                .edipi(EDIPI)
                .grade("SGT")
                .gradeNum(5)
                .dateOfLastPromotion(AS_OF.minusMonths(200))
                .gradeEffectiveDate(AS_OF.minusMonths(200))
                .pebd(AS_OF.minusMonths(300))
                .dateOfEnlistment(AS_OF.minusMonths(300));
    }

    @Test
    void unknownEdipiIsNotFound() {
        EligibilityService service =
                new EligibilityService(Fakes.gradeRepo(), Fakes.masterRepo());
        EligibilityResult result = service.determine(EDIPI, AS_OF);
        assertEquals(EligibilityResult.Outcome.NOT_FOUND, result.getOutcome());
    }

    @Test
    void meetsEveryRequirement() {
        EligibilityResult result = determine(sergeant().build());
        assertTrue(result.isEligible());
        assertEquals(6, result.getTargetGrade());
        assertNull(result.getDenyReason());
    }

    @Nested
    class Bypass {

        @Test
        void topGradeIsBypassedWithoutComputingTimes() {
            EligibilityResult result = determine(sergeant().gradeNum(9).build());
            assertEquals(EligibilityResult.Outcome.BYPASS, result.getOutcome());
            assertEquals("MAXG", result.getDenyReason());
            assertEquals(0, result.getTargetGrade());
        }

        @Test
        void gradeEightIsStillEvaluated() {
            EligibilityResult result = determine(sergeant().gradeNum(8).build());
            assertEquals(9, result.getTargetGrade());
        }

        @Test
        void missingRequirementRowThrows() {
            // Grade 0 targets grade 1, which has no REF_GRADE_REQUIREMENTS row.
            // The batch denies with TIG instead; see DIV-5.
            assertThrows(NullPointerException.class,
                    () -> determine(sergeant().gradeNum(0).build()));
        }
    }

    @Nested
    class DenyPrecedence {

        @ParameterizedTest
        @ValueSource(strings = {"PS", "CF", "AW"})
        void nonPromotableStatusDeniesFirst(String dutyStatus) {
            EligibilityResult result = determine(sergeant()
                    .dutyStatus(dutyStatus)
                    .adverseMaterial(true).adverseMaterialMonths(0)
                    .dateOfLastPromotion(AS_OF).gradeEffectiveDate(AS_OF)
                    .pebd(AS_OF)
                    .component("R").drillStatus("N")
                    .build());
            assertEquals("STAT", result.getDenyReason());
        }

        @Test
        void activeDutyIsPromotable() {
            assertTrue(determine(sergeant().dutyStatus("AC").build()).isEligible());
        }

        @Test
        void adverseMaterialBeatsTimeInGrade() {
            EligibilityResult result = determine(sergeant()
                    .adverseMaterial(true).adverseMaterialMonths(1)
                    .dateOfLastPromotion(AS_OF).gradeEffectiveDate(AS_OF)
                    .build());
            assertEquals("ADVM", result.getDenyReason());
        }

        @Test
        void timeInGradeBeatsTimeInService() {
            EligibilityResult result = determine(sergeant()
                    .dateOfLastPromotion(AS_OF).gradeEffectiveDate(AS_OF)
                    .pebd(AS_OF)
                    .build());
            assertEquals("TIG", result.getDenyReason());
        }

        @Test
        void timeInServiceBeatsDrillStatus() {
            EligibilityResult result = determine(sergeant()
                    .pebd(AS_OF)
                    .component("R").drillStatus("N")
                    .build());
            assertEquals("TIS", result.getDenyReason());
        }
    }

    @Nested
    class AdverseMaterial {

        @ParameterizedTest
        @CsvSource({"0,ADVM", "11,ADVM", "12,ADVM", "23,ADVM", "24,", "25,"})
        void lookbackIsTwentyFourMonths(int months, String expectedDenyReason) {
            EligibilityResult result = determine(sergeant()
                    .adverseMaterial(true).adverseMaterialMonths(months).build());
            assertEquals(expectedDenyReason, result.getDenyReason());
        }

        @Test
        void monthsAreIgnoredWhenTheIndicatorIsNotSet() {
            assertTrue(determine(sergeant()
                    .adverseMaterial(false).adverseMaterialMonths(0).build()).isEligible());
        }
    }

    @Nested
    class Thresholds {

        // Target grade 6 requires 48 months in grade and 72 in service.
        @ParameterizedTest
        @CsvSource({"47,TIG", "48,", "49,"})
        void timeInGradeMinimum(int months, String expectedDenyReason) {
            EligibilityResult result = determine(sergeant()
                    .dateOfLastPromotion(AS_OF.minusMonths(months))
                    .gradeEffectiveDate(AS_OF.minusMonths(months))
                    .build());
            assertEquals(months, result.getTigMonths());
            assertEquals(expectedDenyReason, result.getDenyReason());
        }

        @ParameterizedTest
        @CsvSource({"71,TIS", "72,", "73,"})
        void timeInServiceMinimum(int months, String expectedDenyReason) {
            EligibilityResult result = determine(sergeant()
                    .pebd(AS_OF.minusMonths(months)).build());
            assertEquals(months, result.getTisMonths());
            assertEquals(expectedDenyReason, result.getDenyReason());
        }
    }

    @Nested
    class TimeInGradeBaseDate {

        @Test
        void gradeEffectiveDateWinsOverLastPromotion() {
            EligibilityResult result = determine(sergeant()
                    .dateOfLastPromotion(AS_OF.minusMonths(120))
                    .gradeEffectiveDate(AS_OF.minusMonths(40))
                    .build());
            assertEquals(40, result.getTigMonths());
        }

        @Test
        void fallsBackToLastPromotionWhenEffectiveDateIsAbsent() {
            EligibilityResult result = determine(sergeant()
                    .dateOfLastPromotion(AS_OF.minusMonths(40))
                    .gradeEffectiveDate(null)
                    .build());
            assertEquals(40, result.getTigMonths());
        }

        @Test
        void fallsBackToEnlistmentWhenNoPromotionDateExists() {
            EligibilityResult result = determine(sergeant()
                    .dateOfLastPromotion(null)
                    .gradeEffectiveDate(null)
                    .dateOfEnlistment(AS_OF.minusMonths(50))
                    .build());
            assertEquals(50, result.getTigMonths());
        }

        @Test
        void reductionInGradeIsIgnored() {
            // PROMELIG.cbl accrues from the original promotion date for a
            // reduced-then-restored Marine; the service does not look at it.
            EligibilityResult result = determine(sergeant()
                    .reducedInGrade(true)
                    .dateOfOriginalPromotion(AS_OF.minusMonths(120))
                    .dateOfLastPromotion(AS_OF.minusMonths(6))
                    .gradeEffectiveDate(AS_OF.minusMonths(6))
                    .build());
            assertEquals(6, result.getTigMonths());
            assertEquals("TIG", result.getDenyReason());
        }
    }

    @Nested
    class MonthArithmetic {

        @Test
        void partialMonthsAreRoundedUp() {
            // 36 months and one day past the anniversary reads as 37.
            EligibilityResult result = determine(sergeant()
                    .gradeEffectiveDate(AS_OF.minusMonths(36).minusDays(1)).build());
            assertEquals(37, result.getTigMonths());
        }

        @Test
        void exactAnniversaryIsNotRoundedUp() {
            EligibilityResult result = determine(sergeant()
                    .gradeEffectiveDate(AS_OF.minusMonths(36)).build());
            assertEquals(36, result.getTigMonths());
        }

        @Test
        void oneDayShortOfTheThresholdStillQualifies() {
            // The rounding-up rule credits a Marine 47 months and 30 days in
            // grade with the full 48 months, which the batch would deny.
            EligibilityResult result = determine(sergeant()
                    .gradeEffectiveDate(AS_OF.minusMonths(48).plusDays(1)).build());
            assertEquals(48, result.getTigMonths());
            assertNull(result.getDenyReason());
        }

        @Test
        void futureBaseDateFloorsAtZero() {
            EligibilityResult result = determine(sergeant()
                    .gradeEffectiveDate(AS_OF.plusMonths(6)).build());
            assertEquals(0, result.getTigMonths());
        }
    }

    @Nested
    class BreakInService {

        @Test
        void isSubtractedFromTimeInGrade() {
            EligibilityResult result = determine(sergeant()
                    .gradeEffectiveDate(AS_OF.minusMonths(48))
                    .breakInServiceMonths(6)
                    .build());
            assertEquals(42, result.getTigMonths());
        }

        @Test
        void cannotDriveTimeInGradeNegative() {
            EligibilityResult result = determine(sergeant()
                    .gradeEffectiveDate(AS_OF.minusMonths(12))
                    .breakInServiceMonths(999)
                    .build());
            assertEquals(0, result.getTigMonths());
        }

        @Test
        void doesNotAffectTimeInService() {
            EligibilityResult result = determine(sergeant()
                    .pebd(AS_OF.minusMonths(300))
                    .breakInServiceMonths(120)
                    .build());
            assertEquals(300, result.getTisMonths());
        }
    }

    @Nested
    class DrillStatus {

        @ParameterizedTest
        @CsvSource({"A,S,", "A,N,", "R,S,", "R,N,DRIL"})
        void onlyReservistsAreCheckedForDrillStatus(String component, String drill,
                                                    String expectedDenyReason) {
            EligibilityResult result = determine(sergeant()
                    .component(component).drillStatus(drill).build());
            assertEquals(expectedDenyReason, result.getDenyReason());
        }

        @Test
        void nullDrillStatusDeniesAReservist() {
            EligibilityResult result = determine(sergeant()
                    .component("R").drillStatus(null).build());
            assertEquals("DRIL", result.getDenyReason());
        }

        @Test
        void nullDrillStatusIsIgnoredForActiveDuty() {
            assertTrue(determine(sergeant()
                    .component("A").drillStatus(null).build()).isEligible());
        }
    }
}
