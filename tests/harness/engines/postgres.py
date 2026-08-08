"""Run the reporting extract against a throwaway PostgreSQL container.

The production procedure is Oracle PL/SQL and Oracle is not available here, so
the harness runs the translation in ``tests/sql/sp_promotion_eligibility_pg.sql``
(kept honest by ``test_sql_translation.py``). psql is driven through
``docker exec`` so the suite needs no database driver installed.
"""

from __future__ import annotations

import csv
import io
import shutil
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from ..model import REPO_ROOT, Corpus, to_date
from ..normalize import Row

SQL_DIR = REPO_ROOT / "tests" / "sql"
IMAGE = "postgres:16-alpine"
DB_NAME = "promelig"
DB_USER = "postgres"

# The extract writes NULL into TIG_MOS/TIS_MOS when the underlying date is
# missing, because Oracle GREATEST propagates NULL. The normalized row shape is
# integer-only, so NULL is carried as this sentinel rather than being flattened
# to zero, which would hide the behavior.
NULL_MONTHS = -1


class PostgresUnavailable(RuntimeError):
    pass


def _docker() -> str:
    docker = shutil.which("docker")
    if not docker:
        raise PostgresUnavailable("docker is not installed; the SQL suite needs it")
    return docker


def _psql(container: str, sql: str, expect_csv: bool = False) -> str:
    args = ["-v", "ON_ERROR_STOP=1", "-q"]
    if expect_csv:
        args += ["--csv", "-t"]
    result = subprocess.run(
        [_docker(), "exec", "-i", container, "psql", "-U", DB_USER, "-d", DB_NAME, *args],
        input=sql, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql failed: {result.stderr.strip()}")
    return result.stdout


@contextmanager
def database() -> Iterator[str]:
    """Start a PostgreSQL container with the schema and procedure loaded."""
    docker = _docker()
    container = f"promelig-test-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [docker, "run", "-d", "--rm", "--name", container,
         "-e", f"POSTGRES_DB={DB_NAME}",
         "-e", "POSTGRES_HOST_AUTH_METHOD=trust",
         IMAGE],
        check=True, capture_output=True, text=True,
    )
    try:
        # pg_isready reports success during the image's bootstrap phase, before
        # POSTGRES_DB exists, so wait on a real query instead.
        deadline = time.time() + 90
        while True:
            probe = subprocess.run(
                [docker, "exec", container, "psql", "-U", DB_USER, "-d", DB_NAME,
                 "-tAc", "SELECT 1"],
                capture_output=True, text=True,
            )
            if probe.returncode == 0 and probe.stdout.strip() == "1":
                break
            if time.time() > deadline:
                raise PostgresUnavailable(
                    f"PostgreSQL container did not become ready: {probe.stderr.strip()}")
            time.sleep(0.5)

        _psql(container, (SQL_DIR / "schema.sql").read_text())
        _psql(container, (SQL_DIR / "sp_promotion_eligibility_pg.sql").read_text())
        yield container
    finally:
        subprocess.run([docker, "rm", "-f", container], capture_output=True, text=True)


def _sql_date(value: int) -> str:
    parsed = to_date(value)
    return f"DATE '{parsed.isoformat()}'" if parsed else "NULL"


def _sql_text(value: str) -> str:
    stripped = value.strip()
    return f"'{stripped}'" if stripped else "NULL"


def load_corpus(container: str, corpus: Corpus) -> None:
    values = []
    for s in corpus.scenarios:
        values.append(
            "(" + ", ".join([
                str(s.edipi), _sql_text(s.last_nm), _sql_text(s.first_nm),
                _sql_text(s.middle_init), _sql_text(s.grade), str(s.grade_num),
                _sql_text(s.pmos), _sql_date(s.dt_last_promo), _sql_date(s.dt_orig_promo),
                _sql_date(s.grade_eff_dt), _sql_date(s.pebd), _sql_date(s.dt_enlist),
                _sql_text(s.red_in_grade_ind), str(s.brk_svc_mos),
                _sql_text(s.adv_matl_ind), str(s.adv_matl_mos),
                _sql_text(s.duty_stat), _sql_text(s.component), _sql_text(s.rc_drill_stat),
            ]) + ")"
        )
    _psql(container, "TRUNCATE MARINE_MASTER;\nINSERT INTO MARINE_MASTER VALUES\n"
          + ",\n".join(values) + ";")


def run_extract(container: str, corpus: Corpus, component: Optional[str] = None) -> list[Row]:
    component_arg = f"'{component}'" if component else "NULL"
    _psql(container, f"CALL SP_PROMOTION_ELIGIBILITY(DATE '{corpus.as_of.isoformat()}', "
                     f"{component_arg}, NULL);")
    out = _psql(
        container,
        "SELECT EDIPI, TGT_GRADE_NUM, COALESCE(TIG_MOS, %d), COALESCE(TIS_MOS, %d), "
        "ELIG_IND, COALESCE(DENY_RSN, '') FROM RPT_PROMOTION_ELIGIBILITY ORDER BY EDIPI;"
        % (NULL_MONTHS, NULL_MONTHS),
        expect_csv=True,
    )
    rows = []
    for record in csv.reader(io.StringIO(out)):
        if not record:
            continue
        rows.append(Row.make(record[0], record[1], record[2], record[3], record[4], record[5]))
    return rows


def run_rows(corpus: Corpus, _workdir: Optional[Path] = None) -> list[Row]:
    with database() as container:
        load_corpus(container, corpus)
        return run_extract(container, corpus)
