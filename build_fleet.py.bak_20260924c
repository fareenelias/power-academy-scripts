#!/usr/bin/env python3
"""
build_fleet.py - generation fleet layer (roadmap I.F, v1, 2026-09-24) -> data/fleet.json

Generator-level EIA-860 (data/eia_cache/eia860.zip, 3_1_Generator: Operable / Proposed /
Retired and Canceled) joined to the coverage utility IDs in data/eia_utility_id_map.json
(pinned + verified since 2026-09-24). Per ticker:
  operable   MW by technology group, capacity-weighted age, MW by vintage decade, MW 40y+
  coal       every operable coal unit (plant, unit, MW, online year, age, announced retirement),
             MW with an announced retirement by year, MW with NONE announced
  retiring   announced retirements (all technologies) by year, next 10 years
  proposed   the build pipeline: MW by technology x status (under construction / approved /
             planned) and by expected in-service year
  retired    MW retired since 2020 by technology
Standing caveats (printed in the file and on every view):
  * attribution is by OPERATOR (EIA-860 Utility ID) - a jointly owned unit counts 100% to the
    operator and 0% to co-owners; ownership shares (4___Owner) are a v2 refinement;
  * the 2025 file is EIA's EARLY RELEASE - EIA says it is 'inappropriate for aggregation';
  * nameplate MW throughout (same basis as data/plants/*.json).
Re-run after a new eia860.zip or an eia_utility_id_map.json change. Relative paths - runs anywhere.
"""
import io, json, os, re, sys, zipfile, collections
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZIP = os.path.join(BASE, 'data', 'eia_cache', 'eia860.zip')
IDMAP = os.path.join(BASE, 'data', 'eia_utility_id_map.json')
OUT = os.path.join(BASE, 'data', 'fleet.json')
AS_OF_YEAR = 2025            # data year of the EIA-860 file
NOW = date.today().year

GROUPS = [  # (group, regex on EIA 'Technology')
    ('Coal', r'coal'), ('Nuclear', r'nuclear'),
    ('Gas CC', r'natural gas fired combined cycle'),
    ('Gas CT/recip', r'natural gas fired combustion turbine|natural gas internal combustion'),
    ('Gas steam', r'natural gas steam turbine|natural gas with compressed air'),
    ('Wind', r'wind'), ('Solar', r'solar'),
    ('Storage', r'batter|flywheel|pumped storage'),
    ('Hydro', r'hydroelectric'), ('Oil', r'petroleum'),
]
def group(tech):
    t = (tech or '').lower()
    for g, rx in GROUPS:
        if re.search(rx, t):
            return g
    return 'Other'

PROPOSED_STATUS = {'U': 'under construction', 'V': 'under construction', 'TS': 'under construction',
                   'T': 'approved', 'P': 'planned', 'L': 'planned', 'OT': 'planned'}

def sheet_rows(wb, name):
    ws = wb[name]
    it = ws.iter_rows(values_only=True)
    hdr = None
    for row in it:
        if row and row[0] == 'Utility ID':
            hdr = [str(c).strip() if c else '' for c in row]
            break
    if not hdr:
        sys.exit('ABORT: no header row in sheet %s' % name)
    for row in it:
        if row and row[0] not in (None, ''):
            yield dict(zip(hdr, row))

def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def yr(v):
    try:
        y = int(float(v))
        return y if 1880 <= y <= 2100 else None
    except (TypeError, ValueError):
        return None

