"""Run the Python reporting extract (``promelig.sql_extract``).

The Python replacement reads and writes the same tables as the procedure it
replaces, so it runs against the same throwaway PostgreSQL container as
``postgres.py``: that harness loads the corpus and this one drives the Python
code over it. The two must produce identical rows -- that is the whole point of
``tests/test_python_sql_extract.py``.
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path
from typing import Optional

from ..model import REPO_ROOT, Corpus
from ..normalize import Row
from . import postgres

PACKAGE_ROOT = REPO_ROOT / "python"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from promelig import sql_extract  # noqa: E402
from promelig.db import PsqlDatabase  # noqa: E402


def connect(container: str) -> PsqlDatabase:
    return PsqlDatabase.in_docker(container, dbname=postgres.DB_NAME, user=postgres.DB_USER)


def normalize(rows: list[sql_extract.ExtractRow]) -> list[Row]:
    """Reduce extract rows to the six columns every engine is compared on.

    NULL month counts are carried as ``postgres.NULL_MONTHS`` for the same
    reason the SQL harness does it: flattening them to zero would hide DIV-6.
    """
    return [
        Row.make(row.edipi, row.tgt_grade_num,
                 postgres.NULL_MONTHS if row.tig_mos is None else row.tig_mos,
                 postgres.NULL_MONTHS if row.tis_mos is None else row.tis_mos,
                 row.elig_ind, row.deny_rsn)
        for row in rows
    ]


def run_extract(container: str, corpus: Corpus,
                component: Optional[str] = None) -> list[Row]:
    rows = sql_extract.run_extract(connect(container), corpus.as_of, component)
    return normalize(rows)


def read_report(container: str) -> list[Row]:
    """Read back what the extract wrote, so the insert path is characterized too."""
    out = postgres._psql(
        container,
        "SELECT EDIPI, TGT_GRADE_NUM, COALESCE(TIG_MOS, %d), COALESCE(TIS_MOS, %d), "
        "ELIG_IND, COALESCE(DENY_RSN, '') FROM RPT_PROMOTION_ELIGIBILITY ORDER BY EDIPI;"
        % (postgres.NULL_MONTHS, postgres.NULL_MONTHS),
        expect_csv=True,
    )
    return [
        Row.make(r[0], r[1], r[2], r[3], r[4], r[5])
        for r in csv.reader(io.StringIO(out)) if r
    ]


def run_rows(corpus: Corpus, _workdir: Optional[Path] = None) -> list[Row]:
    with postgres.database() as container:
        postgres.load_corpus(container, corpus)
        return run_extract(container, corpus)
