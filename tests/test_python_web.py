"""The Python replacement for the web-tier determination.

Two kinds of test: the corpus pinned to the golden, which is what proves the
rewrite did not change behavior, and behavior-level cases mirroring
``EligibilityServiceTest.java`` so a failure says which rule broke.
"""

from __future__ import annotations

import datetime as dt

import pytest

from harness import golden
from harness.engines import python_web
from harness.marrec import DECLARED_RECORD_LEN, write_master_file
from harness.model import Corpus
from harness.normalize import read_rows, write_rows

from promelig import (EligibilityService, InMemoryGradeRequirementRepository,
                      InMemoryMarineMasterRepository, MarineMaster,
                      MissingGradeRequirementError, Outcome)
from promelig.cli_web import main as cli_main
from promelig.monthmath import add_months

ENGINE = "python_web"
AS_OF = dt.date(2026, 6, 15)
EDIPI = 1234567890


@pytest.fixture(scope="module")
def rows(corpus: Corpus):
    return python_web.run(corpus)


def test_matches_golden(rows):
    expected, actual = golden.compare(ENGINE, rows)
    assert actual == expected, golden.describe_difference(expected, actual)


def test_matches_the_java_golden_byte_for_byte(rows, tmp_path):
    """The point of the exercise: same six columns, same bytes, as the service
    it replaces."""
    written = tmp_path / "python_web.csv"
    write_rows(written, rows)
    assert written.read_bytes() == golden.golden_path("java").read_bytes()


def test_every_scenario_produces_exactly_one_row(corpus: Corpus, rows):
    assert len(rows) == len(corpus.scenarios)
    assert len({row.edipi for row in rows}) == len(rows)


def test_the_command_line_reads_the_fixed_width_master_file(corpus: Corpus, tmp_path):
    """End to end through MARREC.cpy offsets rather than the in-process model.

    The one scenario with no grade requirement row fails the determination
    (DIV-5), so the CLI reports it on stderr and emits no row for it.
    """
    master = tmp_path / "MASTER.DAT"
    write_master_file(master, corpus.scenarios)
    out = tmp_path / "out.csv"
    status = cli_main(["--master", str(master), "--as-of", corpus.as_of.isoformat(),
                       "--record-len", str(DECLARED_RECORD_LEN), "--output", str(out)])

    assert status == 1
    expected = [row for row in read_rows(golden.golden_path("java")) if row.elig_ind != "E"]
    assert read_rows(out) == expected


def test_an_unknown_edipi_is_not_found(corpus: Corpus, tmp_path):
    master = tmp_path / "MASTER.DAT"
    write_master_file(master, corpus.scenarios)
    out = tmp_path / "out.csv"
    assert cli_main(["--master", str(master), "--as-of", corpus.as_of.isoformat(),
                     "--edipi", "9999999999", "--output", str(out)]) == 0
    assert out.read_text().splitlines()[1] == "9999999999,0,0,0,X,NOTF"


def determine(master: MarineMaster) -> object:
    service = EligibilityService(InMemoryGradeRequirementRepository(),
                                 InMemoryMarineMasterRepository([master]))
    return service.determine(master.edipi, AS_OF)


def sergeant(**overrides) -> MarineMaster:
    defaults = dict(
        edipi=EDIPI,
        grade="SGT",
        grade_num=5,
        date_of_last_promotion=add_months(AS_OF, -200),
        grade_effective_date=add_months(AS_OF, -200),
        pebd=add_months(AS_OF, -300),
        date_of_enlistment=add_months(AS_OF, -300),
    )
    return MarineMaster(**{**defaults, **overrides})


def test_meets_every_requirement():
    result = determine(sergeant())
    assert result.eligible
    assert result.target_grade == 6
    assert result.deny_reason is None


class TestBypass:

    def test_top_grade_is_bypassed_without_computing_times(self):
        result = determine(sergeant(grade_num=9))
        assert (result.outcome, result.deny_reason, result.target_grade) == (
            Outcome.BYPASS, "MAXG", 0)

    def test_grade_eight_is_still_evaluated(self):
        assert determine(sergeant(grade_num=8)).target_grade == 9

    def test_missing_requirement_row_raises(self):
        # Grade 0 targets grade 1, which has no REF_GRADE_REQUIREMENTS row.
        # The batch denies with TIG instead; see DIV-5.
        with pytest.raises(MissingGradeRequirementError):
            determine(sergeant(grade_num=0))

    def test_missing_requirement_row_is_reached_after_the_status_checks(self):
        # The Java service dereferences the requirement only at the TIG
        # comparison, so an earlier denial wins over the missing row.
        assert determine(sergeant(grade_num=0, duty_status="CF")).deny_reason == "STAT"


class TestDenyPrecedence:

    @pytest.mark.parametrize("duty_status", ["PS", "CF", "AW"])
    def test_non_promotable_status_denies_first(self, duty_status):
        result = determine(sergeant(
            duty_status=duty_status, adverse_material=True, adverse_material_months=0,
            date_of_last_promotion=AS_OF, grade_effective_date=AS_OF, pebd=AS_OF,
            component="R", drill_status="N"))
        assert result.deny_reason == "STAT"

    def test_active_duty_is_promotable(self):
        assert determine(sergeant(duty_status="AC")).eligible

    def test_adverse_material_beats_time_in_grade(self):
        result = determine(sergeant(adverse_material=True, adverse_material_months=1,
                                    date_of_last_promotion=AS_OF, grade_effective_date=AS_OF))
        assert result.deny_reason == "ADVM"

    def test_time_in_grade_beats_time_in_service(self):
        result = determine(sergeant(date_of_last_promotion=AS_OF,
                                    grade_effective_date=AS_OF, pebd=AS_OF))
        assert result.deny_reason == "TIG"

    def test_time_in_service_beats_drill_status(self):
        result = determine(sergeant(pebd=AS_OF, component="R", drill_status="N"))
        assert result.deny_reason == "TIS"


