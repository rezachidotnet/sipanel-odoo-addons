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
    ('rehearsal_A_*_en_US.pdf', 'Installation & Execution (10% of item subtotal)', 'way A: installation line 10 %'),
    ('rehearsal_A_*_en_US.pdf', 'Rials only', 'way A: amount in words'),
    ('rehearsal_A_*_fa_IR.pdf', 'نصب و اجرا', 'way A: installation section (fa_IR)'),
    ('rehearsal_B_*_en_US.pdf', '(supply only)', 'way B: v3 Scope anchors'),
    ('rehearsal_B_*_en_US.pdf', 'Installation & Execution (10% of item subtotal)', 'way B: installation line 10 %'),
    ('rehearsal_B_*_fa_IR.pdf', 'فقط تأمین', 'way B: v3 Scope anchors (fa_IR)'),
]
# old wording that must NOT appear where the new model is printed
ABSENT = [
    ('rehearsal_B_*_en_US.pdf', 'supplied and installed', 'v2 wording gone from the v3 quotation'),
    ('post_SI-26-2546_en_US.pdf', 'IRRial', 'old unit label gone'),
]


def text_of(path):
    return squash(subprocess.run(['pdftotext', '-layout', path, '-'], capture_output=True, text=True, check=True).stdout)


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
    print('MARKERS ' + ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]) if len(sys.argv) == 2 else __doc__)
