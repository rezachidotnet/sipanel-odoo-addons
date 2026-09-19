#!/usr/bin/env bash
# Install / upgrade the SIPANEL modules on database `sipanel` (container odoo-sipanel only) and run the tagged tests.
# Usage: scripts/sipanel_install_and_test.sh install|upgrade|test|smoke
set -euo pipefail
MODE=${1:-test}
APPC=odoo-sipanel
REPO=/home/ubuntu/sipanel_odoo_addons
MODS=sipanel_commercial_scope_core,sipanel_sale_scope,sipanel_scope_execution,sipanel_scope_costing
LOG=${LOG:-$REPO/reports/odoo-${MODE}-$(date -u +%Y%m%dT%H%M%SZ).log}
# Production addons path is /opt/odoo/addons (bind-mounted at /mnt/extra-addons). Deploy by copy (never symlink into the repo).
deploy() {
  for m in ${MODS//,/ }; do sudo rsync -a --delete "$REPO/addons/$m/" "/opt/odoo/addons/$m/"; done
  sudo chown -R --reference=/opt/odoo/addons/sale_shamsi_report /opt/odoo/addons/sipanel_*
}
case "$MODE" in
  install) deploy; docker exec "$APPC" odoo -c /etc/odoo/odoo.conf -d sipanel --no-http --stop-after-init -i "$MODS" 2>&1 | tee "$LOG" ;;
  upgrade) deploy; docker exec "$APPC" odoo -c /etc/odoo/odoo.conf -d sipanel --no-http --stop-after-init -u sipanel_commercial_scope_core 2>&1 | tee "$LOG" ;;
  test)    deploy; sudo rsync -a --delete "$REPO/test_addons/sipanel_scope_demo/" /opt/odoo/addons/sipanel_scope_demo/
           docker exec "$APPC" odoo -c /etc/odoo/odoo.conf -d sipanel --no-http --stop-after-init -u "$MODS" --test-enable --test-tags /sipanel 2>&1 | tee "$LOG" ;;
  smoke)   docker exec "$APPC" odoo -c /etc/odoo/odoo.conf -d sipanel --no-http --stop-after-init --test-enable --test-tags /sipanel_pilot -i sipanel_scope_demo 2>&1 | tee "$LOG" ;;
  *) echo "unknown mode"; exit 2 ;;
esac
grep -E "ERROR|FAIL|CRITICAL" "$LOG" | grep -v "0 failed" | head -50 || true
grep -E "tests? (ran|passed)|failed, .* error" "$LOG" | tail -5 || true
echo "log: $LOG"
