r"""build_water_territories.py - water-utility service territories -> data\territories\{TICKER}.geojson (tracker 483)

Source: EPA Community Water System Service Area Boundaries (ORD SAB model), ArcGIS feature service
  https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/Water_System_Boundaries/FeatureServer/0
There is no owner field, so systems are selected by PWS_Name pattern + primacy state (RULES below, curated
2026-09-26 against the full name list). Geometry is simplified server-side (maxAllowableOffset 0.002 deg) and
rounded to 3 decimals. AQN also gets its three electric opcos from iou_territories.geojson (EIA IDs 5860 / 26510 / 57483).

Known gaps (written into each file's coverage_gaps): Connecticut Water (HTO), Tidewater (MSEX), Aqua TX/NC/VA
systems under local names (WTRG), CWT's non-California subsidiaries, gas LDC territories.

    python scripts\build_water_territories.py [data_dir]
"""
import sys, os, re, json, datetime, urllib.parse, urllib.request

DATA = sys.argv[1] if len(sys.argv) > 1 else r'E:\PowerAcademy\data'
Q = 'https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/Water_System_Boundaries/FeatureServer/0/query'
RULES = {
    'AWK': (r'(CALIFORNIA-AMERICAN|CAL AMERICAN|^MO AMERICAN|^TN AMERICAN|TENNESSEE AMERICAN|^IL AMERICAN|INDIANA AMERICAN|^PA[ -]AMERICAN|^NJ AMERICAN|^NJAW|MARYLAND AMERICAN|IOWA[ -]AMERICAN|VIRGINIA-AMERICAN|^VA AMERICAN WATER|KENTUCKY[ -]AMERICAN|WEST VIRGINIA[ -]AMERICAN|HAWAII[ -]AMERICAN|NEW YORK AMERICAN)',
            'CA,HI,IA,IL,IN,KY,MD,MO,NJ,NY,PA,TN,VA,WV', ['%AMERICAN%', 'NJAW%'], 'American Water Works'),
    'WTRG': (r'^AQUA (ILLINOIS|INDIANA|NJ|OHIO|PA|NORTH CAROLINA|TEXAS|VIRGINIA)|^AQUA SHENANDOAH', 'PA,OH,TX,IL,NC,NJ,IN,VA', ['AQUA%'], 'Essential Utilities'),
    'CWT': (r'CAL WATER SERVICE|CAL WATER SVC|^CALIFORNIA WATER SERVICE', 'CA', ['%CAL WATER%', 'CALIFORNIA WATER SERVICE%'], 'California Water Service Group'),
    'AWR': (r'^GOLDEN STATE W|^GSWC', 'CA', ['GOLDEN STATE%', 'GSWC%'], 'American States Water'),
    'HTO': (r'^SAN JOSE WATER$|^SJWTX|^MAINE WATER COMPANY', 'CA,TX,ME,CT', ['SAN JOSE WATER%', 'SJWTX%', 'MAINE WATER COMPANY%'], 'H2O America'),
    'MSEX': (r'^MIDDLESEX WATER COMPANY$', 'NJ,DE', ['MIDDLESEX WATER COMPANY%'], 'Middlesex Water'),
    'YORW': (r'^YORK WATER CO$|FRANKLIN SYSTEM YORK WATER', 'PA', ['%YORK WATER%'], 'York Water'),
    'GWRS': (r'^GW SANTA CRUZ WATER|^GW- BWC', 'AZ', ['GW%'], 'Global Water Resources'),
    'AQN': (r'^LIBERTY UTILITIES|^LIBERTY WATER (LPSCO|RIO RICO|NOEL)|^LIBERTY -YERMO|^LIBERTY-BELLVIEW|^LIBERTY - WOODSON', 'CA,AZ,AR,MO,NY', ['LIBERTY%'], 'Algonquin Power & Utilities (Liberty)'),
}
GAPS = {'HTO': 'Connecticut Water systems are not in the EPA layer under that name.',
        'MSEX': 'Tidewater Utilities (DE) is not in the EPA layer.',
        'WTRG': 'Aqua Texas / North Carolina / Virginia systems use local names in the EPA layer and are missing; Peoples gas territory not included.',
        'CWT': 'Only California systems matched; Washington, New Mexico, Hawaii and Texas subsidiaries use local names.',
        'AWK': 'Military-contract systems (American Water O&M) excluded as non-regulated.',
        'GWRS': 'Only the Santa Cruz / BWC systems matched.',
        'AQN': 'Liberty gas LDCs are not included.'}
