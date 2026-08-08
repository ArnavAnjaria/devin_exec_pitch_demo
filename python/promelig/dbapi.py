"""DB-API connection helpers.

The unit diary loader is written against a DB-API 2.0 connection so the same
code runs against SQLite (which is what the characterization harness compares
the Perl loader on) and PostgreSQL (the production target). The only dialect
detail that leaks into the SQL is the parameter marker, which is derived from
the driver's declared ``paramstyle``.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any, Protocol

PLACEHOLDERS = {"qmark": "?", "format": "%s", "pyformat": "%s", "numeric": "?"}

# dbi:SQLite:dbname=/path/to/db -- the DSN form load_unit_diary.pl is given, so
# a Perl DSN can be handed to the Python loader unchanged.
_DBI_SQLITE_RE = re.compile(r"^dbi:SQLite:(?:dbname=)?(?P<path>.+)$", re.IGNORECASE)
_SQLITE_URL_RE = re.compile(r"^sqlite:(?://)?(?P<path>.+)$", re.IGNORECASE)
_POSTGRES_PREFIXES = ("postgres://", "postgresql://", "dbi:Pg:", "host=", "dbname=")


class Connection(Protocol):
    """The slice of DB-API 2.0 the loader needs."""

    def cursor(self) -> Any: ...

    def commit(self) -> None: ...

    def close(self) -> None: ...


def sqlite_path(dsn: str) -> str | None:
    """Return the database path if ``dsn`` names a SQLite database."""
    for pattern in (_DBI_SQLITE_RE, _SQLITE_URL_RE):
        match = pattern.match(dsn)
        if match:
            return match.group("path")
    if dsn.endswith((".sqlite", ".sqlite3", ".db")) or dsn == ":memory:":
        return dsn
    return None


def connect(dsn: str, user: str | None = None,
            password: str | None = None) -> tuple[Connection, str]:
    """Open ``dsn`` and return the connection and its parameter marker."""
    path = sqlite_path(dsn)
    if path is not None:
        sqlite3 = importlib.import_module("sqlite3")
        connection = sqlite3.connect(Path(path))
        return connection, PLACEHOLDERS[sqlite3.paramstyle]
    if dsn.startswith(_POSTGRES_PREFIXES):
        driver = _import_first("psycopg", "psycopg2")
        connection = driver.connect(_postgres_dsn(dsn), **_credentials(user, password))
        return connection, PLACEHOLDERS[driver.paramstyle]
    raise ValueError(f"unsupported DSN: {dsn!r}")


def _credentials(user: str | None, password: str | None) -> dict[str, str]:
    return {key: value for key, value in (("user", user), ("password", password))
            if value}


def _postgres_dsn(dsn: str) -> str:
    return dsn[len("dbi:Pg:"):] if dsn.startswith("dbi:Pg:") else dsn


def _import_first(*names: str) -> Any:
    for name in names:
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
    raise ImportError(f"none of {', '.join(names)} is installed")
