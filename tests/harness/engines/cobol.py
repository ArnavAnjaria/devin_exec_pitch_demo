"""Run PROMELIG.cbl under GnuCOBOL.

The production source is never modified. It is copied into a build directory and
two patches from ``tests/cobol/patches`` are applied there, because without them
the program cannot process the corpus at all:

* ``0001-def1-read-next-record`` -- ``PERFORM 2000-PROCESS UNTIL WS-EOF`` only
  re-reads the master via the grade >= 9 bypass path, so any eligible or denied
  record loops forever (DEF-1).
* ``0002-def2-record-length`` -- the copybook is 137 bytes but the FD declares
  140, which makes GnuCOBOL treat the file as variable length and read every
  field four bytes off (DEF-2).

Both are tracked as defects, not silently absorbed: ``test_defects.py`` asserts
the unpatched program still exhibits them, so the patches disappear the moment
the underlying tickets are fixed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from ..marrec import DECLARED_RECORD_LEN, parse_elig_file, write_master_file
from ..model import REPO_ROOT, Corpus
from ..normalize import Row

PATCH_DIR = REPO_ROOT / "tests" / "cobol" / "patches"
ELIG_RECORD_LEN = 60


class CobolUnavailable(RuntimeError):
    pass


def require_gnucobol() -> str:
    cobc = shutil.which("cobc")
    if not cobc:
        raise CobolUnavailable("GnuCOBOL (cobc) is not installed; see docs/testing.md")
    return cobc


def available_patches() -> list[Path]:
    return sorted(PATCH_DIR.glob("*.patch"))


def build(workdir: Path, patched: bool = True,
          patches: Optional[list[Path]] = None) -> Path:
    """Compile PROMELIG into ``workdir`` and return the executable path.

    ``patches`` selects a subset of the build-time patches, which the defect
    tests use to isolate one defect from the other.
    """
    require_gnucobol()
    src = workdir / "src"
    copybook = src / "copybook"
    copybook.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO_ROOT / "cobol" / "PROMELIG.cbl", src / "PROMELIG.cbl")
    shutil.copy(REPO_ROOT / "cobol" / "copybook" / "MARREC.cpy", copybook / "MARREC.cpy")

    if patched:
        for patch in (available_patches() if patches is None else patches):
            subprocess.run(
                ["patch", "-p2", "-i", str(patch)],
                cwd=src, check=True, capture_output=True, text=True,
            )

    exe = workdir / "promelig"
    subprocess.run(
        [
            "cobc", "-x",
            # DD names in the SELECT clauses are external file names, as they
            # are on z/OS; GnuCOBOL binds them from DD_<name> in the environment.
            "-fassign-clause=external",
            "-I", str(copybook),
            "-o", str(exe),
            str(src / "PROMELIG.cbl"),
        ],
        check=True, capture_output=True, text=True,
    )
    return exe


def run(corpus: Corpus, workdir: Path, patched: bool = True,
        timeout: int = 60) -> tuple[list[Row], str]:
    """Run the batch over the corpus; return normalized rows and the RPTOUT text."""
    exe = build(workdir, patched=patched)
    master = workdir / "master.dat"
    elig = workdir / "elig.dat"
    report = workdir / "rpt.txt"

    # The JCL sorts the master by EDIPI before PROMELIG sees it (STEP020).
    scenarios = sorted(corpus.scenarios, key=lambda s: s.edipi)
    write_master_file(master, scenarios, record_len=DECLARED_RECORD_LEN)

    env = dict(os.environ)
    env.update({
        "DD_MSTRIN": str(master),
        "DD_ELIGOUT": str(elig),
        "DD_RPTOUT": str(report),
        # PROMELIG takes the run date from the system clock (ACCEPT FROM DATE),
        # so the corpus as-of date is injected via libcob's date override.
        "COB_CURRENT_DATE": corpus.as_of.strftime("%Y/%m/%d 00:00:00"),
    })
    subprocess.run([str(exe)], env=env, cwd=workdir, check=True,
                   capture_output=True, text=True, timeout=timeout)

    rows = [
        Row.make(r["edipi"], r["tgt_grade"], r["tig_mos"], r["tis_mos"],
                 r["elig_ind"], r["deny_rsn"])
        for r in parse_elig_file(elig, ELIG_RECORD_LEN)
    ]
    return rows, report.read_text(errors="replace")


def run_rows(corpus: Corpus, workdir: Path) -> list[Row]:
    return run(corpus, workdir)[0]
