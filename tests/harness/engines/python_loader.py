"""Run the Python unit diary loader against a throwaway SQLite database.

Deliberately the same shape as ``perl_loader``: same schema, same fixtures, same
``LoaderRun``, so the two loaders can be driven by one test and compared row for
row. The loader is invoked through its CLI rather than imported, so the parity
comparison covers the entry point as well as the parsing.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Iterable, Optional

from ..model import REPO_ROOT
from .perl_loader import (LOADED_COLUMNS, SCHEMA, LoaderRun,  # noqa: F401
                          create_database, feed_from_scenarios, write_feed)

PACKAGE_ROOT = REPO_ROOT / "python"
MODULE = "promelig.unit_diary"


def run(workdir: Path, feed: Path, database: Optional[Path] = None,
        seed: Iterable[dict] = ()) -> LoaderRun:
    workdir.mkdir(parents=True, exist_ok=True)
    db = database or create_database(workdir / "master.sqlite", seed)
    result = subprocess.run(
        [sys.executable, "-m", MODULE, "--feed", str(feed),
         "--dsn", f"dbi:SQLite:dbname={db}"],
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(PACKAGE_ROOT)},
        capture_output=True, text=True, timeout=120,
    )
    return LoaderRun(result.returncode, result.stdout, result.stderr, db)
