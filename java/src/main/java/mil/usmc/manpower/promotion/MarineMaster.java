package mil.usmc.manpower.promotion;

import java.time.LocalDate;
import java.util.Set;

/**
 * Master personnel record as the web tier sees it.
 *
 * RECONSTRUCTED. The original class was not delivered with the source drop;
 * this definition is derived from the fields EligibilityService reads and from
 * the MARREC.cpy layout. Field semantics -- in particular which duty statuses
 * are non-promotable -- follow the copybook 88-levels.
 */
public final class MarineMaster {

    /** MM-NON-PROMOTABLE in MARREC.cpy: pending separation, confined, AWOL. */
    private static final Set<String> NON_PROMOTABLE_DUTY_STATUS = Set.of("PS", "CF", "AW");

    private final long edipi;
    private final String grade;
    private final int gradeNum;
    private final LocalDate dateOfLastPromotion;
    private final LocalDate dateOfOriginalPromotion;
    private final LocalDate gradeEffectiveDate;
    private final LocalDate pebd;
    private final LocalDate dateOfEnlistment;
    private final boolean reducedInGrade;
    private final int breakInServiceMonths;
    private final boolean adverseMaterial;
    private final int adverseMaterialMonths;
    private final String dutyStatus;
    private final String component;
    private final String drillStatus;

    private MarineMaster(Builder b) {
        this.edipi = b.edipi;
        this.grade = b.grade;
        this.gradeNum = b.gradeNum;
        this.dateOfLastPromotion = b.dateOfLastPromotion;
        this.dateOfOriginalPromotion = b.dateOfOriginalPromotion;
        this.gradeEffectiveDate = b.gradeEffectiveDate;
        this.pebd = b.pebd;
        this.dateOfEnlistment = b.dateOfEnlistment;
        this.reducedInGrade = b.reducedInGrade;
        this.breakInServiceMonths = b.breakInServiceMonths;
        this.adverseMaterial = b.adverseMaterial;
        this.adverseMaterialMonths = b.adverseMaterialMonths;
        this.dutyStatus = b.dutyStatus;
        this.component = b.component;
        this.drillStatus = b.drillStatus;
    }

    public long getEdipi() { return edipi; }

    public String getGrade() { return grade; }

    public int getGradeNum() { return gradeNum; }

    public LocalDate getDateOfLastPromotion() { return dateOfLastPromotion; }

    public LocalDate getDateOfOriginalPromotion() { return dateOfOriginalPromotion; }

    public LocalDate getGradeEffectiveDate() { return gradeEffectiveDate; }

    public LocalDate getPebd() { return pebd; }

    public LocalDate getDateOfEnlistment() { return dateOfEnlistment; }

    public boolean isReducedInGrade() { return reducedInGrade; }

    public int getBreakInServiceMonths() { return breakInServiceMonths; }

    public boolean hasAdverseMaterial() { return adverseMaterial; }

    public int getAdverseMaterialMonths() { return adverseMaterialMonths; }

    public String getDutyStatus() { return dutyStatus; }

    public boolean isNonPromotable() { return NON_PROMOTABLE_DUTY_STATUS.contains(dutyStatus); }

    public String getComponent() { return component; }

    public boolean isReserveComponent() { return "R".equals(component); }

    public String getDrillStatus() { return drillStatus; }

    public static Builder builder() { return new Builder(); }

    public static final class Builder {
        private long edipi;
        private String grade = "";
        private int gradeNum;
        private LocalDate dateOfLastPromotion;
        private LocalDate dateOfOriginalPromotion;
        private LocalDate gradeEffectiveDate;
        private LocalDate pebd;
        private LocalDate dateOfEnlistment;
        private boolean reducedInGrade;
        private int breakInServiceMonths;
        private boolean adverseMaterial;
        private int adverseMaterialMonths;
        private String dutyStatus = "AC";
        private String component = "A";
        private String drillStatus;

        public Builder edipi(long v) { this.edipi = v; return this; }

        public Builder grade(String v) { this.grade = v; return this; }

        public Builder gradeNum(int v) { this.gradeNum = v; return this; }

        public Builder dateOfLastPromotion(LocalDate v) { this.dateOfLastPromotion = v; return this; }

        public Builder dateOfOriginalPromotion(LocalDate v) { this.dateOfOriginalPromotion = v; return this; }

        public Builder gradeEffectiveDate(LocalDate v) { this.gradeEffectiveDate = v; return this; }

        public Builder pebd(LocalDate v) { this.pebd = v; return this; }

        public Builder dateOfEnlistment(LocalDate v) { this.dateOfEnlistment = v; return this; }

        public Builder reducedInGrade(boolean v) { this.reducedInGrade = v; return this; }

        public Builder breakInServiceMonths(int v) { this.breakInServiceMonths = v; return this; }

        public Builder adverseMaterial(boolean v) { this.adverseMaterial = v; return this; }

        public Builder adverseMaterialMonths(int v) { this.adverseMaterialMonths = v; return this; }

        public Builder dutyStatus(String v) { this.dutyStatus = v; return this; }

        public Builder component(String v) { this.component = v; return this; }

        public Builder drillStatus(String v) { this.drillStatus = v; return this; }

        public MarineMaster build() { return new MarineMaster(this); }
    }
}
