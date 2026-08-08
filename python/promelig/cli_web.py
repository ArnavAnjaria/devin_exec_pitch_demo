"""Command line front end for the eligibility determination.

Reads the fixed-width master file, runs the same determination the web tier
serves, and writes the six normalized columns every engine in this repo emits:
``edipi,tgt_grade,tig_mos,tis_mos,elig_ind,deny_rsn``.

A determination that cannot be completed (DIV-5) is reported on stderr and sets
the exit status; it is deliberately not flattened into a row here, because what
that row should say is the open question in DIV-5.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
from pathlib import Path
from typing import Optional, Sequence, TextIO

from .eligibility import EligibilityError, EligibilityService
from .marrec import DECLARED_RECORD_LEN, read_master_file
from .model import EligibilityResult, Outcome
from .repositories import (InMemoryGradeRequirementRepository,
                           InMemoryMarineMasterRepository)

COLUMNS = ("edipi", "tgt_grade", "tig_mos", "tis_mos", "elig_ind", "deny_rsn")

ELIG_INDICATOR = {
    Outcome.ELIGIBLE: "Y",
    Outcome.DENIED: "N",
    Outcome.BYPASS: "B",
    Outcome.NOT_FOUND: "X",
}


def to_row(result: EligibilityResult) -> tuple:
    deny_reason = result.deny_reason or ("NOTF" if result.outcome is Outcome.NOT_FOUND else "")
    return (result.edipi, result.target_grade, result.tig_months, result.tis_months,
            ELIG_INDICATOR[result.outcome], deny_reason)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="promelig",
        description="Promotion eligibility determination for the web tier.")
    parser.add_argument("--master", type=Path, required=True,
                        help="fixed-width MARREC master file")
    parser.add_argument("--as-of", type=dt.date.fromisoformat, default=dt.date.today(),
                        help="determination date, YYYY-MM-DD (default: today)")
    parser.add_argument("--edipi", type=int, action="append", dest="edipis", metavar="EDIPI",
                        help="determine one EDIPI; repeatable (default: the whole file)")
    parser.add_argument("--record-len", type=int, default=DECLARED_RECORD_LEN,
                        help=f"master record length (default: {DECLARED_RECORD_LEN})")
    parser.add_argument("--output", type=Path,
                        help="write the rows here instead of stdout")
    return parser


def run(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    masters = list(read_master_file(args.master, args.record_len))
    service = EligibilityService(InMemoryGradeRequirementRepository(),
                                 InMemoryMarineMasterRepository(masters))
    edipis = args.edipis if args.edipis else [m.edipi for m in masters]

    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    failures = 0
    for edipi in edipis:
        try:
            writer.writerow(to_row(service.determine(edipi, args.as_of)))
        except EligibilityError as exc:
            failures += 1
            print(f"{edipi}: {exc}", file=err)
    return 1 if failures else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", newline="") as fh:
            return run(args, fh, sys.stderr)
    return run(args, sys.stdout, sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
