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
# Breaks read against the source and explained - kept in the report, tagged so they stop reading as open.
EXPLAINED = {
    ('NEE', 'florida power light', 2019): 'Gulf Power restatement (confirmed 2026-09-26 off the FY2021 10-K segment table): the SEC '
        'figure is FPL consolidated incl. Gulf Power (2,519 = FPL segment 2,334 + Gulf 180 + other 5); the FPL segment alone '
        '(2,334) ties to FERC. FERC Form 1 is FPL-only for 2019.',
    ('NEE', 'florida power light', 2020): 'Gulf Power restatement (confirmed 2026-09-26 off the FY2021 10-K segment table): the SEC '
        'figure is FPL consolidated incl. Gulf Power (2,890 = FPL segment 2,650 + Gulf 238 + other 2); the FPL segment alone '
        '(2,650) ties to FERC. FERC Form 1 is FPL-only for 2020.',
}
# 2026-09-26: re-read against the as-filed FERC Form 1 XBRL (PUDL out_ferc1__yearly_income_statements_sched114): the FERC side of
# every break below equals the filed Form 1 net income exactly, so neither file is wrong - these are GAAP (10-K) vs FERC (Form 1)
# basis differences. The ROE Gap uses the FERC basis throughout.
_BASIS = ('Both figures verified as filed (FERC side = Form 1 XBRL via PUDL, sched. 114 net income; SEC side = 10-K XBRL). A GAAP vs '
          'FERC-basis difference, not a data error. Form 1 carries large regulatory credits in these years ({rc}), which GAAP books '
          'differently; the ROE Gap uses the FERC basis.')
for _k, _rc in {('EVRG', 'evergy kansas central', 2020): '$60.5M', ('EVRG', 'evergy kansas central', 2021): '$75.5M', ('EVRG', 'evergy kansas central', 2022): '$64.5M',
                ('EVRG', 'evergy metro', 2020): '$197.1M', ('EVRG', 'evergy metro', 2021): '$272.1M',
                ('EVRG', 'evergy metro', 2022): '$309.4M',
                ('D', 'virginia electric and power', 2021): '$931.3M', ('D', 'virginia electric and power', 2022): '$574.6M'}.items():
    EXPLAINED[_k] = _BASIS.format(rc='regulatory credits ' + _rc)
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
for r in breaks:
    why = EXPLAINED.get((r['ticker'], n(r['opco']), r['year']))
    if why: r['explained'] = why
out = {'_generated': datetime.date.today().isoformat(), '_tolerance_pct': TOL,
       'pairs': len(rows), 'within': len(rows) - len(breaks), 'breaks': breaks,
       'explained': sum(1 for r in breaks if r.get('explained')),
       'unmatched_sec_entities': unmatched,
       'by_year': {y: {'pairs': sum(r['year'] == y for r in rows), 'breaks': sum(r['year'] == y for r in breaks)}
                   for y in sorted({r['year'] for r in rows})}}
(DATA / '_qc').mkdir(exist_ok=True)
(DATA / '_qc' / f"sec_vs_ferc_{out['_generated']}.json").write_text(json.dumps(out, indent=2), encoding='utf-8')
print(f"{out['pairs']} opco-years, {out['within']} within {TOL}%")
for y, c in out['by_year'].items(): print(f'  {y}: {c["pairs"]} pairs, {c["breaks"]} breaks')
for b in sorted(breaks, key=lambda r: (r['ticker'], r['opco'], r['year'])):
    print(f"  {b['ticker']:5} {b['opco'][:38]:38} {b['year']}  SEC {b['sec_ni_m']:>9}  FERC {b['ferc_ni_m']:>9}  {b['diff_pct']:+.1f}%{'  [explained]' if b.get('explained') else ''}")
print('unmatched:', unmatched)
