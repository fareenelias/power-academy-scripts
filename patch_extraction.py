"""
patch_extraction.py  
====================
Targeted patch to fetch_edgar_rate_base_v3.py that fixes extraction for
EIX, NEE, ETR, AEE, HE, EVRG, PCG — and corrects false positives for D/POR.

Adds two new extraction strategies inside extract_rate_base_from_text():

  Strategy 5: "Rate Base ($B)" / "Rate Base, $ in Billions" header table
              Numbers follow as bare floats: 27.7 30.4 33.4... then years
              OR dollar series: $41.2 $42.8 $49.4... then years

  Strategy 5b: Stricter dollar_rate_base_phrase — rejects matches where 
               "capital", "invest", "deploy", or "spend" appear within 
               80 chars before the figure (fixes D: $138B and POR: $1.4B)

  Also fixes: pick_best() to correctly handle None result from process_company()
              (the NoneType AttributeError crash at the end of main())

Run from E:\\PowerAcademy\\scripts\\ alongside v3:
  python patch_extraction.py

This modifies fetch_edgar_rate_base_v3.py in-place.
Or run directly: python patch_extraction.py --run
  (runs the full extraction after patching)
"""

import sys, re
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
V3_PATH    = SCRIPT_DIR / "fetch_edgar_rate_base_v3.py"

if not V3_PATH.exists():
    sys.exit(f"ERROR: {V3_PATH} not found. Copy fetch_edgar_rate_base_v3.py first.")

src = V3_PATH.read_text(encoding="utf-8")

