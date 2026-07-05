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
parser.add_argument("--out", required=True, help="Output directory")
parser.add_argument("--only", choices=["electric_territories","gas_territories","transmission"],
                    help="Download only one layer")
args = parser.parse_args()

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
    print("\n=== Electric Retail Service Territories (HIFLD layer 26) ===")

    # Build state filter - each state needs its own clause
    state_clauses = " OR ".join(f"STATE='{s}'" for s in sorted(COVERAGE_STATES))
    encoded = urllib.parse.quote(state_clauses)

    BASE = "https://maps.nccs.nasa.gov/mapping/rest/services/hifld_open/energy/FeatureServer/26/query"
    url = (
        f"{BASE}?where={encoded}"
        f"&outFields=NAME,ID,STATE,HOLDING_CO,CUSTOMERS,SUMMER_CAP_MW,WINTER_CAP_MW"
        f"&outSR=4326&f=geojson"
    )

    try:
        features = fetch_arcgis_pages(url, "electric territories")
        out_path = os.path.join(args.out, "electric_territories_full.geojson")
        save_geojson(features, out_path, {
            "_source": "HIFLD Electric Retail Service Territories (EIA-861)",
            "_layer": "maps.nccs.nasa.gov energy FeatureServer layer 26",
            "_downloaded": time.strftime("%Y-%m-%d"),
            "_states": sorted(COVERAGE_STATES),
        })
    except Exception as e:
        print(f"  FAILED: {e}")
        print("  Try manually downloading from:")
        print("  https://hifld-geoplatform.opendata.arcgis.com/datasets/electric-retail-service-territories")

# ── 2. Natural Gas Service Territories ────────────────────────────────────
if not args.only or args.only == "gas_territories":
    print("\n=== Natural Gas Service Territories (HIFLD layer 29) ===")

    state_clauses = " OR ".join(f"STATE='{s}'" for s in sorted(COVERAGE_STATES))
    encoded = urllib.parse.quote(state_clauses)

    BASE = "https://maps.nccs.nasa.gov/mapping/rest/services/hifld_open/energy/FeatureServer/29/query"
    url = (
        f"{BASE}?where={encoded}"
        f"&outFields=NAME,HIFLDID,STATE,SUPPLIER,TYPE,CUSTOMERS"
        f"&outSR=4326&f=geojson"
    )

    try:
        features = fetch_arcgis_pages(url, "gas territories")
        out_path = os.path.join(args.out, "gas_territories.geojson")
        save_geojson(features, out_path, {
            "_source": "HIFLD Natural Gas Service Territories (EIA Form 176 / state PUC)",
            "_layer": "maps.nccs.nasa.gov energy FeatureServer layer 29",
            "_downloaded": time.strftime("%Y-%m-%d"),
            "_states": sorted(COVERAGE_STATES),
        })
    except Exception as e:
        print(f"  FAILED: {e}")
        print("  Try manually downloading from:")
        print("  https://hifld-geoplatform.opendata.arcgis.com/datasets/natural-gas-local-distribution-companies")

# ── 3. Transmission Lines ──────────────────────────────────────────────────
if not args.only or args.only == "transmission":
    print("\n=== Electric Power Transmission Lines (HIFLD, updated Aug 2025) ===")
    print("  Filtering to >=115kV, in service, coverage states")

    # This service uses a different host - confirmed working as of Aug 2025
    # Query by state is not available on all fields; filter voltage instead
    # and do a bbox query per region to keep request size manageable

    BASE = "https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/US_Electric_Power_Transmission_Lines/FeatureServer/0/query"

    # Filter: voltage >= 115kV and in service
    # STATE field may not exist; filter by VOLT_CLASS instead
    tx_where = "VOLTAGE >= 115 AND (STATUS = 'IN SERVICE' OR STATUS = 'Active' OR STATUS IS NULL)"
    encoded  = urllib.parse.quote(tx_where)

    url = (
        f"{BASE}?where={encoded}"
        f"&outFields=ID,OWNER,VOLTAGE,VOLT_CLASS,STATUS,STATE,TYPE,SHAPE_Length"
        f"&outSR=4326&f=geojson"
    )

    try:
        features = fetch_arcgis_pages(url, "transmission lines")

        # Post-filter to coverage states where STATE field exists
        filtered = []
        for feat in features:
            props = feat.get("properties") or {}
            state = props.get("STATE", "")
            if not state or state in COVERAGE_STATES:
                filtered.append(feat)

        out_path = os.path.join(args.out, "transmission_lines.geojson")
        save_geojson(filtered, out_path, {
            "_source": "HIFLD Electric Power Transmission Lines (updated Aug 2025)",
            "_layer": "services2.arcgis.com FiaPA4ga0iQKduv3 US_Electric_Power_Transmission_Lines",
            "_downloaded": time.strftime("%Y-%m-%d"),
            "_filter": "VOLTAGE >= 115kV, IN SERVICE, coverage states",
        })
    except Exception as e:
        print(f"  FAILED: {e}")
        print("\n  Fallback: download the shapefile directly from:")
        print("  https://hifld-geoplatform.opendata.arcgis.com/datasets/electric-power-transmission-lines")
        print("  Then convert to GeoJSON with: ogr2ogr -f GeoJSON transmission_lines.geojson Electric_Power_Transmission_Lines.shp")

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