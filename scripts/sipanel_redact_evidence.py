#!/usr/bin/env python3
"""Redact captured evidence (portal HTML, logs, JSON) in place before it is saved to a report.

  scripts/sipanel_redact_evidence.py FILE [FILE ...]

Replaces portal access tokens (query string and data-token), CSRF tokens and session ids with placeholders, then
re-scans each file with the patterns of scripts/sipanel_secret_scan.py and exits 1 if anything is left.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sipanel_secret_scan import _NZ, PATTERNS, texts  # noqa: E402  same patterns as the pre-push scan

REDACTIONS = [
    (re.compile(r'(access_token=)' + _NZ + r'[0-9a-fA-F][0-9a-fA-F-]{7,}'), r'\1<REDACTED_ACCESS_TOKEN>'),
    (re.compile(r'(data-token=")' + _NZ + r'[0-9a-fA-F][0-9a-fA-F-]{7,}(")'), r'\1<REDACTED_ACCESS_TOKEN>\2'),
    (re.compile(r'(csrf_token["\']?\s*[:=]\s*["\'])[0-9a-fA-F]{20,}[0-9A-Za-z]*(["\'])'), r'\1<REDACTED_CSRF_TOKEN>\2'),
    (re.compile(r'(name=["\']csrf_token["\'][^>]*?value=["\'])[^"\']+(["\'])'), r'\1<REDACTED_CSRF_TOKEN>\2'),
    (re.compile(r'(value=["\'])[0-9a-f]{40}o[0-9]{8,}(["\'][^>]*?name=["\']csrf_token)'), r'\1<REDACTED_CSRF_TOKEN>\2'),
    (re.compile(r'\b[0-9a-f]{40}o[0-9]{9,11}\b'), '<REDACTED_CSRF_TOKEN>'),
    (re.compile(r'(session_id=)[0-9A-Za-z_-]{16,}'), r'\1<REDACTED_SESSION>'),
]


def redact(text):
    for rx, repl in REDACTIONS:
        text = rx.sub(repl, text)
    return text


def main(paths):
    left = 0
    for path in paths:
        raw = open(path, 'rb').read()
        text = redact(raw.decode('utf-8', 'surrogateescape'))
        with open(path, 'wb') as f:
            f.write(text.encode('utf-8', 'surrogateescape'))
        for member, content in texts(path, text.encode('utf-8', 'surrogateescape')):
            for key, rx in PATTERNS.items():
                for _m in rx.finditer(content):
                    print(f'NOT REDACTED {key}: {member}', file=sys.stderr)
                    left += 1
    print(f'redacted {len(paths)} file(s), {left} secret(s) left')
    return 1 if left else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
