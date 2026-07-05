import json

TX   = r'E:\PowerAcademy\data\transmission_lines.geojson'
GAS  = r'E:\PowerAcademy\data\gas_territories.geojson'
IOU  = r'E:\PowerAcademy\data\iou_grouped.json'

print("=== 1. TRANS BAY CABLE in transmission_lines.geojson ===")
with open(TX, encoding='utf-8') as f:
    tx = json.load(f)
found = []
for feat in tx['features']:
    o = (feat['properties'].get('OWNER') or '').lower()
    if 'trans bay' in o or 'transbay' in o:
        found.append(feat['properties'])
if found:
    for p in found: print(p)
else:
    print("NOT FOUND. Checking DC/cable lines:")
    for feat in tx['features']:
        t = (feat['properties'].get('TYPE') or '').lower()
        if 'dc' in t or 'cable' in t:
            print(feat['properties'])
            break

print("\n=== 2. CenterPoint in iou_grouped.json ===")
with open(IOU, encoding='utf-8') as f:
    iou = json.load(f)
g = iou['groups']
for k in g:
    if 'centerpoint' in k.lower():
        print(f"Parent: '{k}'")
        for item in g[k]:
            print(f"  name={item.get('name')!r} type={item.get('type')!r} state={item.get('state')!r} states={item.get('states')} gas_ldc_name={item.get('gas_ldc_name')!r}")

print("\n=== 3. Questar/Utah in gas_territories.geojson ===")
with open(GAS, encoding='utf-8') as f:
    gas = json.load(f)
for feat in gas['features']:
    p = feat['properties']
    state = p.get('LDC_STATE') or p.get('STATE') or ''
    name = p.get('NAME') or ''
    if state == 'UT' or 'questar' in name.lower() or 'enbridge' in name.lower():
        print({'NAME': name, 'TYPE': p.get('TYPE'), 'LDC_STATE': state, 'TOTAL_CUST': p.get('TOTAL_CUST')})

print("\n=== 4. Morgan City in gas_territories.geojson ===")
for feat in gas['features']:
    p = feat['properties']
    if 'morgan' in (p.get('NAME') or '').lower():
        print({'NAME': p.get('NAME'), 'TYPE': p.get('TYPE'), 'LDC_STATE': p.get('LDC_STATE'), 'STATE': p.get('STATE')})

print("\n=== 5. Morgan City in iou_grouped.json ===")
for k in g:
    for item in g[k]:
        if 'morgan' in item.get('name','').lower():
            print(f"Parent='{k}' entry={item}")