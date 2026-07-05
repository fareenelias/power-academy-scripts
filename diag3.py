import json, re

IOU  = r'E:\PowerAcademy\data\iou_grouped.json'
ELEC = r'E:\PowerAcademy\data\electric_territories_full.geojson'

def norm(s):
    s = s.lower()
    for sfx in [' co.',' corp.',' inc.',' llc',' l.p.',' lp',' ltd',' company',' corporation']:
        s = s.replace(sfx, ' ')
    s = s.replace(' and ',' ').replace('&',' ')
    s = re.sub(r'[^a-z0-9 ]',' ', s)
    return re.sub(r'\s+', ' ', s).strip()

with open(IOU, encoding='utf-8') as f:
    iou = json.load(f)
g = iou['groups']

# NV Energy entry name
print("=== NV Energy in iou_grouped ===")
for k,v in g.items():
    for item in v:
        if 'nv energy' in item.get('name','').lower() or 'nevada' in item.get('name','').lower():
            print(f"  parent='{k}' name='{item['name']}' type='{item.get('type')}'")

# What the JS info panel does:
# normFn(name) where name = item['name'] from sidebar
# Then looks for k in flat_utilities where nn.includes(k) || k.includes(nn)
# NV Energy name in sidebar -> normFn -> what?
for k,v in g.items():
    for item in v:
        if 'nv energy' in item.get('name','').lower() or 'nevada' in item.get('name','').lower():
            n = norm(item['name'])
            print(f"  norm('{item['name']}') = '{n}'")
            # Does 'nv energy' in 'nevada power d b a nv energy'? YES
            # Does 'nevada power d b a nv energy' in 'nv energy'? NO
            # Does norm(sidebar_name) in flat_key? 
            flat_key = 'nevada power d b a nv energy'
            print(f"  '{n}' in '{flat_key}': {n in flat_key}")
            print(f"  '{flat_key}' in '{n}': {flat_key in n}")

# Electric territories capacity fields - build lookup
print("\n=== Building name->capacity lookup from electric_territories_full.geojson ===")
print("Reading electric territories (slow ~10s)...")
cap_lookup = {}
cust_lookup_elec = {}
with open(ELEC, encoding='utf-8') as f:
    elec = json.load(f)
for feat in elec['features']:
    p = feat['properties']
    if p.get('TYPE') not in ('INVESTOR OWNED', 'COOPERATIVE', 'MUNICIPAL'):
        pass
    name = (p.get('NAME') or '').strip().upper()
    cap  = p.get('SUMMER_CAP') or 0
    cust = p.get('CUSTOMERS') or 0
    if name:
        cap_lookup[name]  = (cap_lookup.get(name,  0) or 0) + (cap  or 0)
        cust_lookup_elec[name] = (cust_lookup_elec.get(name, 0) or 0) + (cust or 0)

# Check NV Energy
for name, cap in cap_lookup.items():
    if 'nevada' in name.lower() or 'nv energy' in name.lower() or 'sierra pacific' in name.lower():
        print(f"  '{name}': SUMMER_CAP={cap:.0f} MW, CUSTOMERS={cust_lookup_elec.get(name,0):,}")

# Check a few non-coverage IOUs
for name in ['EL PASO ELECTRIC CO', 'CLECO POWER LLC', 'AEP TEXAS CENTRAL', 'EVERGY METRO', 'NV ENERGY']:
    if name in cap_lookup:
        print(f"  '{name}': {cap_lookup[name]:.0f} MW, {cust_lookup_elec.get(name,0):,} cust")

print(f"\nTotal entries in cap_lookup: {len(cap_lookup)}")