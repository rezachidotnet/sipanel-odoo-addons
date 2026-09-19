#!/usr/bin/env bash
# SIPANEL pre-implementation recovery point (MANDATORY before the first DB/config/module write).
# Scope: database `sipanel` + filestore + custom addons + container config refs + installed module list + checksums.
# Never touches other tenants. Stores OUTSIDE the git repository. Requires sudo (filestore/config are root-only).
set -euo pipefail
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
echo "Restore: docker exec -i $PGC psql -U odoo -d postgres -c \"CREATE DATABASE ${DB}_restore\" && docker exec -i $PGC pg_restore -U odoo -d ${DB}_restore < $DEST/${DB}.dump ; sudo tar -C /opt/odoo/data/filestore -xzf $DEST/filestore-${DB}.tar.gz"
