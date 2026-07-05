"""
download_gis_layers.py
-----------------------
Downloads 4 GIS layers for Power Academy energy map:

1. Electric retail service territories (EIA-861 compiled by HIFLD)
   → ALL utilities in coverage states, with customers + capacity
   → output: data/electric_territories_full.geojson

2. Natural gas service territories (EIA Form 176 / state PUC, compiled by HIFLD)
   → ALL LDC gas utilities in coverage states
   → output: data/gas_territories.geojson

3. Electric power transmission lines (HIFLD, >=115kV, in service)
   → output: data/transmission_lines.geojson

Sources: HIFLD Open via NASA NCCS mirror (maps.nccs.nasa.gov)
  Layer IDs on energy FeatureServer:
    26 = electric_retail_service_territories
    29 = natural_gas_service_territories
  Transmission lines: services2.arcgis.com (separate service, updated Aug 2025)

All public, no API key required.

Run:
    python download_gis_layers.py --out E:/PowerAcademy/data
    python download_gis_layers.py --out E:/PowerAcademy/data --only transmission
    python download_gis_layers.py --out E:/PowerAcademy/data --only electric_territories
"""

import argparse, json, os, sys, time, urllib.request, urllib.parse

parser = argparse.ArgumentParser()
parser.add_argument("--out", required=True, help="Output directory (data folder)")
parser.add_argument("--only", choices=["electric_territories","gas_territories","transmission"],
                    help="Download/process only one layer")
parser.add_argument("--local-electric", default=None, help="Path to locally downloaded electric territories GeoJSON")
parser.add_argument("--local-gas",      default=None, help="Path to locally downloaded gas territories GeoJSON")
parser.add_argument("--local-tx",       default=None, help="Path to locally downloaded transmission lines GeoJSON")
args = parser.parse_args()

# ── Manual download instructions (shown when local files not found) ────────
MANUAL_DOWNLOADS = {
    "electric_territories": {
        "url":  "https://hifld-geoplatform.opendata.arcgis.com/datasets/electric-retail-service-territories/explore",
        "hint": "Click Download → GeoJSON. Large file ~50MB.",
        "save": "electric_territories_raw.geojson",
    },
    "gas_territories": {
        "url":  "https://hifld-geoplatform.opendata.arcgis.com/datasets/natural-gas-local-distribution-companies/explore",
        "hint": "Click Download → GeoJSON.",
        "save": "gas_territories_raw.geojson",
    },
    "transmission": {
        "url":  "https://hifld-geoplatform.opendata.arcgis.com/datasets/electric-power-transmission-lines/explore",
        "hint": "Click Download → GeoJSON. Large file ~200MB. Will be filtered to >=115kV.",
        "save": "transmission_lines_raw.geojson",
    },
}

os.makedirs(args.out, exist_ok=True)

# ── Coverage states ────────────────────────────────────────────────────────
COVERAGE_STATES = {
    "FL","TX","NH","CT","MA","RI","NY","NJ","PA","MD","VA","NC","SC",
    "GA","AL","MS","LA","AR","OK","MO","IL","MI","WI","MN","IA","KS",
    "OH","KY","IN","WV","TN","CA","OR","HI","AZ","CO","UT","NM",
}

# ── Pagination helper ──────────────────────────────────────────────────────
def fetch_arcgis_pages(base_url, label, page_size=1000, max_pages=500):
    """Paginate through an ArcGIS FeatureServer layer, return all features."""
    features = []
    offset = 0
    for page in range(max_pages):
        sep = "&" if "?" in base_url else "?"
        url = f"{base_url}{sep}resultOffset={offset}&resultRecordCount={page_size}"
        print(f"  [{label}] page {page+1}, offset={offset}...", end=" ", flush=True)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PowerAcademy/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print(f"ERROR: {e}")
            if page == 0:
                raise
            break
        batch = data.get("features", [])
        print(f"{len(batch)} features")
        features.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
        time.sleep(0.3)
    return features

