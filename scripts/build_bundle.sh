#!/usr/bin/env bash
# Build the implementation bundle for a report run directory: SHA256SUMS, release + bundle manifests, ZIP + .sha256.
set -euo pipefail
REPO=/home/ubuntu/sipanel_odoo_addons
RUN=${1:?run dir name under reports/}
R=$REPO/reports/$RUN
cd $REPO
COMMIT=$(git rev-parse HEAD 2>/dev/null || echo NONE)
{
echo "SIPANEL Commercial Scope / Recipe / Estimation — RELEASE MANIFEST"
echo "Run: $RUN"
echo "Generated (UTC): $(date -u +%FT%TZ)"
echo "Verdict: BLOCKED_BEFORE_DATABASE_WRITE"
echo "Bundle: SIPANEL_PRODUCTION_IMPLEMENTATION_BUNDLE.zip (source + tests + docs; NOT a tested release candidate)"
echo
echo "Target platform (verified read-only from image 1cd111414896): Odoo 19.0-20260528 Community, Python 3.12.3, PostgreSQL 15.18"
echo "Target database: sipanel (NOT modified)  container: odoo-sipanel (NOT restarted)  addons path: /opt/odoo/addons (NOT modified)"
echo
echo "Modules (WRITTEN, STATICALLY CHECKED, NOT INSTALLED, NOT TESTED):"
for m in addons/sipanel_commercial_scope_core addons/sipanel_sale_scope addons/sipanel_scope_execution addons/sipanel_scope_costing test_addons/sipanel_scope_demo; do
  v=$(python3 -c "import ast;print(ast.literal_eval(open('$m/__manifest__.py').read())['version'])")
  h=$(find $m -type f ! -name '*.pyc' ! -path '*__pycache__*' -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-64)
  printf "  %-32s %-12s tree-sha256: %s  files: %s  lines: %s\n" "$(basename $m)" "$v" "$h" "$(find $m -type f ! -path '*__pycache__*' | wc -l)" "$(find $m -type f \( -name '*.py' -o -name '*.xml' -o -name '*.csv' -o -name '*.js' \) ! -path '*__pycache__*' -print0 | xargs -0 cat | wc -l)"
done
echo
echo "Repository: $REPO  branch: $(git rev-parse --abbrev-ref HEAD)  source commit: $COMMIT"
echo
echo "Applied decision profile (management authorization 2026-09-19): BQ-01=B, BQ-02=B joint, BQ-03=A, BQ-04 one terminal event per route, BQ-05=A, BQ-06=A+UNALLOCATED, BQ-07=A, BQ-08=B, BQ-09=A;"
echo "  AM-01-R2, AM-02, AM-03-R1, AM-04 APPROVED; AM-05 DEFERRED. FROZEN decisions altered: NONE. IF-01, IF-02, IF-03 applied."
echo
echo "Test totals: PASS 0 / FAIL 0 / BLOCKED 31 / NOT_RUN 1 (PT-30) / NOT_APPLICABLE 0. Automated test methods written: $(grep -rh '    def test_' addons/*/tests test_addons/*/tests | wc -l)."
echo "Recovery point: NOT CREATED (harness denial, EV-02). Installed modules changed: NONE. Configuration changes: NONE. Test records created in sipanel: 0."
echo "odoo-sipanel restarted: NO. Other databases / tenant containers modified: NO."
echo
echo "PRODUCTION_DEPLOYMENT_REQUIRES_SEPARATE_EXPLICIT_AUTHORIZATION"
} > $R/SIPANEL_RELEASE_MANIFEST.txt
# bundle manifest (list of report files)
{
echo "REPORT BUNDLE MANIFEST — $RUN — generated $(date -u +%FT%TZ)"
echo "Source commit: $COMMIT"
echo
for f in $(cd $R && ls -1 *.md *.txt evidence/* 2>/dev/null | grep -v REPORT_BUNDLE_MANIFEST.txt | grep -v SHA256SUMS); do printf "%-70s %8s bytes\n" "$f" "$(stat -c %s $R/$f)"; done
echo
echo "Excluded from ZIP: secrets, private keys, database dumps, filestore, personal data (none present)."
} > $R/REPORT_BUNDLE_MANIFEST.txt
# zip: source + tests + docs + reports
ZIP=$R/SIPANEL_PRODUCTION_IMPLEMENTATION_BUNDLE.zip
rm -f "$ZIP" "$ZIP.sha256" $R/SHA256SUMS
STAGE=$(mktemp -d)
mkdir -p $STAGE/bundle/reports/$RUN
rsync -a --exclude '__pycache__' --exclude '*.pyc' addons test_addons scripts .gitignore $STAGE/bundle/
rsync -a --exclude 'SIPANEL_PRODUCTION_IMPLEMENTATION_BUNDLE.zip*' --exclude SHA256SUMS $R/ $STAGE/bundle/reports/$RUN/
cp -r reports/sipanel_scope_implementation_rc_20260919T140237Z $STAGE/bundle/reports/
(cd $STAGE/bundle && find . -type f -print0 | sort -z | xargs -0 sha256sum > $R/SHA256SUMS)
cp $R/SHA256SUMS $STAGE/bundle/reports/$RUN/SHA256SUMS
# refuse if any secret-looking content slipped in
if grep -rIlE 'BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|db_password\s*=\s*[^<]|admin_passwd\s*=\s*[^<]' $STAGE/bundle >/dev/null; then echo "SECRET DETECTED, abort" >&2; exit 4; fi
(cd $STAGE/bundle && python3 - "$ZIP" <<'PYZ'
import os, sys, zipfile
zp=sys.argv[1]
with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk('.'):
        dirs.sort()
        for f in sorted(files):
            p=os.path.join(root, f); z.write(p, os.path.relpath(p, '.'))
PYZ
)
rm -rf $STAGE
(cd $R && sha256sum SIPANEL_PRODUCTION_IMPLEMENTATION_BUNDLE.zip > SIPANEL_PRODUCTION_IMPLEMENTATION_BUNDLE.zip.sha256)
echo "ZIP: $ZIP"; cat $R/SIPANEL_PRODUCTION_IMPLEMENTATION_BUNDLE.zip.sha256; ls -la $R
