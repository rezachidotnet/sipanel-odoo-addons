#!/usr/bin/env python3
"""Content markers that only the code under test produces, checked in the clone PDFs (decision 2026-10-06).

Usage: qlines_code_markers.py <evidence dir>   -> one line per check, last line "MARKERS PASS|FAIL"; exit 0/1.

Text is taken with `pdftotext -layout` and compared after NFKC normalisation (Arabic presentation forms -> letters)
with whitespace and bidi controls removed, so Persian matches in logical order. Persian markers avoid brackets
(RTL extraction may mirror them).
"""
import glob
import os
import subprocess
import sys
import unicodedata


def squash(text):
    text = unicodedata.normalize('NFKC', text)
    return ''.join(c for c in text if not c.isspace() and unicodedata.category(c) != 'Cf')


# (pdf glob, marker, what it proves)
MARKERS = [
    ('post_SI-26-2546_en_US.pdf', 'Rials only', 'English amount in words, owner decision 2026-10-06'),
    ('post_SI-26-2546_fa_IR.pdf', 'مبلغ کل به حروف', 'amount in words (sipanel_quotation_lines)'),
    ('post_synthetic_en_US_install40.pdf', 'Installation & Execution (40% of item subtotal)', 'installation line'),
    ('post_synthetic_en_US_install40.pdf', '(supply only)', 'v3 supply-only wording on the Scope anchor'),
    ('post_synthetic_fa_IR_install40.pdf', 'فقط تأمین', 'v3 supply-only wording (fa_IR)'),
    ('post_synthetic_fa_IR_install40.pdf', 'نصب و اجرا', 'installation section (fa_IR)'),
    ('p9_SI-26-2546_en_US.pdf', 'Rials only', 'P9 way A: amount in words'),
    ('p9_SI-26-2546_fa_IR.pdf', 'نصب و اجرا', 'P9 way A: installation section (fa_IR)'),
    ('p9_SI-26-2546_en_US.pdf', '30,087,618,000', 'P9 way A: total incl. VAT'),
    ('p9_SI-26-2546_fa_IR.pdf', '30,087,618,000', 'P9 way A: total incl. VAT (fa_IR)'),
]
# old wording that must NOT appear where the new model is printed
ABSENT = [
    ('p9_SI-26-2546_en_US.pdf', 'IRRial', 'old unit label gone (way A)'),
    ('post_SI-26-2546_en_US.pdf', 'IRRial', 'old unit label gone'),
]


def text_of(path):
    return squash(subprocess.run(['pdftotext', '-layout', path, '-'], capture_output=True, text=True, check=True).stdout)


def installation_rows(evid):
    """P9 (SI-26/2546 after way A): the printed installation row (quantity + unit) in both languages. The unit name must be the
    Units record's name in that language (from p9_summary.json); the quantity format is reported as is."""
    import json
    import re
    try:
        names = json.load(open(os.path.join(evid, 'p9_summary.json')))['unit_name']
    except (OSError, KeyError, ValueError) as exc:
        print(f'FAIL installation row: no unit names in p9_summary.json ({exc})')
        return False
    ok = True
    # the line text is stored in the customer's language when it is created (SI-26/2546: fa_IR), so the row is
    # found by its amount + tax column, not by its label; the section row has the amount but no tax
    for lang in ('en_US', 'fa_IR'):
        files = sorted(glob.glob(os.path.join(evid, f'p9_SI-26-2546_{lang}.pdf')))
        if not files:
            print(f'FAIL installation row {lang}: no PDF')
            ok = False
            continue
        layout = subprocess.run(['pdftotext', '-layout', files[0], '-'], capture_output=True, text=True,
                                check=True).stdout
        rows = [r for r in layout.splitlines() if r.count('2,486,580,000') == 2 and '10%' in r]
        unit = squash(names[lang])
        good = len(rows) == 1 and unit in squash(rows[0])
        qty = re.findall(r'(?<![\d,])(\d+(?:\.\d+)?)(?![\d,%])', rows[0]) if rows else []
        ok &= good
        print(f"{'PASS' if good else 'FAIL'} {os.path.basename(files[0])}: installation row has unit "
              f"{names[lang]!r}; quantity printed as {qty[:3]} (INFO); row: {' '.join(rows[0].split()) if rows else None!r}")
    return ok


def main(evid):
    ok = True
    for pattern, marker, why in MARKERS + [(p, m, w) for p, m, w in ABSENT]:
        must = (pattern, marker, why) not in ABSENT
        files = sorted(glob.glob(os.path.join(evid, pattern)))
        if not files:
            print(f'FAIL {pattern}: no such PDF ({why})')
            ok = False
            continue
        for f in files:
            found = squash(marker) in text_of(f)
            good = found if must else not found
            ok &= good
            print(f"{'PASS' if good else 'FAIL'} {os.path.basename(f)}: {'has' if must else 'has not'} "
                  f"{marker!r} ({why})")
    ok &= installation_rows(evid)
    print('MARKERS ' + ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]) if len(sys.argv) == 2 else __doc__)
