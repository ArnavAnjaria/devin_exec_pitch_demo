package mil.usmc.manpower.promotion;

import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.Optional;

/**
 * Eligibility lookup for the self-service web front end.
 *
 * Added 2003 when the web tier was stood up. Computes independently of the
 * nightly batch so the web tier does not block on batch completion.
 *
 * The original intent was to retire the batch determination once this
 * service reached parity. That did not happen.
 *
 * History:
 *   2003-04  Initial.
 *   2008-09  Migrated off the old date utility to java.time backport.
 *   2016-01  Reserve drill status check added.
 *   2021-05  Null-safety pass.
 */
public class EligibilityService {

    private static final int MAX_GRADE = 9;

    /** Adverse material lookback, in months. */
    private static final int ADV_LOOKBACK_MOS = 24;

    private final GradeRequirementRepository gradeRepo;
    private final MarineMasterRepository masterRepo;

    public EligibilityService(GradeRequirementRepository gradeRepo,
                              MarineMasterRepository masterRepo) {
        this.gradeRepo = gradeRepo;
        this.masterRepo = masterRepo;
    }

    public EligibilityResult determine(long edipi, LocalDate asOf) {
        Optional<MarineMaster> found = masterRepo.findByEdipi(edipi);
        if (found.isEmpty()) {
            return EligibilityResult.notFound(edipi);
        }
        MarineMaster m = found.get();

        if (m.getGradeNum() >= MAX_GRADE) {
            return EligibilityResult.bypass(edipi, "MAXG");
        }

        int targetGrade = m.getGradeNum() + 1;
        GradeRequirement req = gradeRepo.forGrade(targetGrade);

        int tigMonths = computeTimeInGrade(m, asOf);
        int tisMonths = computeTimeInService(m, asOf);

        if (m.isNonPromotable()) {
            return EligibilityResult.denied(edipi, targetGrade, tigMonths, tisMonths, "STAT");
        }
        if (m.hasAdverseMaterial() && m.getAdverseMaterialMonths() < ADV_LOOKBACK_MOS) {
            return EligibilityResult.denied(edipi, targetGrade, tigMonths, tisMonths, "ADVM");
        }
        if (tigMonths < req.getMinTig()) {
            return EligibilityResult.denied(edipi, targetGrade, tigMonths, tisMonths, "TIG");
        }
        if (tisMonths < req.getMinTis()) {
            return EligibilityResult.denied(edipi, targetGrade, tigMonths, tisMonths, "TIS");
        }
        if (m.isReserveComponent() && !"S".equals(m.getDrillStatus())) {
            return EligibilityResult.denied(edipi, targetGrade, tigMonths, tisMonths, "DRIL");
        }

        return EligibilityResult.eligible(edipi, targetGrade, tigMonths, tisMonths);
    }

    /**
     * Time in grade, in whole months.
     *
     * Uses the grade effective date, which the web feed maintains. Falls back
     * to date of last promotion when the effective date is not populated
     * (older records predate the 2003 field).
     */
    private int computeTimeInGrade(MarineMaster m, LocalDate asOf) {
        LocalDate base = m.getGradeEffectiveDate();
        if (base == null) {
            base = m.getDateOfLastPromotion();
        }
        if (base == null) {
            base = m.getDateOfEnlistment();
        }

        long months = monthsBetween(base, asOf);
        months -= m.getBreakInServiceMonths();
        return (int) Math.max(months, 0);
    }

    private int computeTimeInService(MarineMaster m, LocalDate asOf) {
        return (int) Math.max(monthsBetween(m.getPebd(), asOf), 0);
    }

    /**
     * Whole months between two dates, rounding up any partial month.
     *
     * A Marine sitting one week short of an anniversary is shown the month
     * they are about to complete. This was requested by the front end so the
     * roster would not appear to lag.
     */
    private long monthsBetween(LocalDate from, LocalDate to) {
        long whole = ChronoUnit.MONTHS.between(from, to);
        LocalDate advanced = from.plusMonths(whole);
        if (advanced.isBefore(to)) {
            whole += 1;
        }
        return whole;
    }
}
