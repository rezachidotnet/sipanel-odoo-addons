#!/usr/bin/env bash
# Quotation lines: description / installation line / amount in words (work order 2026-10-05) — CLONE validation.
# Derived from scripts/sipanel_page1_clone_validate.sh (same clone, ownership and neutralization contract).
# Production DB `sipanel` is only READ (pg_dump streamed into the clone). Nothing is installed on `sipanel`.
# Usage: scripts/sipanel_qlines_clone_validate.sh all|clone|pre|install|test|post|evidence|drop
#   CLONE=<db name>   reuse/choose the clone (default sipanel_qlines_clone_<UTC timestamp>, printed on start)
#   PG_ADMIN=<role>   postgres maintenance role in odoo-db for CREATE/DROP DATABASE and pg_dump (default odoo, the role sipanel_recovery_point.sh uses)
# Clone ownership = Odoo's db_user from /etc/odoo/odoo.conf; a clone that fails restore, ownership check or
# neutralization is dropped immediately (fail closed).
# The module directory is copied into /opt/odoo/addons (inert until installed; it is not auto_install).
#
# ONE Odoo process per clone at a time (2026-10-05: an interrupted `test` left its in-container `odoo -u` running,
# the next `test` died on a lock timeout and `post` deadlocked against it):
#   - one run per host: flock on $LOCK (a second invocation is refused, it never waits silently);
#   - before every Odoo step: no in-container process may reference the clone and the clone may have no
#     non-idle PostgreSQL backend — otherwise the step is REFUSED (never run alongside);
#   - after every Odoo step: wait until its in-container process is gone and the clone is quiet;
#   - Ctrl-C / error / hang-up: the in-container processes of THIS clone are stopped (docker exec does not
#     forward signals to them);
#   - a failed step stops the run (`all` never continues past a failed install, test or render).
set -euo pipefail
MODE=${1:-all}
REPO=/home/ubuntu/sipanel_odoo_addons
MOD=sipanel_quotation_lines
SIPANEL_MODS=sipanel_commercial_scope_core,sipanel_sale_scope,sipanel_scope_execution,sipanel_scope_costing,sipanel_quotation_project_info
APPC=odoo-sipanel; PGC=odoo-db; SRC_DB=sipanel
TS=$(date -u +%Y%m%dT%H%M%SZ)
CLONE_GIVEN=${CLONE:-}
CLONE=${CLONE:-sipanel_qlines_clone_${TS}}
# evidence belongs to the clone (never to the invocation, never to an exported EVID): one clone, one directory
EVID=/home/ubuntu/sipanel_audit/docs/audits/data/quotation_lines_clone_${CLONE#sipanel_qlines_clone_}
LOGDIR=${LOGDIR:-$REPO/reports}
LOCK=${LOCK:-$LOGDIR/.sipanel_qlines_clone.lock}
QUIET_TIMEOUT=${QUIET_TIMEOUT:-180}
# Known, pre-existing failure on master (memory: sale_scope '1.00' needle, unrelated to this module). Reported, not hidden.
KNOWN_FAIL='TestInvoiceFlow.test_generated_line_appears_in_the_customer_pdf_without_internal_data'
ODOO=(docker exec "$APPC" odoo -c /etc/odoo/odoo.conf -d "$CLONE" --no-http --stop-after-init)
echo "clone database: $CLONE"
echo "evidence: $EVID"
[[ "$CLONE" == sipanel_qlines_clone_* ]] || { echo "refusing: clone name must start with sipanel_qlines_clone_"; exit 2; }

mkdir -p "$LOGDIR"
exec 9>"$LOCK"
flock -n 9 || { echo "REFUSED: another sipanel_qlines_clone_validate.sh is running (lock $LOCK)"; exit 5; }

# PG_ADMIN: maintenance role used only for CREATE/DROP DATABASE and the read-only pg_dump of production.
PG_ADMIN=${PG_ADMIN:-odoo}
# Odoo's own role, read from the running container's config (never hard-coded); every clone object must belong to it.
db_user() {
  local u
  u=$(docker exec "$APPC" sh -c "sed -n 's/^[[:space:]]*db_user[[:space:]]*=[[:space:]]*//p' /etc/odoo/odoo.conf" | tail -1 | tr -d '[:space:]')
  [[ "$u" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || { echo "cannot read a valid db_user from /etc/odoo/odoo.conf in $APPC" >&2; exit 2; }
  echo "$u"
}
psql_admin() { docker exec -i "$PGC" psql -U "$PG_ADMIN" -v ON_ERROR_STOP=1 "$@"; }

# ------------------------------------------------------------------ one Odoo process per clone
# In-container processes whose command line names the clone. The clone name travels in the environment, so the
# scanning shell itself never matches.
clone_procs() {
  docker exec -e QL_CLONE="$CLONE" "$APPC" sh -c '
    for d in /proc/[0-9]*; do
      [ "${d#/proc/}" = "$$" ] && continue
      c=$(tr "\0" " " < "$d/cmdline" 2>/dev/null) || continue
      case "$c" in *"$QL_CLONE"*) echo "${d#/proc/} $c";; esac
    done'
}
# PostgreSQL backends on the clone that are not idle (idle pooled connections hold no lock).
clone_busy_backends() {
  psql_admin -d postgres -tAc "select pid || ' ' || state || ' ' || coalesce(wait_event_type, '-') || ' ' ||
      left(regexp_replace(query, '\s+', ' ', 'g'), 100)
    from pg_stat_activity where datname = '${CLONE}' and pid <> pg_backend_pid() and coalesce(state, '') <> 'idle'"
}
assert_exclusive() {  # $1 = step about to start
  local procs busy
  procs=$(clone_procs); busy=$(clone_busy_backends)
  if [ -n "$procs" ] || [ -n "$busy" ]; then
    echo "REFUSED ($1): the clone is in use by another process; nothing was started." >&2
    [ -z "$procs" ] || printf 'in-container processes on %s:\n%s\n' "$CLONE" "$procs" >&2
    [ -z "$busy" ] || printf 'non-idle backends on %s:\n%s\n' "$CLONE" "$busy" >&2
    exit 6
  fi
}
wait_quiet() {  # $1 = step that just ended
  local i procs busy
  for ((i = 0; i < QUIET_TIMEOUT; i += 2)); do
    procs=$(clone_procs); busy=$(clone_busy_backends)
    [ -z "$procs" ] && [ -z "$busy" ] && { echo "clone quiet after $1"; return 0; }
    sleep 2
  done
  printf 'NOT_QUIET after %s (%ss):\n%s\n%s\n' "$1" "$QUIET_TIMEOUT" "$procs" "$busy" >&2
  exit 7
}
stop_clone_procs() {  # only processes naming THIS clone; TERM, then KILL
  local pids i
  pids=$(clone_procs | awk '{print $1}' | tr '\n' ' ')
  [ -n "${pids// /}" ] || return 0
  echo "stopping in-container processes on ${CLONE}: ${pids}" >&2
  docker exec "$APPC" sh -c "kill -TERM $pids" 2>/dev/null || true
  for ((i = 0; i < 30; i++)); do [ -z "$(clone_procs)" ] && return 0; sleep 1; done
  pids=$(clone_procs | awk '{print $1}' | tr '\n' ' ')
  [ -z "${pids// /}" ] || docker exec "$APPC" sh -c "kill -KILL $pids" 2>/dev/null || true
}
OWN_STEP=0   # 1 while an Odoo process started by this invocation may still run on the clone
on_exit() {
  local rc=$?
  trap - EXIT INT TERM HUP
  # only a step THIS invocation launched is stopped (a refused invocation never touches another run's processes)
  if [ "$rc" -ne 0 ] && [ "$OWN_STEP" = 1 ]; then stop_clone_procs || true; fi
  exit "$rc"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

capacity() {
  local size free need
  size=$(psql_admin -d postgres -tAc "select pg_database_size('${SRC_DB}')")
  free=$(df -B1 --output=avail / | tail -1)
  need=$(( size * 2 + 300 * 1024 * 1024 ))            # restored DB + indexes slack + filestore copy
  echo "db=${size} free=${free} need=${need}"
  [ $(( (free - need) / 1048576 )) -ge 1500 ] || { echo "BLOCKED_DISK_CAPACITY"; exit 3; }
}
drop_clone() {  # clone only: in-container processes on it, database, its filestore copy
  [[ "$CLONE" == sipanel_qlines_clone_* ]] || { echo "refusing to drop $CLONE"; exit 2; }
  stop_clone_procs
  psql_admin -d postgres -c "DROP DATABASE IF EXISTS \"${CLONE}\" WITH (FORCE)" || true
  sudo rm -rf "/opt/odoo/data/filestore/${CLONE:?}"
  psql_admin -d postgres -tAc "select 1 from pg_database where datname='${CLONE}'" | grep -q 1 \
    && { echo "DROP FAILED: ${CLONE} still exists"; return 1; }
  echo "DROPPED ${CLONE}"
}
fail_clone() { echo "CLONE_FAILED: $1 -> dropping clone ${CLONE}" >&2; drop_clone; exit "${2:-4}"; }
clone() {
  local owner bad neutral
  [ -z "$CLONE_GIVEN" ] || { echo "refusing: a clone is always created fresh (unset CLONE)"; exit 2; }
  owner=$(db_user)
  echo "clone owner (db_user from odoo.conf): ${owner}"
  capacity
  psql_admin -d postgres -tAc "select 1 from pg_database where datname='${CLONE}'" | grep -q 1 && { echo "clone exists"; exit 1; }
  [ ! -e "$EVID" ] || { echo "refusing: evidence directory $EVID already exists"; exit 2; }
  # same encoding / collation as production (template0 would otherwise take the server defaults)
  local enc collate ctype
  IFS='|' read -r enc collate ctype < <(psql_admin -d postgres -tAc \
    "select pg_encoding_to_char(encoding), datcollate, datctype from pg_database where datname = '${SRC_DB}'")
  [ -n "$enc" ] || { echo "cannot read ${SRC_DB} encoding"; exit 2; }
  psql_admin -d postgres -c "CREATE DATABASE \"${CLONE}\" OWNER \"${owner}\" TEMPLATE template0
      ENCODING '${enc}' LC_COLLATE '${collate}' LC_CTYPE '${ctype}'" || fail_clone "create database"
  # plain-SQL dump without ownership/ACL statements, replayed by the Odoo role itself: every object it creates is
  # owned by ${owner}, exactly like production. Any statement error stops the restore (ON_ERROR_STOP) and drops the clone.
  docker exec "$PGC" sh -c "pg_dump -U '${PG_ADMIN}' --no-owner --no-privileges -d '${SRC_DB}' \
      | psql -U '${owner}' -d '${CLONE}' -q -v ON_ERROR_STOP=1 --single-transaction > /dev/null" \
    || fail_clone "restore as ${owner}"
  bad=$(psql_admin -d "$CLONE" -tAc "select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace
          where n.nspname = 'public' and c.relkind in ('r','p','v','m','S','f')
            and pg_get_userbyid(c.relowner) <> '${owner}'") || fail_clone "ownership query"
  echo "public relations (tables/views/sequences) not owned by ${owner}: ${bad}"
  [ "$bad" = "0" ] || fail_clone "${bad} public relations not owned by ${owner}"
  sudo cp -a "/opt/odoo/data/filestore/${SRC_DB}" "/opt/odoo/data/filestore/${CLONE}" || fail_clone "filestore copy"
  # no mail, no crons, no payment providers; a clone that is not neutralized must never survive
  OWN_STEP=1
  docker exec "$APPC" odoo neutralize -c /etc/odoo/odoo.conf -d "$CLONE" || fail_clone "odoo neutralize"
  wait_quiet neutralize; OWN_STEP=0
  neutral=$(psql_admin -d "$CLONE" -tAc "select value from ir_config_parameter where key = 'database.is_neutralized'") \
    || fail_clone "neutralization check"
  [ "$(echo "$neutral" | tr -d '[:space:]')" = "true" ] || fail_clone "database.is_neutralized is '${neutral}'"
  mkdir -p "$EVID"
  echo "CLONE_READY ${CLONE} owner=${owner} neutralized=true"
}
deploy_dir() {
  sudo rsync -a --delete "$REPO/addons/$MOD/" "/opt/odoo/addons/$MOD/"
  sudo chown -R --reference=/opt/odoo/addons/sale_shamsi_report "/opt/odoo/addons/$MOD"
}
render() {  # $1 = pre|post ; acceptance + PDFs, everything it writes is rolled back
  local out rc
  assert_exclusive "render $1"
  mkdir -p "$EVID"
  rm -f "$EVID/$1"_*                                       # never mix files of an earlier or interrupted run
  docker exec "$APPC" rm -rf /tmp/qlines /tmp/qlines_src && docker exec "$APPC" mkdir -p /tmp/qlines_src
  docker cp "$REPO/scripts/sipanel_standing_seam_v3.py" "$APPC:/tmp/qlines_src/sipanel_standing_seam_v3.py"
  OWN_STEP=1; set +e
  out=$(docker exec -i -e PHASE="$1" -e OUT=/tmp/qlines -e V3_SCRIPT=/tmp/qlines_src/sipanel_standing_seam_v3.py "$APPC" \
    odoo shell -c /etc/odoo/odoo.conf -d "$CLONE" --no-http < "$REPO/scripts/quotation_lines_acceptance.py" 2>&1)
  rc=$?
  set -e
  echo "$out" > "$LOGDIR/qlines-$1-${TS}.log"
  wait_quiet "render $1"; OWN_STEP=0
  docker cp "$APPC:/tmp/qlines/." "$EVID/" || true
  echo "$out" | grep '^QLINES_' || true
  echo "$out" | grep -q '^QLINES_[A-Z]* {"all_ok": true' && [ "$rc" -eq 0 ] \
    || { echo "RENDER_$1 FAILED (rc=$rc, log $LOGDIR/qlines-$1-${TS}.log, summary $EVID/$1_summary.json)"; exit 8; }
  echo "RENDER_$1 OK"
}
install() {
  local log=$LOGDIR/qlines-install-${TS}.log rc
  assert_exclusive install
  deploy_dir
  OWN_STEP=1; set +e; "${ODOO[@]}" -i "$MOD" > "$log" 2>&1; rc=$?; set -e
  wait_quiet install; OWN_STEP=0
  grep -E "ERROR|CRITICAL|Traceback|sipanel_quotation_lines:" "$log" || true
  [ "$rc" -eq 0 ] && ! grep -qE " (ERROR|CRITICAL) " "$log" || { echo "INSTALL FAILED (rc=$rc, log $log)"; exit 9; }
  echo "INSTALL OK"
}
run_tests() {
  local log=$LOGDIR/qlines-test-${TS}.log rc ran fails errs known other complete
  assert_exclusive test
  deploy_dir
  OWN_STEP=1; set +e; "${ODOO[@]}" -u "$MOD,$SIPANEL_MODS" --test-enable --test-tags sipanel > "$log" 2>&1; rc=$?; set -e
  wait_quiet test; OWN_STEP=0
  ran=$(grep -cE " Starting [A-Za-z0-9_]+\.test" "$log" || true)
  fails=$(grep -E " (FAIL|ERROR): " "$log" | grep -E "odoo\.(addons\.[a-z_]+\.tests|tests\.)" | sed -E 's/.* (FAIL|ERROR): /\1: /' || true)
  known=$(echo "$fails" | grep -cF "FAIL: $KNOWN_FAIL" || true)
  other=$(echo "$fails" | grep -vF "FAIL: $KNOWN_FAIL" | grep -c . || true)
  errs=$(echo "$fails" | grep -c '^ERROR' || true)
  complete=no; grep -qE "odoo\.service\.server: [0-9]+ post-tests in" "$log" && complete=yes
  grep -qE "Failed to initialize database|CRITICAL" "$log" && complete=no
  echo "$fails" | sed '/^$/d'
  echo "QLINES_TEST ran=${ran} failed_or_error=$((known + other)) (known_preexisting=${known}, new=${other}, of_which_errors=${errs}) complete=${complete} rc=${rc} log=${log}"
  grep -E "odoo\.tests\.stats: " "$log" | sed -E 's/.*odoo\.tests\.stats: //' || true
  [ "$complete" = yes ] && [ "$other" -eq 0 ] || { echo "TEST FAILED"; exit 10; }
  echo "TEST OK (only the known pre-existing failure, if any)"
}
evidence() {
  local d=$REPO/scripts/qlines_pdf_diff.py en fa f lang words
  cd "$EVID"
  for f in pre_summary.json post_summary.json; do
    python3 -c "import json,sys; sys.exit(0 if json.load(open('$f'))['all_ok'] else 1)" \
      || { echo "EVIDENCE REFUSED: $f is missing or not all_ok (no verdict on a partial run)"; exit 11; }
  done
  for f in *.pdf; do pdftotext -layout "$f" "${f%.pdf}.txt"; pdftoppm -r 60 -png "$f" "${f%.pdf}"; \
    echo "$f pages=$(pdfinfo "$f" | awk '/^Pages/{print $2}')"; done
  en=$(python3 -c "import json; print(json.load(open('post_summary.json'))['si26_2546_words_en'])")
  fa='مبلغ کل به حروف: بیست و هفت میلیارد و سیصد و پنجاه و دو میلیون و سیصد و هشتاد هزار ریال'
  for lang in fa_IR en_US; do
    diff <(pdftotext -layout "pre_SI-26-2546_${lang}.pdf" -) <(pdftotext -layout "post_SI-26-2546_${lang}.pdf" -) \
      > "SI-26-2546_${lang}_pre_post.diff" || true
    [ "$lang" = fa_IR ] && words=$fa || words="Amount in words: $en"
    # module installed: only the amount-in-words line may appear
    python3 "$d" "pre_SI-26-2546_${lang}.pdf" "post_SI-26-2546_${lang}.pdf" --words-line "$words" || true
    # Standing Seam v3 released: SI-26/2546 (old wording, no installation line) must not change at all
    python3 "$d" "post_SI-26-2546_${lang}.pdf" "post_SI-26-2546_after_v3_${lang}.pdf" --identical || true
  done | tee SI-26-2546_verdicts.txt
  grep -q "VERDICT FAIL" SI-26-2546_verdicts.txt && { echo "EVIDENCE FAILED (see SI-26-2546_verdicts.txt)"; exit 12; }
  echo "EVIDENCE OK"
}
case "$MODE" in
  clone)    clone ;;
  pre)      render pre ;;
  install)  install ;;
  test)     run_tests ;;
  post)     render post ;;
  evidence) evidence ;;
  all)      clone; render pre; install; run_tests; render post; evidence ;;
  drop)     # DESTRUCTIVE, clone only; the clone must be named explicitly
            [ -n "$CLONE_GIVEN" ] || { echo "set CLONE=sipanel_qlines_clone_..."; exit 2; }
            drop_clone ;;
  *) echo "unknown mode"; exit 2 ;;
esac
