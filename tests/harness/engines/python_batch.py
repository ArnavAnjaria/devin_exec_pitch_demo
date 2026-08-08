"""Run the Python batch (``python/promelig``) over the corpus.

Mirrors ``engines/cobol.py`` step for step so the two are comparable: the same
fixed-width master file, sorted by EDIPI the way STEP020 sorts it, the same
60-byte extract parsed back with the same reader.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from promelig import batch, job

from ..marrec import DECLARED_RECORD_LEN, parse_elig_file, write_master_file
from ..model import Corpus
from ..normalize import Row

ELIG_RECORD_LEN = batch.ELIG_RECORD_LEN


def run(corpus: Corpus, workdir: Path) -> tuple[list[Row], bytes]:
    """Run the batch over the corpus; return normalized rows and the RPTOUT bytes."""
    workdir.mkdir(parents=True, exist_ok=True)
    master = workdir / "master.dat"
    elig = workdir / "elig.dat"
    report = workdir / "rpt.txt"

    # STEP020 sorts the master by EDIPI before PROMELIG sees it.
    scenarios = sorted(corpus.scenarios, key=lambda s: s.edipi)
    write_master_file(master, scenarios, record_len=DECLARED_RECORD_LEN)

    batch.run(master, elig, report, corpus.as_of)

    rows = [
        Row.make(r["edipi"], r["tgt_grade"], r["tig_mos"], r["tis_mos"],
                 r["elig_ind"], r["deny_rsn"])
        for r in parse_elig_file(elig, ELIG_RECORD_LEN)
    ]
    return rows, report.read_bytes()


def run_rows(corpus: Corpus, workdir: Path) -> list[Row]:
    return run(corpus, workdir)[0]


def run_job(corpus: Corpus, workdir: Path,
            run_date: dt.date | None = None) -> job.JobResult:
    """Run the full four-step job over the corpus master."""
    workdir.mkdir(parents=True, exist_ok=True)
    master = workdir / "MANPWR.PROD.MASTER"
    write_master_file(master, sorted(corpus.scenarios, key=lambda s: s.edipi),
                      record_len=DECLARED_RECORD_LEN)
    return job.run_job(
        master=master,
        elig_out=workdir / "MANPWR.PROD.ELIG.EXTRACT",
        work_dir=workdir / "work",
        run_date=run_date or corpus.as_of,
        report_out=workdir / "rpt.txt",
    )
