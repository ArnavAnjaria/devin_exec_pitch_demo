"""Static checks on jcl/PROMELIG.jcl.

JCL cannot be executed off the mainframe, so the job is characterized by
parsing it and validating every value that couples it to something else in the
repository: copybook offsets, DD names, and the record length the COBOL FD
declares. These are the couplings that break silently when a modernized
component replaces a step.
"""

from __future__ import annotations

import re

import pytest

from harness.marrec import FIELDS
from harness.model import REPO_ROOT

JCL_PATH = REPO_ROOT / "jcl" / "PROMELIG.jcl"
JCL = JCL_PATH.read_text()
COBOL_SOURCE = (REPO_ROOT / "cobol" / "PROMELIG.cbl").read_text()


def statements() -> dict[str, str]:
    """name -> operand text, for every //NAME OP OPERAND statement."""
    out = {}
    name = None
    for line in JCL.splitlines():
        if line.startswith("//*") or not line.startswith("//"):
            continue
        match = re.match(r"//(\S+)\s+(\S+)\s+(.*)", line)
        if match:
            name = match.group(1)
            out[name] = f"{match.group(2)} {match.group(3)}".strip()
        elif name and line.startswith("//  "):
            out[name] += " " + line[2:].strip()
    return out


STATEMENTS = statements()


def test_every_statement_fits_in_the_fixed_card_format():
    for number, line in enumerate(JCL.splitlines(), start=1):
        if line.startswith("//*"):
            continue
        assert len(line) <= 72, f"line {number} exceeds column 72"


def test_one_comment_card_overflows_column_72():
    """Harmless (the text past 72 is ignored) but it is truncated in the log."""
    overlong = [line for line in JCL.splitlines()
                if line.startswith("//*") and len(line) > 72]
    assert len(overlong) == 1
    assert overlong[0].endswith("SP_PROMOTION_ELIGIBILITY.")


def test_steps_run_in_the_documented_order():
    steps = re.findall(r"//(STEP\d+)\s+EXEC", JCL)
    assert steps == ["STEP010", "STEP020", "STEP030", "STEP040"]


def test_every_step_after_the_first_is_conditioned_on_success():
    for step in ("STEP020", "STEP030", "STEP040"):
        assert "COND=(0,NE)" in STATEMENTS[step], f"{step} runs even after a failure"


def test_the_batch_program_reads_the_sorted_file_not_the_master():
    assert "DSN=&&SORTED" in STATEMENTS["MSTRIN"]
    assert "DSN=MANPWR.PROD.MASTER" in STATEMENTS["SORTIN"]


def test_dd_names_match_the_cobol_select_clauses():
    declared = set(re.findall(r'ASSIGN TO\s+"?(\w+)"?', COBOL_SOURCE))
    assert declared == {"MSTRIN", "ELIGOUT", "RPTOUT"}
    assert declared <= set(STATEMENTS)


def test_eligibility_output_record_length_matches_the_cobol_fd():
    lrecl = int(re.search(r"LRECL=(\d+)", STATEMENTS["ELIGOUT"]).group(1))
    declared = int(re.search(
        r"FD  ELIG-FILE.*?RECORD CONTAINS (\d+) CHARACTERS", COBOL_SOURCE, re.S).group(1))
    assert lrecl == declared == 60


def test_the_sort_key_is_the_edipi():
    position, length, fmt, order = re.search(
        r"SORT FIELDS=\((\d+),(\d+),(\w+),(\w)\)", JCL).groups()
    edipi = FIELDS["MM-EDIPI"]
    assert (int(position), int(length)) == (edipi.offset + 1, edipi.length)
    assert (fmt, order) == ("ZD", "A")


def test_the_include_filter_does_not_point_at_the_grade_number():
    """DEF-3. Position 58 is inside MM-GRADE ('SGT'), not MM-GRADE-NUM."""
    position, length = re.search(r"INCLUDE COND=\((\d+),(\d+),ZD", JCL).groups()
    expected = FIELDS["MM-GRADE-NUM"].offset + 1
    assert int(length) == FIELDS["MM-GRADE-NUM"].length
    assert int(position) != expected, "if this fails, DEF-3 is fixed"
    assert int(position) == FIELDS["MM-GRADE"].offset + 1


def test_the_include_filter_reads_non_numeric_data(corpus):
    """The two bytes the filter compares as zoned decimal are alphabetic."""
    from harness.marrec import encode

    position = int(re.search(r"INCLUDE COND=\((\d+),", JCL).group(1))
    length = int(re.search(r"INCLUDE COND=\(\d+,(\d+),", JCL).group(1))
    sampled = {
        encode(scenario)[position - 1:position - 1 + length].decode()
        for scenario in corpus.scenarios
    }
    assert sampled, "no scenarios encoded"
    assert not any(value.isdigit() for value in sampled), (
        f"the filter compares {sorted(sampled)} as zoned decimal")


def test_the_bypass_filter_duplicates_a_rule_the_program_also_applies():
    """Both the SORT step and 2000-PROCESS drop grade 9; the constants must agree."""
    jcl_limit = int(re.search(r"INCLUDE COND=\(\d+,\d+,ZD,LT,(\d+)\)", JCL).group(1))
    cobol_limit = int(re.search(r"WS-MAX-GRADE\s+PIC 9\(02\) VALUE (\d+)",
                                COBOL_SOURCE).group(1))
    assert jcl_limit == cobol_limit


def test_the_extract_step_is_not_wired_to_the_batch_output():
    """STEP040 rebuilds the report from the master, which is why it can drift."""
    assert "ELIGOUT" not in STATEMENTS["SYSTSIN"]
    assert "IKJEFT01" in STATEMENTS["STEP040"]


@pytest.mark.parametrize("dd,disposition", [
    ("DELOLD", "DISP=(MOD,DELETE,DELETE)"),
    ("MSTRIN", "DISP=(OLD,DELETE)"),
    ("ELIGOUT", "DISP=(NEW,CATLG,DELETE)"),
])
def test_dataset_dispositions(dd, disposition):
    assert disposition in STATEMENTS[dd].replace(" ", "")


def test_the_sorted_work_file_is_deleted_by_the_batch_step():
    """&&SORTED is passed from STEP020 and consumed by STEP030."""
    assert "DISP=(NEW,PASS)" in STATEMENTS["SORTOUT"].replace(" ", "")
    assert "DISP=(OLD,DELETE)" in STATEMENTS["MSTRIN"].replace(" ", "")
