package mil.usmc.manpower.promotion;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

/**
 * Characterization test: the whole corpus, pinned to tests/golden/java.csv.
 *
 * Run with {@code -Dgolden.update=true} to rewrite the golden after an
 * intentional behavior change; the diff is then reviewed like any other.
 */
class GoldenCorpusTest {

    private static final Path GOLDEN = Path.of("..", "tests", "golden", "java.csv");

    @Test
    void corpusMatchesGolden() throws Exception {
        Corpus corpus = Corpus.load();
        EligibilityService service =
                new EligibilityService(Fakes.gradeRepo(), Fakes.masterRepo(corpus));
        List<NormalizedRow> actual = NormalizedRow.runAll(service, corpus);

        if (Boolean.getBoolean("golden.update") || !Files.exists(GOLDEN)) {
            NormalizedRow.write(GOLDEN, actual);
            return;
        }

        List<NormalizedRow> expected = NormalizedRow.read(GOLDEN);
        assertEquals(expected.size(), actual.size(), "row count");
        for (int i = 0; i < expected.size(); i++) {
            assertEquals(expected.get(i), actual.get(i), "row " + i);
        }
    }

    @Test
    void everyScenarioProducesExactlyOneRow() {
        Corpus corpus = Corpus.load();
        EligibilityService service =
                new EligibilityService(Fakes.gradeRepo(), Fakes.masterRepo(corpus));
        assertEquals(corpus.entries().size(), NormalizedRow.runAll(service, corpus).size());
    }
}
