"""Executable evidence for the defects in docs/defects.md.

These tests fail when a defect is fixed. That is intentional: the ticket that
fixes one updates or deletes its test here and, for DEF-1/DEF-2, drops the
matching build-time patch under tests/cobol/patches.
"""

from __future__ import annotations

import os
import re
import subprocess

import pytest

from harness.engines import cobol
from harness.marrec import FIELDS, encode, write_master_file
from harness.model import REPO_ROOT

JCL = (REPO_ROOT / "jcl" / "PROMELIG.jcl").read_text()
COBOL_SOURCE = (REPO_ROOT / "cobol" / "PROMELIG.cbl").read_text()
PERL_SOURCE = (REPO_ROOT / "perl" / "load_unit_diary.pl").read_text()


def _patches_except(name: str) -> list:
    return [p for p in cobol.available_patches() if name not in p.name]


def _master(workdir, *scenarios):
    path = workdir / "master.dat"
    write_master_file(path, list(scenarios))
    return path


def _run(exe, master, workdir, corpus, timeout):
    env = dict(os.environ, DD_MSTRIN=str(master), DD_ELIGOUT=str(workdir / "elig.dat"),
               DD_RPTOUT=str(workdir / "rpt.txt"),
               COB_CURRENT_DATE=corpus.as_of.strftime("%Y/%m/%d 00:00:00"))
    return subprocess.run([str(exe)], env=env, cwd=workdir, capture_output=True,
                          timeout=timeout)


@pytest.mark.cobol
def test_def1_unpatched_batch_drops_every_record_after_the_first_denial(corpus, tmp_path):
    """GO TO 2490-EXIT falls through into 9000-TERM, which closes the files.

    The run then ends normally, having written one record of a two record
    master: the board slate is silently short. Built with the record-length
    patch applied so the layout is not also broken.
    """
    workdir = tmp_path / "unpatched-denied"
    exe = cobol.build(workdir, patches=_patches_except("def1"))
    master = workdir / "master.dat"
    denied = [corpus.by_id("tig-02-below"), corpus.by_id("tis-02-below")]
    write_master_file(master, denied)

    result = _run(exe, master, workdir, corpus, timeout=30)

    assert result.returncode == 0, "the job reports success"
    written = (workdir / "elig.dat").stat().st_size // cobol.ELIG_RECORD_LEN
    assert written == 1, "if this fails, DEF-1 is fixed"


@pytest.mark.cobol
@pytest.mark.slow
def test_def1_unpatched_batch_loops_forever_on_an_eligible_record(corpus, tmp_path):
    """After the fall-through closes the files, the loop keeps rewriting."""
    workdir = tmp_path / "unpatched-eligible"
    exe = cobol.build(workdir, patches=_patches_except("def1"))
    master = workdir / "master.dat"
    write_master_file(master, [corpus.by_id("tig-02-at"), corpus.by_id("tig-02-above")])

    try:
        with pytest.raises(subprocess.TimeoutExpired):
            _run(exe, master, workdir, corpus, timeout=5)
        written = (workdir / "elig.dat").stat().st_size // cobol.ELIG_RECORD_LEN
        assert written > 2, "the same record is written over and over"
    finally:
        # The run fills the disk quickly; do not leave the output behind.
        (workdir / "elig.dat").unlink(missing_ok=True)


def test_def1_apply_rules_branches_outside_the_performed_paragraph():
    """GO TO 2490-EXIT leaves the range of PERFORM 2400-APPLY-RULES."""
    assert "PERFORM 2400-APPLY-RULES\n" in COBOL_SOURCE
    assert "THRU 2490-EXIT" not in COBOL_SOURCE
    assert COBOL_SOURCE.count("GO TO 2490-EXIT") == 5


@pytest.mark.cobol
def test_def2_record_length_mismatch_shifts_every_field(corpus, tmp_path):
    """With the 137-byte copybook, GnuCOBOL reads the 140-byte file as variable
    length and each record lands four bytes off."""
    scenario = corpus.by_id("tig-02-below")

    correct = tmp_path / "correct"
    _run(cobol.build(correct), _master(correct, scenario), correct, corpus, timeout=30)

    shifted = tmp_path / "shifted"
    _run(cobol.build(shifted, patches=_patches_except("def2")),
         _master(shifted, scenario), shifted, corpus, timeout=30)

    assert (correct / "elig.dat").read_bytes()[:10].decode() == str(scenario.edipi)
    assert (shifted / "elig.dat").read_bytes() != (correct / "elig.dat").read_bytes(), (
        "if this fails, DEF-2 is fixed"
    )


