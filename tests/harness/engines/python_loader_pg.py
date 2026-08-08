"""Run the Python unit diary loader against the real PostgreSQL schema.

SQLite is what the parity comparison against the Perl loader runs on, because
that is where the Perl loader can be driven; PostgreSQL is the production target,
so this exercises the same loader against ``tests/sql/schema.sql`` -- typed DATE,
BIGINT and SMALLINT columns rather than SQLite's TEXT.

Needs docker and a PostgreSQL driver; the tests using it skip without either.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from ..model import REPO_ROOT
from .postgres import DB_NAME, DB_USER, IMAGE, PostgresUnavailable, _docker, _psql

SQL_DIR = REPO_ROOT / "tests" / "sql"
PACKAGE_ROOT = REPO_ROOT / "python"


class DriverUnavailable(RuntimeError):
    pass


def require_driver() -> Any:
    for name in ("psycopg", "psycopg2"):
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
    raise DriverUnavailable("no PostgreSQL driver installed (psycopg2-binary)")


@contextmanager
def database() -> Iterator[str]:
    """A PostgreSQL container with the master schema loaded, on a mapped port."""
    docker = _docker()
    require_driver()
    container = f"promelig-loader-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [docker, "run", "-d", "--rm", "--name", container,
         "-e", f"POSTGRES_DB={DB_NAME}",
         "-e", "POSTGRES_HOST_AUTH_METHOD=trust",
         "-p", "0:5432", IMAGE],
        check=True, capture_output=True, text=True,
    )
    try:
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
        yield container
    finally:
        subprocess.run([docker, "rm", "-f", container], capture_output=True, text=True)


def port(container: str) -> int:
    result = subprocess.run(
        [_docker(), "port", container, "5432/tcp"],
        check=True, capture_output=True, text=True)
    return int(result.stdout.splitlines()[0].rsplit(":", 1)[1])


def dsn(container: str) -> str:
    return (f"postgresql://{DB_USER}@127.0.0.1:{port(container)}/{DB_NAME}")


def run(container: str, feed: Path,
        commit_every: Optional[int] = None) -> subprocess.CompletedProcess:
    argv = [sys.executable, "-m", "promelig.unit_diary",
            "--feed", str(feed), "--dsn", dsn(container)]
    if commit_every is not None:
        argv += ["--commit-every", str(commit_every)]
    return subprocess.run(argv, env={"PATH": "/usr/bin:/bin",
                                     "PYTHONPATH": str(PACKAGE_ROOT)},
                          capture_output=True, text=True, timeout=180)


COLUMNS = ("EDIPI, GRADE, GRADE_NUM, DT_LAST_PROMO, DT_ORIG_PROMO, "
           "GRADE_EFF_DT, PEBD")


def rows(container: str, columns: str = COLUMNS) -> list[str]:
    out = _psql(container, f"SELECT {columns} FROM MARINE_MASTER ORDER BY EDIPI;",
                expect_csv=True)
    return [line for line in out.splitlines() if line]
