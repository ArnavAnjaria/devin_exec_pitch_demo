"""Read MARINE-MASTER records off the fixed-width master file.

Offsets are parsed out of ``cobol/copybook/MARREC.cpy`` at import time rather
than written down again here, so a copybook change breaks loudly instead of
shifting every field silently -- which is how ``perl/load_unit_diary.pl`` breaks
today (DEF-8's neighbour, DEF-6).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from .model import MarineMaster

REPO_ROOT = Path(__file__).resolve().parents[2]
COPYBOOK_PATH = REPO_ROOT / "cobol" / "copybook" / "MARREC.cpy"

# FD MASTER-FILE declares RECORD CONTAINS 140; the copybook adds up to 137.
# That mismatch is DEF-2, so the record length is a parameter, not a constant.
DECLARED_RECORD_LEN = 140

_PIC_RE = re.compile(
    r"^\s*(?P<level>\d{2})\s+(?P<name>[A-Z0-9-]+)\s+PIC\s+(?P<pic>[9XS][^.\s]*)"
    r"(?P<comp>\s+COMP-3)?\s*\.",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Field:
    name: str
    offset: int
    length: int
    packed: bool
    digits: int


def _pic_length(pic: str) -> int:
    match = re.fullmatch(r"[9X]\((?P<count>\d+)\)", pic, re.IGNORECASE)
    return int(match.group("count")) if match else len(pic)


def parse_copybook(path: Path = COPYBOOK_PATH) -> "dict[str, Field]":
    """Elementary items of MARREC.cpy, in declaration order, keyed by name."""
    fields: dict[str, Field] = {}
    offset = 0
    for line in path.read_text().splitlines():
        if len(line) > 6 and line[6] == "*":
            continue
        match = _PIC_RE.match(line)
        if not match:
            continue
        digits = _pic_length(match.group("pic"))
        packed = bool(match.group("comp"))
        length = (digits // 2) + 1 if packed else digits
        name = match.group("name").upper()
        key = name if name != "FILLER" else f"FILLER@{offset}"
        fields[key] = Field(name=name, offset=offset, length=length,
                            packed=packed, digits=digits)
        offset += length
    return fields


FIELDS = parse_copybook()
COPYBOOK_RECORD_LEN = max(f.offset + f.length for f in FIELDS.values())


def _decode_comp3(raw: bytes) -> int:
    digits = "".join(f"{b >> 4:x}{b & 0x0F:x}" for b in raw)
    return int(digits[:-1] or "0")


def _text(record: bytes, name: str) -> str:
    field = FIELDS[name]
    return record[field.offset:field.offset + field.length].decode("ascii").strip()


def _packed(record: bytes, name: str) -> int:
    field = FIELDS[name]
    return _decode_comp3(record[field.offset:field.offset + field.length])


def _date(record: bytes, name: str) -> Optional[dt.date]:
    """A CCYYMMDD field. All zeros or blank means the field was never populated."""
    text = _text(record, name)
    if not text or set(text) == {"0"}:
        return None
    return dt.datetime.strptime(text, "%Y%m%d").date()


def decode(record: bytes) -> MarineMaster:
    """One fixed-width master record as a :class:`MarineMaster`."""
    drill_status = _text(record, "MM-RC-DRILL-STAT")
    return MarineMaster(
        edipi=int(_text(record, "MM-EDIPI")),
        grade=_text(record, "MM-GRADE"),
        grade_num=int(_text(record, "MM-GRADE-NUM")),
        date_of_last_promotion=_date(record, "MM-DT-LAST-PROMO"),
        date_of_original_promotion=_date(record, "MM-DT-ORIG-PROMO"),
        grade_effective_date=_date(record, "MM-GRADE-EFF-DT"),
        pebd=_date(record, "MM-PEBD"),
        date_of_enlistment=_date(record, "MM-DT-ENLIST"),
        reduced_in_grade=_text(record, "MM-RED-IN-GRADE-IND") == "Y",
        break_in_service_months=_packed(record, "MM-BRK-SVC-MOS"),
        adverse_material=_text(record, "MM-ADV-MATL-IND") == "Y",
        adverse_material_months=_packed(record, "MM-ADV-MATL-MOS"),
        duty_status=_text(record, "MM-DUTY-STAT"),
        component=_text(record, "MM-COMPONENT"),
        drill_status=drill_status or None,
    )


def read_master_file(path: Path,
                     record_len: int = DECLARED_RECORD_LEN) -> Iterator[MarineMaster]:
    raw = path.read_bytes()
    if len(raw) % record_len:
        raise ValueError(f"{path}: {len(raw)} bytes is not a multiple of {record_len}")
    for start in range(0, len(raw), record_len):
        yield decode(raw[start:start + record_len])