def test_def2_copybook_is_shorter_than_the_declared_record_length():
    declared = int(re.search(r"RECORD CONTAINS (\d+) CHARACTERS", COBOL_SOURCE).group(1))
    copybook_length = max(f.offset + f.length for f in FIELDS.values())
    assert declared == 140
    assert copybook_length == 137, "copybook length changed; update docs/defects.md"


def test_def3_jcl_include_filter_points_at_the_wrong_field():
    """INCLUDE COND=(58,2,ZD,LT,09) reads MM-GRADE, not MM-GRADE-NUM."""
    position, length = re.search(r"INCLUDE COND=\((\d+),(\d+),ZD", JCL).groups()
    grade = FIELDS["MM-GRADE"]
    grade_num = FIELDS["MM-GRADE-NUM"]

    assert int(position) == grade.offset + 1, "the filter starts inside MM-GRADE"
    assert int(position) != grade_num.offset + 1, "if this fails, DEF-3 is fixed"
    assert int(length) == grade_num.length


def test_def3_jcl_sort_key_matches_edipi():
    position, length = re.search(r"SORT FIELDS=\((\d+),(\d+),ZD", JCL).groups()
    edipi = FIELDS["MM-EDIPI"]
    assert (int(position), int(length)) == (edipi.offset + 1, edipi.length)


def test_def4_eligibility_record_truncates_the_computed_month_counters():
    tig_working = re.search(r"WS-TIG-MOS\s+PIC S9\((\d+)\)", COBOL_SOURCE).group(1)
    tig_output = re.search(r"EL-TIG-MOS\s+PIC 9\((\d+)\)", COBOL_SOURCE).group(1)
    assert int(tig_working) > int(tig_output)


@pytest.mark.cobol
def test_def5_report_counters_are_written_as_packed_decimal(cobol_run):
    """9000-TERM STRINGs COMP-3 counters into a character report."""
    _, report = cobol_run
    assert "PROMELIG READ=" in report
    assert not re.search(r"READ=\s*\d+", report), "if this fails, DEF-5 is fixed"


def test_def6_loader_does_not_validate_the_input_record_length():
    assert "length(" not in PERL_SOURCE.lower()
    assert "substr" in PERL_SOURCE


def test_def7_loader_offsets_track_the_copybook(corpus):
    """The Perl offsets and the copybook agree today; this pins them together."""
    offsets = {
        name: (int(off), int(length))
        for name, off, length in re.findall(
            r"(\w+)\s*=>\s*\[\s*(\d+),\s*(\d+)\s*\]", PERL_SOURCE)
    }
    expected = {
        "edipi": "MM-EDIPI", "last_nm": "MM-LAST-NM", "first_nm": "MM-FIRST-NM",
        "middle_init": "MM-MIDDLE-INIT", "grade": "MM-GRADE", "grade_num": "MM-GRADE-NUM",
        "pmos": "MM-PMOS", "dt_last_promo": "MM-DT-LAST-PROMO",
        "dt_orig_promo": "MM-DT-ORIG-PROMO", "grade_eff_dt": "MM-GRADE-EFF-DT",
        "pebd": "MM-PEBD", "dt_enlist": "MM-DT-ENLIST",
        "red_in_grade_ind": "MM-RED-IN-GRADE-IND",
    }
    assert set(offsets) == set(expected)
    for perl_name, copybook_name in expected.items():
        field = FIELDS[copybook_name]
        assert offsets[perl_name] == (field.offset, field.length), copybook_name


def test_def8_loader_ignores_every_field_after_the_reduction_indicator(corpus):
    """Duty status, component, drill status and the packed counters never load."""
    loaded = set(re.findall(r"(\w+)\s*=>\s*\[\s*\d+,\s*\d+\s*\]", PERL_SOURCE))
    never_loaded = {"duty_stat", "component", "rc_drill_stat", "brk_svc_mos",
                    "adv_matl_ind", "adv_matl_mos"}
    assert not (loaded & never_loaded)


def test_def9_reporting_extract_uses_a_stale_adverse_lookback():
    sql = (REPO_ROOT / "sql" / "promotion_eligibility.sql").read_text()
    cobol_lookback = re.search(r"WS-ADV-LOOKBACK-MOS\s+PIC 9\(03\) VALUE (\d+)",
                               COBOL_SOURCE).group(1)
    sql_lookback = re.search(r"V_ADV_LOOKBACK_MOS\s+NUMBER := (\d+)", sql).group(1)
    assert int(cobol_lookback) == 24
    assert int(sql_lookback) == 12, "if this fails, DEF-9 is fixed"


def test_scenario_encoding_is_exactly_the_declared_record_length(corpus):
    assert all(len(encode(s)) == 140 for s in corpus.scenarios)