# ── Patch 1: Replace extract_rate_base_from_text() entirely ──────────────────
OLD_FN_MARKER = "def extract_rate_base_from_text(text: str, opco_labels: list,"
NEW_FN = '''def extract_rate_base_from_text(text: str, opco_labels: list,
                                 keywords: list) -> list:
    """
    Returns list of candidate dicts sorted by strategy quality.
    
    Strategies (in priority order):
      1. total_rate_base_row     — "Total Rate Base $X.X $X.X..."
      2. rate_base_table_header  — "Rate Base ($B) 27.7 30.4..." + year sequence
      3. dollar_series_years     — "$41.2 $42.8 $49.4... 2023 2024 2025..."
      4. regulatory_overview     — "Year-End Rate Base ($B) $X.X" per opco slide
      5. dollar_rate_base_phrase — "rate base of $X.XB" (strict, rejects capital context)
      6. balance_sheet_nup       — net utility plant from balance sheet (Tier 3)
    """
    results = []

    # ── Strategy 1: "Total Rate Base $X.X $X.X..." explicit row ──────────────
    p1 = re.compile(
        r\'(?:\\w[\\w\\s&]*?\\s+)?Total\\s+Rate\\s+Base\\s+(?:\\d+)?\\s*\',
        r\'((?:\\$?\\s*[\\d,\\.]+\\s+){1,8})\',
        re.IGNORECASE
    )
    p1 = re.compile(
        r\'(?:[\\w\\s&]*?)?Total\\s+Rate\\s+Base\\s*(?:\\d+)?\\s*\'
        r\'((?:\\$?\\s*[\\d,\\.]+\\s*){1,8})\',
        re.IGNORECASE
    )
    for m in p1.finditer(text):
        raw = m.group(1)
        vals = []
        for v in re.findall(r\'[\\d,\\.]+\', raw):
            try:
                f = float(v.replace(\',\', \'\'))
                if 0.2 < f < 800:
                    vals.append(f)
            except ValueError:
                pass
        if not vals:
            continue
        ctx = text[max(0, m.start()-400):m.end()+200]
        years_int = sorted(set(int(y) for y in re.findall(r\'\\b(20[2-3]\\d)\\b\', ctx)))
        base_year = str(years_int[0]) if years_int else None
        future = {str(int(base_year)+i): v for i, v in enumerate(vals[1:6], 1)} \\
                 if base_year else {}
        results.append({
            \'total_b\': vals[0], \'year\': base_year, \'future_values\': future,
            \'opco_breakdown\': [], \'strategy\': \'total_rate_base_row\',
            \'context\': ctx[:300],
        })

    # ── Strategy 2: "Rate Base ($B)" header + bare number series + years ─────
    # Matches: "Rate Base ($B) 27.7 30.4 33.4 2025 2026 2027"
    # Also:    "Rate Base, $ in Billions 33.6 7.6 $41.2 $42.8 $49.4 2023 2024 2025"
    header_pat = re.compile(
        r\'(?:Total\\s+|Projected\\s+|Company\\s+)?\'
        r\'(?:\\w+\\s+)?Rate\\s+Base\\s*(?:\\d+)?\\s*\'
        r\'(?:[,;]?\\s*\\$\\s*in\\s+[Bb]illions?\'
        r\'|\\(\\$\\s*[Bb]\\)\'
        r\'|\\(\\$\\s*in\\s+[Bb]illions?\\))\',
        re.IGNORECASE
    )
    for hm in header_pat.finditer(text):
        window = text[hm.end():hm.end()+400]
        # Collect dollar-prefixed values first (higher confidence)
        dollar_vals = [float(v.replace(\',\', \'\'))
                       for v in re.findall(r\'\\$([\\d,\\.]+)\', window)
                       if 0.1 < float(v.replace(\',\', \'\')) < 800]
        # Collect bare decimal values
        bare_vals = [float(v)
                     for v in re.findall(r\'\\b(\\d{1,3}\\.\\d)\\b\', window)
                     if 0.1 < float(v) < 800]
        all_vals = dollar_vals if dollar_vals else bare_vals
        years = re.findall(r\'\\b(20[2-3]\\d)\\b\', window)
        if not all_vals or not years:
            continue
        n = min(len(all_vals), len(years))
        yr_map = dict(zip(years[:n], all_vals[:n]))
        # Must have 2024 or 2025 in the map
        base_year = \'2025\' if \'2025\' in yr_map else (\'2024\' if \'2024\' in yr_map else None)
        if not base_year:
            continue
        total_b = yr_map[base_year]
        future = {y: v for y, v in yr_map.items() if int(y) > int(base_year)}
        ctx = text[max(0, hm.start()-100):hm.end()+400]
        results.append({
            \'total_b\': total_b, \'year\': base_year,
            \'future_values\': future, \'opco_breakdown\': [],
            \'strategy\': \'rate_base_table_header\', \'context\': ctx[:300],
        })

    # ── Strategy 3: "$X.X $X.X $X.X... YEAR YEAR YEAR" dollar series ─────────
    # Matches EIX: "$41.2 $42.8 $49.4 $53.0 2023 2024 2025 2026"
    dollar_series = re.compile(
        r\'(\\$[\\d,\\.]+(?:\\s+\\$[\\d,\\.]+){2,})\'
        r\'\\s+\'
        r\'(20[2-3]\\d(?:\\s+20[2-3]\\d)+)\',
    )
    for m in dollar_series.finditer(text):
        vals = [float(v.replace(\',\', \'\'))
                for v in re.findall(r\'\\$([\\d,\\.]+)\', m.group(1))
                if 0.1 < float(v.replace(\',\', \'\')) < 800]
        years = re.findall(r\'20[2-3]\\d\', m.group(2))
        if len(vals) < 3 or len(years) < 3:
            continue
        n = min(len(vals), len(years))
        yr_map = dict(zip(years[:n], vals[:n]))
        base_year = \'2025\' if \'2025\' in yr_map else (\'2024\' if \'2024\' in yr_map else None)
        if not base_year:
            continue
        ctx = text[max(0, m.start()-200):m.end()+100]
        results.append({
            \'total_b\': yr_map[base_year], \'year\': base_year,
            \'future_values\': {y: v for y, v in yr_map.items() if int(y) > int(base_year)},
            \'opco_breakdown\': [], \'strategy\': \'dollar_series_years\',
            \'context\': ctx[:300],
        })

    # ── Strategy 4: Per-opco "Year-End Rate Base ($B) $X.X" slides ───────────
    p4 = re.compile(
        r\'(?:Year-End\\s+)?Rate\\s+Base\\s+\\(\\$B\\)\\s+\\$?\\s*([\\d,\\.]+)\',
        re.IGNORECASE
    )
    opco_vals = []
    for m in p4.finditer(text):
        val = float(m.group(1).replace(\',\', \'\'))
        if not 0.05 < val < 300:
            continue
        ctx = text[max(0, m.start()-300):m.end()+100]
        years = re.findall(r\'\\b(20[2-3]\\d)\\b\', ctx)
        year = years[0] if years else None
        opco = next((lb for lb in opco_labels if lb.lower() in ctx.lower()), None)
        if not opco:
            opco = next((k for k in keywords if k.lower() in ctx.lower()), None)
        opco_vals.append({\'opco\': opco, \'value_b\': val, \'year\': year})
    if opco_vals:
        total = round(sum(v[\'value_b\'] for v in opco_vals), 1)
        years = [v[\'year\'] for v in opco_vals if v[\'year\']]
        results.append({
            \'total_b\': total, \'year\': years[0] if years else None,
            \'future_values\': {}, \'opco_breakdown\': opco_vals,
            \'strategy\': \'regulatory_overview_slides\',
            \'context\': f\'Sum of {len(opco_vals)} opco values\',
        })

    # ── Strategy 5: Strict dollar phrase — rejects capital/invest context ─────
    # Fixes D: "$138B" (capital plan), POR: "$1.4B" (segment)
    for pat in [
        re.compile(
            r\'(?:total\\s+|projected\\s+|year.end\\s+)?rate\\s+base\\s+\'
            r\'(?:of\\s+)?(?:~\\s*)?\\$\\s*([\\d,\\.]+)\\s*(?:billion|B\\b|bn\\b)\',
            re.IGNORECASE
        ),
        re.compile(
            r\'(?:~\\s*)?\\$\\s*([\\d,\\.]+)\\s*(?:billion|B\\b|bn\\b)\\s+\'
            r\'(?:total\\s+|projected\\s+)?rate\\s+base\',
            re.IGNORECASE
        ),
    ]:
        for m in pat.finditer(text):
            val = float(m.group(1).replace(\',\', \'\'))
            if not 0.2 < val < 500:
                continue
            # Reject if "capital", "invest", "deploy", "spend" within 100 chars before
            ctx_before = text[max(0, m.start()-100):m.start()].lower()
            if any(kw in ctx_before for kw in
                   [\'capital\', \'invest\', \'deploy\', \'spend\', \'program\', \'plan\']):
                continue
            ctx = text[max(0, m.start()-150):m.end()+200]
            years = re.findall(r\'\\b(20[2-3]\\d[EF]?)\\b\', ctx)
            results.append({
                \'total_b\': val, \'year\': years[0] if years else None,
                \'future_values\': {}, \'opco_breakdown\': [],
                \'strategy\': \'dollar_rate_base_phrase\', \'context\': ctx[:250],
            })

    # ── Strategy 6: Net utility plant from balance sheet (Tier 3 fallback) ────
    bs_patterns = [
        re.compile(r\'[Rr]egulated\\s+utility\\s+plant,?\\s+net\\s+\\$?\\s*([\\d,]+)\', re.I),
        re.compile(r\'[Nn]et\\s+utility\\s+plant\\s+\\$?\\s*([\\d,]+)\', re.I),
        re.compile(r\'[Nn]et\\s+[Pp]roperty,?\\s+[Pp]lant\\s+&?\\s+[Ee]quipment\\s+\\$?\\s*([\\d,]+)\', re.I),
    ]
    for pat in bs_patterns:
        for m in pat.finditer(text):
            val_m = float(m.group(1).replace(\',\', \'\'))
            if not 100 < val_m < 500_000:
                continue
            val_b = round(val_m / 1000, 1)
            ctx = text[max(0, m.start()-100):m.end()+100]
            years = re.findall(r\'\\b(20[2-3]\\d)\\b\', ctx)
            results.append({
                \'total_b\': val_b, \'year\': years[0] if years else None,
                \'future_values\': {}, \'opco_breakdown\': [],
                \'strategy\': \'balance_sheet_net_utility_plant\',
                \'context\': \'Net utility plant (GAAP) from balance sheet\',
                \'is_tier3\': True,
            })
            break

    # ── Deduplicate and rank ──────────────────────────────────────────────────
    RANK = {
        \'total_rate_base_row\': 1,
        \'rate_base_table_header\': 2,
        \'dollar_series_years\': 2,
        \'regulatory_overview_slides\': 3,
        \'dollar_rate_base_phrase\': 4,
        \'balance_sheet_net_utility_plant\': 5,
    }
    results.sort(key=lambda r: RANK.get(r.get(\'strategy\'), 9))
    seen = set()
    unique = []
    for r in results:
        key = round(r[\'total_b\'], 0)
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique

'''

