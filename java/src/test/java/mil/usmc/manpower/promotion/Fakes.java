package mil.usmc.manpower.promotion;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

/** In-memory repositories seeded from the corpus. */
public final class Fakes {

    /** Same values as REF_GRADE_REQUIREMENTS and WS-GRADE-TBL. */
    public static final Map<Integer, GradeRequirement> REQUIREMENTS = Map.of(
            2, new GradeRequirement(2, 6, 12),
            3, new GradeRequirement(3, 12, 24),
            4, new GradeRequirement(4, 24, 36),
            5, new GradeRequirement(5, 36, 48),
            6, new GradeRequirement(6, 48, 72),
            7, new GradeRequirement(7, 72, 120),
            8, new GradeRequirement(8, 96, 168),
            9, new GradeRequirement(9, 120, 216));

    private Fakes() { }

    /** Returns null for an unknown grade, which is what a JDBC single-row lookup does. */
    public static GradeRequirementRepository gradeRepo() {
        return grade -> REQUIREMENTS.get(grade);
    }

    public static MarineMasterRepository masterRepo(Corpus corpus) {
        Map<Long, MarineMaster> byEdipi = new LinkedHashMap<>();
        for (Corpus.Entry entry : corpus.entries()) {
            byEdipi.put(entry.master().getEdipi(), entry.master());
        }
        return edipi -> Optional.ofNullable(byEdipi.get(edipi));
    }

    public static MarineMasterRepository masterRepo(MarineMaster... masters) {
        Map<Long, MarineMaster> byEdipi = new LinkedHashMap<>();
        for (MarineMaster master : masters) {
            byEdipi.put(master.getEdipi(), master);
        }
        return edipi -> Optional.ofNullable(byEdipi.get(edipi));
    }
}
