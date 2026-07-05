import json, os, re
"""
build_gas_ldc_groups.py  v3
"""
import json, os

GAS_PATH  = r'E:\PowerAcademy\data\gas_territories.geojson'
IOU_PATH  = r'E:\PowerAcademy\data\iou_grouped.json'
ELEC_PATH = r'E:\PowerAcademy\data\electric_territories_full.geojson'

GAS_PARENT_MAP = {
    'CENTERPOINT ENERGY - ENTEX':           'CenterPoint Energy',
    'CENTERPOINT ENERGY - ARKLA':           'CenterPoint Energy',
    'CENTERPOINT ENERGY':                   'CenterPoint Energy',
    'VECTREN ENERGY DELIVERY OF OHIO':      'CenterPoint Energy',
    'VECTREN ENERGY DELIVERY OF INDIANA':   'CenterPoint Energy',
    'INDIANA GAS AND ELECTRIC':             'CenterPoint Energy',
    'ATMOS ENERGY CORPORATION':             'Atmos Energy',
    'ATMOS ENERGY':                         'Atmos Energy',
    'ATMOS PIPELINE - TEXAS':               'Atmos Energy',
    'NATIONAL FUEL GAS DISTRIBUTION CORPORATION': 'NFG — National Fuel Gas',
    'NATIONAL FUEL GAS DISTRIBUTION':             'NFG — National Fuel Gas',
    'NATIONAL FUEL GAS SUPPLY CORPORATION':       'NFG — National Fuel Gas',
    'COLUMBIA GAS OF OHIO':                 'NiSource',
    'COLUMBIA GAS OF PENNSYLVANIA':         'NiSource',
    'COLUMBIA GAS OF VIRGINIA':             'NiSource',
    'COLUMBIA GAS OF KENTUCKY':             'NiSource',
    'COLUMBIA GAS OF MARYLAND':             'NiSource',
    'COLUMBIA GAS OF MASSACHUSETTS':        'NiSource',
    'NORTHERN INDIANA PUB SVC CO':          'NiSource',
    'PUBLIC SERVICE CO OF COLORADO':        'Xcel Energy',
    'NORTHERN STATES POWER CO':             'Xcel Energy',
    'SOUTHWESTERN PUBLIC SERVICE':          'Xcel Energy',
    'DTE GAS COMPANY':                      'DTE Energy',
    'SEMCO ENERGY GAS COMPANY':             'DTE Energy',
    'NICOR GAS COMPANY':                    'WEC Energy',
    'PEOPLES ENERGY':                       'WEC Energy',
    'NORTH SHORE GAS CO':                   'WEC Energy',
    'MICHIGAN GAS UTILITIES COMPANY':       'WEC Energy',
    'MINNESOTA ENERGY RESOURCES':           'WEC Energy',
    'WISCONSIN PUB SVC CORP':               'WEC Energy',
    'WISCONSIN POWER AND LIGHT':            'WEC Energy',
    'UPPER MICHIGAN ENERGY RESOURCES':      'WEC Energy',
    'WPS GAS DISTRIBUTION':                 'WEC Energy',
    'SPIRE MISSOURI INC.':                  'Spire',
    'SPIRE MISSOURI':                       'Spire',
    'SPIRE ALABAMA INC.':                   'Spire',
    'SPIRE ALABAMA':                        'Spire',
    'SPIRE GULF INC.':                      'Spire',
    'LACLEDE GAS COMPANY':                  'Spire',
    'ALABAMA GAS CORP':                     'Spire',
    'MOBILE GAS SERVICE':                   'Spire',
    'OKLAHOMA NATURAL GAS COMPANY':         'ONE Gas',
    'OKLAHOMA NATURAL GAS':                 'ONE Gas',
    'KANSAS GAS SERVICE':                   'ONE Gas',
    'TEXAS GAS SERVICE':                    'ONE Gas',
    'TEXAS GAS SERVICE COMPANY':            'ONE Gas',
    'SOUTHWEST GAS CORPORATION':            'Southwest Gas',
    'SOUTHWEST GAS':                        'Southwest Gas',
    'UNISOURCE ENERGY SERVICES (UNS)':      'Southwest Gas',
    'NATIONAL GRID':                        'National Grid',
    'KEYSPAN ENERGY DELIVERY':              'National Grid',
    'BROOKLYN UNION GAS':                   'National Grid',
    'UGI CENTRAL PENN GAS':                 'UGI Corporation',
    'UGI PENN NATURAL GAS':                 'UGI Corporation',
    'UGI UTILITIES':                        'UGI Corporation',
    'ELKTON GAS':                           'UGI Corporation',
    'MIDAMERICAN ENERGY':                   'BHE — Berkshire Hathaway Energy',
    'QUESTAR GAS CO':                       'Enbridge — Questar Gas',
    'QUESTAR GAS COMPANY':                  'Enbridge — Questar Gas',
    'QUESTAR PIPELINE':                     'Enbridge — Questar Gas',
    'ROCHESTER GAS AND ELECTRIC':           'Avangrid',
    'NYS ELECTRIC AND GAS':                 'Avangrid',
    'NEW ENGLAND GAS':                      'Avangrid',
    'NEW JERSEY NATURAL GAS':               'NJR — NJ Resources',
    'NEW JERSEY NATURAL GAS COMPANY':       'NJR — NJ Resources',
    'SOUTH JERSEY GAS':                     'SJI — South Jersey Industries',
    'SOUTH JERSEY GAS COMPANY':             'SJI — South Jersey Industries',
    'CHESAPEAKE UTILITIES CORPORATION':     'Chesapeake Utilities',
    'CHESAPEAKE UTILITIES':                 'Chesapeake Utilities',
    'FLORIDA CITY GAS':                     'Chesapeake Utilities',
    'INTERMOUNTAIN GAS COMPANY':            'MDU Resources',
    'INTERMOUNTAIN GAS':                    'MDU Resources',
    'CASCADE NATURAL GAS':                  'MDU Resources',
    'BLACK HILLS ENERGY':                   'Black Hills Corporation',
    'BLACK HILLS CORPORATION':              'Black Hills Corporation',
    'BLACK HILLS/COLORADO GAS':             'Black Hills Corporation',
    'BLACK HILLS/WYOMING GAS':              'Black Hills Corporation',
    'BLACK HILLS/NEBRASKA GAS':             'Black Hills Corporation',
    'BLACK HILLS/IOWA GAS':                 'Black Hills Corporation',
    'CONSUMERS ENERGY COMPANY':             'CMS — CMS Energy',
    'NSTAR GAS COMPANY':                    'ES — Eversource',
    'NARRAGANSETT ELECTRIC CO (GAS DIVISION OF RI)': 'PPL — PPL Corporation',
    'LOUISVILLE GAS & ELECTRIC':            'PPL — PPL Corporation',
    'BALTIMORE GAS AND ELECTRIC CO':        'EXC — Exelon',
    'SOUTH CAROLINA ELECTRIC & GAS':        'D — Dominion Energy',
    'DOMINION HOPE GAS INC':               'D — Dominion Energy',
    'PIEDMONT NATURAL GAS':                'Duke Energy',
    'PIEDMONT NATURAL GAS COMPANY':        'Duke Energy',
    'DUKE ENERGY OHIO':                    'Duke Energy',
    'DUKE ENERGY INDIANA':                 'Duke Energy',
    'DUKE ENERGY KENTUCKY':                'Duke Energy',
    # Additional unmapped LDCs
    'NORTHERN STATES POWER COMPANY (XCEL ENERGY)': 'Xcel Energy',
    'NORTHWEST NATURAL GAS CO.':           'NW Natural',
    'NORTHWEST NATURAL GAS COMPANY':       'NW Natural',
    'NORTHWEST NATURAL':                   'NW Natural',
    'CENTRAL HUDSON GAS AND ELECTRIC':     'Central Hudson Gas & Electric',
    'LIBERTY UTILITIES':                   'Liberty Utilities',
    'LIBERTY UTILITIES MA':                'Liberty Utilities',
    'LIBERTY UTILITIES NATURAL GAS':       'Liberty Utilities',
    'LIBERTY UTILITIES (EMPIRE STATE NATURAL GAS)': 'Liberty Utilities',
    'FLORIDA PUBLIC UTILITIES CO':         'Florida Public Utilities',
    'FLORIDA PUBLIC UTILITIES COMPANY':    'Florida Public Utilities',
    'PEOPLES NATURAL GAS COMPANY':         'Peoples Natural Gas',
    'PEOPLES NATURAL GAS':                 'Peoples Natural Gas',
    'COSERV GAS':                          'CoServ',
    'MOBILE GAS SVC CORP':                 'Spire',
    'MOBILE GAS SERVICE CORPORATION':      'Spire',
    'ROANOKE GAS COMPANY':                 'RGC Resources',
    'ROANOKE GAS':                         'RGC Resources',
}

