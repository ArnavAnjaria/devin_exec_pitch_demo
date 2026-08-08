package mil.usmc.manpower.promotion;

/**
 * Minimum time in grade and time in service for a target grade.
 *
 * RECONSTRUCTED. Mirrors REF_GRADE_REQUIREMENTS, which is duplicated in
 * PROMELIG.cbl WORKING-STORAGE (WS-GRADE-TBL).
 */
public final class GradeRequirement {

    private final int gradeNum;
    private final int minTig;
    private final int minTis;

    public GradeRequirement(int gradeNum, int minTig, int minTis) {
        this.gradeNum = gradeNum;
        this.minTig = minTig;
        this.minTis = minTis;
    }

    public int getGradeNum() { return gradeNum; }

    public int getMinTig() { return minTig; }

    public int getMinTis() { return minTis; }
}
