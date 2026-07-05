"""
download_gas_and_transmission.py
---------------------------------
Downloads two GIS datasets for Power Academy:

1. HIFLD Natural Gas Distribution Service Territories (polygon)
   → Filters to coverage utility companies
   → Output: data/gas_territories.geojson

2. EIA / HIFLD Electric Power Transmission Lines (line)
   → Filters to states where coverage companies operate
   → Output: data/transmission_lines.geojson

Both are public, no API key required.

Run:
    python download_gas_and_transmission.py --out E:/PowerAcademy/data

These files are large - expect a few minutes for transmission lines.
"""

import argparse, json, os, sys, time, urllib.request, urllib.error

parser = argparse.ArgumentParser()
parser.add_argument("--out", required=True, help="Output directory (data folder)")
parser.add_argument("--skip-gas",  action="store_true", help="Skip gas territories")
parser.add_argument("--skip-tx",   action="store_true", help="Skip transmission lines")
args = parser.parse_args()

os.makedirs(args.out, exist_ok=True)

# Coverage states - where our utilities operate
COVERAGE_STATES = {
    "FL","TX","NH","CT","MA","RI","NY","NJ","PA","MD","VA","NC","SC",
    "GA","AL","MS","LA","AR","OK","MO","IL","MI","WI","MN","IA","KS",
    "OH","KY","IN","WV","TN","CA","OR","HI","AZ","CO","UT","NM",
}

# Coverage utility company names (partial match against HIFLD NAME field)
GAS_COVERAGE_NAMES = [
    "Consumers Energy", "Dominion", "Ameren", "Eversource",
    "PPL", "Louisville Gas", "National Fuel",
    "Columbia Gas", "Peoples Natural Gas", "Essential Utilities",
    "Southwest Gas", "New Jersey Resources", "South Jersey",
]

def fetch_arcgis(url, label, max_records=2000):
    """Paginate through ArcGIS Feature Service and return all features."""
    features = []
    offset = 0
    while True:
        paged = f"{url}&resultOffset={offset}&resultRecordCount={max_records}"
        print(f"  Fetching {label} offset={offset}...", end=" ", flush=True)
        try:
            with urllib.request.urlopen(paged, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print(f"ERROR: {e}")
            break
        batch = data.get("features", [])
        print(f"{len(batch)} features")
        features.extend(batch)
        if len(batch) < max_records:
            break
        offset += max_records
        time.sleep(0.5)
    return features

# ── 1. Gas Service Territories ─────────────────────────────────────────────
if not args.skip_gas:
    print("\n=== Downloading Gas Service Territories (HIFLD) ===")
    # HIFLD Natural Gas Distribution Areas
    GAS_URL = (
        "https://services1.arcgis.com/Hp6G80Pky0om7QvQ/arcgis/rest/services/"
        "Natural_Gas_Local_Distribution_Companies/FeatureServer/0/query?"
        "where=1%3D1&outFields=NAME,STATE,HIFLDID,SUPPLIER,TYPE&"
        "outSR=4326&f=geojson"
    )
    features = fetch_arcgis(GAS_URL, "gas territories")

    # Filter to coverage states and companies
    filtered = []
    for feat in features:
        props = feat.get("properties") or feat.get("attributes") or {}
        state = props.get("STATE", "")
        name  = props.get("NAME", "")
        if state in COVERAGE_STATES:
            filtered.append(feat)

    out = {
        "type": "FeatureCollection",
        "features": filtered,
        "_source": "HIFLD Natural Gas Local Distribution Companies",
        "_downloaded": time.strftime("%Y-%m-%d"),
        "_filter": f"States: {sorted(COVERAGE_STATES)}",
    }
    out_path = os.path.join(args.out, "gas_territories.geojson")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f)
    print(f"✓ Gas territories: {len(filtered)} features → {out_path}")

# ── 2. Transmission Lines ──────────────────────────────────────────────────
if not args.skip_tx:
    print("\n=== Downloading Transmission Lines (HIFLD) ===")
    print("  Note: large dataset, filtering to coverage states on download")

    # HIFLD Electric Power Transmission Lines
    # Filter by state at query time to reduce size
    state_clause = " OR ".join(f"STATE='{s}'" for s in sorted(COVERAGE_STATES))
    TX_URL = (
        "https://services1.arcgis.com/Hp6G80Pky0om7QvQ/arcgis/rest/services/"
        "Electric_Power_Transmission_Lines/FeatureServer/0/query?"
        f"where={urllib.parse.quote(state_clause)}&"
        "outFields=ID,OWNER,VOLTAGE,VOLT_CLASS,STATUS,STATE,TYPE&"
        "outSR=4326&f=geojson"
    )

    import urllib.parse
    features = fetch_arcgis(TX_URL, "transmission lines", max_records=1000)

    # Further filter: only high voltage (>= 115kV) to keep file manageable
    hv_features = []
    for feat in features:
        props = feat.get("properties") or feat.get("attributes") or {}
        voltage = props.get("VOLTAGE", 0) or 0
        status  = props.get("STATUS", "")
        if voltage >= 115 and status in ("IN SERVICE", "Active", "ACTIVE", "IN_SERVICE", ""):
            hv_features.append(feat)

    out = {
        "type": "FeatureCollection",
        "features": hv_features,
        "_source": "HIFLD Electric Power Transmission Lines",
        "_downloaded": time.strftime("%Y-%m-%d"),
        "_filter": f"States: coverage states, Voltage >= 115kV, In Service",
    }
    out_path = os.path.join(args.out, "transmission_lines.geojson")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f)
    mb = os.path.getsize(out_path) / 1e6
    print(f"✓ Transmission lines: {len(hv_features)} features ({mb:.1f} MB) → {out_path}")

print("\nDone. Add these server routes to serve the new files:")
print("  GET /api/eia/gas_territories.geojson")
print("  GET /api/eia/transmission_lines.geojson")
print("(Already handled by the wildcard /api/eia/* route in server.js)")