"""
Check HIFLD names for unmatched companies
Run: python check_hifld_names.py
"""
import json
from pathlib import Path

INPUT = Path("E:/PowerAcademy/data/eia_cache/hifld_territories.geojson")

# Search terms for unmatched companies
SEARCH = {
    "PCG":  ["pacific gas","pg&e","pge","pacific gas and electric"],
    "VST":  ["vistra","luminant","txu","dynegy","energy future"],
    "TLN":  ["talen","susquehanna","brandon shores","wagner","ppl generation"],
    "XIFR": ["nextera energy partners","xplr","nep renewable"],
}

print("Loading HIFLD...")
with open(INPUT, encoding='utf-8') as f:
    data = json.load(f)

features = data.get("features", [])
print(f"Searching {len(features):,} features...\n")

for ticker, terms in SEARCH.items():
    print(f"=== {ticker} ===")
    found = []
    for feat in features:
        name = str(feat.get("properties", {}).get("NAME", "")).lower()
        for term in terms:
            if term.lower() in name:
                found.append(feat["properties"]["NAME"])
                break
    if found:
        print(f"  MATCHES: {found}")
    else:
        print(f"  No match. Showing all names containing common keywords:")
        # Show any name that might be related
        for feat in features:
            name = str(feat.get("properties", {}).get("NAME", ""))
            state = feat.get("properties", {}).get("STATE", "")
            # PCG is CA, VST/TLN are TX/PA/MD, XIFR is multi-state
            if ticker == "PCG" and state == "CA":
                print(f"    CA: {name}")
            elif ticker == "VST" and state in ("TX","IL","OH","PA"):
                print(f"    {state}: {name}")
            elif ticker == "TLN" and state in ("PA","MD","MT"):
                print(f"    {state}: {name}")
    print()