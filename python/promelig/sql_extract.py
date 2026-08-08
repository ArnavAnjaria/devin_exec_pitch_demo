"""The promotion eligibility reporting extract, in Python.

Replaces the Oracle procedure ``SP_PROMOTION_ELIGIBILITY`` in
``sql/promotion_eligibility.sql``. It is a characterization-driven rewrite: the
observable output is identical to the legacy extract's, defects included, and
``tests/test_python_sql_extract.py`` holds it to ``tests/golden/sql.csv``.

Division of labour between SQL and Python
-----------------------------------------
The database still does what a database is good at, and only that:

* the row set — the join to ``REF_GRADE_REQUIREMENTS``, the ``GRADE_NUM < 9``
  filter and the component filter (:data:`CANDIDATE_QUERY`);
* the delete-then-insert of a run's rows into ``RPT_PROMOTION_ELIGIBILITY``.

Everything that decides an answer — the month arithmetic and the denial rules —
is Python, because that is the part that has to be readable, unit-testable
without a database, and shared with the other components when they migrate. The
Oracle-emulating date math lives in :mod:`promelig.oracle`.

Preserved legacy behavior
-------------------------
* **DEF-9 / DIV-1** — the adverse material lookback is 12 months here, while the
  batch and the web service use 24 (:data:`ADV_LOOKBACK_MOS`).
* **DIV-3** — time in grade accrues from ``DT_LAST_PROMO`` only; neither the
  reduction indicator nor ``GRADE_EFF_DT`` is read.
* **DIV-4** — grade 9 is filtered out rather than reported as a bypass.
* **DIV-5** — the inner join drops a grade with no requirement row silently.
* **DIV-6** — a missing ``DT_LAST_PROMO`` yields a NULL time in grade, and every
  threshold comparison against NULL is unknown, so the record is reported
  eligible.
* **DIV-2** — partial months are rounded to nearest, not truncated or rounded up.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from . import oracle
from .db import Database, Record, quote_literal

REPORT_TABLE = "RPT_PROMOTION_ELIGIBILITY"

# Duty statuses that are not promotable at all: prisoner, confined, absent.
NON_PROMOTABLE_DUTY_STATUSES = ("PS", "CF", "AW")

# DEF-9 / DIV-1: the 2011 change extending the adverse material lookback to 24
# months updated the batch and the web service but never this extract. Preserved
# deliberately -- fixing it is a behavior change and belongs in its own PR.
ADV_LOOKBACK_MOS = 12

# DIV-4: the top grade has nothing to be promoted to, so the extract omits the
# row entirely instead of reporting a bypass the way the web service does.
MAX_GRADE_NUM = 9

RESERVE_COMPONENT = "R"
DRILLING_STATUS = "S"

# The join to REF_GRADE_REQUIREMENTS is an INNER join: a record whose grade has
# no requirement row is dropped without a trace (DIV-5).
CANDIDATE_QUERY = """
SELECT m.EDIPI,
       m.GRADE,
       m.GRADE_NUM,
       m.DT_LAST_PROMO,
       m.PEBD,
       m.BRK_SVC_MOS,
       m.ADV_MATL_IND,
       m.ADV_MATL_MOS,
       m.DUTY_STAT,
       m.COMPONENT,
       m.RC_DRILL_STAT,
       r.MIN_TIG,
       r.MIN_TIS
  FROM MARINE_MASTER m
  JOIN REF_GRADE_REQUIREMENTS r
    ON r.GRADE_NUM = m.GRADE_NUM + 1
 WHERE m.GRADE_NUM < {max_grade_num}{component_filter}
 ORDER BY m.EDIPI
