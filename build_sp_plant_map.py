# -*- coding: utf-8 -*-
r"""build_sp_plant_map.py - S&P Global 'Power Plants' exports -> data\<ticker>_plant_map.json (2026-09-24i).

Generalises build_xplr_plant_map.py (kept for history). For each configured ticker, every OPERATING US
plant in the S&P export is matched to EIA-860 plant code(s) + technology group:
  * candidates = EIA plants in the same state that have MW in the S&P plant's technology group;
  * score = name-token Jaccard (parenthetical aliases tried too) - 0.15 if the unit numerals differ
            + 0.3 if EIA nameplate for that technology is within max(5 MW, 15%) of the S&P plant total;
  * accepted when score >= 0.6, or >= 0.34 with the capacity check passing, and the runner-up trails by
    >= 0.1; MANUAL entries (read against the EIA plant list) override;
  * the technology filter is written whenever the EIA plant holds more than one technology group, so an
    S&P solar row and battery row at one EIA hybrid carry their own ownership %.
Unaccepted plants are listed in 'unmatched' with their best candidates - review, then add to MANUAL.

PIPELINE (2026-09-26): S&P 'Planned' / 'Operating & Planned' US plants are matched the same way against the
EIA-860 PROPOSED generator sheet (same state, name tokens, technology group, planned MW within 15%). Output
'pipeline' - build_fleet.py credits those EIA proposed plant codes to the ticker's pipeline, which is how NEER
projects that file under their own project-LLC utility ids get counted. 'pipeline_unmatched' lists the rest.

build_fleet.py (SP_AUTHORITATIVE) uses the output as the owned-view source for the ticker.

  python build_sp_plant_map.py              # all configured tickers
  python build_sp_plant_map.py NEE          # one
"""
import io, os, re, sys, json, glob, zipfile, collections
import openpyxl

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_fleet import group      # one technology grouping for both scripts

EIA_ZIP = os.path.join(BASE, 'data', 'eia_cache', 'eia860.zip')

PM_GROUPS = {   # S&P prime mover -> EIA technology groups it can match
    'Solar': ['Solar'], 'Wind Turbine': ['Wind'], 'Battery': ['Storage'], 'Other Energy Storage': ['Storage'],
    'Pumped Storage': ['Storage'], 'Combined Cycle': ['Gas CC'], 'Gas Turbine': ['Gas CT/recip', 'Oil'],
    'Internal Combustion': ['Gas CT/recip', 'Other', 'Oil'], 'Steam Turbine': ['Gas steam', 'Coal', 'Oil', 'Other'],
    'Nuclear': ['Nuclear'], 'Hydraulic Turbine': ['Hydro'], 'Fuel Cell': ['Other'],
}

