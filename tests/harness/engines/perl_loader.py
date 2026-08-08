"""Run perl/load_unit_diary.pl against a throwaway SQLite database.

The loader takes its DSN from the environment, so pointing it at SQLite needs
no change to the script. DBD::SQLite accepts the UPDATE-then-INSERT upsert and
the manual commit handling unchanged.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from ..marrec import feed_line
from ..model import REPO_ROOT, Scenario

LOADER = REPO_ROOT / "perl" / "load_unit_diary.pl"

# Only the columns load_unit_diary.pl writes.
LOADED_COLUMNS = (
    "edipi", "last_nm", "first_nm", "middle_init", "grade", "grade_num", "pmos",
    "dt_last_promo", "dt_orig_promo", "grade_eff_dt", "pebd", "dt_enlist",
    "red_in_grade_ind",
)

SCHEMA = """
CREATE TABLE MARINE_MASTER (
    edipi            TEXT PRIMARY KEY,
    last_nm          TEXT,
    first_nm         TEXT,
    middle_init      TEXT,
    grade            TEXT,
    grade_num        TEXT,
    pmos             TEXT,
    dt_last_promo    TEXT,
    dt_orig_promo    TEXT,
    grade_eff_dt     TEXT,
    pebd             TEXT,
    dt_enlist        TEXT,
    red_in_grade_ind TEXT
);
"""


class PerlUnavailable(RuntimeError):
    pass


@dataclass
class LoaderRun:
    returncode: int
    stdout: str
    stderr: str
    database: Path

    @property
    def loaded(self) -> int:
        return int(self.stdout.split("loaded ")[1].split(" ")[0])

    @property
    def carried_forward(self) -> int:
        return int(self.stdout.split("records, ")[1].split(" ")[0])

    def rows(self) -> list[dict]:
        with sqlite3.connect(self.database) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in
                    conn.execute("SELECT * FROM MARINE_MASTER ORDER BY edipi")]

    def row(self, edipi: int) -> Optional[dict]:
        return next((r for r in self.rows() if r["edipi"] == str(edipi)), None)


def require_perl() -> None:
    if not shutil.which("perl"):
        raise PerlUnavailable("perl is not installed")
    probe = subprocess.run(["perl", "-MDBD::SQLite", "-e", "1"], capture_output=True)
    if probe.returncode != 0:
        raise PerlUnavailable("DBD::SQLite is not installed (libdbd-sqlite3-perl)")


def create_database(path: Path, seed: Iterable[dict] = ()) -> Path:
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        for row in seed:
            columns = ", ".join(row)
            binds = ", ".join("?" for _ in row)
            conn.execute(f"INSERT INTO MARINE_MASTER ({columns}) VALUES ({binds})",
                         list(row.values()))
    return path


def write_feed(path: Path, lines: Iterable[str]) -> Path:
    path.write_text("".join(line.rstrip("\n") + "\n" for line in lines))
    return path


def feed_from_scenarios(path: Path, scenarios: Iterable[Scenario]) -> Path:
    return write_feed(path, [feed_line(s) for s in scenarios])


def run(workdir: Path, feed: Path, database: Optional[Path] = None,
        seed: Iterable[dict] = ()) -> LoaderRun:
    require_perl()
    workdir.mkdir(parents=True, exist_ok=True)
    db = database or create_database(workdir / "master.sqlite", seed)
    result = subprocess.run(
        ["perl", str(LOADER)],
        env={
            "PATH": "/usr/bin:/bin",
            "UD_FEED": str(feed),
            "DSN": f"dbi:SQLite:dbname={db}",
            "DBUSER": "",
            "DBPASS": "",
        },
        capture_output=True, text=True, timeout=120,
    )
    return LoaderRun(result.returncode, result.stdout, result.stderr, db)