def main():
    import openpyxl
    idmap = json.load(open(IDMAP, encoding='utf-8'))
    uid2t = collections.defaultdict(set)
    for t, e in idmap.items():
        if isinstance(e, dict) and e.get('type') != 'water':
            for u in e.get('utility_ids') or []:
                uid2t[str(u)].add(t)
    z = zipfile.ZipFile(ZIP)
    gname = next(n for n in z.namelist() if re.match(r'3_1_Generator', n))
    wb = openpyxl.load_workbook(io.BytesIO(z.read(gname)), read_only=True)

    out = {}
    def T(t):
        if t not in out:
            out[t] = {'operable': collections.Counter(), 'units': 0, 'age_w': 0.0, 'age_mw': 0.0,
                      'decade': collections.Counter(), 'mw40': 0.0, 'coal_units': [],
                      'retiring': collections.defaultdict(collections.Counter),
                      'proposed': collections.defaultdict(collections.Counter),
                      'proposed_year': collections.defaultdict(collections.Counter),
                      'retired': collections.defaultdict(collections.Counter), 'uprates': 0.0}
        return out[t]

    for r in sheet_rows(wb, 'Operable'):
        ts = uid2t.get(str(r.get('Utility ID')).strip().split('.')[0])
        if not ts:
            continue
        if not str(r.get('Status') or '').upper().startswith(('OP', 'SB', 'OS', 'OA')):
            continue
        mw = num(r.get('Nameplate Capacity (MW)')) or 0.0
        g = group(r.get('Technology'))
        oy = yr(r.get('Operating Year')); ry = yr(r.get('Planned Retirement Year'))
        for t in ts:
            x = T(t)
            x['operable'][g] += mw; x['units'] += 1
            if oy:
                x['age_w'] += mw * (AS_OF_YEAR - oy); x['age_mw'] += mw
                x['decade'][str(oy // 10 * 10) + 's'] += mw
                if AS_OF_YEAR - oy >= 40: x['mw40'] += mw
            if ry:
                x['retiring'][ry][g] += mw
            if g == 'Coal':
                x['coal_units'].append({'plant': r.get('Plant Name'), 'plant_code': str(r.get('Plant Code')),
                                        'unit': str(r.get('Generator ID')), 'state': r.get('State'),
                                        'mw': round(mw, 1), 'online': oy, 'age': (AS_OF_YEAR - oy) if oy else None,
                                        'retire_year': ry, 'status': r.get('Status')})

    for r in sheet_rows(wb, 'Proposed'):
        ts = uid2t.get(str(r.get('Utility ID')).strip().split('.')[0])
        if not ts:
            continue
        mw = num(r.get('Nameplate Capacity (MW)')) or 0.0
        g = group(r.get('Technology'))
        st = PROPOSED_STATUS.get(str(r.get('Status') or '').strip().upper(), 'planned')
        ey = yr(r.get('Current Year')) or yr(r.get('Effective Year'))
        for t in ts:
            x = T(t)
            x['proposed'][g][st] += mw
            if ey: x['proposed_year'][ey][g] += mw

    for r in sheet_rows(wb, 'Retired and Canceled'):
        ts = uid2t.get(str(r.get('Utility ID')).strip().split('.')[0])
        if not ts:
            continue
        ryr = yr(r.get('Retirement Year'))
        if not ryr or ryr < 2020 or not str(r.get('Status') or '').upper().startswith('RE'):
            continue     # 'CN' = canceled proposals, not retirements
        mw = num(r.get('Nameplate Capacity (MW)')) or 0.0
        g = group(r.get('Technology'))
        for t in ts:
            T(t)['retired'][ryr][g] += mw

    R = lambda v: round(v, 1)
    doc = {'_schema_version': 1, '_generated': date.today().isoformat(),
           '_source': 'EIA-860 %d EARLY RELEASE (%s), generator level' % (AS_OF_YEAR, gname),
           '_caveats': ["Attribution is by OPERATOR (EIA-860 Utility ID): a jointly owned unit counts 100% to its operator and 0% to co-owners.",
                        "EIA's early release is 'inappropriate for aggregation' per EIA; company-level views are indicative.",
                        "Nameplate MW. Planned retirements are what the operator reported to EIA, which can lag IRP/filing announcements."],
           '_units': 'MW nameplate', 'as_of_year': AS_OF_YEAR, 'tickers': {}}
    for t in sorted(out):
        x = out[t]
        tot = sum(x['operable'].values())
        coal = x['operable'].get('Coal', 0.0)
        coal_ret = collections.Counter()
        for u in x['coal_units']:
            if u['retire_year']: coal_ret[u['retire_year']] += u['mw']
        coal_ann = sum(coal_ret.values())
        horizon = range(NOW, NOW + 10)
        ret10 = sum(sum(c.values()) for y, c in x['retiring'].items() if y in horizon)
        prop_tot = sum(sum(c.values()) for c in x['proposed'].values())
        prop_uc = sum(c.get('under construction', 0) for c in x['proposed'].values())
        doc['tickers'][t] = {
            'operable_mw': R(tot), 'units': x['units'],
            'by_tech': {g: R(v) for g, v in x['operable'].most_common()},
            'share_pct': {g: round(100 * v / tot, 1) for g, v in x['operable'].most_common()} if tot else {},
            'avg_age_yrs': round(x['age_w'] / x['age_mw'], 1) if x['age_mw'] else None,
            'mw_40y_plus': R(x['mw40']), 'pct_40y_plus': round(100 * x['mw40'] / tot, 1) if tot else None,
            'by_decade': {d: R(v) for d, v in sorted(x['decade'].items())},
            'coal': {'operable_mw': R(coal), 'share_pct': round(100 * coal / tot, 1) if tot else 0.0,
                     'announced_retirement_mw': R(coal_ann), 'no_announced_retirement_mw': R(coal - coal_ann),
                     'retirement_by_year': {str(y): R(v) for y, v in sorted(coal_ret.items())},
                     'units': sorted(x['coal_units'], key=lambda u: (-(u['mw'] or 0)))},
            'retiring_next10_mw': R(ret10),
            'retiring_by_year': {str(y): {g: R(v) for g, v in c.most_common()} for y, c in sorted(x['retiring'].items()) if y in horizon},
            'proposed_mw': R(prop_tot), 'proposed_under_construction_mw': R(prop_uc),
            'proposed_by_tech': {g: {s: R(v) for s, v in c.items()} for g, c in sorted(x['proposed'].items(), key=lambda kv: -sum(kv[1].values()))},
            'proposed_by_year': {str(y): {g: R(v) for g, v in c.most_common()} for y, c in sorted(x['proposed_year'].items())},
            'retired_since_2020': {str(y): {g: R(v) for g, v in c.most_common()} for y, c in sorted(x['retired'].items())},
            'retired_since_2020_mw': R(sum(sum(c.values()) for c in x['retired'].values())),
            'utility_ids': (idmap.get(t) or {}).get('utility_ids'),
        }
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, indent=1)
    os.replace(tmp, OUT)
    print('%-5s %9s %6s %6s %8s %8s %9s %8s' % ('TKR', 'MW', 'age', 'coal%', 'coalMW', 'coal-noRet', 'retire10y', 'proposed'))
    for t, v in doc['tickers'].items():
        print('%-5s %9.0f %6s %6s %8.0f %8.0f %9.0f %8.0f' % (t, v['operable_mw'], v['avg_age_yrs'], v['coal']['share_pct'],
              v['coal']['operable_mw'], v['coal']['no_announced_retirement_mw'], v['retiring_next10_mw'], v['proposed_mw']))
    print('wrote', OUT)

if __name__ == '__main__':
    main()