MANUAL = {
    'XIFR': {   # reviewed 2026-09-24h (Stateline = FPL Energy Vansycle; Arrow = Windstar 1; Tehachapi 3 = Coram sites)
        'Adelanto II Solar Farm': [('59440', None)], 'Ashtabula II – NextEra': [('57121', None)],
        'Blue Summit III Wind Project': [('62566', None)], 'Breckinridge Wind Project': [('58994', None)],
        'Brady 2 Wind Farm': [('60354', None)], 'Brady Wind Energy Center 1': [('60355', None)],
        'Cool Springs Battery Storage Plant': [('63721', ['Storage'])], 'Cool Springs Solar Power Plant': [('63721', ['Solar'])],
        'Dodge Flat Battery Storage Project': [('63913', ['Storage'])], 'Dodge Flat Solar Energy Center': [('63913', ['Solar'])],
        'Energy Conversion Technology II (Tehachapi 3)': [('54298', None)],
        'Fish Springs Ranch Battery Storage Project': [('64148', ['Storage'])], 'Fish Springs Ranch Solar Farm': [('64148', ['Solar'])],
        'Hubbard Wind Project (Aquilla Lake Wind)': [('65048', None)], 'Javelina Wind CISD': [('60104', None)],
        'McCoy Battery Storage Project': [('58462', ['Storage'])], 'McCoy Solar Energy Project': [('58462', ['Solar'])],
        'Minco III Wind Energy Center': [('58203', None)], 'Ponderosa Wind Farm': [('63590', None)],
        'Saint Solar Project': [('63476', None)], 'Saint Battery Storage Project': [('66716', None)],
        'Sanford Seacoast Regional Airport Solar Project': [('63667', None)], 'Seiling Wind I': [('59311', None)],
        'Silver State South Solar Project': [('58644', None)], 'Stateline Energy Center (OR)': [('55989', None)],
        'Stateline Energy Center (WA)': [('55560', None)], 'Story County II - Garden Wind': [('57469', None)],
        'Tehachapi Wind Farm I (Tehachapi 3)': [('54299', None), ('54300', None), ('54750', None)],
        'Wilmot Battery Storage Project': [('64426', ['Storage'])], 'Wilmot Energy Center I': [('64426', ['Solar'])],
        'Yellow Pine II Battery Storage': [('67091', ['Storage'])], 'Yellow Pine Solar II Project': [('67091', ['Solar'])],
        'Yellow Pine Solar': [('66357', ['Solar'])],
        'Florida Municipal Solar Project 2 (Harmony)': [('63582', None)],   # Harmony Solar (FL); 67208 'Harmony Florida Solar II' is FPL's
    },
    'NEE': {    # reviewed 2026-09-24i against the EIA plant list (FPL fossil/nuclear sites split by technology)
        'Fort Myers': [('612', ['Gas CC'])], 'Ft Myers Peaking': [('612', ['Gas CT/recip', 'Oil'])],
        'Turkey Point Nuclear': [('621', ['Nuclear'])], 'Turkey Point CC': [('621', ['Gas CC'])],
        'Manatee': [('6042', ['Gas steam', 'Oil'])], 'Manatee CC': [('6042', ['Gas CC'])],
        'FPL Manatee (Parrish Facility) Battery Storage': [('6042', ['Storage'])],
        'Riviera Beach Next Generation Clean Energy Center': [('619', None)],
        'FPL Dania Beach Clean Energy Center': [('65978', None)],
        'Point Beach': [('4046', None)],
        'Gulf Clean Energy Center CT (Crist)': [('641', ['Gas CT/recip'])], 'Gulf Clean Energy Center (Crist)': [('641', ['Gas steam', 'Coal', 'Gas CC'])],
        'Stanton CC': [('55821', None)], 'King Mountain Wind Ranch': [('55581', None)],
        'Logan Wind Energy Center (Peetz Table II)': [('56613', None)],
        'Crowned Ridge Wind Energy Center Project I': [('60503', None)],
        'Minco Wind Energy Center': [('57590', None)], 'Tuscola Bay Wind Park II': [('58587', None)],
        'Florida Municipal Solar Project 2 (Harmony)': [('63582', None)],
        'Florida International University Solar Plant': [('60006', None)],
        'Martin Combined Cycle': [('6043', ['Gas CC'])], 'Pioneer DJ Wind Project': [('66531', None)],
        'Chaves County Solar': [('60405', None)], 'Oliver Wind Energy Center': [('56392', None)],
        'Montezuma Wind Plant': [('57201', None)], 'Westside Solar Project': [('60981', None)],
        'Point Beach CT': [('4046', ['Gas CT/recip', 'Oil'])], 'Georges Lakes Solar Energy Center': [('65907', None)],
        'Shippensburg (Cumberland County) Landfill': [('56887', None)],
        # no operable EIA plant yet (EIA-860 2025ER lists the project at 0 MW) - never let the matcher borrow a sibling
        'Wilmot Energy Center II': [], 'Wilmot Energy Center II Battery Storage': [], 'Blue Summit II Battery Storage Project': [],
    },
}
CONFIG = {
    'XIFR': {'glob': 'SPGlobal_XPLR*PowerPlants*.xlsx', 'out': 'xplr_plant_map.json'},
    # ',Inc.' matters: the NextEra Energy Resources, LLC export (2026-09-26) also matches 'NextEraEnergy*' and sorts
    # last, and it is a strict SUBSET of the NextEra Energy, Inc. list (710 of its 976 plants, nothing new).
    'NEE': {'glob': 'SPGlobal_NextEraEnergy,Inc.*PowerPlants*.xlsx', 'out': 'nee_plant_map.json'},
}

STOP = set(('wind solar farm farms project projects energy center centre power plant llc lp inc facility the of '
            'phase i ii iii iv v vi nextera fpl storage battery bess ess generating station renewable renewables '
            'resources park ranch company co clean units unit hybrid expansion system slf').split())
