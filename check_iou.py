import json

with open('E:/PowerAcademy/data/iou_grouped.json', encoding='utf-8') as f:
    d = json.load(f)

groups = d['groups']

print("=== CenterPoint parent keys ===")
for k in groups:
    if 'center' in k.lower():
        names = [i['name'] for i in groups[k][:3]]
        print(f"  '{k}': {names}")

print("\n=== NFG parent keys ===")
for k in groups:
    if 'national fuel' in k.lower() or 'nfg' in k.lower():
        print(f"  '{k}'")

print("\n=== Atmos parent keys ===")
for k in groups:
    if 'atmos' in k.lower():
        print(f"  '{k}'")

print("\n=== All parent keys (first 30) ===")
for k in list(groups.keys())[:30]:
    print(f"  '{k}'")