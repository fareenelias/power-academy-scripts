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
Z923 = os.path.join(BASE, 'data', 'eia_cache', 'eia923_2024.zip')   # optional; v2 performance layer
PERF_YEAR = 2024
HOURS = 8784                  # 2024 is a leap year
FOSSIL = {'Coal', 'Gas CC', 'Gas CT/recip', 'Gas steam', 'Oil'}
# Schedule 4 OWNER IDs that belong to a coverage name but are not operator IDs in
# eia_utility_id_map.json. Used for the owned view ONLY - never for operator attribution.
# Add an entry only with a stated source.
OWNER_AFFILIATE_IDS = {
    '62643': ('TLN', "MC Project Company LLC - owns Martins Creek 3/4 (and retired CTG1-4) 100%; confirmed a Talen entity by Fareen 2026-09-24"),
    '61044': ('VST', "Comanche Peak Power Co, LLC - owns Comanche Peak 100%; confirmed Vistra by Fareen 2026-09-24"),
    '56882': ('VST', "DeCordova Power Company LLC - owns DeCordova 100%; confirmed Vistra by Fareen 2026-09-24"),
    '61901': ('XIFR', "NextEra Energy Partners LP - the partnership itself (renamed XPLR Infrastructure 2025); 49.9% of the NEP tranche at Desert Sunlight 250/300 - basis: EIA owner name"),
    '56622': ('NEE', "Shaw Creek Solar (aka Aiken County Solar) - 100% owned by NextEra Energy Resources; confirmed by Fareen 2026-09-24 (EIA owner address is NextEra HQ, 700 Universe Blvd)"),
}
# Plant-level ownership that REPLACES Schedule 4 for every generator at the plant, where EIA's
# owner rows are stale. owners = [(coverage ticker or None, fraction, name)]; stated source required.
PLANT_OWNERSHIP_OVERRIDES = {
    '57993': {'plant': 'Desert Sunlight 300', 'owners': [('XIFR', 0.499, 'XPLR Infrastructure LP'), (None, 0.2447, 'California Public Employees (CalPERS)'),
              (None, 0.1372, 'Clearway Energy Group LLC'), (None, 0.1128, 'Clearway Energy Inc.'), (None, 0.0053, 'Harbert Mgmt Corp.'), ('NEE', 0.001, 'NextEra Energy Resources LLC')],
              'source': "Plant-level ownership table supplied by Fareen 2026-09-24; EIA-860 2025ER Schedule 4 still shows pre-sale owners (Shaw Creek 50% / GE / Sumitomo) on most blocks"},
    '58542': {'plant': 'Desert Sunlight 250', 'owners': [('XIFR', 0.499, 'XPLR Infrastructure LP'), (None, 0.2447, 'California Public Employees (CalPERS)'),
              (None, 0.1372, 'Clearway Energy Group LLC'), (None, 0.1128, 'Clearway Energy Inc.'), (None, 0.0053, 'Harbert Mgmt Corp.'), ('NEE', 0.001, 'NextEra Energy Resources LLC')],
              'source': "Plant-level ownership table supplied by Fareen 2026-09-24 (same holders as Desert Sunlight 300); EIA Schedule 4 stale"},
}
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

