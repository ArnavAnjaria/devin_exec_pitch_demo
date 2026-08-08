"""MARREC.cpy reader.

Field offsets are parsed out of ``cobol/copybook/MARREC.cpy`` at import time
rather than hard-coded, so a copybook change moves the loader's offsets with it
instead of silently shifting every field (which is exactly how
``perl/load_unit_diary.pl`` breaks today -- its offset table is a second,
manually maintained copy of the layout).

This mirrors ``tests/harness/marrec.py``; the harness parses the copybook for
fixture generation, this parses it for the production loader, and
``tests/test_python_unit_diary.py`` asserts the two agree field for field.

The copybook is a mainframe artifact rather than package data -- deliberately, so
there is one copy of the layout and not two. It is located by ``$MARREC_COPYBOOK``
when that is set, and otherwise relative to the source checkout, and it is read on
first use rather than at import so an installed copy of the package fails with the
path in the message instead of on import.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_VAR = "MARREC_COPYBOOK"
COPYBOOK_PATH = REPO_ROOT / "cobol" / "copybook" / "MARREC.cpy"


def copybook_path() -> Path:
    """Where to read MARREC.cpy from: ``$MARREC_COPYBOOK``, else the checkout."""
    override = os.environ.get(ENV_VAR)
    return Path(override) if override else COPYBOOK_PATH


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


def parse_copybook(path: Optional[Path] = None) -> dict[str, Field]:
    """Parse the elementary items of a copybook into ``name -> Field``."""
    path = copybook_path() if path is None else path
    if not path.exists():
        raise FileNotFoundError(
            f"MARREC.cpy not found at {path}; set ${ENV_VAR} to its location")
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


@lru_cache(maxsize=None)
def fields(path: Optional[Path] = None) -> Mapping[str, Field]:
    """The parsed copybook, read once per path."""
    return MappingProxyType(parse_copybook(path))