# When gas LDC name would collide with an electric entry of same parent, use specific display name
DISPLAY_OVERRIDES = {
    'CENTERPOINT ENERGY': 'CenterPoint Gas (MN/MS/OK)',
}

print("Reading gas territories GeoJSON...")
with open(GAS_PATH, encoding='utf-8') as f:
    gas = json.load(f)

ldc_map = {}
for feat in gas['features']:
    p = feat['properties']
    if p.get('TYPE') != 'INVESTOR-OWNED':
        continue
    name = (p.get('NAME') or '').strip().upper()
    if not name or name == 'NOT AVAILABLE':
        continue
    state = (p.get('LDC_STATE') or p.get('STATE') or '').strip()
    cust  = int(p.get('TOTAL_CUST') or 0)
    ldc_map.setdefault(name, {'states': set(), 'total_cust': 0})
    if state:
        ldc_map[name]['states'].add(state)
    ldc_map[name]['total_cust'] += cust

print(f"Found {len(ldc_map)} INVESTOR-OWNED gas LDCs")

mapped = {}
unmapped = []
for name, d in ldc_map.items():
    parent = GAS_PARENT_MAP.get(name)
    display = DISPLAY_OVERRIDES.get(name, name.title())
    if parent:
        mapped.setdefault(parent, []).append({
            'name':         display,
            'gas_ldc_name': name,
            'state':        sorted(d['states'])[0] if d['states'] else '',
            'states':       sorted(d['states']),
            'type':         'gas',
            'total_cust':   d['total_cust'],
        })
    elif d['total_cust'] > 50000:
        unmapped.append((name, sorted(d['states']), d['total_cust']))

