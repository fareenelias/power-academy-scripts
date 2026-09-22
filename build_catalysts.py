"""build_catalysts.py - assemble data\catalysts.json from event streams already on disk.

Streams (no new sources, no network):
  1. earnings_calls.json  -> earnings-call events, DAY precision (call_date), with the
     guidance action carried into the label when the call recorded one.
  2. capiq_export.json past_rate_cases -> rate-case DECISION events, MONTH precision
     (decision_date is 'MM/YYYY'; plotted at the 15th, precision flagged).
  3. capiq_export.json pending_rate_cases -> rate-case FILING events, MONTH precision.
  4. capiq_export.json ma_history -> M&A announcements, MONTH precision.
  5. live_deals.json -> live-deal announcements, DAY precision.

Rules stated once, applied everywhere:
  - MONTH-precision dates plot at day 15 and carry precision:'month' - the UI must
    render them as approximate, never as a day-exact event.
  - Cutoff 2020-01-01: the chart holds ~5y of price history; older events can never render.
  - Dedup: a capiq ma_history row is DROPPED when a live_deals event for the same ticker
    lands in the same calendar month - the live deal is day-precise and curated, the
    CapIQ row is the same announcement at month precision.
  - This file is derived - regenerate after extract_all.py updates capiq_export.json
    or after new call notes land. Never hand-edit.

Served at /api/eia/catalysts.json by the generic DATA_DIR route (no server change).
"""
import json, os, sys, re
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CUTOFF = '2020-01-01'

def load(name):
    with open(os.path.join(DATA, name), encoding='utf-8') as f:
        return json.load(f)

def mm_yyyy_to_date(s):
    """'MM/YYYY' -> 'YYYY-MM-15' or None. Anything else refused (never guessed)."""
    if not isinstance(s, str): return None
    m = re.fullmatch(r'(\d{1,2})/(\d{4})', s.strip())
    if not m: return None
    mo, yr = int(m.group(1)), int(m.group(2))
    if not (1 <= mo <= 12 and 1990 <= yr <= 2035): return None
    return f'{yr:04d}-{mo:02d}-15'

