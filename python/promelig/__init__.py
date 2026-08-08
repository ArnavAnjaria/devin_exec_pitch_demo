"""Python replacements for the legacy promotion eligibility components.

One module per legacy component, migrated one at a time against the
characterization suite in ``tests/``:

* :mod:`promelig.sql_extract` -- ``sql/promotion_eligibility.sql``
  (``SP_PROMOTION_ELIGIBILITY``, the reporting extract).

:mod:`promelig.oracle` holds the Oracle date and NULL semantics the extract
depends on; :mod:`promelig.db` is the thin database access layer.
"""

__all__ = ["db", "oracle", "sql_extract"]