print(f"Mapped {sum(len(v) for v in mapped.values())} LDCs across {len(mapped)} parents")
if unmapped:
    print("Unmapped >50K:")
    for n,s,c in sorted(unmapped, key=lambda x:-x[2])[:10]:
        print(f"  {n:<50} {c:>10,}")

with open(IOU_PATH, encoding='utf-8') as f:
    iou = json.load(f)
groups = iou['groups']

# Remove ALL gas entries from previous runs
for parent in list(groups.keys()):
    groups[parent] = [e for e in groups[parent] if e.get('type') != 'gas']
    if not groups[parent]:
        del groups[parent]

# Permanent muni purge: remove any entry with non-IOU type
NON_IOU = {'NOT AVAILABLE','MUNICIPAL','COOPERATIVE','POLITICAL SUBDIVISION',
            'FEDERAL','BEHIND THE METER','Municipal','Cooperative','Federal'}
removed = 0
for parent in list(groups.keys()):
    before = len(groups[parent])
    groups[parent] = [e for e in groups[parent]
                      if e.get('type','') not in NON_IOU]
    removed += before - len(groups[parent])
    if not groups[parent]:
        del groups[parent]
print(f"\nRemoved {removed} muni/coop entries")

# Add gas LDCs
added = 0
for parent, items in sorted(mapped.items()):
    if parent in groups:
        groups[parent].extend(items)
    else:
        groups[parent] = items
    added += len(items)
print(f"Added {added} gas LDC entries")