ROMAN = {'1': 'i', '2': 'ii', '3': 'iii', '4': 'iv', '5': 'v', '6': 'vi'}

def toks(s):
    s = re.sub(r"[–\-_/,.&'’]", ' ', str(s).lower())
    return [t for t in re.findall(r'[a-z0-9]+', s) if t not in STOP]

def numerals(s):
    return {ROMAN.get(x, x) for x in re.findall(r'\b(i{1,3}|iv|v|vi|[1-6])\b', str(s).lower())}

def variants(n):
    return [re.sub(r'\(.*?\)', '', n)] + re.findall(r'\((.*?)\)', n)

def eia_plants():
    z = zipfile.ZipFile(EIA_ZIP)
    def rows(fn, sheet=None):
        wb = openpyxl.load_workbook(io.BytesIO(z.read(fn)), read_only=True)
        ws = wb[sheet] if sheet else wb.worksheets[0]; hdr = None
        for r in ws.iter_rows(values_only=True):
            if hdr is None:
                if r and r[0] == 'Utility ID': hdr = [str(c).strip() if c else '' for c in r]
                continue
            if r and r[0] not in (None, ''): yield dict(zip(hdr, r))
    pname = next(n for n in z.namelist() if n.startswith('2___Plant'))
    gname = next(n for n in z.namelist() if n.startswith('3_1_Generator'))
    P = {}
    for d in rows(pname):
        P[str(d['Plant Code'])] = {'name': d['Plant Name'], 'state': d['State'], 'op': d['Utility Name'],
                                   'op_id': str(d['Utility ID']), 'mw': 0.0, 'g': collections.Counter()}
    for d in rows(gname, 'Operable'):
        p = P.get(str(d['Plant Code']))
        if not p: continue
        try: mw = float(d['Nameplate Capacity (MW)'] or 0)
        except (TypeError, ValueError): mw = 0.0
        p['mw'] += mw; p['g'][group(d['Technology'])] += mw
    return P

def eia_proposed():
    z = zipfile.ZipFile(EIA_ZIP)
    gname = next(n for n in z.namelist() if n.startswith('3_1_Generator'))
    wb = openpyxl.load_workbook(io.BytesIO(z.read(gname)), read_only=True)
    hdr, Q = None, {}
    for r in wb['Proposed'].iter_rows(values_only=True):
        if hdr is None:
            if r and r[0] == 'Utility ID': hdr = [str(c).strip() if c else '' for c in r]
            continue
        if not r or r[0] in (None, ''): continue
        d = dict(zip(hdr, r))
        code = str(d['Plant Code']).split('.')[0]
        q = Q.setdefault(code, {'name': d['Plant Name'], 'state': d['State'], 'op': d['Utility Name'],
                                'op_id': str(d['Utility ID']).split('.')[0], 'mw': 0.0, 'g': collections.Counter()})
        try: mw = float(d['Nameplate Capacity (MW)'] or 0)
        except (TypeError, ValueError): mw = 0.0
        q['mw'] += mw; q['g'][group(d['Technology'])] += mw
    return Q

