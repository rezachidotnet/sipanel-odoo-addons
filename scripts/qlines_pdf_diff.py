#!/usr/bin/env python3
"""Classify the customer PDF difference between two renders of the same quotation (quotation lines, 2026-10-05).

Usage: qlines_pdf_diff.py BEFORE.pdf AFTER.pdf (--identical | --words-line "LABEL WORDS")

--identical      AFTER must carry exactly the text of BEFORE, every word at the same position.
--words-line S   AFTER may differ from BEFORE by exactly ONE inserted line whose text is S (the amount-in-words
                 label + words); every other word keeps its text and its x position, words below the insertion
                 move down by one constant offset. Anything else (a changed amount, wording, a deleted or a
                 second inserted line) is a FAILURE.

Text is compared on `pdftotext -layout` (logical order, also for RTL) with whitespace collapsed; the geometry on
`pdftotext -bbox`. Raw `-layout` diffs also show column re-flow (the longest line moves pdftotext's text grid),
which is why the raw .diff is not the verdict. Prints one VERDICT line; exit status 0 = PASS, 1 = FAIL.
"""
import difflib
import re
import subprocess
import sys
import unicodedata


def layout_lines(pdf):
    out = subprocess.run(['pdftotext', '-layout', pdf, '-'], check=True, capture_output=True, text=True).stdout
    return [ln for ln in (' '.join(l.split()) for l in out.splitlines()) if ln]


def words(pdf):
    out = subprocess.run(['pdftotext', '-bbox', pdf, '-'], check=True, capture_output=True, text=True).stdout
    return [(float(x), float(y), t) for x, y, t in
            re.findall(r'<word xMin="([\d.]+)" yMin="([\d.]+)"[^>]*>([^<]*)</word>', out)]


def squash(text):
    """NFKC (Arabic presentation forms -> letters), no whitespace, no bidi controls."""
    text = unicodedata.normalize('NFKC', text)
    return ''.join(c for c in text if not c.isspace() and unicodedata.category(c) != 'Cf')


def main(before, after, mode, expected=None):
    problems = []
    a_lines, b_lines = layout_lines(before), layout_lines(after)
    removed = [l for l in difflib.ndiff(a_lines, b_lines) if l.startswith('- ')]
    added = [l[2:] for l in difflib.ndiff(a_lines, b_lines) if l.startswith('+ ')]
    if removed:
        problems.append(f'{len(removed)} line(s) removed or changed: {removed[:5]}')
    if mode == 'identical':
        if added:
            problems.append(f'{len(added)} line(s) added: {added[:5]}')
    else:
        if len(added) != 1:
            problems.append(f'expected exactly one added line, got {len(added)}: {added[:5]}')
        elif squash(added[0]) != squash(expected):
            problems.append(f'added line is not the expected amount-in-words line: {added[0]!r}')
    # geometry: unchanged words keep x; y moves by 0 or by one constant (only below the insertion)
    wa, wb = words(before), words(after)
    sm = difflib.SequenceMatcher(None, [w[2] for w in wa], [w[2] for w in wb], autojunk=False)
    ops = [op for op in sm.get_opcodes() if op[0] != 'equal']
    dx, dy = set(), set()
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            for i, j in zip(range(i1, i2), range(j1, j2)):
                dx.add(round(wb[j][0] - wa[i][0], 2))
                dy.add(round(wb[j][1] - wa[i][1], 2))
    if dx - {0.0}:
        problems.append(f'words moved horizontally: {sorted(dx)[:5]}')
    if mode == 'identical':
        if ops or dy - {0.0}:
            problems.append(f'word stream differs: ops={ops[:3]} y-shifts={sorted(dy)[:5]}')
    else:
        inserts = [op for op in ops if op[0] == 'insert']
        if len(ops) != 1 or len(inserts) != 1:
            problems.append(f'word stream: expected one insertion, got {ops[:5]}')
        else:
            _, _, _, j1, j2 = inserts[0]
            rows = {round(wb[j][1], 1) for j in range(j1, j2)}
            if len(rows) != 1:
                problems.append(f'inserted words span {len(rows)} rows: {sorted(rows)}')
        if len(dy - {0.0}) > 1:
            problems.append(f'more than one vertical offset: {sorted(dy)}')
    verdict = 'PASS' if not problems else 'FAIL'
    detail = (f'added={added!r} y-shift={sorted(dy - {0.0})}' if not problems else ' | '.join(problems))
    print(f'VERDICT {verdict} {before} -> {after}: {detail}')
    return 0 if not problems else 1


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[3] == '--identical':
        sys.exit(main(sys.argv[1], sys.argv[2], 'identical'))
    if len(sys.argv) == 5 and sys.argv[3] == '--words-line':
        sys.exit(main(sys.argv[1], sys.argv[2], 'words', sys.argv[4]))
    sys.exit(__doc__)
