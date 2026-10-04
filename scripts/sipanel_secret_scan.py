#!/usr/bin/env python3
"""Secret scan of the full git history: run before any push, and on bundle staging directories.

  scripts/sipanel_secret_scan.py              every blob reachable from any ref (all branches, all versions)
  scripts/sipanel_secret_scan.py --dir DIR    every file under DIR (e.g. a bundle staging directory)

ZIP members (also nested ZIPs) are scanned, and PDFs as text when pdftotext is installed. Placeholders such as
<REDACTED…>, <redacted>, <from config>, … and $VARS never count as values. A hit is accepted only when its blob id
and pattern are listed in scripts/secret_scan_allowlist.txt. Exit 0 = clean, 1 = unaccepted hit (values masked).
"""
import io
import os
import re
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ALLOWLIST = os.path.join(HERE, 'secret_scan_allowlist.txt')

# a value is never a placeholder: <…>, …, ..., $VAR, ${VAR}
_V = r'(?![<…$]|\.\.\.)'
# a token value is never all zeros (00000000-… is the fake token of negative tests)
_NZ = r'(?=[0-9a-fA-F-]*[1-9a-fA-F])'
PATTERNS = {
    'private_key': re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
    'odoo_conf_secret': re.compile(r'\b(db_password|admin_passwd|smtp_password)\s*[=:]\s*["\']?' + _V + r'[^\s"\'<]{3,}'),
    'password_assign': re.compile(r'\bpassword\s*=\s*["\']' + _V + r'[^"\'\s<]{4,}["\']', re.I),
    'pg_password_env': re.compile(r'\b(PGPASSWORD|POSTGRES_PASSWORD)\s*=\s*["\']?' + _V + r'[^\s"\'<]{3,}'),
    'access_token': re.compile(r'access_token=' + _V + _NZ + r'[0-9a-fA-F][0-9a-fA-F-]{7,}'),
    'data_token': re.compile(r'data-token="' + _V + _NZ + r'[0-9a-fA-F][0-9a-fA-F-]{7,}"'),
    'csrf_token': re.compile(r'csrf_token["\']?\s*[:=]\s*["\']' + _V + r'[0-9a-fA-F]{20,}'),
    'csrf_token_value': re.compile(r'\b[0-9a-f]{40}o[0-9]{9,11}\b'),  # Odoo csrf format: hmac + 'o' + expiry
    'session_id': re.compile(r'session_id=' + _V + r'[0-9A-Za-z_-]{16,}'),
    'aws_key': re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
    'github_token': re.compile(r'\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{30,}'),
    'slack_token': re.compile(r'\bxox[baprs]-[A-Za-z0-9-]{10,}'),
    'api_key_sk': re.compile(r'\bsk-[A-Za-z0-9_-]{20,}'),
    'google_api_key': re.compile(r'\bAIza[0-9A-Za-z_-]{35}\b'),
    'jwt': re.compile(r'\beyJ[A-Za-z0-9_-]{15,}\.eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}'),
    'url_credentials': re.compile(r'\b[a-z][a-z0-9+.-]*://[^/\s:@"\'<>]+:' + _V + r'[^@/\s"\'<>]{3,}@'),
}
SKIP_NAMES = (re.compile(r'(^|/)\.env(\.|$)'), re.compile(r'\.(pem|key|p12|pfx|pgpass|netrc)$'))


def load_allowlist():
    allowed = set()
    if os.path.exists(ALLOWLIST):
        for line in open(ALLOWLIST, encoding='utf-8'):
            line = line.split('#', 1)[0].split()
            if len(line) >= 2:
                allowed.add((line[0], line[1]))
    return allowed


def texts(name, data, depth=0):
    """Yield (member path, text) for a file, descending into ZIPs and PDFs."""
    if name.lower().endswith('.zip') and depth < 4:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for member in z.namelist():
                    if not member.endswith('/'):
                        yield from texts(f'{name}!{member}', z.read(member), depth + 1)
            return
        except zipfile.BadZipFile:
            pass
    if name.lower().endswith('.pdf'):
        try:
            out = subprocess.run(['pdftotext', '-q', '-', '-'], input=data, capture_output=True, timeout=60).stdout
            yield name, out.decode('utf-8', 'replace')
        except FileNotFoundError:
            print(f'warning: pdftotext missing, PDF not scanned: {name}', file=sys.stderr)
        return
    if b'\0' in data[:4096] and not name.lower().endswith(('.html', '.txt', '.log', '.md')):
        return  # other binary (png, …)
    yield name, data.decode('utf-8', 'replace')


def mask(value):
    return value[:12] + '…' if len(value) > 12 else value


def scan(items):
    """items: iterable of (blob id, path, bytes). Returns the list of hits."""
    hits = []
    for blob, path, data in items:
        for rx in SKIP_NAMES:
            if rx.search(path):
                hits.append((blob, path, 'secret_file_name', path))
        for member, text in texts(path, data):
            for key, rx in PATTERNS.items():
                for m in rx.finditer(text):
                    hits.append((blob, member, key, m.group(0)))
    return hits


def git_blobs():
    seen = set()
    objs = subprocess.run(['git', 'rev-list', '--all', '--objects'], capture_output=True, text=True, check=True).stdout
    for line in objs.splitlines():
        sha, _, path = line.partition(' ')
        if not path or sha in seen:
            continue
        if subprocess.run(['git', 'cat-file', '-t', sha], capture_output=True, text=True).stdout.strip() != 'blob':
            continue
        seen.add(sha)
        yield sha, path, subprocess.run(['git', 'cat-file', 'blob', sha], capture_output=True, check=True).stdout


def dir_files(root):
    for base, _dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(base, f)
            data = open(p, 'rb').read()
            sha = subprocess.run(['git', 'hash-object', '--stdin'], input=data, capture_output=True).stdout.decode().strip()
            yield sha, os.path.relpath(p, root), data


def main(argv):
    items = dir_files(argv[argv.index('--dir') + 1]) if '--dir' in argv else git_blobs()
    allowed = load_allowlist()
    hits = scan(items)
    bad = [h for h in hits if (h[0], h[2]) not in allowed]
    for blob, member, key, value in sorted(set(bad)):
        print(f'SECRET {key}: {member} (blob {blob[:12]}): {mask(value)}')
    accepted = len({(h[0], h[1], h[3]) for h in hits}) - len({(h[0], h[1], h[3]) for h in bad})
    print(f'secret scan: {len(set(bad))} unaccepted hit(s), {accepted} accepted (allowlist)')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
