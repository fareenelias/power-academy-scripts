"""Extract sorted IOU list from HIFLD for the map sidebar"""
import json
from pathlib import Path
from collections import Counter

INPUT = Path(r"E:\PowerAcademy\data\eia_cache\hifld_territories.geojson")

EXCLUDE_TYPES = {
    "MUNICIPAL","COOPERATIVE","POLITICAL SUBDIVISION","FEDERAL",
    "STATE","IRRIGATION DISTRICT","OTHER","BEHIND THE METER",
    "WHOLESALE ONLY",
}
EXCLUDE_NAME_KW = [
    "CITY OF ","TOWN OF ","COUNTY OF ","MUNICIPAL"," MUD "," MUA ",
    "RURAL ELEC","RURAL ELECTRIC"," CO-OP"," COOP","COOPERATIVE",
    "ELECTRIC COOPERATIVE","POWER AUTHORITY","PUBLIC POWER",
    "TENNESSEE VALLEY","BONNEVILLE","WESTERN AREA","SOUTHWESTERN POWER",
    "SOUTHEASTERN POWER","ALASKA VILLAGE","IRRIGATION","RECLAMATION",
]

with open(INPUT, encoding="utf-8") as f:
    data = json.load(f)

ious = []
seen = set()
for feat in data["features"]:
    p    = feat.get("properties", {})
    typ  = str(p.get("TYPE","")).upper().strip()
    name = str(p.get("NAME","")).strip()
    state= str(p.get("STATE","")).strip()

    if typ in EXCLUDE_TYPES: continue
    if any(kw.upper() in name.upper() for kw in EXCLUDE_NAME_KW): continue
    if name in seen: continue
    seen.add(name)

    ious.append({"name": name, "state": state, "type": typ})

ious.sort(key=lambda x: x["name"])
print(f"Total IOUs: {len(ious)}")
print("\nFirst 20:")
for u in ious[:20]:
    print(f"  {u['state']:2s}  {u['name']}")

# Output as JSON for the React component
out_path = Path(r"E:\PowerAcademy\data\iou_list.json")
with open(out_path, "w") as f:
    json.dump(ious, f, indent=2)
print(f"\nSaved to {out_path}")