# ── Patch 2: Fix NoneType crash in main() ────────────────────────────────────
# The crash: audit[ticker] can be None if process_company returns None
# (it shouldn't per the code, but as a safety net)
OLD_CRASH = "if not (audit.get(co[\"ticker\"]) or {}).get(\"best\", {}).get(\"total_b\")]"
NEW_CRASH = '''if not ((audit.get(co["ticker"]) or {}).get("best") or {}).get("total_b")]'''

# ── Apply patches ─────────────────────────────────────────────────────────────

# Find and replace the full extract_rate_base_from_text function
fn_start = src.find("def extract_rate_base_from_text(text: str, opco_labels: list,")
if fn_start == -1:
    print("ERROR: Could not find extract_rate_base_from_text in v3 script")
    sys.exit(1)

# Find the next top-level def after it
fn_end = src.find("\ndef ", fn_start + 10)
if fn_end == -1:
    fn_end = src.find("\nclass ", fn_start + 10)
if fn_end == -1:
    print("ERROR: Could not find end of function")
    sys.exit(1)

# Reconstruct - we need to write the actual JSX without the escape issues
# Write the new function directly (not as a quoted string)
print(f"Found function at chars {fn_start}-{fn_end}")
print(f"Function length: {fn_end - fn_start} chars")

