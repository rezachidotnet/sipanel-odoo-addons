#!/usr/bin/env bash
# SIPANEL pre-implementation recovery point (MANDATORY before the first DB/config/module write).
# Scope: database `sipanel` + filestore + custom addons + container config refs + installed module list + checksums.
# Never touches other tenants. Stores OUTSIDE the git repository. Requires sudo (filestore/config are root-only).
set -euo pipefail

# ---------------------------------------------------------------------------------------------
# Safe restore REHEARSAL procedure (printed, never executed by this script).
# Rules: unique rehearsal database + filestore names; dump restored only into the rehearsal
# database; archive layout inspected before extraction; extraction into a temporary directory;
# installation only as /opt/odoo/data/filestore/<rehearsal name>; the live filestore
# /opt/odoo/data/filestore/sipanel is never a target; integrations neutralised before any Odoo
# process opens the rehearsal database; cleanup commands validate their exact resolved target.
# Usage of this mode alone:  scripts/sipanel_recovery_point.sh restore-instructions <point-dir>
# ---------------------------------------------------------------------------------------------
print_restore_instructions() {
  local point="$1"
  cat <<EOF_RESTORE

== RESTORE REHEARSAL PROCEDURE for $point (not executed) ==
# 0. Fix and validate the targets ONCE; every later command uses these exact values
TS=\$(date -u +%Y%m%dT%H%M%SZ)
POINT=\$(sudo realpath -e "$point")
RDB="sipanel_restore_rehearsal_\${TS}"
RFS="/opt/odoo/data/filestore/\${RDB}"
[ "\$RDB" != "sipanel" ] && [ "\$RFS" != "/opt/odoo/data/filestore/sipanel" ] || { echo REFUSED; exit 1; }
(cd "\$POINT" && sudo sha256sum -c SHA256SUMS)                       # every artefact must print OK

# 1. Database: restore ONLY into the rehearsal database (never into sipanel)
docker exec -i odoo-db psql -U odoo -d postgres -tAc "select 1 from pg_database where datname='\${RDB}'" | grep -q 1 && { echo "exists"; exit 1; }
docker exec -i odoo-db psql -U odoo -d postgres -c "CREATE DATABASE \\"\${RDB}\\" OWNER odoo"
docker exec -i odoo-db pg_restore -U odoo -d "\${RDB}" --no-owner --role=odoo < "\$POINT/sipanel.dump"
docker exec -i odoo-db psql -U odoo -d "\${RDB}" -tAc "select count(*) from ir_module_module where state='installed'"

# 2. Filestore: inspect the archive layout BEFORE extracting anything (expect exactly one top-level dir: sipanel)
sudo tar -tzf "\$POINT/filestore-sipanel.tar.gz" | awk -F/ '{print \$1}' | sort -u

# 3. Extract into a temporary directory first - NEVER with -C /opt/odoo/data/filestore
TMP=\$(sudo mktemp -d "/opt/odoo/restore_rehearsal_\${TS}.XXXX")
sudo tar -C "\$TMP" -xzf "\$POINT/filestore-sipanel.tar.gz"
sudo test -d "\$TMP/sipanel" || { echo "unexpected layout"; exit 1; }

# 4. Install ONLY under the rehearsal name, with the live owner and permissions
OWNER=\$(sudo stat -c '%u:%g' /opt/odoo/data/filestore/sipanel)
sudo test ! -e "\$RFS" || { echo "target exists"; exit 1; }
sudo mv "\$TMP/sipanel" "\$RFS" && sudo chown -R "\$OWNER" "\$RFS" && sudo chmod -R u+rwX,go-rwx "\$RFS" && sudo rmdir "\$TMP"

# 5. Neutralise integrations BEFORE any Odoo process opens the rehearsal database.
#    Every optional table is detected with to_regclass() first, so an absent module never fails the block;
#    all statements run inside ONE transaction against the REHEARSAL database only (\${RDB}, never sipanel).
docker exec -i odoo-db psql -U odoo -d "\${RDB}" -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
DO \$\$
BEGIN
  -- outgoing mail and scheduled jobs (always present)
  UPDATE ir_mail_server SET active = false;
  UPDATE ir_cron SET active = false;
  UPDATE ir_config_parameter SET value = 'http://127.0.0.1:8072' WHERE key = 'report.url';
  UPDATE ir_config_parameter SET value = 'http://localhost' WHERE key = 'web.base.url';
  DELETE FROM ir_config_parameter WHERE key = 'web.base.url.freeze';
  -- incoming mail (fetchmail module)
  IF to_regclass('public.fetchmail_server') IS NOT NULL THEN
    UPDATE fetchmail_server SET active = false;
  END IF;
  -- payment providers (Odoo 16+) / acquirers (older)
  IF to_regclass('public.payment_provider') IS NOT NULL THEN
    UPDATE payment_provider SET state = 'disabled' WHERE state <> 'disabled';
  END IF;
  IF to_regclass('public.payment_acquirer') IS NOT NULL THEN
    UPDATE payment_acquirer SET state = 'disabled' WHERE state <> 'disabled';
  END IF;
  -- automation rules and outgoing webhook server actions (Odoo 17+: ir.actions.server state 'webhook')
  IF to_regclass('public.base_automation') IS NOT NULL THEN
    UPDATE base_automation SET active = false;
  END IF;
  IF to_regclass('public.ir_act_server') IS NOT NULL AND EXISTS (
       SELECT 1 FROM information_schema.columns WHERE table_name = 'ir_act_server' AND column_name = 'webhook_url') THEN
    UPDATE ir_act_server SET webhook_url = NULL WHERE state = 'webhook';
  END IF;
  -- IAP services (SMS, partner autocomplete, OCR ...): remove the account tokens so no paid call can leave
  IF to_regclass('public.iap_account') IS NOT NULL AND EXISTS (
       SELECT 1 FROM information_schema.columns WHERE table_name = 'iap_account' AND column_name = 'account_token') THEN
    UPDATE iap_account SET account_token = NULL;
  END IF;
  -- incoming aliases must not route into the rehearsal
  IF to_regclass('public.mail_alias') IS NOT NULL THEN
    UPDATE mail_alias SET alias_name = NULL WHERE alias_name IS NOT NULL;
  END IF;
END
\$\$;
COMMIT;
SQL
# verify (read-only) that nothing outgoing is left enabled in the rehearsal database
docker exec -i odoo-db psql -U odoo -d "\${RDB}" -tAc "select 'mail_servers_active='||count(*) from ir_mail_server where active; select 'crons_active='||count(*) from ir_cron where active;"

# 6. Optional: a THROW-AWAY process against the rehearsal DB only (never the production service, --no-http)
#    docker run --rm --network container:odoo-db -v /opt/odoo/addons:/mnt/extra-addons:ro -v /opt/odoo/data:/var/lib/odoo <odoo-sipanel image> \\
#      odoo -d "\${RDB}" --db_host=db --db_user=odoo --db_password=<from config> --no-http --stop-after-init --list-db=false

# 7. Cleanup - DESTRUCTIVE, exact rehearsal targets only, each validated first
[ "\$RDB" != "sipanel" ] && [ -n "\$TS" ] || exit 1
docker exec -i odoo-db psql -U odoo -d postgres -c "DROP DATABASE \\"\${RDB}\\""                         # DESTRUCTIVE: rehearsal DB only
[ "\$(sudo realpath -e "\$RFS")" = "/opt/odoo/data/filestore/\${RDB}" ] || exit 1
sudo rm -rf --one-file-system -- "/opt/odoo/data/filestore/\${RDB}"                                       # DESTRUCTIVE: rehearsal filestore only
== END OF RESTORE REHEARSAL PROCEDURE ==
EOF_RESTORE
}
if [ "${1:-}" = "restore-instructions" ]; then
  P=${2:?recovery point directory required}
  [ -d "$P" ] || sudo test -d "$P" || { echo "not a directory: $P" >&2; exit 2; }
  print_restore_instructions "$(sudo realpath -e "$P")"
  exit 0
