"""
patch_awr_geojson.py
Creates AWR.geojson with Bear Valley Electric Service territory.
AWR is a water utility but also owns Bear Valley Electric (San Bernardino Mtns).
The water territories aren't in HIFLD electric data — this creates the file
with Bear Valley electric polygon + CA as service state.

Saves to whichever territories directory exists on your machine.
"""
import json, os, sys

DATA_DIR   = r"E:\PowerAcademy\data"
ELEC_FILE  = os.path.join(DATA_DIR, "electric_territories_full.geojson")

# Find the territories directory — check both common layouts
TERR_CANDIDATES = [
    os.path.join(DATA_DIR, "territories"),
    os.path.join(DATA_DIR, "eia", "territories"),
    os.path.join(DATA_DIR, "eia"),
]
TERR_DIR = None
for c in TERR_CANDIDATES:
    if os.path.isdir(c):
        # Check if it has any .geojson files (confirming it's the right dir)
        files = [f for f in os.listdir(c) if f.endswith('.geojson')]
        if files:
            print(f"Found territories dir: {c} ({len(files)} .geojson files, e.g. {files[0]})")
            TERR_DIR = c
            break

if TERR_DIR is None:
    # No existing dir — create under data/territories
    TERR_DIR = os.path.join(DATA_DIR, "territories")
    os.makedirs(TERR_DIR, exist_ok=True)
    print(f"Created territories dir: {TERR_DIR}")

AWR_FILE = os.path.join(TERR_DIR, "AWR.geojson")

print("\nLoading electric territories (150MB, takes ~10s)...")
with open(ELEC_FILE, "r", encoding="utf-8") as f:
    elec = json.load(f)

bear_valley = [
    feat for feat in elec["features"]
    if "bear valley" in (feat.get("properties", {}).get("NAME") or "").lower()
]
print(f"Found {len(bear_valley)} Bear Valley Electric feature(s):")
for feat in bear_valley:
    p = feat.get("properties", {})
    print(f"  NAME={p.get('NAME')} | SOURCEDATE={p.get('SOURCEDATE')}")

if not bear_valley:
    print("ERROR: Bear Valley Electric not found in electric_territories_full.geojson")
    sys.exit(1)

# Tag features with segment label
for feat in bear_valley:
    feat.setdefault("properties", {})
    feat["properties"]["layer"]   = "electric"
    feat["properties"]["segment"] = "Bear Valley Electric Service"

# Build AWR.geojson from scratch (water territories not in HIFLD electric data)
awr = {
    "type": "FeatureCollection",
    "ticker": "AWR",
    "service_states": ["CA"],
    "note": "Includes Bear Valley Electric Service (electric segment). Water territories sourced separately.",
    "features": bear_valley
}

with open(AWR_FILE, "w", encoding="utf-8") as f:
    json.dump(awr, f)

print(f"\nDone. Created {AWR_FILE}")
print(f"  {len(bear_valley)} feature(s), service_states: {awr['service_states']}")
print("Restart Node server so it serves the new file.")