"""


@dataclass(frozen=True)
class Candidate:
    """One ``MARINE_MASTER`` row joined to its target grade's requirements.

    Only the columns the extract reads are here. ``None`` is a SQL NULL; the
    fixed-width padding of the ``CHAR`` columns is stripped on the way in.
    """

    edipi: int
    grade: Optional[str]
    grade_num: int
    dt_last_promo: Optional[dt.date]
    pebd: Optional[dt.date]
    brk_svc_mos: Optional[int]
    adv_matl_ind: Optional[str]
    adv_matl_mos: Optional[int]
    duty_stat: Optional[str]
    component: Optional[str]
    rc_drill_stat: Optional[str]
    min_tig: int
    min_tis: int

    @property
    def tgt_grade_num(self) -> int:
        return self.grade_num + 1


@dataclass(frozen=True)
class ExtractRow:
    """One ``RPT_PROMOTION_ELIGIBILITY`` row."""

    edipi: int
    grade: Optional[str]
    tgt_grade_num: int
    tig_mos: Optional[int]
    tis_mos: Optional[int]
    elig_ind: str
    deny_rsn: Optional[str]
    run_dt: dt.date


# --- SQL three-valued logic -------------------------------------------------
#
# The legacy CASE expressions compare NULL month counts against the thresholds,
# and a NULL comparison is unknown rather than false: the WHEN is not taken and
# evaluation falls through to the next one. Modelling unknown as None rather
# than as False is what keeps DIV-6 reproducible.


def _lt(left: Optional[int], right: Optional[int]) -> Optional[bool]:
    if left is None or right is None:
        return None
    return left < right


def _eq(left: Optional[str], right: str) -> Optional[bool]:
    if left is None:
        return None
    return left == right


def _and(left: Optional[bool], right: Optional[bool]) -> Optional[bool]:
    if left is False or right is False:
        return False
    if left is None or right is None:
        return None
    return True


def _is_true(value: Optional[bool]) -> bool:
    return value is True


# --- month arithmetic -------------------------------------------------------


def time_in_grade(run_dt: dt.date, candidate: Candidate) -> Optional[int]:
    """``GREATEST(ROUND(MONTHS_BETWEEN(run, DT_LAST_PROMO)) - BRK_SVC_MOS, 0)``.

    DIV-3: the date of last promotion is the only base date this extract knows
    about. DIV-6: a missing one leaves the count NULL rather than falling back
    to the enlistment date the way the batch does.
    """
    months = oracle.months_between_rounded(run_dt, candidate.dt_last_promo)
    if months is not None:
        months -= candidate.brk_svc_mos or 0
    return oracle.greatest(months, 0)


def time_in_service(run_dt: dt.date, candidate: Candidate) -> Optional[int]:
    """``GREATEST(ROUND(MONTHS_BETWEEN(run, PEBD)), 0)``."""
    return oracle.greatest(oracle.months_between_rounded(run_dt, candidate.pebd), 0)


# --- denial rules -----------------------------------------------------------
#
# In the legacy procedure these are two duplicated CASE expressions, one for
# ELIG_IND and one for DENY_RSN. One ordered list of rules produces both, so the
# two cannot drift apart; the order and the predicates are unchanged.

Rule = Callable[[Candidate, Optional[int], Optional[int]], Optional[bool]]


def _non_promotable_status(c: Candidate, tig: Optional[int], tis: Optional[int]) -> Optional[bool]:
    if c.duty_stat is None:
        return None
    return c.duty_stat in NON_PROMOTABLE_DUTY_STATUSES


def _recent_adverse_material(c: Candidate, tig: Optional[int],
                             tis: Optional[int]) -> Optional[bool]:
    return _and(_eq(c.adv_matl_ind, "Y"), _lt(c.adv_matl_mos, ADV_LOOKBACK_MOS))


def _below_min_tig(c: Candidate, tig: Optional[int], tis: Optional[int]) -> Optional[bool]:
    return _lt(tig, c.min_tig)


def _below_min_tis(c: Candidate, tig: Optional[int], tis: Optional[int]) -> Optional[bool]:
    return _lt(tis, c.min_tis)


def _not_drilling(c: Candidate, tig: Optional[int], tis: Optional[int]) -> Optional[bool]:
    reserve = _eq(c.component, RESERVE_COMPONENT)
    drill_stat = c.rc_drill_stat if c.rc_drill_stat is not None else "X"
    return _and(reserve, drill_stat != DRILLING_STATUS)


DENIAL_RULES: tuple[tuple[str, Rule], ...] = (
    ("STAT", _non_promotable_status),
    ("ADVM", _recent_adverse_material),
    ("TIG", _below_min_tig),
    ("TIS", _below_min_tis),
    ("DRIL", _not_drilling),
)


def determine(run_dt: dt.date, candidate: Candidate) -> ExtractRow:
    """Apply the extract's rules to one candidate. Pure; no I/O."""
    tig = time_in_grade(run_dt, candidate)
    tis = time_in_service(run_dt, candidate)
    for reason, rule in DENIAL_RULES:
        if _is_true(rule(candidate, tig, tis)):
            return ExtractRow(candidate.edipi, candidate.grade, candidate.tgt_grade_num,
                              tig, tis, "N", reason, run_dt)
    return ExtractRow(candidate.edipi, candidate.grade, candidate.tgt_grade_num,
                      tig, tis, "Y", None, run_dt)


