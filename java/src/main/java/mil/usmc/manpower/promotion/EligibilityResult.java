package mil.usmc.manpower.promotion;

/**
 * Outcome of an eligibility determination.
 *
 * RECONSTRUCTED. Derived from the factory methods EligibilityService calls:
 * notFound, bypass, denied and eligible.
 */
public final class EligibilityResult {

    public enum Outcome { ELIGIBLE, DENIED, BYPASS, NOT_FOUND }

    private final long edipi;
    private final Outcome outcome;
    private final int targetGrade;
    private final int tigMonths;
    private final int tisMonths;
    private final String denyReason;

    private EligibilityResult(long edipi, Outcome outcome, int targetGrade,
                              int tigMonths, int tisMonths, String denyReason) {
        this.edipi = edipi;
        this.outcome = outcome;
        this.targetGrade = targetGrade;
        this.tigMonths = tigMonths;
        this.tisMonths = tisMonths;
        this.denyReason = denyReason;
    }

    public static EligibilityResult notFound(long edipi) {
        return new EligibilityResult(edipi, Outcome.NOT_FOUND, 0, 0, 0, null);
    }

    public static EligibilityResult bypass(long edipi, String reason) {
        return new EligibilityResult(edipi, Outcome.BYPASS, 0, 0, 0, reason);
    }

    public static EligibilityResult denied(long edipi, int targetGrade, int tigMonths,
                                           int tisMonths, String denyReason) {
        return new EligibilityResult(edipi, Outcome.DENIED, targetGrade, tigMonths,
                                     tisMonths, denyReason);
    }

    public static EligibilityResult eligible(long edipi, int targetGrade, int tigMonths,
                                             int tisMonths) {
        return new EligibilityResult(edipi, Outcome.ELIGIBLE, targetGrade, tigMonths,
                                     tisMonths, null);
    }

    public long getEdipi() { return edipi; }

    public Outcome getOutcome() { return outcome; }

    public boolean isEligible() { return outcome == Outcome.ELIGIBLE; }

    public int getTargetGrade() { return targetGrade; }

    public int getTigMonths() { return tigMonths; }

    public int getTisMonths() { return tisMonths; }

    public String getDenyReason() { return denyReason; }

    @Override
    public String toString() {
        return "EligibilityResult{edipi=" + edipi + ", outcome=" + outcome
                + ", targetGrade=" + targetGrade + ", tig=" + tigMonths
                + ", tis=" + tisMonths + ", denyReason=" + denyReason + '}';
    }
}
