#!/usr/bin/env bash
# Quotation lines: description / installation line / amount in words (work order 2026-10-05) — CLONE validation.
# Derived from scripts/sipanel_page1_clone_validate.sh (same clone, ownership and neutralization contract).
# Production DB `sipanel` is only READ (pg_dump streamed into the clone). Nothing is installed on `sipanel`.
# Usage: scripts/sipanel_qlines_clone_validate.sh all|clone|pre|install|test|post|evidence|rehearsal|proof|drop
#   rehearsal (after evidence): COMMITS on the clone - Standing Seam v3 released, SI-26/2546 itself at 10 % (way A, owner decision 2026-10-08)
#   proof (last step of all): code_version.json + PDF content markers (scripts/qlines_code_markers.py)
#   CLONE=<db name>   reuse/choose the clone (default sipanel_qlines_clone_<UTC timestamp>, printed on start)
#   COMMIT=<sha>      commit under test (default: HEAD at clone creation; fixed per clone in code_commit.txt)
#   PG_ADMIN=<role>   postgres maintenance role in odoo-db for CREATE/DROP DATABASE and pg_dump (default odoo, the role sipanel_recovery_point.sh uses)
# Clone ownership = Odoo's db_user from /etc/odoo/odoo.conf; a clone that fails restore, ownership check or
# neutralization is dropped immediately (fail closed).
#
# CODE UNDER TEST (decision 2026-10-06): every Odoo step - neutralize, install, tests, PDF rendering, rehearsal - runs
# in a THROWAWAY container (same image id as Production, odoo.conf read-only) on a git worktree of the commit
# under test: addons path = /mnt/branch (the worktree's addons/), /mnt/deps (each module of /opt/odoo/addons the
# branch does not contain, read-only, listed with a tree hash in deps_modules.txt). Nothing is copied into
# /opt/odoo/addons and the Production container never connects to the clone. PDFs come from a render server in
# its own container: HTTP on 127.0.0.1 inside that container only (no published port, no nginx), --db-filter
# ^clone$, no database list, workers 0, no cron; the clone's web.base.url / report.url point to it. If it cannot
# be started the run stops with RENDER_BLOCKED - there is no fallback to the Production container.
# Every container: --memory 700m --memory-swap 1400m --cpus 1.0 --oom-score-adj 800 (CLONE_MEM / CLONE_MEMSWAP /
# CLONE_CPUS); only the clone's own filestore is mounted.
#
# DELETIONS (2026-10-06): every file deletion goes through a guard - non-empty variable, path resolved with
# realpath and required to sit exactly under its fixed root (evidence root / filestore root / render-out dir /
# worktree root), file prefixes by `find -maxdepth 1 -type f -delete`, never a glob rm.
#
# ONE Odoo process per clone at a time (2026-10-05: an interrupted `test` left its in-container `odoo -u` running,
# the next `test` died on a lock timeout and `post` deadlocked against it):
#   - one run per host: flock on $LOCK (a second invocation is refused, it never waits silently);
#   - before every Odoo step: no process (Production container or a clone container) may reference the clone and
#     the clone may have no non-idle PostgreSQL backend — otherwise the step is REFUSED (never run alongside);
#   - after every Odoo step: wait until its container is gone and the clone is quiet;
#   - Ctrl-C / error / hang-up / watchdog: the clone containers of THIS run are removed;
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
LOGDIR=${LOGDIR:-$EVID/logs}                              # outside the code repo (per run)
EVID_ROOT=/home/ubuntu/sipanel_audit/docs/audits/data
FS_ROOT=/opt/odoo/data/filestore
WT_ROOT=/home/ubuntu/sipanel_qlines_worktrees
CLONE_RE='^sipanel_qlines_clone_[0-9]{8}T[0-9]{6}Z$'
refuse() { echo "REFUSED: $*" >&2; exit 2; }
guard_evid() {  # prints the resolved evidence directory, or refuses
  local r
  : "${EVID:?EVID is empty}"
  r=$(realpath -e -- "$EVID") || refuse "evidence directory $EVID does not exist"
  [ "$r" != / ] && [ "$(dirname -- "$r")" = "$EVID_ROOT" ] && [[ "$(basename -- "$r")" == quotation_lines_clone_* ]] \
    || refuse "$r is not a quotation_lines_clone_* directory directly under $EVID_ROOT"
  printf '%s' "$r"
}
evid_delete() {  # $1 = file prefix (pre | post | rehearsal): regular files "<prefix>_*" directly in EVID only
  local r
  : "${1:?step name is empty}"
  [[ "$1" =~ ^[a-z]+$ ]] || refuse "bad evidence prefix '$1'"
  r=$(guard_evid)
  find "$r" -maxdepth 1 -type f -name "${1}_*" -delete
}
SUDO=${SUDO-sudo}   # the guard test runs it without sudo, inside a sandbox FS_ROOT
filestore_delete() {  # the clone's filestore copy only
  local p r
  : "${CLONE:?CLONE is empty}"
  # hard refusals, independent of FS_ROOT: the Production database name, and anything that is not a clone name
  case "$CLONE" in sipanel|sipanel/*|*/*|.*|'') refuse "filestore of '$CLONE' is never deleted";; esac
  [[ "$CLONE" =~ ^sipanel_qlines_clone_[0-9]{8}T[0-9]{6}Z$ ]] || refuse "filestore of '$CLONE' (not a clone name)"
  [[ "$CLONE" =~ $CLONE_RE ]] || refuse "clone name $CLONE"
  : "${FS_ROOT:?FS_ROOT is empty}"
  p="$FS_ROOT/$CLONE"
  $SUDO test -e "$p" || return 0
  r=$($SUDO realpath -e -- "$p") || refuse "cannot resolve $p"
  [ "$r" = "$p" ] && [ "$(dirname -- "$r")" = "$FS_ROOT" ] \
    && [[ "$(basename -- "$r")" =~ ^sipanel_qlines_clone_[0-9]{8}T[0-9]{6}Z$ ]] || refuse "$p resolves to $r"
  $SUDO rm -rf --one-file-system -- "$r"
}
outdir_delete() {  # a render output directory made by mktemp under LOGDIR
  local r root
  : "${OUTDIR:?OUTDIR is empty}"
  root=$(realpath -e -- "$LOGDIR")
  r=$(realpath -e -- "$OUTDIR") || return 0
  [[ "$r" =~ ^${root}/\.render-out\.[A-Za-z0-9]{6}$ ]] || refuse "$r is not a render output directory under $root"
  rm -rf --one-file-system -- "$r"
}
worktree_delete() {
  : "${WT:?WT is empty}"
  [[ "$CLONE" =~ $CLONE_RE ]] && [ "$WT" = "$WT_ROOT/$CLONE" ] || refuse "worktree path $WT"
  [ ! -d "$WT" ] || git -C "$REPO" worktree remove --force -- "$WT"
}
LOCK=${LOCK:-/home/ubuntu/sipanel_audit/docs/audits/data/.sipanel_qlines_clone.lock}   # one fixed path per host
QUIET_TIMEOUT=${QUIET_TIMEOUT:-180}
# Known, pre-existing failure on master (memory: sale_scope '1.00' needle, unrelated to this module). Reported, not hidden.
KNOWN_FAIL='TestInvoiceFlow.test_generated_line_appears_in_the_customer_pdf_without_internal_data'
ISO=sipanel-qlines-${CLONE#sipanel_qlines_clone_}
CLONE_MEM=${CLONE_MEM:-700m}; CLONE_MEMSWAP=${CLONE_MEMSWAP:-1400m}; CLONE_CPUS=${CLONE_CPUS:-1.0}
RPORT=${RPORT:-18069}                                   # inside the render container's own network namespace
WT=$WT_ROOT/$CLONE
APATH=/mnt/branch,/mnt/deps
MOUNTS=()
IMAGE_ID=; NET=; OUTDIR=
container_setup() {  # worktree of the commit under test + image + mounts; the commit is fixed per clone
  local want conf d m
  mkdir -p "$EVID" "$WT_ROOT"
  if [ -f "$EVID/code_commit.txt" ]; then
    want=$(cat "$EVID/code_commit.txt")
    [ -z "${COMMIT:-}" ] || [ "$(git -C "$REPO" rev-parse "$COMMIT")" = "$want" ] \
      || refuse "this clone is tested at $want, not $COMMIT"
  else
    want=$(git -C "$REPO" rev-parse "${COMMIT:-HEAD}")
    [ -n "${COMMIT:-}" ] || [ -z "$(git -C "$REPO" status --porcelain --untracked-files=no)" ] \
      || echo "NOTE: uncommitted changes in $REPO are NOT under test (worktree = $want)"
    echo "$want" > "$EVID/code_commit.txt"
  fi
  [ -d "$WT" ] || git -C "$REPO" worktree add --detach "$WT" "$want" >/dev/null
  [ "$(git -C "$WT" rev-parse HEAD)" = "$want" ] && [ -z "$(git -C "$WT" status --porcelain)" ] \
    || refuse "worktree $WT is not a clean checkout of $want"
  IMAGE_ID=$(docker inspect -f '{{.Image}}' "$APPC"); NET=$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$APPC")
  conf=$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/etc/odoo/odoo.conf"}}{{.Source}}{{end}}{{end}}' "$APPC")
  [ -n "$IMAGE_ID" ] && [ -n "$NET" ] && [ -n "$conf" ] || refuse "cannot read image / network / odoo.conf of $APPC"
  MOUNTS=(-v "$conf:/etc/odoo/odoo.conf:ro" -v "$WT/addons:/mnt/branch:ro")
  : > "$EVID/deps_modules.txt"
  for d in /opt/odoo/addons/*/; do
    m=$(basename -- "$d")
    [ -f "$d/__manifest__.py" ] && [ ! -e "$WT/addons/$m" ] || continue
    MOUNTS+=(-v "${d%/}:/mnt/deps/$m:ro")
    echo "$m $(cd "$d" && sudo find . -type f ! -name '*.pyc' ! -path '*/__pycache__/*' -print0 | sort -z \
      | sudo xargs -0 sha256sum | sha256sum | cut -c1-16)" >> "$EVID/deps_modules.txt"
  done
  sudo test -d /opt/odoo/data/addons && MOUNTS+=(-v /opt/odoo/data/addons:/var/lib/odoo/addons:ro)
  sudo test -d "$FS_ROOT/$CLONE" && MOUNTS+=(-v "$FS_ROOT/$CLONE:/var/lib/odoo/filestore/$CLONE")
  return 0
}
LIMITS=(--memory "$CLONE_MEM" --memory-swap "$CLONE_MEMSWAP" --cpus "$CLONE_CPUS" --oom-score-adj 800)
iso_run() {  # $1 = role; rest = image + command; one throwaway, limited container per call
  local role=$1; shift
  docker run --rm -i --name "$ISO-$role" --network "$NET" "${LIMITS[@]}" --label "sipanel.qlines.clone=$CLONE" \
    "${MOUNTS[@]}" "$@"
}
odoo_clone() {  # odoo -c ... --addons-path BRANCH -d CLONE --no-http --stop-after-init "$@"
  iso_run step "$IMAGE_ID" odoo -c /etc/odoo/odoo.conf --addons-path "$APATH" -d "$CLONE" --no-http \
    --stop-after-init "$@"
}
render_blocked() { echo "RENDER_BLOCKED: $1" >&2; res_snapshot "render blocked: $1"; exit 15; }
render_server_start() {
  local i code=
  docker ps -aq --filter "name=^/$ISO-render\$" | xargs -r docker rm -f >/dev/null
  # the clone (never Production) points its own URLs at the render server
  psql_admin -d "$CLONE" -q -c "INSERT INTO ir_config_parameter (key, value, create_date, write_date) VALUES
      ('web.base.url', 'http://127.0.0.1:${RPORT}', now(), now()),
      ('report.url', 'http://127.0.0.1:${RPORT}', now(), now()),
      ('web.base.url.freeze', 'True', now(), now())
      ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, write_date = now()" \
    || render_blocked "cannot set web.base.url / report.url on ${CLONE}"
  docker run -d --name "$ISO-render" --network "$NET" "${LIMITS[@]}" --label "sipanel.qlines.clone=$CLONE" \
    "${MOUNTS[@]}" "$IMAGE_ID" \
    odoo -c /etc/odoo/odoo.conf --addons-path "$APATH" -d "$CLONE" --db-filter "^${CLONE}\$" --no-database-list \
    --workers 0 --max-cron-threads 0 --http-interface 127.0.0.1 --http-port "$RPORT" >/dev/null \
    || render_blocked "docker run of the render server failed"
  for ((i = 0; i < 90; i++)); do
    [ -n "$(docker ps -q --filter "name=^/$ISO-render\$")" ] \
      || render_blocked "render server exited: $(docker logs --tail 15 "$ISO-render" 2>&1 | tr '\n' ' ')"
    code=$(docker exec "$ISO-render" python3 -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:${RPORT}/web/login', timeout=5).status)" 2>/dev/null || true)
    [ "$code" = 200 ] && break
    sleep 2
  done
  [ "$code" = 200 ] || render_blocked "render server not answering on 127.0.0.1:${RPORT} after 180 s"
  [ "$(docker inspect -f '{{len .NetworkSettings.Ports}}' "$ISO-render")" = 0 ] \
    || render_blocked "render server publishes ports: $(docker inspect -f '{{json .NetworkSettings.Ports}}' "$ISO-render")"
  res_snapshot "render server up ($ISO-render, 127.0.0.1:${RPORT} inside its own network namespace)"
  echo "render server up: $ISO-render"
}
render_server_stop() {
  res_snapshot "before render server stop"
  docker logs "$ISO-render" > "$LOGDIR/qlines-render-server-${TS}.log" 2>&1 || true
  docker rm -f "$ISO-render" >/dev/null 2>&1 || true
}
render_shell() {  # $1 = script in the worktree's scripts/ ; "$@" extra docker options ; files -> OUTDIR
  local script=$1; shift
  [[ "$script" =~ ^[a-z0-9_]+\.py$ ]] || refuse "script name $script"
  docker run --rm -i --name "$ISO-shell" --network "container:$ISO-render" "${LIMITS[@]}" \
    --label "sipanel.qlines.clone=$CLONE" "${MOUNTS[@]}" -v "$OUTDIR:/out" -v "$WT/scripts:/mnt/scripts:ro" \
    -e OUT=/out -e V3_SCRIPT=/mnt/scripts/sipanel_standing_seam_v3.py "$@" "$IMAGE_ID" \
    odoo shell -c /etc/odoo/odoo.conf --addons-path "$APATH" -d "$CLONE" --no-http < "$WT/scripts/$script"
}
echo "clone database: $CLONE"
echo "evidence: $EVID"
[[ "$CLONE" =~ $CLONE_RE ]] || refuse "clone name must match $CLONE_RE"
[ "$EVID" = "$EVID_ROOT/quotation_lines_clone_${CLONE#sipanel_qlines_clone_}" ] || refuse "evidence path $EVID"

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
  docker ps --filter "label=sipanel.qlines.clone=$CLONE" --format 'container {{.Names}}'
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
stop_clone_procs() {  # only processes naming THIS clone (and its throwaway container); TERM, then KILL
  local pids i
  if [ -n "$(docker ps -aq --filter "label=sipanel.qlines.clone=$CLONE")" ]; then
    echo "removing the clone containers of ${CLONE}" >&2
    docker ps -aq --filter "label=sipanel.qlines.clone=$CLONE" | xargs -r docker rm -f >/dev/null 2>&1 || true
  fi
  pids=$(clone_procs | awk '$1 ~ /^[0-9]+$/ {print $1}' | tr '\n' ' ')
  [ -n "${pids// /}" ] || return 0
  echo "stopping in-container processes on ${CLONE}: ${pids}" >&2
  docker exec "$APPC" sh -c "kill -TERM $pids" 2>/dev/null || true
  for ((i = 0; i < 30; i++)); do [ -z "$(clone_procs | awk '$1 ~ /^[0-9]+$/')" ] && return 0; sleep 1; done
  pids=$(clone_procs | awk '$1 ~ /^[0-9]+$/ {print $1}' | tr '\n' ' ')
  [ -z "${pids// /}" ] || docker exec "$APPC" sh -c "kill -KILL $pids" 2>/dev/null || true
}
# ------------------------------------------------------------------ resource watchdog (2 vCPU / 2 GB host)
# The host also serves Production (odoo-sipanel and the other Odoo containers on odoo-db). Every invocation
# records free / docker stats / OOM events before, during (every RES_INTERVAL s) and after, into
# $EVID/resources.log, and STOPS the run (own processes only) when the clone run endangers the host:
#   - a new OOM-killer event in the kernel log, or a container flagged OOMKilled;
#   - MemAvailable below RES_MIN_AVAIL_MB for 3 consecutive samples;
#   - swap used grown by more than RES_MAX_SWAP_GROWTH_MB over the value at start (the host already swaps at idle);
#   - swap-in above RES_MAX_SWAPIN_PPS pages/s for 3 consecutive samples (thrashing).
RES_INTERVAL=${RES_INTERVAL:-10}
RES_MIN_AVAIL_MB=${RES_MIN_AVAIL_MB:-150}
RES_MAX_SWAP_GROWTH_MB=${RES_MAX_SWAP_GROWTH_MB:-1024}
RES_MAX_SWAPIN_PPS=${RES_MAX_SWAPIN_PPS:-1500}
RESLOG=$EVID/resources.log
MON_PID=
meminfo_mb() { awk -v k="$1:" '$1 == k {print int($2 / 1024)}' /proc/meminfo; }
swap_used_mb() { echo $(( $(meminfo_mb SwapTotal) - $(meminfo_mb SwapFree) )); }
oom_events() { sudo -n dmesg 2>/dev/null | grep -ciE 'out of memory|killed process|oom-kill' || true; }
containers_oomkilled() {
  docker ps --format '{{.Names}}' | xargs -r docker inspect -f '{{.Name}} {{.State.OOMKilled}}' | grep ' true$' || true
}
res_snapshot() {  # $1 = label
  mkdir -p "$EVID"
  {
    echo "=== $(date -u +%FT%TZ) $1"
    free -h
    echo "MemAvailable=$(meminfo_mb MemAvailable)MB swap_used=$(swap_used_mb)MB oom_events=$(oom_events) load=$(cut -d' ' -f1-3 /proc/loadavg)"
    docker stats --no-stream --format '{{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}} ({{.MemPerc}})'
    containers_oomkilled
  } >> "$RESLOG" 2>&1
}
res_monitor() {  # background; signals the main script on danger
  local main=$1 swap0 oom0 low=0 thrash=0 in0 in1 avail swap reason=
  swap0=$(swap_used_mb); oom0=$(oom_events); in0=$(awk '$1 == "pswpin" {print $2}' /proc/vmstat)
  while sleep "$RES_INTERVAL"; do
    avail=$(meminfo_mb MemAvailable); swap=$(swap_used_mb)
    in1=$(awk '$1 == "pswpin" {print $2}' /proc/vmstat)
    local pps=$(( (in1 - in0) / RES_INTERVAL )); in0=$in1
    echo "$(date -u +%TZ) avail=${avail}MB swap=${swap}MB (+$((swap - swap0))) swapin=${pps}p/s load=$(cut -d' ' -f1 /proc/loadavg) $(docker stats --no-stream --format '{{.Name}}={{.MemUsage}}' | awk '{print $1}' | tr '\n' ' ')" >> "$RESLOG"
    [ "$avail" -lt "$RES_MIN_AVAIL_MB" ] && low=$((low + 1)) || low=0
    [ "$pps" -gt "$RES_MAX_SWAPIN_PPS" ] && thrash=$((thrash + 1)) || thrash=0
    if [ "$(oom_events)" -gt "$oom0" ] || [ -n "$(containers_oomkilled)" ]; then reason="OOM-killer event"
    elif [ "$low" -ge 3 ]; then reason="MemAvailable ${avail}MB < ${RES_MIN_AVAIL_MB}MB for 3 samples"
    elif [ $((swap - swap0)) -gt "$RES_MAX_SWAP_GROWTH_MB" ]; then reason="swap grew by $((swap - swap0))MB"
    elif [ "$thrash" -ge 3 ]; then reason="swap-in ${pps} pages/s for 3 samples"
    fi
    if [ -n "$reason" ]; then
      echo "RESOURCE_ABORT $(date -u +%FT%TZ): $reason" | tee -a "$RESLOG" >&2
      res_snapshot "at abort"
      # bash runs the main script's trap only after its foreground command ends: stop the clone's Odoo
      # process here (under the run lock only this run uses the clone), which ends that command
      stop_clone_procs || true
      kill -USR1 "$main" 2>/dev/null
      return
    fi
  done
}
OWN_STEP=0   # 1 while an Odoo process started by this invocation may still run on the clone
on_exit() {
  local rc=$?
  trap - EXIT INT TERM HUP USR1
  # `wait` on the killed watchdog returns 143; under set -e that would end this handler right here (rc lost,
  # no snapshot, own clone processes never stopped) - so the handler must not fail on it
  [ -z "$MON_PID" ] || { kill "$MON_PID" 2>/dev/null || true; wait "$MON_PID" 2>/dev/null || true
                         res_snapshot "after $MODE (rc=$rc)" || true; }
  # only a step THIS invocation launched is stopped (a refused invocation never touches another run's processes)
  if [ "$rc" -ne 0 ] && [ "$OWN_STEP" = 1 ]; then stop_clone_procs || true; fi
  exit "$rc"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
trap 'echo "STOPPED by the resource watchdog - see $RESLOG" >&2; exit 13' USR1

capacity() {
  local size free need
  size=$(psql_admin -d postgres -tAc "select pg_database_size('${SRC_DB}')")
  free=$(df -B1 --output=avail / | tail -1)
  need=$(( size * 2 + 300 * 1024 * 1024 ))            # restored DB + indexes slack + filestore copy
  echo "db=${size} free=${free} need=${need}"
  [ $(( (free - need) / 1048576 )) -ge 1500 ] || { echo "BLOCKED_DISK_CAPACITY"; exit 3; }
}
drop_clone() {  # clone only: in-container processes on it, database, its filestore copy
  [[ "$CLONE" =~ $CLONE_RE ]] || refuse "drop $CLONE"
  stop_clone_procs
  psql_admin -d postgres -c "DROP DATABASE IF EXISTS \"${CLONE}\" WITH (FORCE)" || true
  filestore_delete
  worktree_delete
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
  [ -z "$(ls -A "$EVID" 2>/dev/null | grep -v '^resources.log$\|^code_commit.txt$\|^deps_modules.txt$\|^logs$')" ] \
    && [ -z "$(ls -A "$LOGDIR" 2>/dev/null)" ] \
    || { echo "refusing: evidence directory $EVID already has files"; exit 2; }
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
  container_setup
  OWN_STEP=1
  iso_run neutralize "$IMAGE_ID" odoo neutralize -c /etc/odoo/odoo.conf --addons-path "$APATH" -d "$CLONE" \
    || fail_clone "odoo neutralize"
  wait_quiet neutralize; OWN_STEP=0
  neutral=$(psql_admin -d "$CLONE" -tAc "select value from ir_config_parameter where key = 'database.is_neutralized'") \
    || fail_clone "neutralization check"
  [ "$(echo "$neutral" | tr -d '[:space:]')" = "true" ] || fail_clone "database.is_neutralized is '${neutral}'"
  mkdir -p "$EVID"
  echo "CLONE_READY ${CLONE} owner=${owner} neutralized=true"
}
new_outdir() { OUTDIR=$(mktemp -d "$LOGDIR/.render-out.XXXXXX"); chmod 0777 "$OUTDIR"; }
collect_out() {  # OUTDIR (written by the clone container) -> EVID, then the guarded delete of OUTDIR
  local r
  r=$(guard_evid)
  find "$OUTDIR" -maxdepth 1 -type f -exec cp -t "$r" {} +
  outdir_delete
}
render() {  # $1 = pre|post ; acceptance + PDFs through the render server, everything it writes is rolled back
  local out rc
  : "${1:?step name is empty}"
  assert_exclusive "render $1"
  container_setup
  evid_delete "$1"                                         # never mix files of an earlier or interrupted run
  new_outdir
  OWN_STEP=1
  render_server_start
  set +e; out=$(render_shell quotation_lines_acceptance.py -e PHASE="$1" 2>&1); rc=$?; set -e
  render_server_stop
  echo "$out" > "$LOGDIR/qlines-$1-${TS}.log"
  wait_quiet "render $1"; OWN_STEP=0
  collect_out
  echo "$out" | grep '^QLINES_' || true
  echo "$out" | grep -q '^QLINES_[A-Z]* {"all_ok": true' && [ "$rc" -eq 0 ] \
    || { echo "RENDER_$1 FAILED (rc=$rc, log $LOGDIR/qlines-$1-${TS}.log, summary $EVID/$1_summary.json)"; exit 8; }
  echo "RENDER_$1 OK"
}
rehearsal() {  # supply-only rehearsal (2026-10-06): COMMITS on the clone - v3 released, SI-26/2546 itself at 10 % (way A, owner decision 2026-10-08)
  local out rc f
  assert_exclusive rehearsal
  container_setup
  evid_delete rehearsal
  new_outdir
  OWN_STEP=1
  render_server_start
  set +e; out=$(render_shell roof_v3_rehearsal.py 2>&1); rc=$?; set -e
  render_server_stop
  echo "$out" > "$LOGDIR/qlines-rehearsal-${TS}.log"
  wait_quiet rehearsal; OWN_STEP=0
  collect_out
  for f in "$EVID"/rehearsal_*.pdf; do
    [ -e "$f" ] || continue
    pdftotext -layout "$f" "${f%.pdf}.txt"; pdftoppm -r 60 -png "$f" "${f%.pdf}"
    echo "$(basename "$f") pages=$(pdfinfo "$f" | awk '/^Pages/{print $2}')"
  done
  echo "$out" | grep '^QLINES_REHEARSAL' || true
  echo "$out" | grep -q '^QLINES_REHEARSAL {"all_ok": true' && [ "$rc" -eq 0 ] \
    || { echo "REHEARSAL FAILED (rc=$rc, log $LOGDIR/qlines-rehearsal-${TS}.log, summary $EVID/rehearsal_summary.json)"; exit 14; }
  echo "REHEARSAL OK"
}
proof() {  # which code produced the evidence (commit, image, installed module versions, PDF content markers)
  container_setup
  python3 - "$EVID" "$WT" "$IMAGE_ID" "$(docker inspect -f '{{.Image}}' "$APPC")" \
      "$(psql_admin -d "$CLONE" -tAc "select coalesce(json_object_agg(name, json_build_array(state, latest_version) order by name), '{}')
                                       from ir_module_module where name like 'sipanel%'")" <<'PY'
import ast, json, os, subprocess, sys
evid, wt, image, prod_image, installed = sys.argv[1:6]
git = lambda *a: subprocess.run(['git', '-C', wt, *a], capture_output=True, text=True, check=True).stdout.strip()
manifests = {m: ast.literal_eval(open(os.path.join(wt, 'addons', m, '__manifest__.py')).read()).get('version')
             for m in sorted(os.listdir(os.path.join(wt, 'addons'))) if os.path.isfile(os.path.join(wt, 'addons', m, '__manifest__.py'))}
installed = json.loads(installed)
data = {'commit': git('rev-parse', 'HEAD'), 'worktree': wt, 'worktree_clean': git('status', '--porcelain') == '',
        'image_id': image, 'production_image_id': prod_image, 'same_image': image == prod_image,
        'branch_manifest_versions': manifests, 'installed_sipanel_modules': installed,
        'branch_modules_installed_at_branch_version': {m: installed.get(m, [None, None])[1] == v
                                                      for m, v in manifests.items() if m in installed},
        'non_branch_modules': open(os.path.join(evid, 'deps_modules.txt')).read().split('\n')[:-1]}
json.dump(data, open(os.path.join(evid, 'code_version.json'), 'w'), indent=1)
print(json.dumps({k: data[k] for k in ('commit', 'worktree_clean', 'same_image', 'branch_modules_installed_at_branch_version')}))
PY
  python3 "$WT/scripts/qlines_code_markers.py" "$EVID" | tee "$EVID/code_markers.txt"
  grep -q '^MARKERS PASS' "$EVID/code_markers.txt" || { echo "PROOF FAILED (see code_markers.txt)"; exit 16; }
  echo "PROOF OK"
}
install() {
  local log=$LOGDIR/qlines-install-${TS}.log rc
  assert_exclusive install
  container_setup
  OWN_STEP=1; set +e; odoo_clone -i "$MOD" > "$log" 2>&1; rc=$?; set -e
  [ "$rc" -ne 137 ] || echo "CLONE_OOM: the clone container hit its memory limit ($CLONE_MEM + swap $CLONE_MEMSWAP)" 
  wait_quiet install; OWN_STEP=0
  grep -E "ERROR|CRITICAL|Traceback|sipanel_quotation_lines:" "$log" || true
  [ "$rc" -eq 0 ] && ! grep -qE " (ERROR|CRITICAL) " "$log" || { echo "INSTALL FAILED (rc=$rc, log $log)"; exit 9; }
  echo "INSTALL OK"
}
run_tests() {
  local log=$LOGDIR/qlines-test-${TS}.log rc ran fails errs known other complete
  assert_exclusive test
  container_setup
  OWN_STEP=1; set +e; odoo_clone -u "$MOD,$SIPANEL_MODS" --test-enable --test-tags sipanel > "$log" 2>&1; rc=$?; set -e
  [ "$rc" -ne 137 ] || echo "CLONE_OOM: the clone container hit its memory limit ($CLONE_MEM + swap $CLONE_MEMSWAP)" 
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
  local d=$WT/scripts/qlines_pdf_diff.py en fa f lang words
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
if [[ "$MODE" =~ ^(all|clone|pre|install|test|post|rehearsal|proof)$ ]]; then
  res_snapshot "before $MODE"
  res_monitor $$ &
  MON_PID=$!
fi
case "$MODE" in
  clone)    clone ;;
  pre)      render pre ;;
  install)  install ;;
  test)     run_tests ;;
  post)     render post ;;
  evidence) evidence ;;
  rehearsal) rehearsal ;;
  proof)    proof ;;
  all)      clone; render pre; install; run_tests; render post; (evidence); rehearsal; proof ;;
  drop)     # DESTRUCTIVE, clone only; the clone must be named explicitly
            [ -n "$CLONE_GIVEN" ] || { echo "set CLONE=sipanel_qlines_clone_..."; exit 2; }
            drop_clone ;;
  *) echo "unknown mode"; exit 2 ;;
esac
