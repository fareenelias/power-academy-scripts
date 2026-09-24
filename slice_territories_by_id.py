#!/usr/bin/env python3
"""
slice_territories_by_id.py - per-ticker electric service-territory GeoJSONs, sliced by an
EXPLICIT EIA utility-ID whitelist (2026-09-24). Supersedes slice_hifld_territories.py for
the electric utilities below.

Why: the old slicer matched NAME FRAGMENTS, and a fragment is not an identity. Audit on
2026-09-24 found five files wrong - AEE carried two unrelated co-ops ('Union Electric
Membership Corp' NC, 'Clay-Union Electric' SD), CMS an Iowa co-op also called 'Consumers
Energy', D 'Central Virginia Electric Coop'; ES was missing CL&P + PSNH, PPL was missing LG&E
+ Rhode Island Energy, EVRG was missing Evergy Missouri West. Every ID below was read off
electric_territories_full.geojson (the HIFLD/EIA-861 file; ID = EIA utility number) with its
NAME and HOLDING_CO shown beside it - never typed from memory.

service_states come from rra_states.json company_state_map (the dashboard's canonical list);
HIFLD's STATE field is the utility's HQ state (Ameren Illinois reads 'MO', every AEP opco
'OH'/'OK'), so it is only the fallback.

Run:  python slice_territories_by_id.py            (writes data/territories/<T>.geojson)
      python slice_territories_by_id.py --dry      (prints the diff vs the files on disk)
"""
import argparse, json, os, sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, 'data', 'electric_territories_full.geojson')
OUT = os.path.join(BASE, 'data', 'territories')
RRA = os.path.join(BASE, 'data', 'rra_states.json')

# ticker -> (display name, {EIA utility id: name as printed in the source}, note)
WHITELIST = {
    'AEE':  ('Ameren', {'19436': 'UNION ELECTRIC CO - (MO)', '56697': 'AMEREN ILLINOIS COMPANY'}, ''),
    'CMS':  ('CMS Energy', {'4254': 'CONSUMERS ENERGY CO'}, ''),
    'D':    ('Dominion Energy', {'19876': 'VIRGINIA ELECTRIC & POWER CO', '17539': 'DOMINION ENERGY SOUTH CAROLINA, INC'}, ''),
    'ES':   ('Eversource Energy', {'4176': 'CONNECTICUT LIGHT & POWER CO', '54913': 'NSTAR ELECTRIC COMPANY',
                                   '15472': 'PUBLIC SERVICE CO OF NH'}, ''),
    'PPL':  ('PPL Corporation', {'14715': 'PPL ELECTRIC UTILITIES CORP', '10171': 'KENTUCKY UTILITIES CO',
                                 '11249': 'LOUISVILLE GAS & ELECTRIC CO', '13214': 'THE NARRAGANSETT ELECTRIC CO'},
             "Narragansett = Rhode Island Energy, owned by PPL since May 2022 (HIFLD's HOLDING_CO still reads National Grid)."),
    'EVRG': ('Evergy', {'10000': 'EVERGY METRO', '12698': 'EVERGY MISSOURI WEST', '22500': 'EVERGY KANSAS CENTRAL, INC',
                        '10005': 'EVERGY KANSAS SOUTH, INC'}, ''),
    'NEE':  ('NextEra Energy', {'6452': 'FLORIDA POWER & LIGHT CO'}, 'Gulf Power merged into FPL (2021).'),
    'ETR':  ('Entergy', {'814': 'ENTERGY ARKANSAS LLC', '11241': 'ENTERGY LOUISIANA LLC', '12685': 'ENTERGY MISSISSIPPI LLC',
                         '13478': 'ENTERGY NEW ORLEANS, LLC', '55937': 'ENTERGY TEXAS INC.'}, ''),
    'EIX':  ('Edison International', {'17609': 'SOUTHERN CALIFORNIA EDISON CO'}, ''),
    'PCG':  ('PG&E', {'14328': 'PACIFIC GAS & ELECTRIC CO.'}, ''),
    'POR':  ('Portland General Electric', {'15248': 'PORTLAND GENERAL ELECTRIC CO'}, ''),
    'HE':   ('Hawaiian Electric', {'19547': 'HAWAIIAN ELECTRIC CO INC', '8287': 'HAWAII ELECTRIC LIGHT CO INC',
                                   '11843': 'MAUI ELECTRIC CO LTD'}, ''),
    'AEP':  ('American Electric Power', {'733': 'APPALACHIAN POWER CO', '9324': 'INDIANA MICHIGAN POWER CO',
                                         '14006': 'OHIO POWER CO', '15474': 'PUBLIC SERVICE CO OF OKLAHOMA',
                                         '17698': 'SOUTHWESTERN ELECTRIC POWER CO', '3278': 'AEP TEXAS CENTRAL COMPANY',
                                         '20404': 'AEP TEXAS NORTH COMPANY', '22053': 'KENTUCKY POWER CO',
                                         '20521': 'WHEELING POWER CO', '10331': 'KINGSPORT POWER CO'},
             "Kingsport Power's HOLDING_CO reads itself in HIFLD; it is an AEP subsidiary (Appalachian Power affiliate)."),
}

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--dry', action='store_true'); a = ap.parse_args()
    src = json.load(open(SRC, encoding='utf-8'))
    by_id = {}
    for f in src['features']:
        by_id.setdefault(str(f['properties'].get('ID')), []).append(f)
    csm = json.load(open(RRA, encoding='utf-8')).get('company_state_map', {})
    bad = 0
    for t, (disp, ids, note) in WHITELIST.items():
        feats = []
        for i, nm in ids.items():
            hit = by_id.get(i, [])
            if not hit or hit[0]['properties'].get('NAME') != nm:   # identity guard: ID AND printed name must agree
                print('  !! %s id %s: expected %r, source has %r' % (t, i, nm, hit[0]['properties'].get('NAME') if hit else None))
                bad += 1; continue
            feats.extend(hit)
        states = sorted(x for x in (csm.get(t) or {f['properties'].get('STATE') for f in feats})
                        if isinstance(x, str) and len(x) == 2 and x.isupper())   # drops RRA pseudo-keys ('New_Orleans')
        doc = {'type': 'FeatureCollection', 'ticker': t, 'name': disp,
               'generated': datetime.now().isoformat(timespec='seconds'), 'data_source': 'HIFLD-2024',
               '_method': 'sliced by EIA utility-ID whitelist (slice_territories_by_id.py); service_states from '
                          'rra_states.company_state_map' + (' - ' + note if note else ''),
               'utility_ids': list(ids), 'service_states': states, 'features': feats}
        path = os.path.join(OUT, t + '.geojson')
        old = json.load(open(path, encoding='utf-8')) if os.path.exists(path) else None
        was = sorted(f['properties'].get('NAME') for f in old['features']) if old else None
        now = sorted(f['properties'].get('NAME') for f in feats)
        tag = 'same' if was == now else ('NEW' if old is None else 'CHANGED')
        print('%-5s %-8s %d feature(s)  states=%s' % (t, tag, len(feats), ','.join(states)))
        if tag == 'CHANGED':
            print('        - removed:', sorted(set(was) - set(now)) or '-')
            print('        + added:  ', sorted(set(now) - set(was)) or '-')
        if not a.dry:
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(doc, fh)
    if bad:
        sys.exit('ABORT-LEVEL WARNING: %d whitelist id(s) did not match the source' % bad)

if __name__ == '__main__':
    main()
