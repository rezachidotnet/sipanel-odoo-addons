#!/usr/bin/env python3
"""Structural tests for the restore REHEARSAL procedure printed by scripts/sipanel_recovery_point.sh.
Non-destructive: runs `restore-instructions <point>` and checks the text. Usage:
    python3 scripts/test_restore_instructions.py [<recovery-point-dir>]
Exit 0 when every check passes; prints one PASS/FAIL line per check."""
import re
import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, 'sipanel_recovery_point.sh')


def generate(point):
    return subprocess.run(['bash', SCRIPT, 'restore-instructions', point], capture_output=True, text=True, check=True).stdout


def checks(out):
    live_fs = '/opt/odoo/data/filestore/sipanel'
    idx = out.index
    c = {}
    c['unique rehearsal database name'] = 'RDB="sipanel_restore_rehearsal_${TS}"' in out
    c['rehearsal filestore under the exact rehearsal name'] = 'RFS="/opt/odoo/data/filestore/${RDB}"' in out
    c['live database never a restore target'] = 'pg_restore -U odoo -d sipanel ' not in out and 'pg_restore -U odoo -d "${RDB}"' in out
    c['archive layout inspected before extraction'] = idx('tar -tzf') < idx('tar -C "$TMP" -xzf')
    c['extraction into a temporary directory'] = 'mktemp -d' in out and 'tar -C "$TMP" -xzf' in out
    c['never extracts onto the live filestore'] = 'tar -C /opt/odoo/data/filestore -xzf' not in out and f'-xzf' in out and f'mv "$TMP/sipanel" "$RFS"' in out
    c['live filestore path refused as target'] = f'[ "$RFS" != "{live_fs}" ]' in out
    c['optional tables detected before use (to_regclass)'] = out.count("to_regclass('public.") >= 6
    c['fetchmail disabled when installed'] = "to_regclass('public.fetchmail_server')" in out and 'UPDATE fetchmail_server SET active = false' in out
    c['payment providers/acquirers disabled when installed'] = "UPDATE payment_provider SET state = 'disabled'" in out and "UPDATE payment_acquirer SET state = 'disabled'" in out
    c['automation rules and outgoing webhooks disabled when installed'] = 'UPDATE base_automation SET active = false' in out and "UPDATE ir_act_server SET webhook_url = NULL WHERE state = 'webhook'" in out
    c['IAP tokens removed when installed'] = 'UPDATE iap_account SET account_token = NULL' in out
    c['outgoing mail servers and crons disabled'] = 'UPDATE ir_mail_server SET active = false' in out and 'UPDATE ir_cron SET active = false' in out
    c['neutralisation is one transaction with ON_ERROR_STOP'] = '-v ON_ERROR_STOP=1' in out and out.count('BEGIN;') >= 1 and 'COMMIT;' in out
    c['neutralisation before any Odoo process'] = idx('UPDATE ir_mail_server SET active = false') < idx('THROW-AWAY process')
    c['neutralisation targets the rehearsal database only'] = 'psql -U odoo -d "${RDB}"' in out and not re.search(r'psql -U odoo -d sipanel\b', out)
    c['cleanup commands present and marked DESTRUCTIVE'] = out.count('DESTRUCTIVE') >= 2 and re.search(r'DROP DATABASE \\?"\$\{RDB\}\\?"', out) is not None and 'rm -rf --one-file-system -- "/opt/odoo/data/filestore/${RDB}"' in out
    c['destructive targets validated first'] = '[ "$RDB" != "sipanel" ]' in out and 'realpath -e "$RFS"' in out
    c['no broad glob in destructive commands'] = not re.search(r'(rm -rf|DROP DATABASE)[^\n]*\*', out)
    c['no unresolved destructive variable'] = 'rm -rf --one-file-system -- "/opt/odoo/data/filestore/${RDB}"' in out and '[ -n "$TS" ]' in out
    c['old ambiguous one-liner absent from the script'] = 'Restore: docker exec' not in open(SCRIPT).read()
    return c


def main():
    point = sys.argv[1] if len(sys.argv) > 1 else '/opt/odoo/backups'
    out = generate(point)
    result = checks(out)
    for k, v in result.items():
        print(('PASS' if v else 'FAIL'), k)
    print(f"{sum(result.values())}/{len(result)} checks passed")
    return 0 if all(result.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
