#!/usr/bin/env bash
# Quotation Page 1 Project Information (work order 2026-10-04) — CLONE validation.
# Production DB `sipanel` is only READ (pg_dump streamed into the clone). Nothing is installed on `sipanel`.
# Usage: scripts/sipanel_page1_clone_validate.sh all|clone|pre|install|test|post|evidence|drop
#   CLONE=<db name>   reuse/choose the clone (default sipanel_page1_clone_<UTC timestamp>, printed on start)
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
[ "$CLONE" != "$SRC_DB" ] || { echo "refusing: clone name equals production"; exit 2; }

capacity() {
  local size free need
  size=$(docker exec "$PGC" psql -U odoo -d postgres -tAc "select pg_database_size('${SRC_DB}')")
  free=$(df -B1 --output=avail / | tail -1)
  need=$(( size * 2 + 300 * 1024 * 1024 ))            # restored DB + indexes slack + filestore copy
  echo "db=${size} free=${free} need=${need}"
  [ $(( (free - need) / 1048576 )) -ge 1500 ] || { echo "BLOCKED_DISK_CAPACITY"; exit 3; }
}
clone() {
  capacity
  docker exec "$PGC" psql -U odoo -d postgres -tAc "select 1 from pg_database where datname='${CLONE}'" | grep -q 1 && { echo "clone exists"; exit 1; }
  docker exec "$PGC" psql -U odoo -d postgres -c "CREATE DATABASE \"${CLONE}\" OWNER odoo"
  docker exec "$PGC" sh -c "pg_dump -U odoo -Fc '${SRC_DB}' | pg_restore -U odoo -d '${CLONE}' --no-owner --role=odoo"
  sudo cp -a "/opt/odoo/data/filestore/${SRC_DB}" "/opt/odoo/data/filestore/${CLONE}"
  docker exec "$APPC" odoo neutralize -c /etc/odoo/odoo.conf -d "$CLONE"      # no mail, no crons, no payment providers
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
            [ -n "$CLONE_GIVEN" ] && [[ "$CLONE" == sipanel_page1_clone_* ]] || { echo "set CLONE=sipanel_page1_clone_..."; exit 2; }
            docker exec "$PGC" psql -U odoo -d postgres -c "DROP DATABASE \"${CLONE}\""
            sudo rm -rf "/opt/odoo/data/filestore/${CLONE:?}" ;;
  *) echo "unknown mode"; exit 2 ;;
esac
