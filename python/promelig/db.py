"""Minimal PostgreSQL access through the ``psql`` client.

The characterization harness deliberately has no database driver installed (see
``docs/testing.md``), and this package stays standard-library only, so queries
are sent to ``psql`` on stdin and read back as CSV. ``Database`` is the seam:
anything with ``query``/``execute`` will do, which is what lets the decision
logic be exercised without a database at all.
"""

from __future__ import annotations

import csv
import io
import subprocess
from dataclasses import dataclass
from typing import Optional, Protocol, Sequence

# psql prints NULL as the empty string by default, which is indistinguishable
# from an empty text value. Printing it as \N keeps the two apart.
NULL_SENTINEL = "\\N"

Record = Sequence[Optional[str]]


class Database(Protocol):
    def query(self, sql: str) -> list[Record]:
        """Run ``sql`` and return its rows; NULL comes back as ``None``."""

    def execute(self, sql: str) -> None:
        """Run ``sql`` for its effect."""


class PsqlError(RuntimeError):
    pass


@dataclass(frozen=True)
class PsqlDatabase:
    """A :class:`Database` backed by an invocation of the ``psql`` client.

    ``base_argv`` is the command up to and including ``psql`` with its
    connection arguments; the per-call formatting flags are appended.
    """

    base_argv: tuple[str, ...]

    @classmethod
    def from_dsn(cls, dsn: str, psql: str = "psql") -> "PsqlDatabase":
        return cls(base_argv=(psql, dsn))

    @classmethod
    def in_docker(cls, container: str, dbname: str, user: str,
                  docker: str = "docker") -> "PsqlDatabase":
        return cls(base_argv=(docker, "exec", "-i", container,
                              "psql", "-U", user, "-d", dbname))

    def _run(self, sql: str, extra_argv: Sequence[str]) -> str:
        result = subprocess.run(
            [*self.base_argv, "-v", "ON_ERROR_STOP=1", "-q", *extra_argv],
            input=sql, capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise PsqlError(result.stderr.strip() or "psql failed")
        return result.stdout

    def query(self, sql: str) -> list[Record]:
        out = self._run(sql, ["--csv", "-t", "-P", f"null={NULL_SENTINEL}"])
        return [
            [None if field == NULL_SENTINEL else field for field in record]
            for record in csv.reader(io.StringIO(out)) if record
        ]

    def execute(self, sql: str) -> None:
        self._run(sql, [])


def quote_literal(value: Optional[str]) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"
