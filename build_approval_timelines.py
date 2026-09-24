# -*- coding: utf-8 -*-
"""build_approval_timelines.py - data\\approval_timelines.json (roadmap I.D 'historical approval timelines').

Observed filing->decision durations by state, off every past rate case CapIQ printed for the
coverage names (capiq_export.json past_rate_cases, ~1,260 cases). Complements the RRA
'rate_case_timing' bullets (statutory deadlines) with what actually happened.

Per state (RRA code; Entergy New Orleans cases go to New_Orleans):
  n cases · median / mean / p25 / p75 months · by era (filed <= 2021 vs >= 2022) · by service type ·
  by case_type · settled vs litigated share · median ask-granted % (auth_revenue / req_revenue) ·
  median ROE haircut bps (req_roe - auth_roe) · per utility (n, median months) · the five longest
  cases with docket ids. Dates are CapIQ's MM/YYYY, so a duration is month-granular.
Caveats printed into the file: CapIQ 'rate cases' include riders / formula-rate reviews / fuel
clauses where the state files them as cases (VA's 234 are mostly VEPCO+APCo riders), so the
case_type split matters more than the headline median; only coverage-name cases are here, so a
state's number describes OUR names' experience, not the commission's whole docket.

  python build_approval_timelines.py [--dry]
"""
import io, os, re, sys, json, collections, datetime, statistics

DATA_DIR = r'E:\PowerAcademy\data' if os.name == 'nt' else \
    os.path.join(os.path.expanduser('~'), 'mnt', 'PowerAcademy', 'data')


def load(name):
    p = os.path.join(DATA_DIR, name)
    return json.load(io.open(p, encoding='utf-8')) if os.path.exists(p) else None


def med(v): v = [x for x in v if isinstance(x, (int, float))]; return round(statistics.median(v), 1) if v else None
def mean(v): v = [x for x in v if isinstance(x, (int, float))]; return round(sum(v) / len(v), 1) if v else None
def pct(v, q):
    v = sorted(x for x in v if isinstance(x, (int, float)))
    if not v: return None
    k = (len(v) - 1) * q; f = int(k); c = min(f + 1, len(v) - 1)
    return round(v[f] + (v[c] - v[f]) * (k - f), 1)


def year_of(s):
    m = re.search(r'(\d{4})', str(s or '')); return int(m.group(1)) if m else None


def stats(cases):
    d = [c['duration_months'] for c in cases]
    settled = sum(1 for c in cases if 'settl' in str(c.get('decision_type') or '').lower())
    typed = sum(1 for c in cases if c.get('decision_type'))
    # a printed 0 authorised revenue on a positive ask is usually CapIQ's 'not disclosed' (LA formula-rate plans), not a zero award - excluded and counted
    ask = [100.0 * c['auth_revenue'] / c['req_revenue'] for c in cases
           if isinstance(c.get('auth_revenue'), (int, float)) and c['auth_revenue'] != 0 and isinstance(c.get('req_revenue'), (int, float)) and c['req_revenue'] > 0]
    zero_auth = sum(1 for c in cases if c.get('auth_revenue') == 0 and isinstance(c.get('req_revenue'), (int, float)) and c['req_revenue'] > 0)
    hair = [round((c['req_roe'] - c['auth_roe']) * 100) for c in cases
            if isinstance(c.get('req_roe'), (int, float)) and isinstance(c.get('auth_roe'), (int, float))]
    return collections.OrderedDict([
        ('n', len(cases)), ('median_months', med(d)), ('mean_months', mean(d)), ('p25_months', pct(d, 0.25)), ('p75_months', pct(d, 0.75)),
        ('settled_pct', round(100.0 * settled / typed) if typed else None), ('n_with_decision_type', typed),
        ('median_ask_granted_pct', med(ask)), ('n_ask_granted', len(ask)), ('n_zero_auth_excluded', zero_auth),
        ('median_roe_haircut_bps', med(hair)), ('n_roe_haircut', len(hair)),
    ])


