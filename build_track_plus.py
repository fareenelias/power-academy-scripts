r"""build_track_plus.py - guidance track record beyond EPS (tracker 493) -> data\track_plus.json

1. LT EPS growth promise vs delivery: the long-term growth range printed in the Q4 deck of year Y
   (guidance_history.json lt_eps_growth) vs the delivered adjusted-EPS CAGR from Y-actual to the latest actual
   (track_record.json actuals = CapIQ 'EPS Normalized', available 2023+). Verdict: above / within / below the range.
2. Dividend delivery: annualised dividend printed in each Q4 deck (dividend_guidance.current_annual), its CAGR,
   any cut, and the gap to the LT EPS growth midpoint (dividends usually promised 'in line with earnings').
3. Rate-base growth promise vs the promise restated later: first printed rate-base CAGR and window vs the latest
   printed (a raise/cut signal, not a realised rate-base measurement - utilities do not print a comparable actual).
Capex-vs-plan delivery is in cashflow_vs_plan.json already and is not repeated here.

    python scripts\build_track_plus.py [data_dir]
"""
import sys, os, json, datetime

DATA = sys.argv[1] if len(sys.argv) > 1 else r'E:\PowerAcademy\data'


def pk(p):
    try:
        q, y = p.split(); return int(y) * 10 + int(q[1])
    except Exception:
        return -1


def main():
    gh = json.load(open(os.path.join(DATA, 'guidance_history.json'), encoding='utf-8'))
    tr = json.load(open(os.path.join(DATA, 'track_record.json'), encoding='utf-8'))['tickers']
    out = {}
    for t, tobj in sorted(gh.items()):
        if t.startswith('_') or not isinstance(tobj, dict): continue
        per = sorted([p for p in tobj if not p.startswith('_') and pk(p) > 0], key=pk)
        q4 = [p for p in per if p.startswith('Q4')]
        acts = {y['year']: y['actual']['eps'] for y in (tr.get(t) or {}).get('eps_track', []) if isinstance(y.get('actual'), dict) and y['actual'].get('eps')}
        rec = {}
        # 1. LT EPS growth
        eps = []
        for p in q4:
            y = int(p.split()[1]); lt = tobj[p].get('lt_eps_growth') or {}
            lo, hi = lt.get('rate_low_pct'), lt.get('rate_high_pct')
            if lo is None or hi is None or y not in acts: continue
            later = [yy for yy in acts if yy > y]
            if not later or max(later) - y < 2: continue   # one-year windows are noise
            ye = max(later); n = ye - y
            cagr = 100 * ((acts[ye] / acts[y]) ** (1 / n) - 1)
            verdict = 'above' if cagr > hi + 0.05 else 'below' if cagr < lo - 0.05 else 'within'
            eps.append({'promised_in': p, 'range_pct': [lo, hi], 'base_year': y, 'base_eps': acts[y], 'end_year': ye, 'end_eps': acts[ye],
                        'delivered_cagr_pct': round(cagr, 1), 'verdict': verdict, 'source_url': tobj[p].get('source_url'), 'source_page': lt.get('source_page')})
        if eps: rec['lt_eps_growth'] = eps
        # 2. dividend
        dv = [(p, (tobj[p].get('dividend_guidance') or {}).get('current_annual'), (tobj[p].get('dividend_guidance') or {}).get('source_page'), tobj[p].get('source_url')) for p in q4]
        dv = [x for x in dv if isinstance(x[1], (int, float)) and x[1] > 0]
        if len(dv) >= 2:
            (p0, d0, _, _), (p1, d1, pg1, u1) = dv[0], dv[-1]
            n = int(p1.split()[1]) - int(p0.split()[1])
            cuts = [f'{dv[i][0]} {dv[i-1][1]}->{dv[i][1]}' for i in range(1, len(dv)) if dv[i][1] < dv[i - 1][1] - 1e-9]
            lt = (tobj[p1].get('lt_eps_growth') or {})
            mid = (lt['rate_low_pct'] + lt['rate_high_pct']) / 2 if lt.get('rate_low_pct') is not None and lt.get('rate_high_pct') is not None else None
            cg = 100 * ((d1 / d0) ** (1 / n) - 1) if n > 0 else None
            rec['dividend'] = {'series': [{'period': p, 'annual_dps': d} for p, d, _, _ in dv], 'cagr_pct': round(cg, 1) if cg is not None else None,
                               'years': n, 'cuts': cuts, 'lt_eps_growth_mid_pct': mid,
                               'gap_to_eps_growth_pp': round(cg - mid, 1) if cg is not None and mid is not None else None,
                               'latest_source_url': u1, 'latest_source_page': pg1}
        # 3. rate base promise drift
        rb = [(p, tobj[p].get('rate_base_cagr') or {}) for p in per]
        rb = [(p, x) for p, x in rb if isinstance(x.get('rate_pct'), (int, float))]
        if len(rb) >= 2:
            f, l = rb[0], rb[-1]
            w = lambda x: f"{x.get('from_year')}-{x.get('to_year')}" if x.get('from_year') else None
            rec['rate_base_promise'] = {'first': {'period': f[0], 'rate_pct': f[1]['rate_pct'], 'window': w(f[1]), 'source_url': tobj[f[0]].get('source_url'), 'source_page': f[1].get('source_page')},
                                        'latest': {'period': l[0], 'rate_pct': l[1]['rate_pct'], 'window': w(l[1]), 'source_url': tobj[l[0]].get('source_url'), 'source_page': l[1].get('source_page')},
                                        'change_pp': round(l[1]['rate_pct'] - f[1]['rate_pct'], 1)}
        if rec: out[t] = rec
        e = rec.get('lt_eps_growth', [])
        print(f"{t:5} eps {[ (x['promised_in'], x['range_pct'], x['delivered_cagr_pct'], x['verdict']) for x in e][:2]}  div {rec.get('dividend',{}).get('cagr_pct')} cuts {rec.get('dividend',{}).get('cuts')}  rb {rec.get('rate_base_promise',{}).get('change_pp')}")
    doc = {'_schema_version': '1.0', '_generated': datetime.date.today().isoformat(), '_method': __doc__.split('    python')[0].strip(),
           '_caveat': 'Adjusted-EPS actuals start 2023 (CapIQ EPS Normalized), so delivered EPS CAGRs cover at most 2023-2025. Rate-base rows compare promises, not a realised rate base.',
           'names': out}
    json.dump(doc, open(os.path.join(DATA, 'track_plus.json'), 'w', encoding='utf-8'), indent=1)
    print('wrote track_plus.json', len(out))


if __name__ == '__main__':
    main()
