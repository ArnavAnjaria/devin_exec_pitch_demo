package mil.usmc.manpower.promotion;

/**
 * Lookup of REF_GRADE_REQUIREMENTS rows.
 *
 * RECONSTRUCTED. EligibilityService calls forGrade() and dereferences the
 * result without a null check, so implementations decide what happens for a
 * target grade with no row; see docs/divergence-register.md (DIV-5).
 */
public interface GradeRequirementRepository {

    GradeRequirement forGrade(int gradeNum);
}
