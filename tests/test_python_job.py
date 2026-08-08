"""The Python replacement for jcl/PROMELIG.jcl.

``test_jcl_job.py`` pins the wiring of the JCL itself; this pins that the Python
job keeps it: the same four steps in the same order, the same conditional
execution, the same EDIPI sort key, the same 60-byte extract, and the same
misaimed INCLUDE filter (DEF-3).
"""

from __future__ import annotations

import re

from promelig import batch, job

from harness.engines import python_batch
from harness.marrec import FIELDS, encode, parse_elig_file
from harness.model import REPO_ROOT, Corpus

JCL = (REPO_ROOT / "jcl" / "PROMELIG.jcl").read_text()


def test_steps_run_in_the_documented_order(corpus: Corpus, tmp_path):
    result = python_batch.run_job(corpus, tmp_path)
    assert [step.name for step in result.steps] == [
        "STEP010", "STEP020", "STEP030", "STEP040"]
    assert result.return_code == 0


def test_the_job_produces_the_same_board_slate_as_the_batch(
        corpus: Corpus, python_rows, tmp_path):
    python_batch.run_job(corpus, tmp_path)
    records = parse_elig_file(tmp_path / "MANPWR.PROD.ELIG.EXTRACT",
                              batch.ELIG_RECORD_LEN)
    assert [r["edipi"] for r in records] == [row.edipi for row in sorted(python_rows)]


def test_a_failing_step_stops_the_ones_after_it(corpus: Corpus, tmp_path):
    """COND=(0,NE): STEP030 and STEP040 do not run once the sort has failed."""
    result = job.run_job(master=tmp_path / "absent.master",
                         elig_out=tmp_path / "elig.dat",
                         work_dir=tmp_path / "work",
                         run_date=corpus.as_of)
    assert [step.name for step in result.steps] == ["STEP010", "STEP020"]
    assert result.return_code != 0


def test_step010_deletes_the_previous_extract(corpus: Corpus, tmp_path):
    stale = tmp_path / "MANPWR.PROD.ELIG.EXTRACT"
    stale.write_bytes(b"stale")
    result = python_batch.run_job(corpus, tmp_path)
    assert "deleted previous extract" in result.steps[0].detail
    assert stale.read_bytes() != b"stale"


def test_the_sorted_work_file_is_deleted_by_the_batch_step(corpus: Corpus, tmp_path):
    """&&SORTED is passed from STEP020 and consumed with DISP=(OLD,DELETE)."""
    python_batch.run_job(corpus, tmp_path)
    assert not (tmp_path / "work" / "SORTED").exists()


def test_the_sort_key_is_the_edipi(corpus: Corpus):
    edipi = FIELDS["MM-EDIPI"]
    assert (job.SORT_KEY_POSITION, job.SORT_KEY_LENGTH) == (edipi.offset + 1, edipi.length)

    shuffled = [encode(s) for s in sorted(corpus.scenarios, key=lambda s: -s.edipi)]
    ordered = job.sort_master(b"".join(shuffled))
    edipis = [ordered[i:i + 10].decode() for i in range(0, len(ordered), 140)]
    assert edipis == sorted(edipis)


def test_the_extract_record_length_matches_the_batch(corpus: Corpus, tmp_path):
    python_batch.run_job(corpus, tmp_path)
    raw = (tmp_path / "MANPWR.PROD.ELIG.EXTRACT").read_bytes()
    assert job.ELIG_LRECL == 60
    assert len(raw) % job.ELIG_LRECL == 0


def test_the_include_filter_still_points_at_the_wrong_field():
    """DEF-3, preserved: position 58 is MM-GRADE, not MM-GRADE-NUM at 61."""
    position, length, limit = re.search(
        r"INCLUDE COND=\((\d+),(\d+),ZD,LT,(\d+)\)", JCL).groups()
    assert (job.INCLUDE_POSITION, job.INCLUDE_LENGTH) == (int(position), int(length))
    assert job.INCLUDE_LIMIT == int(limit)
    assert job.INCLUDE_POSITION == FIELDS["MM-GRADE"].offset + 1
    assert job.INCLUDE_POSITION != FIELDS["MM-GRADE-NUM"].offset + 1


def test_the_include_filter_removes_nothing_from_the_board_slate(corpus: Corpus):
    """The grade text it compares is not zoned decimal, so it excludes no one."""
    master = b"".join(encode(s) for s in corpus.scenarios)
    assert len(job.sort_master(master)) == len(master)


def test_the_include_filter_would_drop_the_top_grade_if_it_read_the_right_field():
    """What the filter is for: grade 9 excluded, grade 8 kept."""
    assert job.zoned_decimal(b"09") == 9
    assert job.zoned_decimal(b"08") == 8
    assert job.zoned_decimal(b"SG") is None


def test_the_reporting_extract_step_is_not_wired_to_the_batch_output(corpus: Corpus,
                                                                     tmp_path):
    """STEP040 rebuilds the report from the master, which is why it can drift."""
    seen = []

    def runner(command: str) -> job.StepResult:
        seen.append(command)
        return job.StepResult("STEP040", 0, command)

    master = tmp_path / "master.dat"
    from harness.marrec import write_master_file
    write_master_file(master, corpus.scenarios)
    result = job.run_job(master=master, elig_out=tmp_path / "elig.dat",
                         work_dir=tmp_path / "work", run_date=corpus.as_of,
                         extract_command="refresh-extract", extract_runner=runner)
    assert seen == ["refresh-extract"]
    assert result.steps[-1].ok
    assert "elig.dat" not in seen[0]
