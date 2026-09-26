"""check_sec_vs_ferc.py - tie SEC 10-K opco net income (sec_opco.json, $M) to FERC Form 1
net income (ferc_opco.json, $000) for every co-registrant opco and year both carry.
Writes data\_qc\sec_vs_ferc_<date>.json and prints the breaks over the tolerance.
GAAP vs FERC-basis differences are EXPECTED for some filers (regulatory accounting,
equity in subsidiaries, SCE wildfire charges); the report classifies, it does not fix.
    python scripts\\check_sec_vs_ferc.py [--tol 1.0]
"""
import json, re, sys, datetime, pathlib
DATA = pathlib.Path(r'E:\PowerAcademy\data') if sys.platform == 'win32' else pathlib.Path('.')
TOL = float(sys.argv[sys.argv.index('--tol') + 1]) if '--tol' in sys.argv else 1.0
ALIAS = {  # SEC name -> FERC respondent name (renamed entities)
    'dominion energy south carolina': 'south carolina electric gas',
    'evergy kansas central': 'westar energy',
    'evergy metro': 'kansas city power light',
}
def n(x):
    x = re.sub(r'\(.*?\)', '', x.lower())
    x = re.sub(r'\b(company|co|inc|corporation|corp|llc|the)\b|[.,&]', ' ', x)
    return ' '.join(x.split())
sec = json.loads((DATA / 'sec_opco.json').read_text(encoding='utf-8'))
ferc = json.loads((DATA / 'ferc_opco.json').read_text(encoding='utf-8'))['opcos']
fx = {(t, n(o['ferc_name'])): o for t, L in ferc.items() for o in L}
rows, unmatched = [], []
for t, v in sec['tickers'].items():
    for e in v['entities']:
        if e['role'] == 'parent':
            continue
        key = n(e['name']); key = ALIAS.get(key, key)
        fo = fx.get((t, key))
        if not fo:
            unmatched.append(f"{t} {e['name']}"); continue
        for y, sv in (e['metrics'].get('net_income') or {}).items():
            fy = (fo['years'].get(y) or {}).get('net_income_k')
            if sv is None or fy is None:
                continue
            fm = fy / 1000.0
            d = (sv - fm) / abs(fm) * 100 if fm else None
            rows.append({'ticker': t, 'opco': e['name'], 'year': int(y), 'sec_ni_m': round(sv, 1),
                         'ferc_ni_m': round(fm, 1), 'diff_pct': None if d is None else round(d, 2)})
breaks = [r for r in rows if r['diff_pct'] is None or abs(r['diff_pct']) > TOL]
out = {'_generated': datetime.date.today().isoformat(), '_tolerance_pct': TOL,
       'pairs': len(rows), 'within': len(rows) - len(breaks), 'breaks': breaks,
       'unmatched_sec_entities': unmatched,
       'by_year': {y: {'pairs': sum(r['year'] == y for r in rows), 'breaks': sum(r['year'] == y for r in breaks)}
                   for y in sorted({r['year'] for r in rows})}}
(DATA / '_qc').mkdir(exist_ok=True)
(DATA / '_qc' / f"sec_vs_ferc_{out['_generated']}.json").write_text(json.dumps(out, indent=2), encoding='utf-8')
print(f"{out['pairs']} opco-years, {out['within']} within {TOL}%")
for y, c in out['by_year'].items(): print(f'  {y}: {c["pairs"]} pairs, {c["breaks"]} breaks')
for b in sorted(breaks, key=lambda r: (r['ticker'], r['opco'], r['year'])):
    print(f"  {b['ticker']:5} {b['opco'][:38]:38} {b['year']}  SEC {b['sec_ni_m']:>9}  FERC {b['ferc_ni_m']:>9}  {b['diff_pct']:+.1f}%")
print('unmatched:', unmatched)
