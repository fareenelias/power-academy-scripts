import json, re

GAS  = r'E:\PowerAcademy\data\gas_territories.geojson'
TX   = r'E:\PowerAcademy\data\transmission_lines.geojson'
IOU  = r'E:\PowerAcademy\data\iou_grouped.json'
FERC = r'E:\PowerAcademy\data\ferc1_opco_data.json'

def norm(s):
    s = s.lower()
    for sfx in [' co.',' corp.',' inc.',' llc',' l.p.',' lp',' ltd',' company',' corporation',' incorporated']:
        s = s.replace(sfx, ' ')
    s = s.replace(' and ',' ').replace('&',' ')
    s = re.sub(r'[^a-z0-9 ]',' ', s)
    return re.sub(r'\s+', ' ', s).strip()

# 1. What key does "CenterPoint Gas (MN/MS/OK)" create, and does it match gas GeoJSON?
print("=== 1. CENTERPOINT GAS MATCHING ===")
with open(IOU, encoding='utf-8') as f:
    iou = json.load(f)
g = iou['groups']
for item in g.get('CenterPoint Energy', []):
    print(f"  name={item.get('name')!r} gas_ldc_name={item.get('gas_ldc_name')!r} type={item.get('type')!r}")

# Simulate JS matching: when "CenterPoint Gas (MN/MS/OK)" is selected
# parent='CenterPoint Energy', name='CenterPoint Gas (MN/MS/OK)', ticker=''
# The JS does: gasItem = parentItems.find(i => i.name === name && i.type === 'gas')
# name in sidebar = 'CenterPoint Gas (MN/MS/OK)'
# item.name in iouGroups = 'CenterPoint Gas (MN/MS/OK)'
# So gasItem.gas_ldc_name = 'CENTERPOINT ENERGY'
# exactGasNames.add('CENTERPOINT ENERGY')
# Gas GeoJSON NAME='CENTERPOINT ENERGY' -> matches exactGasNames ✓
# BUT: the parent term 'centerpoint energy' is also in gasTerms
# so BOTH approaches should work
print()
print("  gasTerms would include: norm('CenterPoint Energy') =", norm('CenterPoint Energy'))
print("  GeoJSON NAME 'CENTERPOINT ENERGY - ENTEX' norm =", norm('CENTERPOINT ENERGY - ENTEX'))
print("  Match via gasTermList: 'centerpoint energy' in 'centerpoint energy entex' =", 
      'centerpoint energy' in norm('CENTERPOINT ENERGY - ENTEX'))
print("  Match via exactGasNames: 'CENTERPOINT ENERGY' == 'CENTERPOINT ENERGY' =", True)
print()
print("  KEY QUESTION: does gasDataLoaded ever trigger the effect?")
print("  Check: gas fetch sets setGasDataLoaded(true) -> re-runs effect")
print("  But if user selects CenterPoint BEFORE gas data loads, effect runs once with empty ref")
print("  Then gasDataLoaded flips to true -> effect re-runs -> should work now")
print("  Unless: the effect clears layers and re-runs, but CenterPoint is no longer selected")

# 2. El Paso Electric - what TX lines match?
print("\n=== 2. EL PASO ELECTRIC TX OWNER MATCHING ===")
# El Paso Electric parent key in iou_grouped:
for k in g:
    for item in g[k]:
        if 'el paso' in item.get('name','').lower() and 'electric' in item.get('name','').lower():
            print(f"  Found: parent='{k}' name='{item['name']}'")

# TX matching uses: gasTerms (which includes norm(parent)) + TX_ALIASES
# parent = 'El Paso Electric' -> norm = 'el paso electric'
# TX_ALIASES has no entry for El Paso Electric (it's not a coverage ticker)
# So txTermList includes 'el paso electric'
# OWNER field: what owners contain 'el paso'?
print()
print("  TX owners containing 'el paso' or 'paso':")
with open(TX, encoding='utf-8') as f:
    tx = json.load(f)
owners = set()
for feat in tx['features']:
    o = feat['properties'].get('OWNER','') or ''
    if 'el paso' in o.lower() or ('paso' in o.lower() and 'electric' not in o.lower()):
        owners.add(o)
for o in sorted(owners):
    print(f"    '{o}'")

# Also check firstWord logic: 'El Paso Electric' firstWord = 'el' (2 chars, <=4) -> added to txTerms
# 'el' would match ANYTHING with 'el' in owner name -> massive false positives!
print()
print("  firstWord of 'El Paso Electric' =", 'el paso electric'.split()[0], "(len=2, <=4 -> ADDED TO txTerms)")
print("  This matches any owner containing 'el' -> massive false positives!")

# 3. Non-coverage IOU capacity
print("\n=== 3. NON-COVERAGE IOU CAPACITY ===")
print("  Non-coverage IOUs have no plants file (no EIA 860 plants JSON)")
print("  mw=0, so capacity row doesn't show")
print("  electric_territories_full.geojson has CUSTOMERS and MEGAWATTS fields?")
# Check first few features of electric territories
# We don't have it here but we know it was built from EIA 860

# 4. NV Energy missing from flat_utilities
print("\n=== 4. NV ENERGY IN FERC DATA ===")
with open(FERC, encoding='utf-8') as f:
    ferc = json.load(f)
flat = ferc.get('flat_utilities', {})
# Check for NV Energy
nv_matches = [(k,v) for k,v in flat.items() if 'nevada' in k or 'nv energy' in k or 'sierra pacific' in k or 'nevada power' in k]
print(f"  NV Energy matches in flat_utilities: {nv_matches}")
print(f"  flat_utilities total: {len(flat)} entries")
# NV Energy files as 'Nevada Power Company' and 'Sierra Pacific Power Company'
print("  norm('NV Energy') =", norm('NV Energy'))
print("  Looking for match to 'nv energy' in flat_utilities...")
nn = norm('NV Energy')
match = [(k,v) for k,v in flat.items() if nn in k or k in nn]
print(f"  Matches: {match}")