fi
TS=$(date -u +%Y%m%dT%H%M%SZ)
DEST=${DEST:-/opt/odoo/backups/sipanel-pre-scope-${TS}}
DB=sipanel
PGC=odoo-db
APPC=odoo-sipanel
MIN_FREE_MB=${MIN_FREE_MB:-1500}

echo "== 1. identity"
docker inspect "$APPC" --format 'container={{.Name}} image={{.Image}} status={{.State.Status}}'
DBSIZE=$(docker exec "$PGC" psql -U odoo -d postgres -tAc "select pg_database_size('${DB}')")
FSSIZE=$(sudo du -sb /opt/odoo/data/filestore/${DB} | cut -f1)
ADSIZE=$(du -sb /opt/odoo/addons | cut -f1)
NEED=$(( (DBSIZE + FSSIZE + ADSIZE) / 1024 / 1024 ))
FREE=$(df -Pm /opt | awk 'NR==2{print $4}')
echo "db_bytes=$DBSIZE filestore_bytes=$FSSIZE addons_bytes=$ADSIZE need_mb~=$NEED free_mb=$FREE"
if [ $((FREE - NEED)) -lt "$MIN_FREE_MB" ]; then
  echo "BLOCKED_BACKUP_CAPACITY: need ~${NEED} MB plus ${MIN_FREE_MB} MB headroom, free ${FREE} MB" >&2
  exit 3
fi

echo "== 2. create $DEST"
sudo mkdir -p "$DEST"
docker exec "$PGC" pg_dump -U odoo -Fc "$DB" | sudo tee "$DEST/${DB}.dump" > /dev/null
sudo tar -C /opt/odoo/data/filestore -czf "$DEST/filestore-${DB}.tar.gz" "$DB"
sudo tar -C /opt/odoo -czf "$DEST/addons.tar.gz" addons
sudo cp /opt/odoo/odoo-${DB}.conf "$DEST/odoo-${DB}.conf.redacted" && sudo sed -i -E 's/(db_password|admin_passwd)\s*=.*/\1 = <redacted>/' "$DEST/odoo-${DB}.conf.redacted"
docker inspect "$APPC" | sudo tee "$DEST/container-inspect.json" > /dev/null
docker exec "$PGC" psql -U odoo -d "$DB" -tAc "select name||':'||coalesce(latest_version,'') from ir_module_module where state='installed' order by name" | sudo tee "$DEST/installed_modules.txt" > /dev/null
echo "$TS" | sudo tee "$DEST/TIMESTAMP" > /dev/null

echo "== 3. verify readability + checksums"
sudo pg_restore --list "$DEST/${DB}.dump" > /dev/null 2>&1 || docker run --rm -v "$DEST":/rp postgres:15 pg_restore --list /rp/${DB}.dump > /dev/null
sudo tar -tzf "$DEST/filestore-${DB}.tar.gz" > /dev/null
sudo tar -tzf "$DEST/addons.tar.gz" > /dev/null
(cd "$DEST" && sudo sha256sum ${DB}.dump filestore-${DB}.tar.gz addons.tar.gz installed_modules.txt container-inspect.json odoo-${DB}.conf.redacted | sudo tee SHA256SUMS)
sudo chmod -R go-rwx "$DEST"
echo "RECOVERY_POINT_OK $DEST"
print_restore_instructions "$DEST"
