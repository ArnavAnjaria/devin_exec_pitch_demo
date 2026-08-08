package mil.usmc.manpower.promotion;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.stream.Collectors;

/**
 * The six-column result shape every engine emits, so COBOL, Java, Perl and the
 * SQL extract can be compared row for row.
 */
public record NormalizedRow(long edipi, int tgtGrade, int tigMos, int tisMos,
                            String eligInd, String denyRsn)
        implements Comparable<NormalizedRow> {

    public static final String HEADER = "edipi,tgt_grade,tig_mos,tis_mos,elig_ind,deny_rsn";

    /**
     * Map a service result onto the normalized shape.
     *
     * <p>Outcomes the batch has no equivalent for are kept distinct rather than
     * flattened: {@code B}/{@code MAXG} for the grade 9 bypass, {@code E} for a
     * determination that threw. Those differences are the point of the
     * comparison, so they must survive normalization.
     */
    public static NormalizedRow of(EligibilityResult result) {
        return switch (result.getOutcome()) {
            case ELIGIBLE -> new NormalizedRow(result.getEdipi(), result.getTargetGrade(),
                    result.getTigMonths(), result.getTisMonths(), "Y", "");
            case DENIED -> new NormalizedRow(result.getEdipi(), result.getTargetGrade(),
                    result.getTigMonths(), result.getTisMonths(), "N", result.getDenyReason());
            case BYPASS -> new NormalizedRow(result.getEdipi(), 0, 0, 0, "B",
                    result.getDenyReason());
            case NOT_FOUND -> new NormalizedRow(result.getEdipi(), 0, 0, 0, "X", "NOTF");
        };
    }

    public static List<NormalizedRow> runAll(EligibilityService service, Corpus corpus) {
        List<NormalizedRow> rows = new ArrayList<>();
        for (Corpus.Entry entry : corpus.entries()) {
            long edipi = entry.master().getEdipi();
            try {
                rows.add(of(service.determine(edipi, corpus.asOf())));
            } catch (RuntimeException e) {
                // A missing REF_GRADE_REQUIREMENTS row dereferences null today.
                rows.add(new NormalizedRow(edipi, 0, 0, 0, "E",
                        e.getClass().getSimpleName().equals("NullPointerException") ? "NPE" : "ERR"));
            }
        }
        rows.sort(Comparator.naturalOrder());
        return rows;
    }

    public String toCsv() {
        return edipi + "," + tgtGrade + "," + tigMos + "," + tisMos + "," + eligInd + "," + denyRsn;
    }

    public static void write(Path path, List<NormalizedRow> rows) throws IOException {
        Files.createDirectories(path.getParent());
        String body = rows.stream().map(NormalizedRow::toCsv).collect(Collectors.joining("\n"));
        Files.writeString(path, HEADER + "\n" + body + "\n");
    }

    public static List<NormalizedRow> read(Path path) throws IOException {
        List<String> lines = Files.readAllLines(path);
        List<NormalizedRow> rows = new ArrayList<>();
        for (String line : lines.subList(1, lines.size())) {
            if (line.isBlank()) {
                continue;
            }
            String[] c = line.split(",", -1);
            rows.add(new NormalizedRow(Long.parseLong(c[0]), Integer.parseInt(c[1]),
                    Integer.parseInt(c[2]), Integer.parseInt(c[3]), c[4], c[5]));
        }
        rows.sort(Comparator.naturalOrder());
        return rows;
    }

    @Override
    public int compareTo(NormalizedRow other) {
        return Long.compare(edipi, other.edipi);
    }

    /** Entry point used by the cross-engine equivalence harness. */
    public static void main(String[] args) throws IOException {
        Path corpusDir = Path.of(args[0]);
        Path out = Path.of(args[1]);
        Corpus corpus = Corpus.load(corpusDir);
        EligibilityService service =
                new EligibilityService(Fakes.gradeRepo(), Fakes.masterRepo(corpus));
        write(out, runAll(service, corpus));
    }
}
