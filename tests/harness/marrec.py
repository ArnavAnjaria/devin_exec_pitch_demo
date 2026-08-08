"""MARREC.cpy encoder/decoder.

Field offsets are parsed out of ``cobol/copybook/MARREC.cpy`` at runtime rather
than hard-coded, so a copybook change fails the tests instead of silently
shifting every downstream byte offset (which is exactly how
``perl/load_unit_diary.pl`` breaks today).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .model import REPO_ROOT, Scenario

COPYBOOK_PATH = REPO_ROOT / "cobol" / "copybook" / "MARREC.cpy"

# The FD in PROMELIG.cbl declares RECORD CONTAINS 140; the copybook itself only
# adds up to 137. See docs/defects.md (DEF-2). The harness writes 140-byte
# records so the declared record length is what lands on disk.
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


def _pic_length(pic: str) -> tuple[int, bool]:
    """Return (display digits/chars, is_numeric) for a simple PIC clause."""
    match = re.fullmatch(r"(?P<kind>[9X])\((?P<count>\d+)\)", pic, re.IGNORECASE)
    if match:
        return int(match.group("count")), match.group("kind").upper() == "9"
    return len(pic), pic.upper().startswith("9")


def parse_copybook(path: Path = COPYBOOK_PATH) -> dict[str, Field]:
    """Parse elementary items of MARREC.cpy into name -> Field."""
    fields: dict[str, Field] = {}
    offset = 0
    for line in path.read_text().splitlines():
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


FIELDS = parse_copybook()
COPYBOOK_RECORD_LEN = max(f.offset + f.length for f in FIELDS.values())


def comp3(value: int, digits: int) -> bytes:
    """Encode an unsigned integer as a packed-decimal (COMP-3) field."""
    text = str(abs(int(value))).zfill(digits)
    if len(text) != digits:
        raise ValueError(f"{value} does not fit in {digits} digits")
    if len(text) % 2 == 0:
        text = "0" + text
    out = bytearray()
    for i in range(0, len(text) - 1, 2):
        out.append((int(text[i]) << 4) | int(text[i + 1]))
    out.append((int(text[-1]) << 4) | 0x0F)
    return bytes(out)


def decode_comp3(raw: bytes) -> int:
    digits = "".join(f"{b >> 4:x}{b & 0x0F:x}" for b in raw)
    return int(digits[:-1] or "0")


def _text(value: str, length: int) -> bytes:
    return value.encode("ascii")[:length].ljust(length, b" ")


def _num(value: int, length: int) -> bytes:
    return str(int(value)).zfill(length).encode("ascii")[-length:]


def encode(scenario: Scenario, record_len: int = DECLARED_RECORD_LEN) -> bytes:
    """Render a scenario as one fixed-width master record."""
    values = {
        "MM-EDIPI": _num(scenario.edipi, 10),
        "MM-LAST-NM": _text(scenario.last_nm, 26),
        "MM-FIRST-NM": _text(scenario.first_nm, 20),
        "MM-MIDDLE-INIT": _text(scenario.middle_init, 1),
        "MM-GRADE": _text(scenario.grade, 3),
        "MM-GRADE-NUM": _num(scenario.grade_num, 2),
        "MM-PMOS": _text(scenario.pmos, 4),
        "MM-DT-LAST-PROMO": _num(scenario.dt_last_promo, 8),
        "MM-DT-ORIG-PROMO": _num(scenario.dt_orig_promo, 8),
        "MM-GRADE-EFF-DT": _num(scenario.grade_eff_dt, 8),
        "MM-PEBD": _num(scenario.pebd, 8),
        "MM-DT-ENLIST": _num(scenario.dt_enlist, 8),
        "MM-RED-IN-GRADE-IND": _text(scenario.red_in_grade_ind, 1),
        "MM-BRK-SVC-MOS": comp3(scenario.brk_svc_mos, 3),
        "MM-ADV-MATL-IND": _text(scenario.adv_matl_ind, 1),
        "MM-ADV-MATL-MOS": comp3(scenario.adv_matl_mos, 3),
        "MM-DUTY-STAT": _text(scenario.duty_stat, 2),
        "MM-COMPONENT": _text(scenario.component, 1),
        "MM-RC-DRILL-STAT": _text(scenario.rc_drill_stat, 1),
    }
    record = bytearray(b" " * record_len)
    for key, field in FIELDS.items():
        if field.name == "FILLER":
            continue
        blob = values[field.name]
        if len(blob) != field.length:
            raise ValueError(
                f"{field.name}: encoded {len(blob)} bytes, copybook says {field.length}")
        record[field.offset:field.offset + field.length] = blob
    return bytes(record)


def decode(record: bytes) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, field in FIELDS.items():
        if field.name == "FILLER":
            continue
        raw = record[field.offset:field.offset + field.length]
        out[field.name] = decode_comp3(raw) if field.packed else raw.decode("ascii")
    return out


def write_master_file(path: Path, scenarios: list[Scenario],
                      record_len: int = DECLARED_RECORD_LEN) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(encode(s, record_len) for s in scenarios))


def feed_line(scenario: Scenario) -> str:
    """Unit diary feed line: the character prefix load_unit_diary.pl reads.

    The loader only parses the display fields up to MM-RED-IN-GRADE-IND; the
    packed fields after it are not part of the text feed.
    """
    cutoff = FIELDS["MM-RED-IN-GRADE-IND"]
    record = encode(scenario)
    return record[: cutoff.offset + cutoff.length].decode("ascii")


def parse_elig_record(record: bytes) -> dict[str, object]:
    """Parse one 60-byte ELIGOUT record written by PROMELIG."""
    text = record.decode("ascii")
    return {
        "edipi": int(text[0:10]),
        "grade": text[10:13].strip(),
        "tgt_grade": int(text[13:15]),
        "tig_mos": int(text[15:18]),
        "tis_mos": int(text[18:22]),
        "elig_ind": text[22:23],
        "deny_rsn": text[23:27].strip(),
        "run_dt": int(text[27:35]),
    }


def parse_elig_file(path: Path, record_len: int = 60) -> list[dict[str, object]]:
    raw = path.read_bytes()
    if len(raw) % record_len:
        raise ValueError(f"{path}: {len(raw)} bytes is not a multiple of {record_len}")
    return [parse_elig_record(raw[i:i + record_len]) for i in range(0, len(raw), record_len)]


def grade_num_offset() -> Optional[int]:
    """1-based byte position of MM-GRADE-NUM, used by the JCL offset checks."""
    return FIELDS["MM-GRADE-NUM"].offset + 1