def build():
    cq = (load('capiq_export.json') or {}).get('companies') or {}
    rra = load('rra_states.json') or {}
    names = {v: k for k, v in (rra.get('state_names') or {}).items()}   # 'Virginia' -> 'VA'
    by_state = collections.defaultdict(list)
    skipped = collections.Counter()
    for t, co in cq.items():
        for c in co.get('past_rate_cases') or []:
            if not isinstance(c.get('duration_months'), (int, float)) or c['duration_months'] < 0: skipped['no_duration'] += 1; continue
            st = c.get('state')
            code = names.get(st)
            if st == 'Louisiana' and 'new orleans' in str(c.get('company') or '').lower(): code = 'New_Orleans'
            if not code: skipped['state:' + str(st)] += 1; continue
            cc = dict(c); cc['ticker'] = t; cc['filed_year'] = year_of(c.get('filing_date'))
            by_state[code].append(cc)
    out = collections.OrderedDict()
    out['_schema_version'] = '1.0'
    out['_generated'] = datetime.date.today().isoformat()
    out['_source'] = 'capiq_export.json past_rate_cases (CapIQ Past Rate Cases sheet per coverage name); durations are CapIQ duration_months on MM/YYYY dates'
    out['_caveats'] = [
        "CapIQ 'rate cases' include riders, formula-rate reviews and fuel/cost-recovery filings where the state dockets them as cases - read the case_type split before quoting a state median.",
        "Only the coverage names' cases are here: a state figure is OUR names' experience in that commission, not the commission's whole docket.",
        "Era split: filed <= 2021 vs >= 2022 (the tracker's pre/post-2022 reg-lag split).",
    ]
    out['_skipped'] = dict(skipped)
    out['states'] = collections.OrderedDict()
    for code in sorted(by_state):
        cs = by_state[code]
        rec = collections.OrderedDict()
        rec['all'] = stats(cs)
        rec['general_rate_cases'] = stats([c for c in cs if str(c.get('case_type') or '') in ('Vertically Integrated', 'Distribution', 'Transmission')])
        rec['riders_and_other'] = stats([c for c in cs if str(c.get('case_type') or '') not in ('Vertically Integrated', 'Distribution', 'Transmission')])
        rec['by_era'] = collections.OrderedDict([
            ('filed_to_2021', stats([c for c in cs if c['filed_year'] and c['filed_year'] <= 2021])),
            ('filed_2022_on', stats([c for c in cs if c['filed_year'] and c['filed_year'] >= 2022])),
        ])
        for key, label in [('service_type', 'by_service'), ('case_type', 'by_case_type')]:
            g = collections.defaultdict(list)
            for c in cs: g[str(c.get(key) or 'unstated')].append(c)
            rec[label] = collections.OrderedDict((k, stats(v)) for k, v in sorted(g.items(), key=lambda kv: -len(kv[1])))
        g = collections.defaultdict(list)
        for c in cs: g[(c['ticker'], str(c.get('company') or ''))].append(c)
        rec['by_utility'] = [collections.OrderedDict([('ticker', k[0]), ('company', k[1]), ('n', len(v)), ('median_months', med([x['duration_months'] for x in v])),
                                                      ('latest_decision', max((x.get('decision_date') or '') for x in v))])
                             for k, v in sorted(g.items(), key=lambda kv: -len(kv[1]))]
        longest = sorted(cs, key=lambda c: -c['duration_months'])[:5]
        rec['longest'] = [collections.OrderedDict([('ticker', c['ticker']), ('company', c.get('company')), ('docket', c.get('docket')), ('case_type', c.get('case_type')),
                                                   ('filed', c.get('filing_date')), ('decided', c.get('decision_date')), ('months', c['duration_months']), ('decision_type', c.get('decision_type'))])
                          for c in longest]
        out['states'][code] = rec
    return out


if __name__ == '__main__':
    doc = build()
    for code, r in doc['states'].items():
        a = r['all']; e1 = r['by_era']['filed_to_2021']; e2 = r['by_era']['filed_2022_on']
        print(f"{code:12} n={a['n']:3} med={str(a['median_months']):5} p25-75={a['p25_months']}-{a['p75_months']}  era≤21 {str(e1['median_months']):5} ≥22 {str(e2['median_months']):5}  settled={a['settled_pct']}%  ask-granted={a['median_ask_granted_pct']}%  ROE haircut={a['median_roe_haircut_bps']}bps  types={list(r['by_case_type'])[:3]}")
    print('skipped', doc['_skipped'])
    if '--dry' not in sys.argv:
        p = os.path.join(DATA_DIR, 'approval_timelines.json')
        io.open(p, 'w', encoding='utf-8').write(json.dumps(doc, indent=1, ensure_ascii=False)); json.load(io.open(p, encoding='utf-8'))
        print('wrote', p)
