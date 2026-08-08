"""MARREC.cpy layout, parsed from the copybook at runtime.

The copybook is the authoritative description of the master record, so the
offsets are derived from ``cobol/copybook/MARREC.cpy`` rather than restated
here: a copybook change then moves this reader with it instead of silently
shifting every field (which is how ``perl/load_unit_diary.pl`` breaks today).

Separate from :mod:`promelig.copybook`, which the unit diary loader uses: the
batch reads whole 140-byte records off disk, COMP-3 fields included, while the
loader only needs field offsets. Merging them is safe housekeeping, but it would
touch two migrated components at once, so it is left for a follow-up.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COPYBOOK = REPO_ROOT / "cobol" / "copybook" / "MARREC.cpy"

# ``FD MASTER-FILE`` in PROMELIG.cbl declares RECORD CONTAINS 140; the copybook
# itself only adds up to 137 (DEF-2). The master dataset is allocated
# LRECL=140, so the declared length is what is read off disk and the three
# unaccounted bytes are trailing filler.
MASTER_RECORD_LEN = 140

_PIC_RE = re.compile(
    r"^\s*(?P<level>\d{2})\s+(?P<name>[A-Z0-9-]+)\s+PIC\s+(?P<pic>[9XS][^.\s]*)"
    r"(?P<comp>\s+COMP-3)?\s*\.",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Field:
    """One elementary item of the copybook."""

    name: str
    offset: int
    length: int
    packed: bool
    digits: int


def _pic_length(pic: str) -> tuple[int, bool]:
    match = re.fullmatch(r"(?P<kind>[9X])\((?P<count>\d+)\)", pic, re.IGNORECASE)
    if match:
        return int(match.group("count")), match.group("kind").upper() == "9"
    return len(pic), pic.upper().startswith("9")


def parse_copybook(path: Optional[Path] = None) -> dict[str, Field]:
    """Parse the elementary items of MARREC.cpy into ``name -> Field``."""
    source = path or copybook_path()
    fields: dict[str, Field] = {}
    offset = 0
    for line in source.read_text().splitlines():
        if len(line) > 6 and line[6] == "*":
            continue
        match = _PIC_RE.match(line)
        if not match:
            continue
        digits, _ = _pic_length(match.group("pic"))
        packed = bool(match.group("comp"))
        length = (digits // 2) + 1 if packed else digits
        name = match.group("name").upper()
        key = name if name != "FILLER" else f"FILLER@{offset}"
        fields[key] = Field(name=name, offset=offset, length=length,
                            packed=packed, digits=digits)
        offset += length
    return fields


def copybook_path() -> Path:
    """Copybook location, overridable for deployments outside the repo tree."""
    override = os.environ.get("PROMELIG_COPYBOOK")
    return Path(override) if override else DEFAULT_COPYBOOK


def decode_comp3(raw: bytes) -> int:
    """Decode an unsigned packed-decimal (COMP-3) field."""
    digits = "".join(f"{byte >> 4:x}{byte & 0x0F:x}" for byte in raw)
    return int(digits[:-1] or "0")


def encode_comp3(value: int, digits: int) -> bytes:
    """Encode an unsigned integer as a packed-decimal (COMP-3) field."""
    text = str(abs(int(value))).zfill(digits)[-digits:]
    if len(text) % 2 == 0:
        text = "0" + text
    out = bytearray()
    for i in range(0, len(text) - 1, 2):
        out.append((int(text[i]) << 4) | int(text[i + 1]))
    out.append((int(text[-1]) << 4) | 0x0F)
    return bytes(out)


def numeric(raw: bytes) -> int:
    """Read a PIC 9(n) DISPLAY field; blanks and junk read as zero, as MOVE does."""
    text = raw.decode("ascii", errors="replace").strip()
    return int(text) if text.isdigit() else 0


def to_date(yyyymmdd: int) -> Optional[dt.date]:
    """A CCYYMMDD field as a date, or ``None`` when the field is unpopulated."""
    if not yyyymmdd:
        return None
    text = str(yyyymmdd).zfill(8)
    return dt.date(int(text[0:4]), int(text[4:6]), int(text[6:8]))