def match_pipeline(S, Q, ticker, foreign):
    byst = collections.defaultdict(list)
    for code, q in Q.items(): byst[q['state']].append((code, q))
    got, miss = [], []
    for r in S:
        if r['Operating Status'] not in ('Planned', 'Operating & Planned') or r.get('Country') != 'USA':
            continue
        name, st = r['Power Plant Name'], r['State, Province, or Admin Region']
        pct = fnum(r.get('Planned Ownership (%)')) or fnum(r.get('Operating Ownership (%)'))
        owned = fnum(r.get('Owned Planned Capacity (MW)'))
        if not pct or not owned:
            continue
        tot = owned / (pct / 100.0)
        gs = PM_GROUPS.get(r['Prime Mover'], None)
        best = []
        for code, q in byst.get(st, []):
            gmw = sum(v for g, v in q['g'].items() if gs is None or g in gs)
            if gmw <= 0: continue
            qt = set(toks(q['name'])); sc = 0.0
            for v in variants(name):
                vt = set(toks(v))
                if vt and qt: sc = max(sc, len(vt & qt) / len(vt | qt))
            if sc == 0: continue
            if numerals(name) != numerals(q['name']): sc -= 0.15
            jac = sc
            cap = abs(gmw - tot) <= max(5.0, 0.15 * tot)
            if cap: sc += 0.3
            best.append((round(sc, 2), code, cap, round(gmw, 1), round(jac, 2)))
        best.sort(reverse=True)
        ok = best and (best[0][4] >= 0.6 or (best[0][4] >= 0.34 and best[0][2])) and (len(best) < 2 or best[1][0] <= best[0][0] - 0.1)
        why = None
        if ok and Q[best[0][1]]['op_id'] in foreign:
            ok, why = False, 'EIA proposed operator id belongs to %s' % foreign[Q[best[0][1]]['op_id']]
        rec = {'sp_name': name, 'sp_key': r['Power Plant Key'], 'state': st, 'status': r['Operating Status'],
               'pct': pct, 'sp_owned_planned_mw': owned, 'sp_total_planned_mw': round(tot, 1),
               'sp_operator': r.get('Operator'), 'prime_mover': r['Prime Mover']}
        if not ok:
            rec.update(why=why, candidates=[{'plant_code': c, 'plant': Q[c]['name'], 'score': s_, 'name_jaccard': j, 'tech_mw': m, 'cap_ok': cp}
                                            for s_, c, cp, m, j in best[:3]])
            miss.append(rec); continue
        code = best[0][1]
        rec.update(eia=[{'plant_code': code, 'plant': Q[code]['name'], 'eia_operator': Q[code]['op'],
                         'tech': gs if len([g for g, v in Q[code]['g'].items() if v > 0]) > 1 else None}],
                   eia_proposed_mw=best[0][3], cap_check='ok' if best[0][2] else 'MISMATCH', score=best[0][0])
        got.append(rec)
    return got, miss

def sp_rows(path):
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    hi = next(i for i, r in enumerate(rows) if r and r[0] == 'Power Plant Name')
    out = []
    for r in rows[hi + 1:]:
        if not r or r[0] in (None, 'Power Plant Name') or not isinstance(r[1], int): break   # unit section follows
        out.append(dict(zip(rows[hi], r)))
    return out

def fnum(v):
    return float(v) if isinstance(v, (int, float)) else None