# Instead of string replacement (messy with escapes), write the patched file directly
# by splicing in the new function text
ACTUAL_NEW_FN = '''def extract_rate_base_from_text(text: str, opco_labels: list,
                                 keywords: list) -> list:
    """
    Returns list of candidate dicts sorted by strategy quality.

    Strategies (in priority order):
      1. total_rate_base_row      -- "Total Rate Base $X.X $X.X..."
      2. rate_base_table_header   -- "Rate Base ($B) 27.7 30.4..." + year sequence
         dollar_series_years      -- "$41.2 $42.8 $49.4... 2023 2024 2025..."
      3. regulatory_overview      -- "Year-End Rate Base ($B) $X.X" per opco
      4. dollar_rate_base_phrase  -- strict, rejects capital/invest context
      5. balance_sheet_nup        -- net utility plant (Tier 3 fallback)
    """
    results = []

    # ── Strategy 1: "Total Rate Base $X.X $X.X..." explicit row ──────────────
    p1 = re.compile(
        r'(?:[\w\s&]*?)?Total\s+Rate\s+Base\s*(?:\d+)?\s*'
        r'((?:\$?\s*[\d,\.]+\s*){1,8})',
        re.IGNORECASE
    )
    for m in p1.finditer(text):
        vals = []
        for v in re.findall(r'[\d,\.]+', m.group(1)):
            try:
                f = float(v.replace(',', ''))
                if 0.2 < f < 800:
                    vals.append(f)
            except ValueError:
                pass
        if not vals:
            continue
        ctx = text[max(0, m.start()-400):m.end()+200]
        years_int = sorted(set(int(y) for y in re.findall(r'\b(20[2-3]\d)\b', ctx)))
        base_year = str(years_int[0]) if years_int else None
        future = {str(int(base_year)+i): v for i, v in enumerate(vals[1:6], 1)} \
                 if base_year else {}
        results.append({
            'total_b': vals[0], 'year': base_year, 'future_values': future,
            'opco_breakdown': [], 'strategy': 'total_rate_base_row',
            'context': ctx[:300],
        })

    # ── Strategy 2a: "Rate Base ($B)" header + bare/dollar numbers + years ────
    # Catches: AEE, NEE, ETR, HE, EVRG, PCG, CMS
    # "Rate Base ($B) 27.7 30.4 33.4 2025 2026 2027"
    # "Rate Base, $ in Billions 33.6 7.6 $41.2 $42.8 $49.4 2023 2024 2025"
    header_pat = re.compile(
        r'(?:Total\s+|Projected\s+|Company\s+)?'
        r'(?:\w+\s+)?Rate\s+Base\s*(?:\d+)?\s*'
        r'(?:[,;]?\s*\$\s*in\s+[Bb]illions?'
        r'|\(\$\s*[Bb]\)'
        r'|\(\$\s*in\s+[Bb]illions?\))',
        re.IGNORECASE
    )
    for hm in header_pat.finditer(text):
        window = text[hm.end():hm.end()+400]
        # Dollar-prefixed values (higher confidence)
        dollar_vals = [float(v.replace(',', ''))
                       for v in re.findall(r'\$([\d,\.]+)', window)
                       if 0.1 < float(v.replace(',', '')) < 800]
        # Bare decimal values
        bare_vals = [float(v)
                     for v in re.findall(r'\b(\d{1,3}\.\d)\b', window)
                     if 0.1 < float(v) < 800]
        all_vals = dollar_vals if dollar_vals else bare_vals
        years = re.findall(r'\b(20[2-3]\d)\b', window)
        if not all_vals or not years:
            continue
        n = min(len(all_vals), len(years))
        yr_map = dict(zip(years[:n], all_vals[:n]))
        base_year = '2025' if '2025' in yr_map else ('2024' if '2024' in yr_map else None)
        if not base_year:
            continue
        future = {y: v for y, v in yr_map.items() if int(y) > int(base_year)}
        ctx = text[max(0, hm.start()-100):hm.end()+300]
        results.append({
            'total_b': yr_map[base_year], 'year': base_year,
            'future_values': future, 'opco_breakdown': [],
            'strategy': 'rate_base_table_header', 'context': ctx[:300],
        })

    # ── Strategy 2b: "$X.X $X.X $X.X... YEAR YEAR" dollar series + years ─────
    # Catches EIX: "$41.2 $42.8 $49.4 $53.0 2023 2024 2025 2026"
    dollar_series_pat = re.compile(
        r'(\$[\d,\.]+(?:\s+\$[\d,\.]+){2,})'
        r'\s+'
        r'(20[2-3]\d(?:\s+20[2-3]\d)+)',
    )
    for m in dollar_series_pat.finditer(text):
        vals = [float(v.replace(',', ''))
                for v in re.findall(r'\$([\d,\.]+)', m.group(1))
                if 0.1 < float(v.replace(',', '')) < 800]
        years = re.findall(r'20[2-3]\d', m.group(2))
        if len(vals) < 3 or len(years) < 3:
            continue
        n = min(len(vals), len(years))
        yr_map = dict(zip(years[:n], vals[:n]))
        base_year = '2025' if '2025' in yr_map else ('2024' if '2024' in yr_map else None)
        if not base_year:
            continue
        ctx = text[max(0, m.start()-200):m.end()+100]
        results.append({
            'total_b': yr_map[base_year], 'year': base_year,
            'future_values': {y: v for y, v in yr_map.items() if int(y) > int(base_year)},
            'opco_breakdown': [], 'strategy': 'dollar_series_years',
            'context': ctx[:300],
        })

    # ── Strategy 3: Per-opco "Year-End Rate Base ($B) $X.X" slides ───────────
    p3 = re.compile(
        r'(?:Year-End\s+)?Rate\s+Base\s+\(\$B\)\s+\$?\s*([\d,\.]+)',
        re.IGNORECASE
    )
    opco_vals = []
    for m in p3.finditer(text):
        val = float(m.group(1).replace(',', ''))
        if not 0.05 < val < 300:
            continue
        ctx = text[max(0, m.start()-300):m.end()+100]
        years = re.findall(r'\b(20[2-3]\d)\b', ctx)
        year = years[0] if years else None
        opco = next((lb for lb in opco_labels if lb.lower() in ctx.lower()), None)
        if not opco:
            opco = next((k for k in keywords if k.lower() in ctx.lower()), None)
        opco_vals.append({'opco': opco, 'value_b': val, 'year': year})
    if opco_vals:
        total = round(sum(v['value_b'] for v in opco_vals), 1)
        years = [v['year'] for v in opco_vals if v['year']]
        results.append({
            'total_b': total, 'year': years[0] if years else None,
            'future_values': {}, 'opco_breakdown': opco_vals,
            'strategy': 'regulatory_overview_slides',
            'context': f'Sum of {len(opco_vals)} opco values',
        })

    # ── Strategy 4: Strict dollar phrase — rejects capital/invest context ─────
    for pat in [
        re.compile(
            r'(?:total\s+|projected\s+|year.end\s+)?rate\s+base\s+'
            r'(?:of\s+)?(?:~\s*)?\$\s*([\d,\.]+)\s*(?:billion|B\b|bn\b)',
            re.IGNORECASE
        ),
        re.compile(
            r'(?:~\s*)?\$\s*([\d,\.]+)\s*(?:billion|B\b|bn\b)\s+'
            r'(?:total\s+|projected\s+)?rate\s+base',
            re.IGNORECASE
        ),
    ]:
        for m in pat.finditer(text):
            val = float(m.group(1).replace(',', ''))
            if not 0.2 < val < 500:
                continue
            # Reject if capital/invest/deploy/spend within 100 chars before
            ctx_before = text[max(0, m.start()-100):m.start()].lower()
            if any(kw in ctx_before for kw in
                   ['capital', 'invest', 'deploy', 'spend', 'program', 'plan']):
                continue
            ctx = text[max(0, m.start()-150):m.end()+200]
            years = re.findall(r'\b(20[2-3]\d[EF]?)\b', ctx)
            results.append({
                'total_b': val, 'year': years[0] if years else None,
                'future_values': {}, 'opco_breakdown': [],
                'strategy': 'dollar_rate_base_phrase', 'context': ctx[:250],
            })

    # ── Strategy 5: Net utility plant from balance sheet (Tier 3 fallback) ────
    bs_patterns = [
        re.compile(r'[Rr]egulated\s+utility\s+plant,?\s+net\s+\$?\s*([\d,]+)', re.I),
        re.compile(r'[Nn]et\s+utility\s+plant\s+\$?\s*([\d,]+)', re.I),
        re.compile(r'[Nn]et\s+[Pp]roperty,?\s+[Pp]lant\s+&?\s+[Ee]quipment\s+\$?\s*([\d,]+)', re.I),
    ]
    for pat in bs_patterns:
        for m in pat.finditer(text):
            val_m = float(m.group(1).replace(',', ''))
            if not 100 < val_m < 500_000:
                continue
            val_b = round(val_m / 1000, 1)
            ctx = text[max(0, m.start()-100):m.end()+100]
            years = re.findall(r'\b(20[2-3]\d)\b', ctx)
            results.append({
                'total_b': val_b, 'year': years[0] if years else None,
                'future_values': {}, 'opco_breakdown': [],
                'strategy': 'balance_sheet_net_utility_plant',
                'context': 'Net utility plant (GAAP) from balance sheet',
                'is_tier3': True,
            })
            break

    # ── Deduplicate and rank ──────────────────────────────────────────────────
    RANK = {
        'total_rate_base_row': 1,
        'rate_base_table_header': 2,
        'dollar_series_years': 2,
        'regulatory_overview_slides': 3,
        'dollar_rate_base_phrase': 4,
        'balance_sheet_net_utility_plant': 5,
    }
    results.sort(key=lambda r: RANK.get(r.get('strategy'), 9))
    seen = set()
    unique = []
    for r in results:
        key = round(r['total_b'], 0)
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique

'''

