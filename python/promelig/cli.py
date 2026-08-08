"""Command line entry point for the reporting extract.

    python -m promelig.cli --dsn 'postgresql://user@host/promelig' --run-date 2026-06-15

Equivalent to ``CALL SP_PROMOTION_ELIGIBILITY(:run_dt, :component, :rows_out)``.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
from dataclasses import astuple
from pathlib import Path
from typing import Optional, Sequence

from .db import PsqlDatabase, PsqlError
from .sql_extract import ComponentError, ExtractRow, run_extract

CSV_COLUMNS = ("edipi", "grade", "tgt_grade_num", "tig_mos", "tis_mos",
               "elig_ind", "deny_rsn", "run_dt")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="promelig-sql-extract",
        description="Rebuild RPT_PROMOTION_ELIGIBILITY for one run date.")
    parser.add_argument("--dsn", required=True,
                        help="libpq connection string or URI, passed to psql")
    parser.add_argument("--run-date", type=dt.date.fromisoformat, default=dt.date.today(),
                        help="report as-of date, YYYY-MM-DD (default: today)")
    parser.add_argument("--component", default=None,
                        help="restrict the extract to one component, e.g. R")
    parser.add_argument("--psql", default="psql", help="path to the psql client")
    parser.add_argument("--csv", type=Path, default=None,
                        help="also write the rows to this file ('-' for stdout)")
    return parser


def write_csv(rows: Sequence[ExtractRow], destination: Path) -> None:
    handle = sys.stdout if str(destination) == "-" else destination.open("w", newline="")
    try:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        for row in rows:
            writer.writerow("" if field is None else field for field in astuple(row))
    finally:
        if handle is not sys.stdout:
            handle.close()


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    db = PsqlDatabase.from_dsn(args.dsn, psql=args.psql)
    try:
        rows = run_extract(db, args.run_date, args.component)
    except (ComponentError, PsqlError) as exc:
        print(f"promelig-sql-extract: {exc}", file=sys.stderr)
        return 1
    if args.csv is not None:
        write_csv(rows, args.csv)
    print(f"{len(rows)} rows written for {args.run_date.isoformat()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