def build(ticker, P, Q=None):
    cfg = CONFIG[ticker]
    path = sorted(glob.glob(os.path.join(BASE, 'data', 'eia_cache', cfg['glob'])))[-1]
    S = sp_rows(path)
    byst = collections.defaultdict(list)
    for code, p in P.items(): byst[p['state']].append((code, p))
    man = MANUAL.get(ticker, {})
    idmap = json.load(open(os.path.join(BASE, 'data', 'eia_utility_id_map.json'), encoding='utf-8'))
    friends = {ticker} | ({'NEE', 'XIFR'} if ticker in ('NEE', 'XIFR') else set())   # NEE <-> XPLR share plants by design
    foreign = {str(u): t for t, e in idmap.items() if isinstance(e, dict) and t not in friends for u in (e.get('utility_ids') or [])}
    plants, unmatched, skipped = [], [], []
    for r in S:
        name, st = r['Power Plant Name'], r['State, Province, or Admin Region']
        pct, owned = fnum(r['Operating Ownership (%)']), fnum(r['Owned Existing Capacity (MW)'])
        if r['Operating Status'] not in ('Operating', 'Operating & Planned') or r.get('Country') != 'USA' or not pct:
            skipped.append({'sp_name': name, 'status': r['Operating Status'], 'country': r.get('Country')}); continue
        tot = owned / (pct / 100.0) if owned is not None else None
        gs = PM_GROUPS.get(r['Prime Mover'], None)
        if name in man and not man[name]:
            unmatched.append({'sp_name': name, 'sp_key': r['Power Plant Key'], 'state': st, 'pct': pct, 'sp_owned_mw': owned,
                              'sp_total_mw': round(tot, 1) if tot else None, 'prime_mover': r['Prime Mover'],
                              'why': 'manual: no operable EIA-860 plant yet', 'candidates': []})
            continue
        if name in man:
            eia = man[name]; basis = 'manual'; score = None
        else:
            best = []
            for code, p in byst.get(st, []):
                gmw = sum(v for g, v in p['g'].items() if gs is None or g in gs)
                if gmw <= 0: continue
                pt = set(toks(p['name'])); sc = 0.0
                for v in variants(name):
                    vt = set(toks(v))
                    if vt and pt: sc = max(sc, len(vt & pt) / len(vt | pt))
                if sc == 0: continue
                if numerals(name) != numerals(p['name']): sc -= 0.15
                jac = sc
                cap = bool(tot) and abs(gmw - tot) <= max(5.0, 0.15 * tot)
                if cap: sc += 0.3
                best.append((round(sc, 2), code, cap, round(gmw, 1), round(jac, 2)))
            best.sort(reverse=True)
            ok = best and (best[0][4] >= 0.6 or (best[0][4] >= 0.34 and best[0][2])) and (len(best) < 2 or best[1][0] <= best[0][0] - 0.1)
            why = None
            if ok and P[best[0][1]]['op_id'] in foreign:
                ok, why = False, 'EIA operator id belongs to %s - confirm by hand (MANUAL) if this really is the same plant' % foreign[P[best[0][1]]['op_id']]
            if not ok:
                unmatched.append({'sp_name': name, 'sp_key': r['Power Plant Key'], 'state': st, 'pct': pct, 'sp_owned_mw': owned,
                                  'sp_total_mw': round(tot, 1) if tot else None, 'prime_mover': r['Prime Mover'],
                                  'why': why,
                                  'candidates': [{'plant_code': c, 'plant': P[c]['name'], 'score': s, 'name_jaccard': j, 'tech_mw': m, 'cap_ok': cp} for s, c, cp, m, j in best[:3]]})
                continue
            code = best[0][1]
            eia = [(code, gs if len([g for g, v in P[code]['g'].items() if v > 0]) > 1 else None)]
            basis, score = 'auto', best[0][0]
        emw = 0.0
        for code, tf in eia:
            p = P.get(code) or {'g': {}}
            emw += sum(v for g, v in p['g'].items() if tf is None or g in tf)
        capchk = 'ok' if tot and abs(emw - tot) <= max(5.0, 0.15 * tot) else ('no_sp_total' if not tot else 'MISMATCH')
        plants.append({'sp_name': name, 'sp_key': r['Power Plant Key'], 'state': st, 'pct': pct, 'sp_owned_mw': owned,
                       'sp_total_mw': round(tot, 1) if tot else None, 'sp_operator': r['Operator'], 'prime_mover': r['Prime Mover'],
                       'eia': [{'plant_code': c, 'plant': (P.get(c) or {}).get('name'), 'tech': tf} for c, tf in eia],
                       'eia_mw': round(emw, 1), 'cap_check': capchk, 'match_basis': basis, 'score': score})
    doc = collections.OrderedDict([
        ('_source', 'S&P Global Market Intelligence "Power Plants" export %s (data/eia_cache), supplied by Fareen' % os.path.basename(path)),
        ('_method', __doc__.split('Unaccepted')[0].split('plant code(s) + technology group:')[1].strip()),
        ('ticker', ticker), ('plants', plants), ('unmatched', unmatched), ('skipped', skipped)])
    if Q is not None:
        pipe, pmiss = match_pipeline(S, Q, ticker, foreign)
        doc['pipeline'] = pipe; doc['pipeline_unmatched'] = pmiss
        print('%s pipeline: %d S&P planned plants matched to EIA proposed (%.0f MW owned) | %d unmatched (%.0f MW)' % (
            ticker, len(pipe), sum(x['sp_owned_planned_mw'] for x in pipe), len(pmiss), sum(x['sp_owned_planned_mw'] for x in pmiss)))
    out = os.path.join(BASE, 'data', cfg['out'])
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
    mw = lambda L, k: round(sum(x.get(k) or 0 for x in L), 1)
    print('%s: %d matched (%d manual) %.0f MW owned | %d unmatched %.0f MW | %d skipped | %d capacity MISMATCH -> %s' % (
        ticker, len(plants), sum(1 for p in plants if p['match_basis'] == 'manual'), mw(plants, 'sp_owned_mw'),
        len(unmatched), mw(unmatched, 'sp_owned_mw'), len(skipped), sum(1 for p in plants if p['cap_check'] == 'MISMATCH'), out))

if __name__ == '__main__':
    P = eia_plants(); Q = eia_proposed()
    for t in (sys.argv[1:] or list(CONFIG)):
        build(t, P, Q)
