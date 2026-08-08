"""Unit diary feed loader -- the Python replacement for perl/load_unit_diary.pl.

Reads the nightly fixed-width unit diary feed and upserts personnel records into
MARINE_MASTER. Runs ahead of PROMELIG in the nightly cycle.

This is a like-for-like rewrite: it reproduces the observable behavior of the
Perl loader, defects included. Each preserved defect is marked with its id from
docs/defects.md:

* DEF-6 -- no record length validation; a truncated line still loads.
* DEF-7 -- the carry-forward path inserts a row with no original promotion date.
* DEF-8 -- six of the copybook's fields are never maintained by this loader.

Parsing is pure (``parse_line`` needs neither a file nor a database); everything
that touches the outside world lives in ``UpsertWriter`` and ``load_feed``.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, fields as dataclass_fields
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Optional, Sequence

from .copybook import FIELDS, Field
from .dbapi import Connection, connect

DEFAULT_FEED = Path("/prod/feeds/unitdiary.dat")
DEFAULT_TABLE = "MARINE_MASTER"
COMMIT_EVERY = 5000

# The 13 columns this loader maintains, each mapped to the copybook item it is
# read from. DEF-8: MM-BRK-SVC-MOS, MM-ADV-MATL-IND, MM-ADV-MATL-MOS,
# MM-DUTY-STAT, MM-COMPONENT and MM-RC-DRILL-STAT are deliberately absent even
# though 2400-APPLY-RULES denies on all six -- some other process owns them, and
# establishing which one is a prerequisite for changing this.
COLUMN_FIELDS: tuple[tuple[str, str], ...] = (
    ("edipi", "MM-EDIPI"),
    ("last_nm", "MM-LAST-NM"),
    ("first_nm", "MM-FIRST-NM"),
    ("middle_init", "MM-MIDDLE-INIT"),
    ("grade", "MM-GRADE"),
    ("grade_num", "MM-GRADE-NUM"),
    ("pmos", "MM-PMOS"),
    ("dt_last_promo", "MM-DT-LAST-PROMO"),
    ("dt_orig_promo", "MM-DT-ORIG-PROMO"),
    ("grade_eff_dt", "MM-GRADE-EFF-DT"),
    ("pebd", "MM-PEBD"),
    ("dt_enlist", "MM-DT-ENLIST"),
    ("red_in_grade_ind", "MM-RED-IN-GRADE-IND"),
)

_ZERO_FILLED_RE = re.compile(r"0*")


@dataclass(frozen=True)
class FeedField:
    """One column of the feed, positioned by the copybook."""

    column: str
    offset: int
    length: int

    @classmethod
    def of(cls, column: str, field: Field) -> "FeedField":
        return cls(column=column, offset=field.offset, length=field.length)


def feed_layout(fields: Optional[dict[str, Field]] = None) -> tuple[FeedField, ...]:
    """The feed layout, derived from MARREC.cpy rather than hard-coded."""
    fields = FIELDS if fields is None else fields
    return tuple(FeedField.of(column, fields[name]) for column, name in COLUMN_FIELDS)


LAYOUT = feed_layout()
LOADED_COLUMNS: tuple[str, ...] = tuple(field.column for field in LAYOUT)
FEED_RECORD_LEN = max(field.offset + field.length for field in LAYOUT)


@dataclass(frozen=True)
class DiaryRecord:
    """One feed record. ``None`` means "do not write this column at all"."""

    edipi: Optional[str] = None
    last_nm: Optional[str] = None
    first_nm: Optional[str] = None
    middle_init: Optional[str] = None
    grade: Optional[str] = None
    grade_num: Optional[str] = None
    pmos: Optional[str] = None
    dt_last_promo: Optional[str] = None
    dt_orig_promo: Optional[str] = None
    grade_eff_dt: Optional[str] = None
    pebd: Optional[str] = None
    dt_enlist: Optional[str] = None
    red_in_grade_ind: Optional[str] = None

    def columns(self) -> dict[str, str]:
        """The columns to write: an absent column keeps whatever the master has."""
        values = ((f.name, getattr(self, f.name)) for f in dataclass_fields(self))
        return {name: value for name, value in values if value is not None}


@dataclass(frozen=True)
class ParsedLine:
    record: DiaryRecord
    carried_forward: bool
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class LoadResult:
    loaded: int
    carried_forward: int

    def summary(self) -> str:
        return (f"load_unit_diary: loaded {self.loaded} records, "
                f"{self.carried_forward} carried forward")


def substr(line: str, offset: int, length: int) -> Optional[str]:
    """``substr`` with Perl's out-of-range semantics.

    DEF-6: the record length is never validated, so a line that stops short of
    the layout yields an empty string for the field that starts at its end and
    ``None`` for every field past it. Those fields are then omitted from the
    write and reach the master as NULLs instead of being rejected.
    """
    if offset > len(line):
        return None
    return line[offset:offset + length]


def is_zero_filled(value: Optional[str]) -> bool:
    """True for an absent, empty or all-zero date, as ``/^0*$/`` is in Perl."""
    return value is None or _ZERO_FILLED_RE.fullmatch(value) is not None


def parse_line(line: str, layout: Sequence[FeedField] = LAYOUT) -> ParsedLine:
    """Split one feed line into a record. No file, no database, no side effects."""
    warnings: list[str] = []
    values: dict[str, Optional[str]] = {}
    for field in layout:
        raw = substr(line, field.offset, field.length)
        if raw is None:
            warnings.append(
                f"substr outside of string: {field.column} at offset {field.offset}")
        values[field.column] = raw if raw is None else raw.strip()

    # Records arriving from the reserve component feed do not carry a grade
    # effective date. Leave it null rather than defaulting -- the web service
    # falls back to date of last promotion when it is absent.
    if is_zero_filled(values["grade_eff_dt"]):
        values["grade_eff_dt"] = None

    # A reduction sets the indicator but the feed does not restate the original
    # promotion date. If it is absent, carry forward whatever is already on the
    # master record by leaving the column out of the write.
    #
    # DEF-7: when the EDIPI is unknown the same path inserts a row with no
    # original promotion date at all -- there is nothing to carry forward -- and
    # the run summary still counts it as carried forward.
    carried_forward = (values["red_in_grade_ind"] == "Y"
                       and is_zero_filled(values["dt_orig_promo"]))
    if carried_forward:
        values["dt_orig_promo"] = None

    return ParsedLine(DiaryRecord(**values), carried_forward, tuple(warnings))


def parse_feed(lines: Iterable[str],
               layout: Sequence[FeedField] = LAYOUT) -> Iterator[ParsedLine]:
    """Parse every non-blank line of a feed."""
    for line in lines:
        line = line[:-1] if line.endswith("\n") else line  # chomp
        if not line.strip():
            continue
        yield parse_line(line, layout)


class UpsertWriter:
    """UPDATE the master row, INSERT it when the EDIPI is unknown.

    Written against a DB-API 2.0 connection, so it works on SQLite and on
    PostgreSQL; ``placeholder`` is the driver's parameter marker.
    """

    def __init__(self, connection: Connection, placeholder: str = "?",
                 table: str = DEFAULT_TABLE, commit_every: int = COMMIT_EVERY) -> None:
        self._connection = connection
        self._placeholder = placeholder
        self._table = table
        self._commit_every = commit_every
        self._cursor: Any = connection.cursor()
        self._written = 0

    def upsert(self, record: DiaryRecord) -> None:
        columns = record.columns()
        values = list(columns.values())
        assignments = ", ".join(f"{column} = {self._placeholder}" for column in columns)
        self._cursor.execute(
            f"UPDATE {self._table} SET {assignments} "
            f"WHERE EDIPI = {self._placeholder}",
            values + [record.edipi],
        )
        if self._cursor.rowcount == 0:
            binds = ", ".join(self._placeholder for _ in columns)
            self._cursor.execute(
                f"INSERT INTO {self._table} ({', '.join(columns)}) VALUES ({binds})",
                values,
            )
        self._written += 1
        if self._written % self._commit_every == 0:
            self._connection.commit()

    def finish(self) -> None:
        self._connection.commit()


def load(lines: Iterable[str], writer: UpsertWriter,
         warn: Callable[[str], None] = lambda message: None,
         layout: Sequence[FeedField] = LAYOUT) -> LoadResult:
    """Load an already-opened feed through ``writer``."""
    loaded = 0
    carried_forward = 0
    for parsed in parse_feed(lines, layout):
        for message in parsed.warnings:
            warn(message)
        writer.upsert(parsed.record)
        loaded += 1
        carried_forward += parsed.carried_forward
    writer.finish()
    return LoadResult(loaded=loaded, carried_forward=carried_forward)


def load_feed(feed: Path, connection: Connection, placeholder: str = "?",
              table: str = DEFAULT_TABLE, commit_every: int = COMMIT_EVERY,
              warn: Callable[[str], None] = lambda message: None) -> LoadResult:
    """Load ``feed`` into ``table``."""
    writer = UpsertWriter(connection, placeholder, table, commit_every)
    # newline="" so a line ending is left alone the way Perl's chomp does.
    with feed.open(newline="") as handle:
        return load(handle, writer, warn)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="load_unit_diary",
        description="Load the unit diary feed into MARINE_MASTER.")
    parser.add_argument("--feed", type=Path,
                        default=Path(os.environ.get("UD_FEED", DEFAULT_FEED)),
                        help="fixed-width feed file (default: $UD_FEED)")
    parser.add_argument("--dsn", default=os.environ.get("DSN"),
                        help="database DSN (default: $DSN)")
    parser.add_argument("--user", default=os.environ.get("DBUSER"))
    parser.add_argument("--password", default=os.environ.get("DBPASS"))
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--commit-every", type=int, default=COMMIT_EVERY,
                        help="records per transaction (default: %(default)s)")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.dsn:
        build_parser().error("no DSN given; pass --dsn or set $DSN")

    connection, placeholder = connect(args.dsn, args.user, args.password)
    try:
        result = load_feed(args.feed, connection, placeholder, args.table,
                           args.commit_every,
                           warn=lambda message: print(message, file=sys.stderr))
    finally:
        connection.close()
    print(result.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
