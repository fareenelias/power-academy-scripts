"""
Power Academy — HIFLD Territory Slicer
Reads the 46MB HIFLD GeoJSON and produces per-company territory files.

Run: python slice_hifld_territories.py
Input:  E:\PowerAcademy\data\eia_cache\hifld_territories.geojson
Output: E:\PowerAcademy\data\territories\{TICKER}.geojson (one per company)
"""

import json
from pathlib import Path
from datetime import datetime

INPUT  = Path("E:/PowerAcademy/data/eia_cache/hifld_territories.geojson")
OUTPUT = Path("E:/PowerAcademy/data/territories")

# Company -> subsidiary name fragments to match against HIFLD NAME field
COMPANY_NAMES = {
    "NEE":  ["Florida Power & Light","FPL","Gulf Power","NextEra Energy Resources"],
    "D":    ["Virginia Electric","Dominion Energy South Carolina","Dominion Energy Virginia"],
    "ETR":  ["Entergy Arkansas","Entergy Louisiana","Entergy Mississippi","Entergy New Orleans","Entergy Texas"],
    "CMS":  ["Consumers Energy"],
    "PPL":  ["PPL Electric","Louisville Gas and Electric","Kentucky Utilities"],
    "AEE":  ["Ameren Missouri","Ameren Illinois","Union Electric"],
    "POR":  ["Portland General Electric"],
    "EIX":  ["Southern California Edison"],
    "PCG":  ["Pacific Gas & Electric","Pacific Gas and Electric"],
    "HE":   ["Hawaiian Electric","Hawaii Electric Light","Maui Electric"],
    "EVRG": ["Evergy Metro","Evergy Kansas","Westar","Kansas City Power","KCP&L"],
    "ES":   ["Public Service of New Hampshire","Connecticut Light and Power",
             "NSTAR Electric","Western Massachusetts Electric","Eversource"],
    "VST":  ["Luminant","TXU Energy","Dynegy","Vistra"],
    "TLN":  ["Talen Energy","PPL Susquehanna","Brandon Shores","Susquehanna Nuclear"],
    "XIFR": ["NextEra Energy Partners","XPLR"],
}

COMPANY_DISPLAY = {
    "NEE":"NextEra Energy","D":"Dominion Energy","ETR":"Entergy",
    "CMS":"CMS Energy","PPL":"PPL Corporation","AEE":"Ameren",
    "POR":"Portland General Electric","EIX":"Edison International",
    "PCG":"PG&E","HE":"Hawaiian Electric","EVRG":"Evergy",
    "ES":"Eversource Energy","VST":"Vistra Energy",
    "TLN":"Talen Energy","XIFR":"XPLR Infrastructure",
}

def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)

    if not INPUT.exists():
        print(f"ERROR: {INPUT} not found")
        print("Download from: https://www.datalumos.org/datalumos/project/239091/version/V2/view")
        return

    print(f"Loading {INPUT.stat().st_size//1024//1024}MB HIFLD file...")
    with open(INPUT, encoding='utf-8') as f:
        data = json.load(f)

    features = data.get("features", [])
    print(f"Total features: {len(features):,}")

    # Show sample fields
    if features:
        props = features[0].get("properties", {})
        print(f"Fields: {list(props.keys())}")
        print(f"Sample: {dict(list(props.items())[:5])}")

    # Find the name field
    name_field = None
    if features:
        props = features[0].get("properties", {})
        for candidate in ["NAME","UTILITY_NAME","UTIL_NAME","UTILITYNAM","name"]:
            if candidate in props:
                name_field = candidate
                break
    print(f"Using name field: {name_field}")

    # Slice per company
    results = {}
    for feature in features:
        props = feature.get("properties", {})
        feat_name = str(props.get(name_field, "")).upper() if name_field else ""

        for ticker, fragments in COMPANY_NAMES.items():
            for frag in fragments:
                if frag.upper() in feat_name:
                    if ticker not in results:
                        results[ticker] = []
                    results[ticker].append(feature)
                    break

    # Write per-company GeoJSON
    for ticker, features_list in results.items():
        out = {
            "type":        "FeatureCollection",
            "ticker":      ticker,
            "name":        COMPANY_DISPLAY.get(ticker, ticker),
            "generated":   datetime.now().isoformat(),
            "data_source": "HIFLD-2024",
            "features":    features_list,
            "service_states": sorted(set(
                f.get("properties",{}).get("STATE","")
                for f in features_list
                if f.get("properties",{}).get("STATE")
            )),
        }
        out_path = OUTPUT / f"{ticker}.geojson"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f)
        size_kb = out_path.stat().st_size // 1024
        print(f"  {ticker}: {len(features_list)} polygons → {size_kb}KB")

    # Report missing
    missing = [t for t in COMPANY_NAMES if t not in results]
    if missing:
        print(f"\nNo match found for: {missing}")
        print("Check HIFLD NAME field values manually")

    print(f"\nDone. {len(results)}/{len(COMPANY_NAMES)} companies matched.")
    print(f"Output: {OUTPUT}")

if __name__ == "__main__":
    main()