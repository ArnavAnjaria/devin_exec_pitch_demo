"""The nightly PROMELIG job.

Python replacement for ``jcl/PROMELIG.jcl``. It runs the same four steps in the
same order, with the same conditional execution the JCL expresses as
``COND=(0,NE)``: every step after the first runs only if all the previous ones
returned zero.

===========  ======================================================
STEP010      delete the previous eligibility extract (IEFBR14/DELOLD)
STEP020      sort the master by EDIPI and apply the INCLUDE filter (SORT)
STEP030      run the batch over the sorted work file (PGM=PROMELIG)
STEP040      refresh the reporting extract (IKJEFT01 -> SP_PROMOTION_ELIGIBILITY)
===========  ======================================================

STEP040 does not read the eligibility extract: the stored procedure reads the
master directly, which is why the two can drift (DIV-1, DIV-2). It is therefore
an external command here rather than something this job computes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

from .batch import ELIG_RECORD_LEN, run as run_batch
from .cobol_copybook import MASTER_RECORD_LEN, parse_copybook

# SORT FIELDS=(1,10,ZD,A): the sort key is MM-EDIPI, taken from the copybook so
# a layout change moves the key with it.
_FIELDS = parse_copybook()
SORT_KEY_POSITION = _FIELDS["MM-EDIPI"].offset + 1
SORT_KEY_LENGTH = _FIELDS["MM-EDIPI"].length

# INCLUDE COND=(58,2,ZD,LT,09).
#
# DEF-3: position 58 is the start of MM-GRADE ('SGT', 'CPL', ...), not
# MM-GRADE-NUM, which starts at position 61. The filter is meant to drop grade 9
# before the batch runs; as written it compares two alphabetic bytes as zoned
# decimal. The defect is preserved here -- the ticket to move it to position 61
# is separate -- so the position is derived from MM-GRADE deliberately.
INCLUDE_POSITION = _FIELDS["MM-GRADE"].offset + 1
INCLUDE_LENGTH = _FIELDS["MM-GRADE-NUM"].length
INCLUDE_LIMIT = 9

ELIG_LRECL = ELIG_RECORD_LEN


def zoned_decimal(raw: bytes) -> Optional[int]:
    """Read a ZD field, or ``None`` when the bytes are not zoned decimal.

    Every byte must be a digit, the last one optionally carrying a sign
    overpunch. Alphabetic data -- what DEF-3 points the INCLUDE filter at -- is
    not zoned decimal at all, and what a sort utility makes of it is not defined
    off the mainframe, so it reads as ``None`` rather than as a guessed number.
    See :func:`include_record`.
    """
    if not raw:
        return None
    digits = [byte & 0x0F for byte in raw]
    zones = [byte >> 4 for byte in raw]
    if any(digit > 9 for digit in digits):
        return None
    if any(zone != 0x03 for zone in zones[:-1]):
        return None
    if zones[-1] not in (0x03, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F):
        return None
    sign = -1 if zones[-1] in (0x0B, 0x0D) else 1
    return sign * int("".join(str(digit) for digit in digits))


def include_record(record: bytes) -> bool:
    """STEP020's ``INCLUDE COND``.

    A record is kept when the compared field is *not* a value below the limit.
    Because DEF-3 aims the filter at alphabetic grade text, the comparison
    cannot be evaluated for real master records; those records are kept and the
    grade rule is left to the batch, which applies it anyway (2000-PROCESS
    bypasses grade >= 9). That is the observable behavior today: the filter
    removes nothing from the board slate.
    """
    field_bytes = record[INCLUDE_POSITION - 1:INCLUDE_POSITION - 1 + INCLUDE_LENGTH]
    value = zoned_decimal(field_bytes)
    if value is None:
        return True
    return not value < INCLUDE_LIMIT


def sort_master(raw: bytes, record_len: int = MASTER_RECORD_LEN) -> bytes:
    """STEP020: EDIPI ascending, INCLUDE filter applied first."""
    if len(raw) % record_len:
        raise ValueError(
            f"master is {len(raw)} bytes, not a multiple of the {record_len}-byte record")
    records = [raw[i:i + record_len] for i in range(0, len(raw), record_len)]
    kept = [record for record in records if include_record(record)]
    start = SORT_KEY_POSITION - 1
    kept.sort(key=lambda r: r[start:start + SORT_KEY_LENGTH])
    return b"".join(kept)


@dataclass
class StepResult:
    name: str
    return_code: int
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.return_code == 0


@dataclass
class JobResult:
    steps: list[StepResult] = field(default_factory=list)

    @property
    def return_code(self) -> int:
        return max((step.return_code for step in self.steps), default=0)

    def summary(self) -> str:
        return "\n".join(
            f"{step.name} RC={step.return_code:02d} {step.detail}".rstrip()
            for step in self.steps)


def _run_extract_command(command: str) -> StepResult:
    completed = subprocess.run(shlex.split(command), check=False)
    return StepResult("STEP040", completed.returncode, command)


def run_job(master: Path, elig_out: Path, work_dir: Path, run_date: dt.date,
            report_out: Optional[Path] = None,
            extract_command: Optional[str] = None,
            extract_runner: Optional[Callable[[str], StepResult]] = None) -> JobResult:
    """Run STEP010..STEP040, stopping at the first non-zero return code."""
    result = JobResult()

    # STEP010 EXEC PGM=IEFBR14 -- DELOLD DISP=(MOD,DELETE,DELETE)
    existed = elig_out.exists()
    elig_out.unlink(missing_ok=True)
    result.steps.append(
        StepResult("STEP010", 0, "deleted previous extract" if existed else "nothing to delete"))

    # STEP020 EXEC PGM=SORT
    work_dir.mkdir(parents=True, exist_ok=True)
    sorted_master = work_dir / "SORTED"
    if not master.is_file():
        result.steps.append(StepResult("STEP020", 16, f"SORTIN not found: {master}"))
        return result
    sorted_bytes = sort_master(master.read_bytes())
    sorted_master.write_bytes(sorted_bytes)
    result.steps.append(
        StepResult("STEP020", 0,
                   f"{len(sorted_bytes) // MASTER_RECORD_LEN} records to &&SORTED"))

    # STEP030 EXEC PGM=PROMELIG -- MSTRIN DISP=(OLD,DELETE), ELIGOUT LRECL=60
    batch = run_batch(sorted_master, elig_out, report_out, run_date)
    sorted_master.unlink(missing_ok=True)
    counters = batch.counters
    result.steps.append(StepResult(
        "STEP030", batch.return_code,
        f"read={counters.read} elig={counters.eligible} "
        f"deny={counters.denied} bypass={counters.bypassed}"))
    if not result.steps[-1].ok:
        return result

    # STEP040 EXEC PGM=IKJEFT01 -- SP_PROMOTION_ELIGIBILITY, which reads the
    # master rather than ELIGOUT.
    if extract_command:
        runner = extract_runner or _run_extract_command
        result.steps.append(runner(extract_command))
    else:
        result.steps.append(
            StepResult("STEP040", 0, "skipped: no reporting extract command configured"))
    return result


def _parse_run_date(value: str) -> dt.date:
    return dt.datetime.strptime(value, "%Y%m%d").date()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="promelig-job",
        description="Nightly promotion eligibility job (replaces jcl/PROMELIG.jcl). "
                    "Runs after the unit diary load; the master must be current.")
    parser.add_argument("--master", type=Path, required=True,
                        help="SORTIN: the master personnel file")
    parser.add_argument("--elig-out", type=Path, required=True,
                        help="ELIGOUT: the eligibility extract (LRECL=60)")
    parser.add_argument("--report-out", type=Path, default=None, help="RPTOUT")
    parser.add_argument("--work-dir", type=Path, default=Path("."),
                        help="where the &&SORTED work file lives")
    parser.add_argument("--run-date", type=_parse_run_date, default=dt.date.today(),
                        help="CCYYMMDD run date (default: today)")
    parser.add_argument("--extract-command", default=None,
                        help="STEP040: command that refreshes the reporting extract")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_job(
        master=args.master,
        elig_out=args.elig_out,
        work_dir=args.work_dir,
        run_date=args.run_date,
        report_out=args.report_out,
        extract_command=args.extract_command,
    )
    print(result.summary())
    return result.return_code


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