AQN_ELECTRIC = ('5860', '26510', '57483')


def get(params):
    with urllib.request.urlopen(Q + '?' + urllib.parse.urlencode(params), timeout=120) as r:
        return json.load(r)


def rnd(c):
    return [rnd(x) for x in c] if isinstance(c[0], list) else [round(c[0], 3), round(c[1], 3)]


def main():
    out_dir = os.path.join(DATA, 'territories')
    for t, (rx, states, likes, name) in RULES.items():
        where = '(' + ' OR '.join(f"UPPER(PWS_Name) LIKE '{p}'" for p in likes) + ') AND Primacy_Agency IN (' + ','.join(f"'{s}'" for s in states.split(',')) + ')'
        feats, off = [], 0
        while True:
            j = get({'where': where, 'outFields': 'PWSID,PWS_Name,Primacy_Agency,Population_Served_Count,Service_Connections_Count,Verification_Status,Model_Method',
                     'returnGeometry': 'true', 'outSR': '4326', 'maxAllowableOffset': '0.002', 'geometryPrecision': '4', 'f': 'geojson',
                     'resultRecordCount': '200', 'resultOffset': str(off)})
            page = j.get('features') or []
            for f in page:
                p = f['properties']
                if not re.search(rx, (p.get('PWS_Name') or '').upper()) or not f.get('geometry'):
                    continue
                f['geometry']['coordinates'] = rnd(f['geometry']['coordinates'])
                feats.append({'type': 'Feature', 'geometry': f['geometry'], 'properties': {
                    'NAME': p['PWS_Name'], 'PWSID': p['PWSID'], 'STATE': p['Primacy_Agency'], 'POP_SERVED': p['Population_Served_Count'],
                    'CONNECTIONS': p['Service_Connections_Count'], 'BOUNDARY_METHOD': p['Model_Method'], 'VERIFIED': p['Verification_Status'], 'KIND': 'water'}})
            if len(page) < 200:
                break
            off += 200
        doc = {'type': 'FeatureCollection', 'ticker': t, 'name': name, 'generated': datetime.datetime.now().isoformat(timespec='seconds'),
               'data_source': 'EPA Community Water System Service Area Boundaries (ArcGIS Water_System_Boundaries)',
               '_method': 'systems selected by PWS name pattern + state (RULES in this script); simplified ~0.002 deg, 3-decimal coordinates; boundaries are EPA-modelled where the state supplied none (BOUNDARY_METHOD)',
               'coverage_gaps': GAPS.get(t), 'population_served': sum(f['properties']['POP_SERVED'] or 0 for f in feats), 'systems': len(feats),
               'features': feats, 'service_states': sorted({f['properties']['STATE'] for f in feats})}
        if t == 'AQN':
            iou = json.load(open(os.path.join(DATA, 'iou_territories.geojson'), encoding='utf-8'))
            el = [f for f in iou['features'] if str(f['properties'].get('ID')) in AQN_ELECTRIC]
            for f in el:
                f['properties']['KIND'] = 'electric'
            doc['features'] = el + feats
            doc['utility_ids'] = list(AQN_ELECTRIC)
            doc['service_states'] = sorted(set(doc['service_states']) | {f['properties']['STATE'] for f in el})
        json.dump(doc, open(os.path.join(out_dir, f'{t}.geojson'), 'w', encoding='utf-8'))
        print(f"{t:5} {len(doc['features']):4} features  pop {doc['population_served']:,}  {doc['service_states']}")


if __name__ == '__main__':
    main()
