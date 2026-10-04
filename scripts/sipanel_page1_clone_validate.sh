#!/usr/bin/env bash
# Quotation Page 1 Project Information (work order 2026-10-04) — CLONE validation.
# Production DB `sipanel` is only READ (pg_dump streamed into the clone). Nothing is installed on `sipanel`.
# Usage: scripts/sipanel_page1_clone_validate.sh all|clone|pre|install|test|post|evidence|drop
#   CLONE=<db name>   reuse/choose the clone (default sipanel_page1_clone_<UTC timestamp>, printed on start)
#   PG_ADMIN=<role>   postgres maintenance role in odoo-db for CREATE/DROP DATABASE and pg_dump (default postgres)
# Clone ownership = Odoo's db_user from /etc/odoo/odoo.conf; a clone that fails restore, ownership check or
# neutralization is dropped immediately (fail closed).
# The module directory is copied into /opt/odoo/addons (inert until installed; it is not auto_install).
set -euo pipefail
MODE=${1:-all}
REPO=/home/ubuntu/sipanel_odoo_addons
MOD=sipanel_quotation_project_info
SIPANEL_MODS=sipanel_commercial_scope_core,sipanel_sale_scope,sipanel_scope_execution,sipanel_scope_costing
APPC=odoo-sipanel; PGC=odoo-db; SRC_DB=sipanel
TS=$(date -u +%Y%m%dT%H%M%SZ)
CLONE_GIVEN=${CLONE:-}
CLONE=${CLONE:-sipanel_page1_clone_${TS}}
EVID=${EVID:-/home/ubuntu/sipanel_audit/docs/audits/data/page1_project_info_clone_${TS}}
export CLONE EVID                                          # sub-invocations of "all" reuse the same clone
LOGDIR=${LOGDIR:-$REPO/reports}
ODOO=(docker exec "$APPC" odoo -c /etc/odoo/odoo.conf -d "$CLONE" --no-http --stop-after-init)
echo "clone database: $CLONE"
[[ "$CLONE" == sipanel_page1_clone_* ]] || { echo "refusing: clone name must start with sipanel_page1_clone_"; exit 2; }

# PG_ADMIN: maintenance role used only for CREATE/DROP DATABASE and the read-only pg_dump of production.
PG_ADMIN=${PG_ADMIN:-postgres}
# Odoo's own role, read from the running container's config (never hard-coded); every clone object must belong to it.
db_user() {
  local u
  u=$(docker exec "$APPC" sh -c "sed -n 's/^[[:space:]]*db_user[[:space:]]*=[[:space:]]*//p' /etc/odoo/odoo.conf" | tail -1 | tr -d '[:space:]')
  [[ "$u" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || { echo "cannot read a valid db_user from /etc/odoo/odoo.conf in $APPC" >&2; exit 2; }
  echo "$u"
}
psql_admin() { docker exec -i "$PGC" psql -U "$PG_ADMIN" -v ON_ERROR_STOP=1 "$@"; }
capacity() {
  local size free need
  size=$(psql_admin -d postgres -tAc "select pg_database_size('${SRC_DB}')")
  free=$(df -B1 --output=avail / | tail -1)
  need=$(( size * 2 + 300 * 1024 * 1024 ))            # restored DB + indexes slack + filestore copy
  echo "db=${size} free=${free} need=${need}"
  [ $(( (free - need) / 1048576 )) -ge 1500 ] || { echo "BLOCKED_DISK_CAPACITY"; exit 3; }
}
drop_clone() {  # clone only: database + its filestore copy
  [[ "$CLONE" == sipanel_page1_clone_* ]] || { echo "refusing to drop $CLONE"; exit 2; }
  psql_admin -d postgres -c "DROP DATABASE IF EXISTS \"${CLONE}\" WITH (FORCE)" || true
  sudo rm -rf "/opt/odoo/data/filestore/${CLONE:?}"
}
fail_clone() { echo "CLONE_FAILED: $1 -> dropping clone ${CLONE}" >&2; drop_clone; exit "${2:-4}"; }
clone() {
  local owner bad neutral
  owner=$(db_user)
  echo "clone owner (db_user from odoo.conf): ${owner}"
  capacity
  psql_admin -d postgres -tAc "select 1 from pg_database where datname='${CLONE}'" | grep -q 1 && { echo "clone exists"; exit 1; }
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
  docker exec "$APPC" odoo neutralize -c /etc/odoo/odoo.conf -d "$CLONE" || fail_clone "odoo neutralize"
  neutral=$(psql_admin -d "$CLONE" -tAc "select value from ir_config_parameter where key = 'database.is_neutralized'") \
    || fail_clone "neutralization check"
  [ "$(echo "$neutral" | tr -d '[:space:]')" = "true" ] || fail_clone "database.is_neutralized is '${neutral}'"
  echo "CLONE_READY ${CLONE} owner=${owner} neutralized=true"
}
deploy_dir() {
  sudo rsync -a --delete "$REPO/addons/$MOD/" "/opt/odoo/addons/$MOD/"
  sudo chown -R --reference=/opt/odoo/addons/sale_shamsi_report "/opt/odoo/addons/$MOD"
}
render() {  # $1 = pre|post
  docker exec "$APPC" rm -rf /tmp/page1 && docker exec -i -e PHASE="$1" -e OUT=/tmp/page1 "$APPC" \
    odoo shell -c /etc/odoo/odoo.conf -d "$CLONE" --no-http < "$REPO/scripts/page1_render_check.py" | tail -1
  mkdir -p "$EVID" && docker cp "$APPC:/tmp/page1/." "$EVID/"
}
case "$MODE" in
  clone)    clone ;;
  pre)      render pre ;;
  install)  deploy_dir; "${ODOO[@]}" -i "$MOD" 2>&1 | tee "$LOGDIR/page1-install-${TS}.log" | grep -E "ERROR|CRITICAL|Traceback" || true ;;
  test)     deploy_dir; "${ODOO[@]}" -u "$MOD,$SIPANEL_MODS" --test-enable --test-tags sipanel 2>&1 | tee "$LOGDIR/page1-test-${TS}.log" \
              | grep -E "ERROR|FAIL|tests? .*(ran|passed)|failed, .* error" || true ;;
  post)     render post ;;
  evidence) cd "$EVID" && for f in *.pdf; do pdftotext -layout "$f" "${f%.pdf}.txt"; pdftoppm -r 60 -png -f 1 -l 2 "$f" "${f%.pdf}"; done
            diff <(pdftotext -f 2 -l 99 -layout pre_SI-26-2546_partner_lang.pdf -) <(pdftotext -f 2 -l 99 -layout post_SI-26-2546_partner_lang.pdf -) \
              && echo "PAGE2+_UNCHANGED" || echo "PAGE2+_CHANGED (inspect)" ;;
  all)      clone; render pre; "$0" install; "$0" test; render post; "$0" evidence ;;
  drop)     # DESTRUCTIVE, clone only; the clone must be named explicitly
            [ -n "$CLONE_GIVEN" ] || { echo "set CLONE=sipanel_page1_clone_..."; exit 2; }
            drop_clone ;;
  *) echo "unknown mode"; exit 2 ;;
esac