def perf923(pmcap):
    """EIA-923 plant x prime-mover net generation / fuel -> per-ticker CF and heat rate by technology group."""
    if not os.path.exists(Z923):
        return {}, {'status': 'eia923 zip absent - performance layer skipped', 'path': Z923}
    import openpyxl
    z = zipfile.ZipFile(Z923)
    nm = next(n for n in z.namelist() if re.search(r'Schedules_2_3_4_5', n))
    wb = openpyxl.load_workbook(io.BytesIO(z.read(nm)), read_only=True)
    ws = wb['Page 1 Generation and Fuel Data']
    hdr = None; gen = collections.Counter(); fuel = collections.Counter()
    for row in ws.iter_rows(values_only=True):
        if hdr is None:
            if row and row[0] == 'Plant Id':
                hdr = [re.sub(r'\s+', ' ', str(c or '')).strip() for c in row]
                iP, iPM = hdr.index('Plant Id'), hdr.index('Reported Prime Mover')
                iG, iF = hdr.index('Net Generation (Megawatthours)'), hdr.index('Elec Fuel Consumption MMBtu')
                iY = hdr.index('YEAR')
            continue
        if not row or row[0] in (None, ''): continue
        if str(row[iY]).split('.')[0] != str(PERF_YEAR):
            sys.exit('ABORT: EIA-923 row year %r is not %d' % (row[iY], PERF_YEAR))
        k = (str(row[iP]).split('.')[0], str(row[iPM] or '').strip().upper())
        gen[k] += num(row[iG]) or 0.0; fuel[k] += num(row[iF]) or 0.0
    acc = collections.defaultdict(lambda: collections.defaultdict(lambda: {'mwh': 0.0, 'mw': 0.0, 'mmbtu': 0.0, 'n': 0}))
    qc = collections.Counter(); over = []
    for k, c in pmcap.items():
        if not c['ts'] or c['mw'] <= 0: continue
        if c['partial']: qc['excluded_part_year'] += 1; continue
        if k not in gen: qc['no_923_row'] += 1; continue
        g = c['tech'].most_common(1)[0][0]
        cf = gen[k] / (c['mw'] * HOURS)
        if cf > 1.0:
            qc['excluded_cf_over_100'] += 1; over.append([k[0], k[1], round(100 * cf, 1)]); continue
        for t in c['ts']:
            a = acc[t][g]; a['mwh'] += gen[k]; a['mw'] += c['mw']; a['n'] += 1
            if g in FOSSIL: a['mmbtu'] += fuel[k]
        qc['plant_pm_used'] += 1
    out = {}
    for t, byg in acc.items():
        out[t] = {'year': PERF_YEAR, 'by_tech': {}}
        for g, a in sorted(byg.items(), key=lambda kv: -kv[1]['mw']):
            e = {'mw_basis': round(a['mw'], 1), 'net_gen_gwh': round(a['mwh'] / 1000, 1),
                 'cf_pct': round(100 * a['mwh'] / (a['mw'] * HOURS), 1) if a['mw'] else None, 'plant_pms': a['n']}
            if g in FOSSIL and a['mwh'] > 0 and a['mmbtu'] > 0:
                e['heat_rate_btu_kwh'] = round(1000 * a['mmbtu'] / a['mwh'])
            out[t]['by_tech'][g] = e
    return out, {'source': nm, 'counts': dict(qc), 'cf_over_100_examples': over[:10]}

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
    # v2 (2026-09-24c): Schedule 4 ownership - jointly or third-party owned generators only.
    # A generator absent from Schedule 4 is 100% owned by its operator.
    oname = next(n for n in z.namelist() if re.match(r'4___Owner', n))
    owb = openpyxl.load_workbook(io.BytesIO(z.read(oname)), read_only=True)
    own = collections.defaultdict(list)          # (plant_code, gen_id) -> [(owner_id, frac, owner_name)]
    for r in sheet_rows(owb, owb.sheetnames[0]):
        f = num(r.get('Percent Owned'))
        if f is None: continue
        if f > 1.0001: f = f / 100.0            # guard: a file that prints percent, not fraction
        own[(str(r.get('Plant Code')).split('.')[0], str(r.get('Generator ID')))].append(
            (str(r.get('Ownership ID')).strip().split('.')[0], f, r.get('Owner Name')))
    bad_sum = [k for k, v in own.items() if abs(sum(f for _, f, _ in v) - 1.0) > 0.02]
    oid2t = collections.defaultdict(set, {k: set(v) for k, v in uid2t.items()})
    for oid, (t, _why) in OWNER_AFFILIATE_IDS.items():
        oid2t[oid].add(t)

    out = {}
    def T(t):
        if t not in out:
            out[t] = {'operable': collections.Counter(), 'units': 0, 'age_w': 0.0, 'age_mw': 0.0,
                      'decade': collections.Counter(), 'mw40': 0.0, 'coal_units': [],
                      'retiring': collections.defaultdict(collections.Counter),
                      'proposed': collections.defaultdict(collections.Counter),
                      'proposed_year': collections.defaultdict(collections.Counter),
                      'retired': collections.defaultdict(collections.Counter), 'uprates': 0.0,
                      'owned': collections.Counter(), 'joint': []}
        return out[t]

    pmcap = collections.defaultdict(lambda: {'mw': 0.0, 'tech': collections.Counter(), 'partial': False, 'ts': set()})
    for r in sheet_rows(wb, 'Operable'):
        if not str(r.get('Status') or '').upper().startswith(('OP', 'SB', 'OS', 'OA')):
            continue
        ts = uid2t.get(str(r.get('Utility ID')).strip().split('.')[0]) or set()
        key = (str(r.get('Plant Code')).split('.')[0], str(r.get('Generator ID')))
        mw = num(r.get('Nameplate Capacity (MW)')) or 0.0
        g = group(r.get('Technology'))
        # ownership share per coverage ticker (v2)
        # owners of this generator: [(coverage tickers, fraction, name)] - a plant-level override
        # (stated source) beats Schedule 4; Schedule 4 beats "100% the operator's".
        if key[0] in PLANT_OWNERSHIP_OVERRIDES:
            ol = [({t} if t else set(), f, n) for t, f, n in PLANT_OWNERSHIP_OVERRIDES[key[0]]['owners']]
        elif key in own:
            ol = [(oid2t.get(oid, set()), f, n) for oid, f, n in own[key]]
        else:
            ol = None
        share = collections.Counter()
        if ol is not None:
            for tks, f, _ in ol:
                for t in tks:
                    share[t] += f
        else:
            for t in ts:
                share[t] = 1.0
        for t, f in share.items():
            if f <= 0: continue
            x = T(t); x['owned'][g] += mw * f
            if ol is not None:
                x['joint'].append({'plant': r.get('Plant Name'), 'plant_code': key[0], 'unit': key[1], 'state': r.get('State'),
                                   'tech': g, 'mw': round(mw, 1), 'share_pct': round(100 * f, 1), 'owned_mw': round(mw * f, 1),
                                   'operator': r.get('Utility Name'), 'operated_by_you': t in ts,
                                   'co_owners': [{'name': n, 'pct': round(100 * ff, 2)} for tks, ff, n in ol if t not in tks],
                                   **({'ownership_source': PLANT_OWNERSHIP_OVERRIDES[key[0]]['source']} if key[0] in PLANT_OWNERSHIP_OVERRIDES else {})})
        for t in ts:                      # operators with 0% ownership still appear in the operated view
            if ol is not None and t not in share:
                T(t)['joint'].append({'plant': r.get('Plant Name'), 'plant_code': key[0], 'unit': key[1], 'state': r.get('State'),
                                      'tech': g, 'mw': round(mw, 1), 'share_pct': 0.0, 'owned_mw': 0.0,
                                      'operator': r.get('Utility Name'), 'operated_by_you': True,
                                      'co_owners': [{'name': n, 'pct': round(100 * ff, 2)} for _, ff, n in ol]})
        if not ts:
            continue
        oy = yr(r.get('Operating Year')); ry = yr(r.get('Planned Retirement Year'))
        pm = str(r.get('Prime Mover') or '').strip().upper()
        pmkey = (key[0], pm)
        pmcap[pmkey]['mw'] += mw
        pmcap[pmkey]['tech'][g] += mw
        if oy and oy >= PERF_YEAR: pmcap[pmkey]['partial'] = True      # online during/after the performance year
        pmcap[pmkey]['ts'] |= set(ts)
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
        ryr = yr(r.get('Retirement Year'))
        if ryr and ryr >= PERF_YEAR and str(r.get('Status') or '').upper().startswith('RE'):
            # retired during/after the performance year: its 2024 generation sits in EIA-923 but its MW is not in 'Operable'
            pk = (str(r.get('Plant Code')).split('.')[0], str(r.get('Prime Mover') or '').strip().upper())
            pmcap[pk]['partial'] = True
        ts = uid2t.get(str(r.get('Utility ID')).strip().split('.')[0])
        if not ts:
            continue
        if not ryr or ryr < 2020 or not str(r.get('Status') or '').upper().startswith('RE'):
            continue     # 'CN' = canceled proposals, not retirements
        mw = num(r.get('Nameplate Capacity (MW)')) or 0.0
        g = group(r.get('Technology'))
        for t in ts:
            T(t)['retired'][ryr][g] += mw

    perf, perf_qc = perf923(pmcap)
    R = lambda v: round(v, 1)
    doc = {'_schema_version': 1, '_generated': date.today().isoformat(),
           '_source': 'EIA-860 %d EARLY RELEASE (%s), generator level' % (AS_OF_YEAR, gname),
           '_caveats': ["Operated view (every figure except owned_*): attribution is by OPERATOR (EIA-860 Utility ID) - a jointly owned unit counts 100% to its operator and 0% to co-owners. owned_mw / owned_by_tech apply EIA-860 Schedule 4 ownership shares (a generator absent from Schedule 4 is 100% its operator's).",
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
            'owned_mw': R(sum(x['owned'].values())),
            'owned_by_tech': {g: R(v) for g, v in x['owned'].most_common() if v >= 0.05},
            'owned_minus_operated_mw': R(sum(x['owned'].values()) - tot),
            'joint_units': sorted(x['joint'], key=lambda u: -(u['mw'] or 0)),
            'perf': perf.get(t),
            'utility_ids': (idmap.get(t) or {}).get('utility_ids'),
        }
    doc['_perf_qc'] = perf_qc
    if perf:
        doc['_caveats'].append("Capacity factor / heat rate: EIA-923 %d final, plant x prime-mover net generation over the EIA-860 %d nameplate of that plant's generators (operated view); plant-prime-movers with a unit added or retired in or after %d are excluded (part-year), as are any computing above 100%%. Heat rate = fuel MMBtu for electricity / net MWh, fossil only." % (PERF_YEAR, AS_OF_YEAR, PERF_YEAR))
    doc['_ownership_qc'] = {'owner_affiliate_ids': {k: {'ticker': v[0], 'why': v[1]} for k, v in OWNER_AFFILIATE_IDS.items()},
                            'operated_zero_share_units': {t: sorted({u['plant'] for u in out[t]['joint'] if u['operated_by_you'] and u['share_pct'] == 0})
                                                          for t in out if any(u['operated_by_you'] and u['share_pct'] == 0 for u in out[t]['joint'])},
                            'schedule4_generators': len(own), 'share_sum_off_by_gt_2pct': len(bad_sum),
                            'examples': [list(k) for k in bad_sum[:10]]}
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, indent=1)
    os.replace(tmp, OUT)
    print('%-5s %9s %9s %8s %6s %6s %8s %8s %9s %8s' % ('TKR', 'MW', 'ownedMW', 'delta', 'age', 'coal%', 'coalMW', 'coal-noRet', 'retire10y', 'proposed'))
    for t, v in doc['tickers'].items():
        print('%-5s %9.0f %9.0f %8.0f %6s %6s %8.0f %8.0f %9.0f %8.0f' % (t, v['operable_mw'], v['owned_mw'], v['owned_minus_operated_mw'], v['avg_age_yrs'], v['coal']['share_pct'],
              v['coal']['operable_mw'], v['coal']['no_announced_retirement_mw'], v['retiring_next10_mw'], v['proposed_mw']))
    print('ownership QC:', doc['_ownership_qc'])
    print('wrote', OUT)

if __name__ == '__main__':
    main()
