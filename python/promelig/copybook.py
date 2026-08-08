"""MARREC.cpy reader.

Field offsets are parsed out of ``cobol/copybook/MARREC.cpy`` at import time
rather than hard-coded, so a copybook change moves the loader's offsets with it
instead of silently shifting every field (which is exactly how
``perl/load_unit_diary.pl`` breaks today -- its offset table is a second,
manually maintained copy of the layout).

This mirrors ``tests/harness/marrec.py``; the harness parses the copybook for
fixture generation, this parses it for the production loader, and
``tests/test_python_unit_diary.py`` asserts the two agree field for field.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COPYBOOK_PATH = REPO_ROOT / "cobol" / "copybook" / "MARREC.cpy"

_PIC_RE = re.compile(
    r"^\s*(?P<level>\d{2})\s+(?P<name>[A-Z0-9-]+)\s+PIC\s+(?P<pic>[9XS][^.\s]*)"
    r"(?P<comp>\s+COMP-3)?\s*\.",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Field:
    """One elementary item of the copybook, positioned in the record."""

    name: str
    offset: int
    length: int
    packed: bool
    digits: int


def _pic_length(pic: str) -> int:
    """Number of display digits/characters described by a simple PIC clause."""
    match = re.fullmatch(r"[9X]\((?P<count>\d+)\)", pic, re.IGNORECASE)
    return int(match.group("count")) if match else len(pic)


def parse_copybook(path: Path = COPYBOOK_PATH) -> dict[str, Field]:
    """Parse the elementary items of a copybook into ``name -> Field``."""
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
