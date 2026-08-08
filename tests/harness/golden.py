"""Golden-file comparison.

Set ``UPDATE_GOLDEN=1`` to rewrite the goldens after an intentional change; the
diff is then reviewed like any other code change.
"""

from __future__ import annotations

import os
from pathlib import Path

from .model import GOLDEN_DIR
from .normalize import Row, read_rows, write_rows


def golden_path(engine: str) -> Path:
    return GOLDEN_DIR / f"{engine}.csv"


def updating() -> bool:
    return os.environ.get("UPDATE_GOLDEN") == "1"


def compare(engine: str, actual: list[Row]) -> tuple[list[Row], list[Row]]:
    """Return (expected, actual), writing the golden first when it is missing."""
    path = golden_path(engine)
    if updating() or not path.exists():
        write_rows(path, actual)
    return read_rows(path), sorted(actual)


def describe_difference(expected: list[Row], actual: list[Row]) -> str:
    expected_by_edipi = {r.edipi: r for r in expected}
    actual_by_edipi = {r.edipi: r for r in actual}
    lines = []
    for edipi in sorted(set(expected_by_edipi) | set(actual_by_edipi)):
        want = expected_by_edipi.get(edipi)
        got = actual_by_edipi.get(edipi)
        if want != got:
            lines.append(f"  {edipi}: golden={want} actual={got}")
    return "\n".join(lines)
