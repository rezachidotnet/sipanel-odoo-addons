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
    ('p9_SI-26-2546_en_US.pdf', '30,100,860,240', 'P9: total incl. VAT (owner 2026-10-14)'),
    ('p9_SI-26-2546_fa_IR.pdf', '30,100,860,240', 'P9: total incl. VAT (fa_IR)'),
    ('p9_SI-26-2546_fa_IR.pdf', '27,364,418,400', 'P9: untaxed (owner 2026-10-14)'),
    # requirements 2026-10-08 (code: items 1-4, 10; data P6b: items 6-12)
    # (Persian markers without digits / trailing punctuation: RTL extraction may move them)
    ('p9_SI-26-2546_fa_IR.pdf', 'شرایط پرداخت', 'payment terms in the terms section'),
    ('p9_SI-26-2546_fa_IR.pdf', 'زمان تحویل', 'delivery time label'),
    ('p9_SI-26-2546_fa_IR.pdf', 'روز کاری پس از دریافت پیش‌پرداخت', 'delivery time text'),
    ('p9_SI-26-2546_fa_IR.pdf', 'اعتبار این پیش‌فاکتور تا تاریخ درج‌شده در بالای آن است', 'new terms text'),
    ('p9_SI-26-2546_fa_IR.pdf', 'سیستم پوشش سقف و دیوار استندینگ سیم', 'Persian line description (roof + wall, 2026-10-14)'),
    ('p9_SI-26-2546_fa_IR.pdf', 'متعلقات', 'Persian section'),
    ('p9_SI-26-2546_fa_IR.pdf', 'متر طول', 'meter fa_IR name'),
    ('p9_SI-26-2546_fa_IR.pdf', 'طالقان', 'project site'),
    ('p9_SI-26-2546_fa_IR.pdf', 'استندینگ سیم', 'Requested System in Persian (account 2316 fa_IR)'),
    ('p9_SI-26-2546_fa_IR.pdf', 'شهرستان طالقان', 'project site city (owner review 2026-10-12)'),
    ('p9_SI-26-2546_fa_IR.pdf', 'باقیمانده قبل از بارگیری', 'payment term name (owner review 2026-10-12)'),
    ('p9_SI-26-2546_fa_IR.pdf', 'طالقانی', 'Persian salesperson name (owner review 2026-10-12)'),
    ('p9_SI-26-2546_fa_IR.pdf', 'www.sipanelco.com', 'footer website (owner review 2026-10-12)'),
    ('p9_SI-26-2546_en_US.pdf', 'www.sipanelco.com', 'footer website (en_US)'),
    ('p9_SI-26-2546_en_US.pdf', 'Taleghani', 'salesperson user name (en_US)'),
    ('p9_SI-26-2546_fa_IR.pdf', 'جناب آقای', 'contact name typo fixed'),
    ('p9_SI-26-2546_en_US.pdf', 'Payment terms:', 'payment terms (en_US)'),
    ('p9_SI-26-2546_en_US.pdf', 'Delivery time: 45 working days after receipt of the down payment', 'delivery time (en_US)'),
    ('p9_SI-26-2546_en_US.pdf', 'Sales Department', 'signature caption'),
    # owner requirements 2026-10-14 (code: technical sheet page, shop drawings line; data P8b + P6b item 6)
    ('p9_SI-26-2546_fa_IR.pdf', 'مشخصات فنی سیستم استندینگ سیم', 'technical sheet page title'),
    ('p9_SI-26-2546_fa_IR.pdf', 'لایه‌ی بخاربند', 'technical sheet row 3 (fa_IR)'),
    ('p9_SI-26-2546_fa_IR.pdf', 'پشم سنگ تخته‌ای بدون روکش', 'technical sheet row 6 (fa_IR)'),
    ('p9_SI-26-2546_en_US.pdf', 'Vapour barrier', 'technical sheet row 3 (en_US translation)'),
    ('p9_SI-26-2546_en_US.pdf', '0.7 mm thick', 'liner thickness 0.7 printed in row 2 (en_US)'),
    ('p9_SI-26-2546_fa_IR.pdf', 'سیستم پوشش سقف و دیوار استندینگ سیم', 'first section roof + wall'),
    ('p9_SI-26-2546_fa_IR.pdf', 'فلاشینگ هم‌جنس ورق رویه، عرض گسترده تا', 'flashing split into two lines'),
    ('p9_SI-26-2546_fa_IR.pdf', 'تهیه‌ی نقشه‌های اجرایی', 'shop drawings line (fa_IR)'),
    ('p9_SI-26-2546_fa_IR.pdf', '547,288,368', 'shop drawings price = 2 % of supply + installation'),
    ('p9_SI-26-2546_fa_IR.pdf', '43,800,000', 'flashing 58 cm price'),
    ('p9_SI-26-2546_fa_IR.pdf', '14,600,000', 'flashing 20 cm price'),
    ('p9_SI-26-2546_fa_IR.pdf', 'جنس ورق رویه', 'material on the lines (native no_variant attribute)'),
    ('p9_SI-26-2546_fa_IR.pdf', 'ورق فولادی گالوانیزه‌ی پیش‌رنگ', 'row 7 = galvanized text'),
    ('p9_SI-26-2546_fa_IR.pdf', 'سازه‌ی نگهدارنده', 'row 8 purlin'),
    ('p9_SI-26-2546_en_US.pdf', 'Technical Specification of the Standing Seam System', 'English sheet title'),
    ('p9_SI-26-2546_en_US.pdf', 'Pre-painted galvanized steel sheet', 'row 7 = galvanized text (en_US)'),
    ('p9_SI-26-2546_fa_IR.pdf', 'مقادیر این پیش‌فاکتور تقریبی است', 'terms line 3 (item 6)'),
    ('p9_SI-26-2546_fa_IR.pdf', 'نقشه‌های اجرایی (شاپ) استخراج می‌شود و ملاک محاسبه خواهد بود', 'terms line 3 (item 6)'),
]
# old wording that must NOT appear where the new model is printed
ABSENT = [
    ('p9_SI-26-2546_en_US.pdf', 'IRRial', 'old unit label gone (way A)'),
    ('post_SI-26-2546_en_US.pdf', 'IRRial', 'old unit label gone'),
    ('post_SI-26-2546_en_US.pdf', 'SIP-000074', 'internal code not printed (item 1)'),
    ('post_SI-26-2546_fa_IR.pdf', 'SIP-000074', 'internal code not printed (item 1, fa_IR)'),
    ('p9_SI-26-2546_fa_IR.pdf', 'SIP-0000', 'internal codes not printed'),
    ('p9_SI-26-2546_en_US.pdf', 'SIP-0000', 'internal codes not printed (en_US)'),
    ('p9_SI-26-2546_en_US.pdf', 'Sell Department', 'old signature caption'),
    ('p9_SI-26-2546_fa_IR.pdf', 'ساندویچ پانل تولید شرکت', 'placeholder terms line'),
    ('p9_SI-26-2546_fa_IR.pdf', 'ARCZIP', 'no brand name'),
    ('p9_SI-26-2546_en_US.pdf', 'Excluded:', 'the Excluded note is removed'),
    ('p9_SI-26-2546_en_US.pdf', 'Accessories', 'the section is Persian'),
    ('p9_SI-26-2546_en_US.pdf', 'Delivery Date', 'no native delivery date (commitment_date cleared)'),
    ('p9_SI-26-2546_fa_IR.pdf', 'DAP', 'old incoterm'),
    ('p9_SI-26-2546_fa_IR.pdf', 'جناب اقای', 'contact name typo'),
    ('p9_SI-26-2546_fa_IR.pdf', 'Standing Seam Roof System', 'first section is Persian (owner 2026-10-11)'),
    ('p9_SI-26-2546_fa_IR.pdf', 'EXW', 'Incoterm not printed (owner review 2026-10-12)'),
    ('p9_SI-26-2546_en_US.pdf', 'EXW', 'Incoterm not printed (en_US)'),
    ('p9_SI-26-2546_en_US.pdf', 'Incoterm', 'Incoterm label not printed (en_US)'),
    ('p9_SI-26-2546_fa_IR.pdf', 'جهت شروع تولید', 'payment term note not printed'),
    ('p9_SI-26-2546_en_US.pdf', 'required to commence production', 'payment term note not printed (en_US)'),
    ('p9_SI-26-2546_fa_IR.pdf', 'sipanelco.ir', 'old footer website'),
    ('p9_SI-26-2546_en_US.pdf', 'sipanelco.ir', 'old footer website (en_US)'),
    ('p9_SI-26-2546_fa_IR.pdf', 'Taleghani', 'fa_IR prints the Persian salesperson name'),
    ('p9_SI-26-2546_fa_IR.pdf', 'متره اجرایی', 'old terms line 3 replaced (item 6)'),
    ('p9_SI-26-2546_fa_IR.pdf', 'liner_thickness', 'thickness placeholder replaced (fa_IR)'),
    ('p9_SI-26-2546_en_US.pdf', 'liner_thickness', 'thickness placeholder replaced (en_US)'),
    ('p9_SI-26-2546_fa_IR.pdf', 'آلومینیوم پیش‌رنگ آلیاژ', 'aluminium text not printed for a galvanized quotation'),
    ('post_SI-26-2546_fa_IR.pdf', 'مشخصات فنی', 'no technical sheet page without a sheet (earlier layout)'),
    ('post_SI-26-2546_en_US.pdf', 'Technical Specification', 'no technical sheet page without a sheet (en_US)'),
]
# owner requirements 2026-10-14, item 1: page 1 = info page, page 2 = technical sheet, page 3 = price table
PAGES = [
    ('p9_SI-26-2546_fa_IR.pdf', 2, 'مشخصات فنی سیستم استندینگ سیم', True, 'page 2 is the technical sheet'),
    ('p9_SI-26-2546_fa_IR.pdf', 2, 'مبلغ کل به حروف', False, 'no price table on the technical sheet page'),
    ('p9_SI-26-2546_fa_IR.pdf', 1, 'مشخصات فنی سیستم', False, 'page 1 unchanged (info page)'),
    ('p9_SI-26-2546_fa_IR.pdf', 3, 'سیستم پوشش سقف و دیوار استندینگ سیم', True, 'page 3 starts the price table'),
    ('p9_SI-26-2546_en_US.pdf', 2, 'Vapour barrier', True, 'page 2 is the technical sheet (en_US)'),
    ('p9_SI-26-2546_en_US.pdf', 3, 'Payment terms:', True, 'terms on page 3 (en_US)'),
]


def text_of(path):
    return squash(subprocess.run(['pdftotext', '-layout', path, '-'], capture_output=True, text=True, check=True).stdout)


def page_checks(evid):
    ok = True
    for name, page, marker, must, why in PAGES:
        path = os.path.join(evid, name)
        if not os.path.exists(path):
            print(f'FAIL {name}: no such PDF ({why})')
            ok = False
            continue
        text = squash(subprocess.run(['pdftotext', '-layout', '-f', str(page), '-l', str(page), path, '-'],
                                     capture_output=True, text=True).stdout)
        good = (squash(marker) in text) == must
        ok &= good
        print(f"{'PASS' if good else 'FAIL'} {name} page {page}: {'has' if must else 'has not'} {marker!r} ({why})")
    pages = subprocess.run(['pdfinfo', os.path.join(evid, PAGES[0][0])], capture_output=True, text=True).stdout
    print('INFO ' + PAGES[0][0] + ' ' + ' '.join(l for l in pages.splitlines() if l.startswith('Pages')))
    return ok


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
        rows = [r for r in layout.splitlines() if r.count('2,487,674,400') == 2 and '10%' in r]
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
    ok &= page_checks(evid)
    print('MARKERS ' + ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]) if len(sys.argv) == 2 else __doc__)
