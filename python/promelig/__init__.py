"""Python replacements for the legacy promotion eligibility components.

One module per legacy component, migrated one at a time against the
characterization suite in ``tests/``: behavior -- including the defects in
``docs/defects.md`` -- is reproduced, not corrected.

* :mod:`promelig.sql_extract` -- ``sql/promotion_eligibility.sql``
  (``SP_PROMOTION_ELIGIBILITY``, the reporting extract).
* :mod:`promelig.unit_diary` -- ``perl/load_unit_diary.pl``.

:mod:`promelig.oracle` holds the Oracle date and NULL semantics the extract
depends on. The two database seams are separate on purpose: :mod:`promelig.db`
reaches PostgreSQL through the ``psql`` client for the extract, while
:mod:`promelig.dbapi` opens a DB-API connection for the loader, which must also
run against SQLite.
"""

__all__ = ["db", "dbapi", "oracle", "sql_extract", "unit_diary"]