def save_geojson(features, path, meta):
    out = {"type": "FeatureCollection", "features": features}
    out.update(meta)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f)
    mb = os.path.getsize(path) / 1e6
    print(f"  → {path} ({len(features)} features, {mb:.1f} MB)")

# ── 1. Electric Retail Service Territories ─────────────────────────────────
if not args.only or args.only == "electric_territories":
    print("\n=== Electric Retail Service Territories ===")
    out_path = os.path.join(args.out, "electric_territories_full.geojson")

    # Check for local file first
    local = args.local_electric or os.path.join(args.out, "electric_territories_raw.geojson")
    if os.path.exists(local):
        print(f"  Processing local file: {local}")
        with open(local, encoding="utf-8") as f:
            raw = json.load(f)
        features = raw.get("features", [])
        # Filter to coverage states
        filtered = [feat for feat in features
                    if (feat.get("properties") or {}).get("STATE","") in COVERAGE_STATES]
        print(f"  Filtered {len(features)} → {len(filtered)} features (coverage states)")
        save_geojson(filtered, out_path, {
            "_source": "HIFLD Electric Retail Service Territories (EIA-861)",
            "_downloaded": time.strftime("%Y-%m-%d"),
            "_states": sorted(COVERAGE_STATES),
        })
    else:
        # Try live fetch
        state_clauses = " OR ".join(f"STATE='{s}'" for s in sorted(COVERAGE_STATES))
        encoded = urllib.parse.quote(state_clauses)
        BASE = "https://maps.nccs.nasa.gov/mapping/rest/services/hifld_open/energy/FeatureServer/26/query"
        url = (f"{BASE}?where={encoded}"
               f"&outFields=NAME,ID,STATE,HOLDING_CO,CUSTOMERS,SUMMER_CAP_MW,WINTER_CAP_MW"
               f"&outSR=4326&f=geojson")
        try:
            features = fetch_arcgis_pages(url, "electric territories")
            save_geojson(features, out_path, {
                "_source": "HIFLD Electric Retail Service Territories (EIA-861)",
                "_downloaded": time.strftime("%Y-%m-%d"),
                "_states": sorted(COVERAGE_STATES),
            })
        except Exception as e:
            print(f"  Live fetch failed: {e}")
            info = MANUAL_DOWNLOADS["electric_territories"]
            print(f"\n  Manual download required:")
            print(f"  1. Open: {info['url']}")
            print(f"  2. {info['hint']}")
            print(f"  3. Save to: {os.path.join(args.out, info['save'])}")
            print(f"  4. Re-run: python download_gis_layers.py --out {args.out} --only electric_territories")

# ── 2. Natural Gas Service Territories ────────────────────────────────────
if not args.only or args.only == "gas_territories":
    print("\n=== Natural Gas Service Territories ===")
    out_path = os.path.join(args.out, "gas_territories.geojson")

    local = args.local_gas or os.path.join(args.out, "gas_territories_raw.geojson")
    if os.path.exists(local):
        print(f"  Processing local file: {local}")
        with open(local, encoding="utf-8") as f:
            raw = json.load(f)
        features = raw.get("features", [])
        filtered = [feat for feat in features
                    if (feat.get("properties") or {}).get("STATE","") in COVERAGE_STATES]
        print(f"  Filtered {len(features)} → {len(filtered)} features (coverage states)")
        save_geojson(filtered, out_path, {
            "_source": "HIFLD Natural Gas Service Territories",
            "_downloaded": time.strftime("%Y-%m-%d"),
            "_states": sorted(COVERAGE_STATES),
        })
    else:
        state_clauses = " OR ".join(f"STATE='{s}'" for s in sorted(COVERAGE_STATES))
        encoded = urllib.parse.quote(state_clauses)
        BASE = "https://maps.nccs.nasa.gov/mapping/rest/services/hifld_open/energy/FeatureServer/29/query"
        url = (f"{BASE}?where={encoded}"
               f"&outFields=NAME,HIFLDID,STATE,SUPPLIER,TYPE,CUSTOMERS"
               f"&outSR=4326&f=geojson")
        try:
            features = fetch_arcgis_pages(url, "gas territories")
            save_geojson(features, out_path, {
                "_source": "HIFLD Natural Gas Service Territories",
                "_downloaded": time.strftime("%Y-%m-%d"),
                "_states": sorted(COVERAGE_STATES),
            })
        except Exception as e:
            print(f"  Live fetch failed: {e}")
            info = MANUAL_DOWNLOADS["gas_territories"]
            print(f"\n  Manual download required:")
            print(f"  1. Open: {info['url']}")
            print(f"  2. {info['hint']}")
            print(f"  3. Save to: {os.path.join(args.out, info['save'])}")
            print(f"  4. Re-run: python download_gis_layers.py --out {args.out} --only gas_territories")