# ── Embed SUMMER_CAP + CUSTOMERS from electric territories GeoJSON ──────
print("\nEmbedding capacity + customers from electric territories GeoJSON (slow ~10s)...")
try:
    with open(ELEC_PATH, encoding='utf-8') as f:
        elec_data = json.load(f)
    # Build name -> {summer_cap, customers} lookup (sum across multiple features per utility)
    elec_cap  = {}
    elec_cust = {}
    for feat in elec_data['features']:
        p    = feat['properties']
        name = (p.get('NAME') or '').strip().upper()
        cap  = float(p.get('SUMMER_CAP') or 0)
        cust = int(p.get('CUSTOMERS') or 0)
        if name:
            elec_cap[name]  = elec_cap.get(name,  0) + cap
            elec_cust[name] = elec_cust.get(name, 0) + cust
    print(f"  Loaded {len(elec_cap)} unique utility names")

    # Embed into iou_grouped entries
    updated = 0
    for parent in groups:
        for entry in groups[parent]:
            if entry.get('type') == 'gas': continue
            name_upper = entry.get('name','').upper()
            if name_upper in elec_cap:
                cap  = elec_cap[name_upper]
                cust = elec_cust.get(name_upper, 0)
                if cap  > 0: entry['summer_cap_mw'] = round(cap, 1)
                if cust > 0: entry['customers']     = cust
                updated += 1
    print(f"  Updated {updated} electric entries with capacity/customers")
except Exception as e:
    print(f"  Warning: could not read electric territories: {e}")

# ── Embed NUP + customers from FERC flat_utilities into electric entries ─
print("\nEmbedding NUP + customers from FERC flat_utilities...")
try:
    with open(r'E:\PowerAcademy\data\ferc1_opco_data.json', encoding='utf-8') as f:
        ferc1 = json.load(f)
    flat = ferc1.get('flat_utilities', {})

    def norm_simple(s):
        s = s.lower().strip()
        # Strip trailing legal suffixes (with and without period)
        for sfx in [' co.', ' corp.', ' inc.', ' llc', ' l.p.', ' lp', ' ltd', ' company', ' corporation', ' co']:
            if s.endswith(sfx):
                s = s[:-len(sfx)].strip()
        s = s.replace(' d/b/a ', ' ').replace(' dba ', ' ').replace(' and ', ' ').replace('&', ' ')
        s = re.sub(r'[^a-z0-9 ]', ' ', s)
        return re.sub(r'\s+', ' ', s).strip()

    flat_norm = {norm_simple(k): v for k, v in flat.items()}

    embedded_ferc = 0
    for parent in groups:
        for entry in groups[parent]:
            if entry.get('type') == 'gas': continue
            # Already has customers from GeoJSON — only add NUP from FERC
            name = entry.get('name', '')
            nn = norm_simple(name)
            # Try direct match first, then substring
            match = flat_norm.get(nn)
            if not match:
                for k, v in flat_norm.items():
                    if len(k) >= 5 and len(nn) >= 5 and (nn in k or k in nn):
                        match = v
                        break
            if match:
                if match.get('electric_nup_b'): entry['electric_nup_b'] = match['electric_nup_b']
                elif match.get('nup_b'):         entry['electric_nup_b'] = match['nup_b']
                if match.get('gas_nup_b'):       entry['gas_nup_b']      = match['gas_nup_b']
                # Only use FERC customers if GeoJSON didn't have them
                if not entry.get('customers') and match.get('customers'):
                    entry['customers'] = match['customers']
                embedded_ferc += 1
    print(f"  Embedded FERC data into {embedded_ferc} electric entries")
except Exception as e:
    print(f"  Warning: could not embed FERC data: {e}")

with open(IOU_PATH, 'w', encoding='utf-8') as f:
    json.dump(iou, f, indent=2, ensure_ascii=False)
print(f"Saved: {IOU_PATH}")

# Verify
remaining = [(k,e) for k,v in groups.items() for e in v
             if e.get('type','') in NON_IOU]
if remaining:
    print(f"WARNING: {len(remaining)} bad entries remain:")
    for k,e in remaining[:5]: print(f"  {k}: {e.get('name')}")
else:
    print("Verified: no munis/coops remain")

# Check Questar added
questar = [(k,e) for k,v in groups.items() for e in v
           if 'questar' in e.get('gas_ldc_name','').lower()]
print(f"Questar entries: {questar}")

# Check CenterPoint MN
cnp = [(k,e) for k,v in groups.items() for e in v
       if e.get('gas_ldc_name') == 'CENTERPOINT ENERGY']
print(f"CenterPoint gas MN/MS/OK entry: {cnp}")