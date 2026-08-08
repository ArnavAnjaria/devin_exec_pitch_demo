"""PROMELIG: the nightly promotion eligibility batch.

Python replacement for ``cobol/PROMELIG.cbl``. This module owns the I/O the
COBOL program did through its three DD names -- MSTRIN, ELIGOUT and RPTOUT --
and delegates every decision to :mod:`promelig.eligibility`.

The record layouts stay byte-for-byte identical: the master is read through the
copybook (``MARREC.cpy``, parsed at runtime), and the extract is the same
60-byte ELIG-REC that ``jcl/PROMELIG.jcl`` allocates with ``LRECL=60``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional, Sequence

from .cobol_copybook import (
    MASTER_RECORD_LEN,
    Field,
    copybook_path,
    decode_comp3,
    encode_comp3,
    numeric,
    parse_copybook,
    to_date,
)
from .cobol_rules import Decision, MarineRecord, evaluate

# FD ELIG-FILE / 01 ELIG-REC in PROMELIG.cbl. The month counters are narrower
# than the working-storage fields that feed them, so a corrupt date is reported
# as its low-order digits rather than rejected (DEF-4).
ELIG_RECORD_LEN = 60
EL_EDIPI_DIGITS = 10
EL_GRADE_LEN = 3
EL_TGT_GRADE_DIGITS = 2
EL_TIG_DIGITS = 3
EL_TIS_DIGITS = 4
EL_DENY_LEN = 4
EL_RUN_DT_DIGITS = 8

REPORT_RECORD_LEN = 132
COUNTER_DIGITS = 7

OPEN_FAILED_RC = 16


@dataclass(frozen=True)
class RunCounters:
    """WS-COUNTERS, as reported by 9000-TERM."""

    read: int = 0
    eligible: int = 0
    denied: int = 0
    bypassed: int = 0


@dataclass(frozen=True)
class RunResult:
    decisions: list[Decision]
    counters: RunCounters
    return_code: int = 0


def _text(value: str, length: int) -> bytes:
    return value.encode("ascii", errors="replace")[:length].ljust(length, b" ")


def _zoned(value: int, digits: int) -> bytes:
    """PIC 9(n) DISPLAY: high-order digits are lost, as a COBOL MOVE loses them."""
    return str(abs(int(value))).zfill(digits)[-digits:].encode("ascii")


def read_master(path: Path, fields: Optional[dict[str, Field]] = None,
                record_len: int = MASTER_RECORD_LEN) -> Iterator[MarineRecord]:
    """1100-READ-MASTER: decode every fixed-length record of the master file."""
    layout = fields if fields is not None else parse_copybook()
    raw = path.read_bytes()
    if len(raw) % record_len:
        raise ValueError(
            f"{path}: {len(raw)} bytes is not a multiple of the {record_len}-byte record")
    for start in range(0, len(raw), record_len):
        yield decode_master_record(raw[start:start + record_len], layout)


def decode_master_record(record: bytes,
                         fields: Optional[dict[str, Field]] = None) -> MarineRecord:
    """One MARINE-MASTER-REC, decoded through the copybook offsets."""
    layout = fields if fields is not None else parse_copybook()

    def raw(name: str) -> bytes:
        field = layout[name]
        return record[field.offset:field.offset + field.length]

    def chars(name: str) -> str:
        return raw(name).decode("ascii", errors="replace")

    return MarineRecord(
        edipi=numeric(raw("MM-EDIPI")),
        grade=chars("MM-GRADE"),
        grade_num=numeric(raw("MM-GRADE-NUM")),
        dt_last_promo=to_date(numeric(raw("MM-DT-LAST-PROMO"))),
        dt_orig_promo=to_date(numeric(raw("MM-DT-ORIG-PROMO"))),
        grade_eff_dt=to_date(numeric(raw("MM-GRADE-EFF-DT"))),
        pebd=to_date(numeric(raw("MM-PEBD"))),
        dt_enlist=to_date(numeric(raw("MM-DT-ENLIST"))),
        red_in_grade_ind=chars("MM-RED-IN-GRADE-IND"),
        brk_svc_mos=decode_comp3(raw("MM-BRK-SVC-MOS")),
        adv_matl_ind=chars("MM-ADV-MATL-IND"),
        adv_matl_mos=decode_comp3(raw("MM-ADV-MATL-MOS")),
        duty_stat=chars("MM-DUTY-STAT").strip(),
        component=chars("MM-COMPONENT"),
        rc_drill_stat=chars("MM-RC-DRILL-STAT"),
    )


def encode_elig_record(decision: Decision, run_date: dt.date) -> bytes:
    """2500-WRITE-ELIG: render one 60-byte ELIG-REC."""
    record = b"".join((
        _zoned(decision.edipi, EL_EDIPI_DIGITS),
        _text(decision.grade, EL_GRADE_LEN),
        _zoned(decision.tgt_grade, EL_TGT_GRADE_DIGITS),
        _zoned(decision.tig_mos, EL_TIG_DIGITS),
        _zoned(decision.tis_mos, EL_TIS_DIGITS),
        _text(decision.elig_ind, 1),
        # EL-DENY-RSN is PIC X(04): 'TIG ' and 'TIS ' carry a trailing space.
        _text(decision.deny_reason, EL_DENY_LEN),
        _zoned(int(run_date.strftime("%Y%m%d")), EL_RUN_DT_DIGITS),
    ))
    return record.ljust(ELIG_RECORD_LEN, b" ")


def encode_report_line(counters: RunCounters) -> bytes:
    """9000-TERM's RPTOUT line.

    The counters are COMP-3 and are STRINGed straight into a character record,
    so the report carries packed bytes where digits are expected (DEF-5).
    """
    line = b"".join((
        b"PROMELIG READ=", encode_comp3(counters.read, COUNTER_DIGITS),
        b" ELIG=", encode_comp3(counters.eligible, COUNTER_DIGITS),
        b" DENY=", encode_comp3(counters.denied, COUNTER_DIGITS),
        b" BYPASS=", encode_comp3(counters.bypassed, COUNTER_DIGITS),
    ))
    return line.ljust(REPORT_RECORD_LEN, b" ")


def process(records: Sequence[MarineRecord], run_date: dt.date) -> RunResult:
    """0000-MAIN over an already-read master: decide every record, count them."""
    decisions: list[Decision] = []
    eligible = denied = bypassed = 0
    for record in records:
        decision = evaluate(record, run_date)
        if decision is None:
            bypassed += 1
            continue
        decisions.append(decision)
        if decision.eligible:
            eligible += 1
        else:
            denied += 1
    return RunResult(
        decisions=decisions,
        counters=RunCounters(read=len(records), eligible=eligible,
                             denied=denied, bypassed=bypassed),
    )


def run(master: Path, elig_out: Path, report_out: Optional[Path],
        run_date: dt.date, fields: Optional[dict[str, Field]] = None) -> RunResult:
    """Run the batch end to end: MSTRIN in, ELIGOUT and RPTOUT out."""
    if not master.is_file():
        return RunResult(decisions=[], counters=RunCounters(), return_code=OPEN_FAILED_RC)

    result = process(list(read_master(master, fields)), run_date)

    elig_out.parent.mkdir(parents=True, exist_ok=True)
    elig_out.write_bytes(
        b"".join(encode_elig_record(d, run_date) for d in result.decisions))
    if report_out is not None:
        report_out.parent.mkdir(parents=True, exist_ok=True)
        report_out.write_bytes(encode_report_line(result.counters))
    return result


def _parse_run_date(value: str) -> dt.date:
    return dt.datetime.strptime(value, "%Y%m%d").date()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="promelig-batch",
        description="Nightly promotion eligibility determination (replaces PROMELIG.cbl).")
    parser.add_argument("--master", type=Path, required=True,
                        help="MSTRIN: fixed-width master personnel file")
    parser.add_argument("--elig-out", type=Path, required=True,
                        help="ELIGOUT: 60-byte eligibility extract to write")
    parser.add_argument("--report-out", type=Path, default=None,
                        help="RPTOUT: run summary line")
    parser.add_argument("--run-date", type=_parse_run_date, default=dt.date.today(),
                        help="CCYYMMDD run date (default: today, as ACCEPT FROM DATE)")
    parser.add_argument("--copybook", type=Path, default=None,
                        help=f"MARREC copybook to read the layout from "
                             f"(default: {copybook_path()})")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    fields = parse_copybook(args.copybook) if args.copybook else parse_copybook()
    result = run(args.master, args.elig_out, args.report_out, args.run_date, fields)
    if result.return_code:
        print(f"PROMELIG - MSTR OPEN FAILED {args.master}", file=sys.stderr)
        return result.return_code
    counters = result.counters
    print(f"PROMELIG READ={counters.read} ELIG={counters.eligible} "
          f"DENY={counters.denied} BYPASS={counters.bypassed}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