# ── 3. Transmission Lines ──────────────────────────────────────────────────
if not args.only or args.only == "transmission":
    print("\n=== Electric Power Transmission Lines ===")
    out_path = os.path.join(args.out, "transmission_lines.geojson")

    local = args.local_tx or os.path.join(args.out, "transmission_lines_raw.geojson")
    if os.path.exists(local):
        print(f"  Processing local file: {local} ...")
        with open(local, encoding="utf-8") as f:
            raw = json.load(f)
        features = raw.get("features", [])
        # Filter: voltage >= 115kV, in service, coverage states
        filtered = []
        for feat in features:
            props = feat.get("properties") or {}
            voltage = props.get("VOLTAGE") or props.get("voltage") or 0
            status  = (props.get("STATUS") or props.get("status") or "").upper()
            state   = props.get("STATE") or props.get("state") or ""
            try: voltage = float(voltage)
            except: voltage = 0
            if voltage < 115: continue
            if status and status not in ("IN SERVICE","ACTIVE","IN_SERVICE",""): continue
            if state and state not in COVERAGE_STATES: continue
            filtered.append(feat)
        print(f"  Filtered {len(features)} → {len(filtered)} features (>=115kV, in service, coverage states)")
        save_geojson(filtered, out_path, {
            "_source": "HIFLD Electric Power Transmission Lines",
            "_downloaded": time.strftime("%Y-%m-%d"),
            "_filter": "VOLTAGE >= 115kV, IN SERVICE, coverage states",
        })
    else:
        # Try live
        BASE = "https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/US_Electric_Power_Transmission_Lines/FeatureServer/0/query"
        tx_where = "VOLTAGE >= 115 AND (STATUS = 'IN SERVICE' OR STATUS = 'Active' OR STATUS IS NULL)"
        url = (f"{BASE}?where={urllib.parse.quote(tx_where)}"
               f"&outFields=ID,OWNER,VOLTAGE,VOLT_CLASS,STATUS,STATE,TYPE"
               f"&outSR=4326&f=geojson")
        try:
            features = fetch_arcgis_pages(url, "transmission lines")
            filtered = [f for f in features
                        if not (f.get("properties") or {}).get("STATE")
                        or (f.get("properties") or {}).get("STATE") in COVERAGE_STATES]
            save_geojson(filtered, out_path, {
                "_source": "HIFLD Electric Power Transmission Lines",
                "_downloaded": time.strftime("%Y-%m-%d"),
                "_filter": "VOLTAGE >= 115kV, IN SERVICE, coverage states",
            })
        except Exception as e:
            print(f"  Live fetch failed: {e}")
            info = MANUAL_DOWNLOADS["transmission"]
            print(f"\n  Manual download required:")
            print(f"  1. Open: {info['url']}")
            print(f"  2. {info['hint']}")
            print(f"  3. Save to: {os.path.join(args.out, info['save'])}")
            print(f"  4. Re-run: python download_gis_layers.py --out {args.out} --only transmission")

print("""
Done!

Server routes (already handled by /api/eia/* wildcard in server.js):
  GET /api/eia/electric_territories_full.geojson
  GET /api/eia/gas_territories.geojson
  GET /api/eia/transmission_lines.geojson

These files are large — serve them with compression if possible.
The electric_territories_full.geojson contains ALL utilities in coverage states
with customer counts and capacity, not just your coverage names.
""")