def is_day(s):
    return isinstance(s, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', s) is not None

events = defaultdict(list)
counts = defaultdict(int)

# ── 1. earnings calls ────────────────────────────────────────────────────────
ec = load('earnings_calls.json')
for tkr, arr in ec['calls'].items():
    for c in arr:
        d = c.get('call_date')
        if not is_day(d) or d < CUTOFF: continue
        ga = c.get('guidance_action')
        sub = None
        if isinstance(ga, dict):
            sub = ga.get('action') or None
        elif isinstance(ga, str) and ga.strip():
            sub = ga.strip()
        label = c.get('period') or 'Earnings call'
        ct = (c.get('call_type') or '').lower()
        if 'earning' in ct or not ct:
            label = f'{label} earnings call'
        events[tkr].append({
            'date': d, 'precision': 'day', 'cat': 'earnings',
            'label': label, 'sub': sub,
            'url_path': c.get('source_url_path') or None,
        })
        counts['earnings'] += 1

# ── 2-4. capiq streams ───────────────────────────────────────────────────────
cap = load('capiq_export.json')['companies']
for tkr, c in cap.items():
    for rc in (c.get('past_rate_cases') or []):
        d = mm_yyyy_to_date(rc.get('decision_date'))
        if not d or d < CUTOFF: continue
        roe = rc.get('auth_roe')
        bits = [b for b in [rc.get('decision_type'),
                            (f'ROE {roe}%' if isinstance(roe, (int, float)) else None)] if b]
        events[tkr].append({
            'date': d, 'precision': 'month', 'cat': 'rate_case',
            'label': f"{rc.get('state','?')} {rc.get('service_type','')} rate case decided".replace('  ', ' '),
            'sub': ' - '.join([rc.get('docket') or '', ', '.join(bits)]).strip(' -') or None,
        })
        counts['rate_case_decided'] += 1
    for rc in (c.get('pending_rate_cases') or []):
        d = mm_yyyy_to_date(rc.get('filing_date'))
        if not d or d < CUTOFF: continue
        events[tkr].append({
            'date': d, 'precision': 'month', 'cat': 'rate_case',
            'label': f"{rc.get('state','?')} {rc.get('service_type','')} rate case filed".replace('  ', ' '),
            'sub': rc.get('docket') or None,
        })
        counts['rate_case_filed'] += 1
    for ma in (c.get('ma_history') or []):
        d = mm_yyyy_to_date(ma.get('announced'))
        if not d or d < CUTOFF: continue
        v = ma.get('value_m')
        events[tkr].append({
            'date': d, 'precision': 'month', 'cat': 'ma',
            'label': f"{ma.get('acq_or_sale') or 'M&A'}: {ma.get('target') or '?'}",
            'sub': (f"${v:,.0f}M" if isinstance(v, (int, float)) else None),
            '_capiq_ma': True,
        })
        counts['ma_capiq'] += 1

# ── 5. live deals (day-precise, curated) ─────────────────────────────────────
ld = load('live_deals.json')
for deal in ld['deals']:
    d = deal.get('announced')
    if not is_day(d) or d < CUTOFF: continue
    for tkr in deal.get('tickers') or []:
        events[tkr].append({
            'date': d, 'precision': 'day', 'cat': 'ma',
            'label': deal.get('headline') or 'Live deal announced',
            'sub': deal.get('status') or None,
        })
        counts['ma_live'] += 1

# ── dedup: drop capiq ma rows in the same ticker-month as a live-deal event ──
dropped = 0
for tkr, arr in events.items():
    live_months = {e['date'][:7] for e in arr if e['cat'] == 'ma' and not e.get('_capiq_ma')}
    keep = []
    for e in arr:
        if e.pop('_capiq_ma', False) and e['date'][:7] in live_months:
            dropped += 1; continue
        keep.append(e)
    keep.sort(key=lambda e: e['date'])
    events[tkr] = keep

# ── controls - refuse to write a file that fails any of them ─────────────────
UNIVERSE = ['NEE','D','ETR','CMS','PPL','AEE','POR','EIX','PCG','HE','EVRG','ES','VST','TLN',
            'XIFR','AWR','CWT','YORW','GWRS','AWK','WTRG','HTO','MSEX','AQN']
for t in UNIVERSE:
    events.setdefault(t, [])   # every coverage name present, even if empty
total = sum(len(v) for v in events.values())
assert total > 100, f'implausibly few events ({total}) - a stream failed silently'
for tkr, arr in events.items():
    for e in arr:
        assert is_day(e['date']), (tkr, e)
        assert CUTOFF <= e['date'] <= '2027-12-31', (tkr, e)
        assert e['cat'] in ('earnings', 'rate_case', 'ma'), (tkr, e)
        assert e['precision'] in ('day', 'month'), (tkr, e)
# earnings stream sanity: every ticker with calls on disk got at least one event
ec_tickers = {t for t, a in ec['calls'].items() if a}
missing = [t for t in ec_tickers if not any(e['cat'] == 'earnings' for e in events[t])]
assert not missing, f'call-note tickers with no earnings events: {missing}'

out = {
    '_schema_version': '1.0',
    '_note': ('Catalyst event streams for the stock-chart annotation layer. DERIVED file - '
              'regenerate with scripts/build_catalysts.py after extract_all.py or new call '
              'notes; never hand-edit. month-precision events plot at day 15 and MUST render '
              'as approximate. CapIQ ma_history rows are dropped when a curated live_deals '
              'event for the same ticker lands in the same month.'),
    'categories': {
        'earnings': {'label': 'Earnings call', 'glyph': 'E'},
        'rate_case': {'label': 'Rate case', 'glyph': 'R'},
        'ma': {'label': 'M&A', 'glyph': 'M'},
    },
    'events': {t: events[t] for t in sorted(events)},
}
path = os.path.join(DATA, 'catalysts.json')
with open(path, 'w', encoding='utf-8') as f:
    json.dump(out, f, indent=1, ensure_ascii=False)

print(f'wrote {path}')
print(f'total events: {total} across {len(events)} tickers | capiq-ma dropped as live-deal dupes: {dropped}')
for k in sorted(counts): print(f'  {k}: {counts[k]}')
for t in sorted(events): print(f'  {t}: {len(events[t])}')
