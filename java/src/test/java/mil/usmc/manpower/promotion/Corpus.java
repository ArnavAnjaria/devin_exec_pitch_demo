package mil.usmc.manpower.promotion;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Loads the shared scenario corpus (tests/corpus/scenarios.csv) that every
 * engine harness runs against.
 */
public final class Corpus {

    private static final DateTimeFormatter YYYYMMDD = DateTimeFormatter.ofPattern("yyyyMMdd");

    public record Entry(String id, MarineMaster master) { }

    private final LocalDate asOf;
    private final List<Entry> entries;

    private Corpus(LocalDate asOf, List<Entry> entries) {
        this.asOf = asOf;
        this.entries = entries;
    }

    public LocalDate asOf() { return asOf; }

    public List<Entry> entries() { return entries; }

    public MarineMaster byId(String id) {
        return entries.stream()
                .filter(e -> e.id().equals(id))
                .findFirst()
                .orElseThrow(() -> new IllegalArgumentException("no scenario " + id))
                .master();
    }

    public static Path corpusDir() {
        // Tests run with the java/ module as the working directory.
        return Path.of("..", "tests", "corpus");
    }

    public static Corpus load() {
        return load(corpusDir());
    }

    public static Corpus load(Path dir) {
        try {
            LocalDate asOf = LocalDate.parse(Files.readString(dir.resolve("as_of.txt")).trim());
            List<String> lines = Files.readAllLines(dir.resolve("scenarios.csv"));
            String[] header = lines.get(0).split(",", -1);
            List<Entry> entries = new ArrayList<>();
            for (String line : lines.subList(1, lines.size())) {
                if (line.isBlank()) {
                    continue;
                }
                String[] cells = line.split(",", -1);
                Map<String, String> row = new LinkedHashMap<>();
                for (int i = 0; i < header.length; i++) {
                    row.put(header[i], cells[i]);
                }
                entries.add(new Entry(row.get("id"), toMaster(row)));
            }
            return new Corpus(asOf, List.copyOf(entries));
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    private static MarineMaster toMaster(Map<String, String> row) {
        return MarineMaster.builder()
                .edipi(Long.parseLong(row.get("edipi")))
                .grade(row.get("grade"))
                .gradeNum(Integer.parseInt(row.get("grade_num")))
                .dateOfLastPromotion(date(row.get("dt_last_promo")))
                .dateOfOriginalPromotion(date(row.get("dt_orig_promo")))
                .gradeEffectiveDate(date(row.get("grade_eff_dt")))
                .pebd(date(row.get("pebd")))
                .dateOfEnlistment(date(row.get("dt_enlist")))
                .reducedInGrade("Y".equals(row.get("red_in_grade_ind")))
                .breakInServiceMonths(Integer.parseInt(row.get("brk_svc_mos")))
                .adverseMaterial("Y".equals(row.get("adv_matl_ind")))
                .adverseMaterialMonths(Integer.parseInt(row.get("adv_matl_mos")))
                .dutyStatus(row.get("duty_stat"))
                .component(row.get("component"))
                .drillStatus(row.get("rc_drill_stat").isEmpty() ? null : row.get("rc_drill_stat"))
                .build();
    }

    /** A zero or blank date column means the field was never populated. */
    private static LocalDate date(String value) {
        String trimmed = value.trim();
        if (trimmed.isEmpty() || trimmed.chars().allMatch(c -> c == '0')) {
            return null;
        }
        return LocalDate.parse(trimmed, YYYYMMDD);
    }
}