# Write patched file
patched = src[:fn_start] + ACTUAL_NEW_FN + src[fn_end:]

# Patch 2: fix NoneType crash
patched = patched.replace(
    'if not (audit.get(co["ticker"]) or {}).get("best", {}).get("total_b")]',
    'if not ((audit.get(co["ticker"]) or {}).get("best") or {}).get("total_b")]'
)

V3_PATH.write_text(patched, encoding="utf-8")
print(f"[OK] Patched {V3_PATH}")
print(f"     New file: {len(patched):,} chars")

# Verify
verify = V3_PATH.read_text(encoding="utf-8")
checks = {
    "rate_base_table_header strategy": "'rate_base_table_header'" in verify,
    "dollar_series_years strategy":    "'dollar_series_years'" in verify,
    "capital context rejection":       "'capital', 'invest', 'deploy'" in verify,
    "NoneType crash fix":              '((audit.get(co["ticker"]) or {}).get("best") or {})' in verify,
    "extract fn still present":        "def extract_rate_base_from_text" in verify,
}
print("\nVerification:")
for label, ok in checks.items():
    print(f"  {'[OK]  ' if ok else '[FAIL]'} {label}")

if all(checks.values()):
    print("\n[OK] All patches applied. Run: python fetch_edgar_rate_base_v3.py")
    print("     EIX/NEE/ETR/AEE/HE/EVRG/PCG should now extract correctly.")
    print("     D and POR false positives fixed by capital-context filter.")
else:
    print("\n[WARN] Some patches may not have applied. Review manually.")

if "--run" in sys.argv:
    print("\nRunning v3 script...")
    import subprocess
    subprocess.run([sys.executable, str(V3_PATH)], check=True)