#!/usr/bin/env python3
"""Reservation / locking / failure tests for scripts/sipanel_recovery_point.sh, run entirely in temporary
directories with RP_SIMULATE=1 (no docker, no sudo, no real backup). Usage: python3 scripts/test_recovery_point_concurrency.py"""
import hashlib
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, 'sipanel_recovery_point.sh')
ARTEFACTS = ['sipanel.dump', 'filestore-sipanel.tar.gz', 'addons.tar.gz', 'installed_modules.txt', 'container-inspect.json', 'odoo-sipanel.conf.redacted']


def run(dest, lock, src, delay=0, fail_at='', wait=True):
    env = dict(os.environ, DEST=dest, RP_LOCK=lock, RP_SIMULATE='1', RP_SIM_SRC=src, RP_SIMULATE_DELAY=str(delay), RP_FAIL_AT=fail_at)
    proc = subprocess.Popen(['bash', SCRIPT], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if not wait:
        return proc
    out, _ = proc.communicate()
    return proc.returncode, out


def tree(d):
    return {f: hashlib.sha256(open(os.path.join(d, f), 'rb').read()).hexdigest() for f in sorted(os.listdir(d))} if os.path.isdir(d) else None


def verify_sums(d):
    sums = dict(line.split('  ', 1)[::-1] for line in open(os.path.join(d, 'SHA256SUMS')).read().splitlines())
    return set(sums) == set(ARTEFACTS) and all(hashlib.sha256(open(os.path.join(d, f), 'rb').read()).hexdigest() == h for f, h in sums.items())


def main():
    results = {}
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, 'src'); os.makedirs(os.path.join(src, 'sipanel')); os.makedirs(os.path.join(src, 'addons'))
        open(os.path.join(src, 'sipanel', 'f1'), 'w').write('filestore'); open(os.path.join(src, 'addons', 'a1'), 'w').write('addons')
        base = os.path.join(tmp, 'backups'); os.makedirs(base)
        lock = os.path.join(tmp, 'recovery.lock')
        # 1. successful unique destination
        d1 = os.path.join(base, 'sipanel-pre-test-1')
        rc, out = run(d1, lock, src)
        results['successful unique destination'] = rc == 0 and 'RECOVERY_POINT_OK' in out and verify_sums(d1) and os.path.exists(os.path.join(d1, 'TIMESTAMP')) \
            and not os.path.exists(os.path.join(d1, 'INVALID_DO_NOT_USE.txt'))
        snap1 = tree(d1); mtime1 = os.stat(os.path.join(d1, 'SHA256SUMS')).st_mtime
        # 2. destination already exists: refused, nothing written, valid point untouched
        rc, out = run(d1, lock, src)
        results['destination already exists is refused'] = rc == 7 and 'DEST_ALREADY_EXISTS' in out and 'RECOVERY_POINT_OK' not in out
        results['no overwrite of a valid recovery point'] = tree(d1) == snap1 and os.stat(os.path.join(d1, 'SHA256SUMS')).st_mtime == mtime1
        # 3. two concurrent invocations, same destination
        d3 = os.path.join(base, 'sipanel-pre-test-3')
        pa = run(d3, lock, src, delay=1, wait=False); time.sleep(0.2); pb = run(d3, lock, src, delay=1, wait=False)
        oa, _ = pa.communicate(); ob, _ = pb.communicate()
        outs = [(pa.returncode, oa), (pb.returncode, ob)]
        winners = [o for o in outs if o[0] == 0 and 'RECOVERY_POINT_OK' in o[1]]
        losers = [o for o in outs if o[0] in (6, 7) and ('RECOVERY_POINT_BUSY' in o[1] or 'DEST_ALREADY_EXISTS' in o[1])]
        results['two concurrent invocations: exactly one succeeds'] = len(winners) == 1 and len(losers) == 1
        results['concurrent loser wrote nothing and winner verifies'] = verify_sums(d3) and not os.path.exists(os.path.join(d3, 'INVALID_DO_NOT_USE.txt')) \
            and all('SIMULATED' not in o[1] for o in losers)
        # 4. two concurrent invocations, different destinations: the lock serialises them (loser BUSY, its DEST not created)
        d4a, d4b = os.path.join(base, 'sipanel-pre-test-4a'), os.path.join(base, 'sipanel-pre-test-4b')
        pa = run(d4a, lock, src, delay=1, wait=False); time.sleep(0.2); pb = run(d4b, lock, src, delay=0, wait=False)
        oa, _ = pa.communicate(); ob, _ = pb.communicate()
        results['concurrent different destinations: loser is BUSY and creates nothing'] = pa.returncode == 0 and pb.returncode == 6 and 'RECOVERY_POINT_BUSY' in ob \
            and not os.path.exists(d4b) and verify_sums(d4a)
        # 5. failure before completion: no OK, INVALID marker, no SHA256SUMS, earlier valid point untouched
        d5 = os.path.join(base, 'sipanel-pre-test-5')
        rc, out = run(d5, lock, src, fail_at='filestore')
        results['failure before completion is marked INVALID without RECOVERY_POINT_OK'] = rc != 0 and 'RECOVERY_POINT_OK' not in out \
            and 'RECOVERY_POINT_FAILED' in out and os.path.exists(os.path.join(d5, 'INVALID_DO_NOT_USE.txt')) and not os.path.exists(os.path.join(d5, 'SHA256SUMS'))
        results['failed run does not delete or touch the valid point'] = tree(d1) == snap1 and os.path.isdir(d5)
        # 5b. the failed directory is never silently reused
        rc, out = run(d5, lock, src)
        results['failed destination is not reused'] = rc == 7 and 'DEST_ALREADY_EXISTS' in out and not os.path.exists(os.path.join(d5, 'SHA256SUMS'))
        # 6. no mixed checksums: every SHA256SUMS references exactly its own six artefacts and verifies
        results['no mixed checksums across points'] = all(verify_sums(d) for d in (d1, d3, d4a)) and \
            open(os.path.join(d1, 'sipanel.dump')).read() != open(os.path.join(d3, 'sipanel.dump')).read()
        # 7. failure at verify keeps the marker too
        d7 = os.path.join(base, 'sipanel-pre-test-7')
        rc, out = run(d7, lock, src, fail_at='verify')
        results['failure at verification is marked INVALID'] = rc != 0 and os.path.exists(os.path.join(d7, 'INVALID_DO_NOT_USE.txt')) and 'RECOVERY_POINT_OK' not in out
    for k, v in results.items():
        print(('PASS' if v else 'FAIL'), k)
    print(f"{sum(results.values())}/{len(results)} checks passed")
    return 0 if all(results.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
