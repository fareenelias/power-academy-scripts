r"""build_water_map_stats.py - Map sidebar figures for the water names (+ AQN), which have no FERC Form 1 -> data\water_map_stats.json

Per ticker:
  net_utility_plant_b   FY2025 10-K XBRL, consolidated: PublicUtilitiesPropertyPlantAndEquipmentNet, else PropertyPlantAndEquipmentNet,
                        else (plant in service or gross PP&E) - accumulated depreciation. The water analogue of the electric 'NUP'
                        line on the Map (a rate-base proxy, not rate base: includes non-utility plant and acquisition adjustments where tagged).
  rate_base             company-stated rate base where a deck prints one (opco_guidance.json / Guidance_ip.json), with page link.
  connections / population_served   sum over the EPA community-water-system boundaries in territories\{T}.geojson (water systems only).

    python scripts\build_water_map_stats.py [data_dir]
"""
import sys, os, re, json, glob, datetime

DATA = sys.argv[1] if len(sys.argv) > 1 else r'E:\PowerAcademy\data'
TICKERS = ['AWK', 'WTRG', 'CWT', 'AWR', 'HTO', 'MSEX', 'YORW', 'GWRS', 'AQN']
NET = ['PublicUtilitiesPropertyPlantAndEquipmentNet', 'PropertyPlantAndEquipmentNet']
GROSS = ['PublicUtilitiesPropertyPlantAndEquipmentPlantInService', 'PropertyPlantAndEquipmentGross']
ACCUM = ['PublicUtilitiesPropertyPlantAndEquipmentAccumulatedDepreciation',
         'AccumulatedDepreciationDepletionAndAmortizationPropertyPlantAndEquipment']


def facts_of(path):
    s = open(path, encoding='utf-8', errors='ignore').read()
    ctx = {}
    for m in re.finditer(r'<(?:xbrli:)?context id="([^"]+)">(.*?)</(?:xbrli:)?context>', s, re.S):
        b = m.group(2); inst = re.search(r'<(?:xbrli:)?instant>([\d-]+)<', b)
        ctx[m.group(1)] = ('explicitMember' in b or 'typedMember' in b, inst.group(1) if inst else None)
    f = {}
    for m in re.finditer(r'<us-gaap:(\w+)\s+([^>]*?)>([^<]*)</us-gaap:\1>', s):
        c = re.search(r'contextRef="([^"]+)"', m.group(2))
        if not c or c.group(1) not in ctx or ctx[c.group(1)][0] or not ctx[c.group(1)][1]: continue
        try: v = float(m.group(3))
        except ValueError: continue
        f.setdefault(m.group(1), {})[ctx[c.group(1)][1]] = v
    return f


def main():
    man = json.load(open(os.path.join(DATA, '_sec_xbrl', '_manifest.json'), encoding='utf-8'))
    inst = {t: f"{r['accession']}_{r['instance']}" for t, rows in man['tickers'].items() for r in rows if r.get('role') == 'parent' and r.get('accession') and r.get('instance')}
    og = json.load(open(os.path.join(DATA, 'opco_guidance.json'), encoding='utf-8'))['names']
    gi = json.load(open(os.path.join(DATA, 'Guidance_ip.json'), encoding='utf-8'))
    out = {}
    for t in TICKERS:
        rec = {}
        p = os.path.join(DATA, '_sec_xbrl', inst.get(t, '-'))
        if os.path.exists(p):
            f = facts_of(p)
            fye = max(f.get('Assets', {}) or {'': 0})
            val, how = None, None
            for n in NET:
                if fye in f.get(n, {}): val, how = f[n][fye], n; break
            if val is None:
                g = next((f[n][fye] for n in GROSS if fye in f.get(n, {})), None)
                a = next((f[n][fye] for n in ACCUM if fye in f.get(n, {})), None)
                if g is not None and a is not None: val, how = g - a, 'gross PP&E - accumulated depreciation'
            if val is not None:
                rec['net_utility_plant_b'] = round(val / 1e9, 2); rec['nup_basis'] = how; rec['nup_as_of'] = fye
                rec['nup_source'] = f'FY{fye[:4]} 10-K XBRL ({inst[t]})'
        # company-stated rate base
        x = og.get(t) or {}
        rbs = [r for r in ((x.get('rate_base') or {}).get('by_opco') or []) if r.get('value_b') is not None]
        tot = [r for r in rbs if re.search(r'consolidated|total', r.get('opco', ''), re.I)] or (rbs if len(rbs) == 1 else [])
        if tot:
            r = sorted(tot, key=lambda r: str(r.get('year')))[0]
            rec['rate_base'] = {'value_b': r['value_b'], 'year': r.get('year'), 'label': r.get('opco'), 'url': x.get('deck_url'), 'page': r.get('page')}
        elif rbs:
            rec['rate_base_parts'] = [{'label': r['opco'], 'value_b': r['value_b'], 'year': r.get('year'), 'page': r.get('page')} for r in rbs][:12]
            rec['rate_base_parts_url'] = x.get('deck_url')
        if t == 'AQN' and isinstance(gi.get('AQN'), dict):
            a = gi['AQN']; rec['rate_base'] = {'value_b': 8.2, 'year': '2025A', 'label': 'total rate base (deck)', 'url': a.get('source_url'), 'page': (a.get('source_pages') or {}).get('rate_base_cagr')}
        # connections from the EPA water-system layer
        tp = os.path.join(DATA, 'territories', f'{t}.geojson')
        if os.path.exists(tp):
            fs = [f for f in json.load(open(tp, encoding='utf-8'))['features'] if (f.get('properties') or {}).get('KIND') == 'water']
            rec['water_systems'] = len(fs)
            rec['connections'] = int(sum((f['properties'].get('CONNECTIONS') or 0) for f in fs))
            rec['population_served'] = int(sum((f['properties'].get('POP_SERVED') or 0) for f in fs))
        out[t] = rec
        print(t, rec.get('net_utility_plant_b'), rec.get('nup_basis'), (rec.get('rate_base') or {}).get('value_b'), len(rec.get('rate_base_parts') or []), rec.get('connections'))
    doc = {'_schema_version': '1.0', '_generated': datetime.date.today().isoformat(), '_method': __doc__.split('    python')[0].strip(),
           '_caveat': 'Net utility plant is a rate-base PROXY (consolidated, may include non-utility plant; WTRG includes Peoples gas). Company-stated rate base is shown where a deck prints it. Connections cover only the systems matched in the EPA layer (see each territory file\'s coverage_gaps).',
           'tickers': out}
    json.dump(doc, open(os.path.join(DATA, 'water_map_stats.json'), 'w', encoding='utf-8'), indent=1)
    print('wrote water_map_stats.json')


if __name__ == '__main__':
    main()
