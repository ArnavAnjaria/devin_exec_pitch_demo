#!/usr/bin/env bash
#
# Nightly promotion eligibility run: the shell equivalent of submitting
# jcl/PROMELIG.jcl. Runs after the unit diary load -- do not run standalone,
# the master must be current or the board slate will be stale.
#
# Dataset names map to paths:
#   MANPWR.PROD.MASTER        -> $PROMELIG_MASTER
#   MANPWR.PROD.ELIG.EXTRACT  -> $PROMELIG_ELIG_OUT
#
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

master="${PROMELIG_MASTER:?PROMELIG_MASTER is not set}"
elig_out="${PROMELIG_ELIG_OUT:?PROMELIG_ELIG_OUT is not set}"
report_out="${PROMELIG_REPORT_OUT:-/dev/stdout}"
work_dir="${PROMELIG_WORK_DIR:-$(mktemp -d)}"
run_date="${PROMELIG_RUN_DATE:-$(date +%Y%m%d)}"

exec env PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}" \
    "${PYTHON:-python3}" -m promelig.job \
    --master "$master" \
    --elig-out "$elig_out" \
    --report-out "$report_out" \
    --work-dir "$work_dir" \
    --run-date "$run_date" \
    ${PROMELIG_EXTRACT_COMMAND:+--extract-command "$PROMELIG_EXTRACT_COMMAND"} \
    "$@"
