"""
Power Academy — IOU Territory Builder
Reads HIFLD GeoJSON, filters to regulated IOUs only,
outputs a single file for the full-map view.

Run: python build_iou_map.py
Output: E:\PowerAcademy\data\iou_territories.geojson
"""

import json
from pathlib import Path
from datetime import datetime

INPUT  = Path(r"E:\PowerAcademy\data\eia_cache\hifld_territories.geojson")
OUTPUT = Path(r"E:\PowerAcademy\data\iou_territories.geojson")

# HIFLD TYPE field values to EXCLUDE (keep only regulated IOUs)
EXCLUDE_TYPES = {
    "MUNICIPAL",
    "COOPERATIVE",
    "POLITICAL SUBDIVISION",
    "FEDERAL",
    "STATE",
    "IRRIGATION DISTRICT",
    "OTHER",
    "BEHIND THE METER",
    "WHOLESALE ONLY",
}

# Keywords in NAME that indicate non-IOU even if TYPE is wrong
EXCLUDE_NAME_KEYWORDS = [
    " CITY OF ", "CITY OF ", "TOWN OF ", "COUNTY OF ",
    "MUNICIPAL", " MUD ", " MUA ", " MUNI ",
    "RURAL ELEC", "RURAL ELECTRIC", " CO-OP", " COOP",
    "COOPERATIVE", "ELECTRIC COOPERATIVE",
    "POWER AUTHORITY", "PUBLIC POWER",
    "TENNESSEE VALLEY", "BONNEVILLE",
    "WESTERN AREA", "SOUTHWESTERN POWER",
    "SOUTHEASTERN POWER", "ALASKA VILLAGE",
    "IRRIGATION", "RECLAMATION",
]

# Your 15 coverage company tickers mapped to HIFLD NAME fragments
COVERAGE_MAP = {
    "NEE":  ["FLORIDA POWER & LIGHT","FPL","GULF POWER","NEXTERA ENERGY RESOURCES"],
    "D":    ["VIRGINIA ELECTRIC","DOMINION ENERGY SOUTH CAROLINA","DOMINION ENERGY VIRGINIA"],
    "ETR":  ["ENTERGY ARKANSAS","ENTERGY LOUISIANA","ENTERGY MISSISSIPPI","ENTERGY NEW ORLEANS","ENTERGY TEXAS"],
    "CMS":  ["CONSUMERS ENERGY"],
    "PPL":  ["PPL ELECTRIC","LOUISVILLE GAS AND ELECTRIC","KENTUCKY UTILITIES"],
    "AEE":  ["AMEREN MISSOURI","AMEREN ILLINOIS","UNION ELECTRIC"],
    "POR":  ["PORTLAND GENERAL ELECTRIC"],
    "EIX":  ["SOUTHERN CALIFORNIA EDISON"],
    "PCG":  ["PACIFIC GAS & ELECTRIC","PACIFIC GAS AND ELECTRIC"],
    "HE":   ["HAWAIIAN ELECTRIC","HAWAII ELECTRIC LIGHT","MAUI ELECTRIC"],
    "EVRG": ["EVERGY METRO","EVERGY KANSAS","WESTAR","KANSAS CITY POWER","KCP&L"],
    "ES":   ["PUBLIC SERVICE OF NEW HAMPSHIRE","CONNECTICUT LIGHT AND POWER",
             "NSTAR ELECTRIC","WESTERN MASSACHUSETTS ELECTRIC","EVERSOURCE"],
    "VST":  [],  # merchant, no territory
    "TLN":  [],  # merchant
    "XIFR": [],  # yieldco
}

def get_ticker(name_upper):
    for ticker, frags in COVERAGE_MAP.items():
        for frag in frags:
            if frag in name_upper:
                return ticker
    return None

def is_iou(feat):
    props     = feat.get("properties", {})
    feat_type = str(props.get("TYPE", "")).upper().strip()
    feat_name = str(props.get("NAME", "")).upper().strip()
    naics     = str(props.get("NAICS_CODE", "")).strip()

    # Exclude by type
    if feat_type in EXCLUDE_TYPES:
        return False

    # Exclude by name keywords
    for kw in EXCLUDE_NAME_KEYWORDS:
        if kw.upper() in feat_name:
            return False

    # NAICS 2211 = Electric Power Generation/Transmission/Distribution (IOU)
    # NAICS 2212 = Natural Gas Distribution (sometimes included)
    # Cooperatives often have NAICS 2211 too — catch them by name/type above
    # Keep if type looks like IOU
    iou_types = {"INVESTOR OWNED", "IOU", "INVESTOR-OWNED", "PRIVATE"}
    if any(t in feat_type for t in iou_types):
        return True

    # If type is empty or unknown but name doesn't match exclusions, include
    if feat_type in ("", "NONE", "NOT AVAILABLE"):
        return True

    return True  # default include if passed all filters above

def main():
    if not INPUT.exists():
        print(f"ERROR: {INPUT} not found")
        return

    print(f"Loading {INPUT.stat().st_size//1024//1024}MB HIFLD file...")
    with open(INPUT, encoding="utf-8") as f:
        data = json.load(f)

    all_features = data.get("features", [])
    print(f"Total features: {len(all_features):,}")

    # Show type distribution
    from collections import Counter
    types = Counter(str(f.get("properties",{}).get("TYPE","")).upper() for f in all_features)
    print("Type distribution:")
    for t, count in types.most_common(15):
        print(f"  {count:4d}  {t}")

    # Filter to IOUs
    iou_features = []
    excluded = 0
    for feat in all_features:
        if is_iou(feat):
            props = feat.get("properties", {})
            name  = str(props.get("NAME","")).upper()
            ticker = get_ticker(name)

            # Add coverage flag to properties
            feat["properties"]["_coverage_ticker"] = ticker
            feat["properties"]["_is_coverage"]     = ticker is not None
            iou_features.append(feat)
        else:
            excluded += 1

    print(f"\nKept {len(iou_features):,} IOUs, excluded {excluded:,} munis/co-ops/federal")

    coverage_count = sum(1 for f in iou_features if f["properties"]["_is_coverage"])
    print(f"Coverage companies found: {coverage_count} polygons across your 15 companies")

    # Write output
    out = {
        "type":      "FeatureCollection",
        "generated": datetime.now().isoformat(),
        "note":      "Regulated IOUs only. Coverage companies flagged with _is_coverage=true.",
        "features":  iou_features,
    }

    print(f"\nWriting {OUTPUT}...")
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(out, f)

    size_mb = OUTPUT.stat().st_size // 1024 // 1024
    print(f"Done. Output: {size_mb}MB at {OUTPUT}")

if __name__ == "__main__":
    main()