def determine_all(run_dt: dt.date, candidates: Sequence[Candidate]) -> list[ExtractRow]:
    return [determine(run_dt, candidate) for candidate in candidates]


# --- database I/O -----------------------------------------------------------


class ComponentError(ValueError):
    pass


def _validate_component(component: Optional[str]) -> Optional[str]:
    """Check a component code before it is interpolated into the query.

    The comparison itself is exact, as in the legacy predicate
    ``m.COMPONENT = P_COMPONENT``: a lower-case code matches nothing and leaves
    the run date's report empty, and the case is not normalized. The check only
    rejects a value that cannot be a component code at all, rather than letting
    it reach the SQL.
    """
    if component is None:
        return None
    if not component.isalpha() or len(component) != 1:
        raise ComponentError(f"component must be a single letter, got {component!r}")
    return component


def _optional_date(value: Optional[str]) -> Optional[dt.date]:
    return dt.date.fromisoformat(value) if value else None


def _optional_int(value: Optional[str]) -> Optional[int]:
    return int(value) if value is not None else None


def _optional_text(value: Optional[str]) -> Optional[str]:
    return value.strip() if value is not None else None


def candidate_from_record(record: Record) -> Candidate:
    return Candidate(
        edipi=int(record[0]),
        grade=_optional_text(record[1]),
        grade_num=int(record[2]),
        dt_last_promo=_optional_date(record[3]),
        pebd=_optional_date(record[4]),
        brk_svc_mos=_optional_int(record[5]),
        adv_matl_ind=_optional_text(record[6]),
        adv_matl_mos=_optional_int(record[7]),
        duty_stat=_optional_text(record[8]),
        component=_optional_text(record[9]),
        rc_drill_stat=_optional_text(record[10]),
        min_tig=int(record[11]),
        min_tis=int(record[12]),
    )


def candidate_sql(component: Optional[str] = None) -> str:
    component = _validate_component(component)
    filter_sql = ""
    if component is not None:
        filter_sql = f"\n   AND m.COMPONENT = {quote_literal(component)}"
    return CANDIDATE_QUERY.format(max_grade_num=MAX_GRADE_NUM, component_filter=filter_sql)


def fetch_candidates(db: Database, component: Optional[str] = None) -> list[Candidate]:
    # Dates come back as YYYY-MM-DD whatever the server's datestyle is.
    sql = "SET datestyle TO 'ISO, MDY';\n" + candidate_sql(component)
    return [candidate_from_record(record) for record in db.query(sql)]


def _insert_values(row: ExtractRow) -> str:
    def number(value: Optional[int]) -> str:
        return "NULL" if value is None else str(value)

    return "(" + ", ".join([
        str(row.edipi), quote_literal(row.grade), str(row.tgt_grade_num),
        number(row.tig_mos), number(row.tis_mos), quote_literal(row.elig_ind),
        quote_literal(row.deny_rsn), f"DATE {quote_literal(row.run_dt.isoformat())}",
    ]) + ")"


def write_rows(db: Database, run_dt: dt.date, rows: Sequence[ExtractRow]) -> None:
    """Replace this run date's rows, the way the procedure does."""
    statements = [
        f"DELETE FROM {REPORT_TABLE} WHERE RUN_DT = DATE "
        f"{quote_literal(run_dt.isoformat())};",
    ]
    if rows:
        statements.append(
            f"INSERT INTO {REPORT_TABLE} (EDIPI, GRADE, TGT_GRADE_NUM, TIG_MOS, TIS_MOS, "
            "ELIG_IND, DENY_RSN, RUN_DT) VALUES\n"
            + ",\n".join(_insert_values(row) for row in rows) + ";"
        )
    db.execute("BEGIN;\n" + "\n".join(statements) + "\nCOMMIT;")


def run_extract(db: Database, run_dt: dt.date,
                component: Optional[str] = None) -> list[ExtractRow]:
    """Rebuild the report for ``run_dt`` and return the rows written."""
    rows = determine_all(run_dt, fetch_candidates(db, component))
    write_rows(db, run_dt, rows)
    return rows
