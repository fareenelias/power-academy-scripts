"""
fix_nasdaq_regex.py  —  Run once, fixes the NASDAQGS/NASDAQGM ticker
extraction bug in extract_surprise_data.py and extract_capiq_reports.py.

The old regex matched bare 'NASDAQ' first, leaving 'GS'/'GM' prepended
to the ticker (e.g. GSEVRG, GSHTO, GMGWRS). The fix adds the full
exchange codes before NASDAQ so they match first.
"""

import re, os

SCRIPTS_DIR = r"E:\PowerAcademy\scripts"

TARGETS = [
    'extract_surprise_data.py',
    'extract_capiq_reports.py',
    'fetch_ferc1_opco_data.py',   # included in case it reads Excel files too
]

# The broken pattern (may appear with slight variations)
OLD_PATTERNS = [
    r'(?:NYSE|NASDAQ|NasdaqGS|NasdaqCM|OTC)',
    r"(?:NYSE|NASDAQ|NasdaqGS|NasdaqCM|OTC)",
]

NEW_PATTERN = r'(?:NYSE|NASDAQGS|NASDAQGM|NASDAQCM|NASDAQ|NasdaqGS|NasdaqCM|OTC)'

for fname in TARGETS:
    fpath = os.path.join(SCRIPTS_DIR, fname)
    if not os.path.exists(fpath):
        print(f'  SKIP (not found): {fname}')
        continue

    with open(fpath, encoding='utf-8') as f:
        src = f.read()

    fixed = False
    for old in OLD_PATTERNS:
        if old in src:
            src = src.replace(old, NEW_PATTERN)
            fixed = True
            break

    if fixed:
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(src)
        print(f'  [✓] Fixed: {fname}')
    else:
        # Check if it's already fixed or uses a totally different pattern
        if NEW_PATTERN in src:
            print(f'  [=] Already fixed: {fname}')
        else:
            print(f'  [?] Pattern not found — check manually: {fname}')
            # Show context around any nasdaq/exchange reference
            for i, line in enumerate(src.splitlines(), 1):
                if 'NASDAQ' in line.upper() and 'Report' in line:
                    print(f'      Line {i}: {line.strip()}')

print('\nDone. Re-run extract_surprise_data.py and extract_capiq_reports.py.')