class TestAdverseMaterial:

    @pytest.mark.parametrize("months,expected", [(0, "ADVM"), (11, "ADVM"), (12, "ADVM"),
                                                 (23, "ADVM"), (24, None), (25, None)])
    def test_lookback_is_twenty_four_months(self, months, expected):
        result = determine(sergeant(adverse_material=True, adverse_material_months=months))
        assert result.deny_reason == expected

    def test_months_are_ignored_when_the_indicator_is_not_set(self):
        assert determine(sergeant(adverse_material=False, adverse_material_months=0)).eligible


class TestThresholds:

    # Target grade 6 requires 48 months in grade and 72 in service.
    @pytest.mark.parametrize("months,expected", [(47, "TIG"), (48, None), (49, None)])
    def test_time_in_grade_minimum(self, months, expected):
        result = determine(sergeant(date_of_last_promotion=add_months(AS_OF, -months),
                                    grade_effective_date=add_months(AS_OF, -months)))
        assert (result.tig_months, result.deny_reason) == (months, expected)

    @pytest.mark.parametrize("months,expected", [(71, "TIS"), (72, None), (73, None)])
    def test_time_in_service_minimum(self, months, expected):
        result = determine(sergeant(pebd=add_months(AS_OF, -months)))
        assert (result.tis_months, result.deny_reason) == (months, expected)


class TestTimeInGradeBaseDate:

    def test_grade_effective_date_wins_over_last_promotion(self):
        result = determine(sergeant(date_of_last_promotion=add_months(AS_OF, -120),
                                    grade_effective_date=add_months(AS_OF, -40)))
        assert result.tig_months == 40

    def test_falls_back_to_last_promotion_when_effective_date_is_absent(self):
        result = determine(sergeant(date_of_last_promotion=add_months(AS_OF, -40),
                                    grade_effective_date=None))
        assert result.tig_months == 40

    def test_falls_back_to_enlistment_when_no_promotion_date_exists(self):
        result = determine(sergeant(date_of_last_promotion=None, grade_effective_date=None,
                                    date_of_enlistment=add_months(AS_OF, -50)))
        assert result.tig_months == 50

    def test_reduction_in_grade_is_ignored(self):
        # PROMELIG.cbl accrues from the original promotion date for a
        # reduced-then-restored Marine; the service does not look at it (DIV-3).
        result = determine(sergeant(reduced_in_grade=True,
                                    date_of_original_promotion=add_months(AS_OF, -120),
                                    date_of_last_promotion=add_months(AS_OF, -6),
                                    grade_effective_date=add_months(AS_OF, -6)))
        assert (result.tig_months, result.deny_reason) == (6, "TIG")


class TestMonthArithmetic:

    def test_partial_months_are_rounded_up(self):
        # 36 months and one day past the anniversary reads as 37 (DIV-2).
        base = add_months(AS_OF, -36) - dt.timedelta(days=1)
        assert determine(sergeant(grade_effective_date=base)).tig_months == 37

    def test_exact_anniversary_is_not_rounded_up(self):
        assert determine(sergeant(grade_effective_date=add_months(AS_OF, -36))).tig_months == 36

    def test_one_day_short_of_the_threshold_still_qualifies(self):
        # Rounding up credits 47 months and 30 days as the full 48, which the
        # batch would deny.
        base = add_months(AS_OF, -48) + dt.timedelta(days=1)
        result = determine(sergeant(grade_effective_date=base))
        assert (result.tig_months, result.deny_reason) == (48, None)

    def test_future_base_date_floors_at_zero(self):
        assert determine(sergeant(grade_effective_date=add_months(AS_OF, 6))).tig_months == 0


class TestBreakInService:

    def test_is_subtracted_from_time_in_grade(self):
        result = determine(sergeant(grade_effective_date=add_months(AS_OF, -48),
                                    break_in_service_months=6))
        assert result.tig_months == 42

    def test_cannot_drive_time_in_grade_negative(self):
        result = determine(sergeant(grade_effective_date=add_months(AS_OF, -12),
                                    break_in_service_months=999))
        assert result.tig_months == 0

    def test_does_not_affect_time_in_service(self):
        result = determine(sergeant(pebd=add_months(AS_OF, -300),
                                    break_in_service_months=120))
        assert result.tis_months == 300


class TestDrillStatus:

    @pytest.mark.parametrize("component,drill,expected", [("A", "S", None), ("A", "N", None),
                                                          ("R", "S", None), ("R", "N", "DRIL")])
    def test_only_reservists_are_checked_for_drill_status(self, component, drill, expected):
        result = determine(sergeant(component=component, drill_status=drill))
        assert result.deny_reason == expected

    def test_missing_drill_status_denies_a_reservist(self):
        assert determine(sergeant(component="R", drill_status=None)).deny_reason == "DRIL"

    def test_missing_drill_status_is_ignored_for_active_duty(self):
        assert determine(sergeant(component="A", drill_status=None)).eligible
