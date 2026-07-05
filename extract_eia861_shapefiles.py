"""
Power Academy — EIA 861 Shapefile Extractor
Reads the 2019 EIA 861 zip (which contains .shp files) and produces
exact service territory GeoJSON files per company.

Run: python extract_eia861_shapefiles.py
Requires: pip install pyshp (or shapefile)
"""

import os, json, zipfile, struct
from pathlib import Path
from datetime import datetime

BASE_DIR  = Path("E:/PowerAcademy/data")
SHP_ZIP   = BASE_DIR / "eia_cache/eia861_shp.zip"
TERR_DIR  = BASE_DIR / "territories"
LOG_FILE  = BASE_DIR / "shapefile_extract_log.txt"

# Same company->utility ID mapping from the pipeline
KNOWN_IDS = {
    "NEE":  ["6452","56545","14876","31719","64260","49963","6607","6354","6850"],
    "D":    ["19876","17539"],
    "ETR":  ["5416","17613","8901","12341","17634"],
    "CMS":  ["4254"],
    "PPL":  ["14827","10171","9417"],
    "AEE":  ["18630","814"],
    "POR":  ["15267"],
    "EIX":  ["17609"],
    "PCG":  ["14328"],
    "HE":   ["8051","8052","12347"],
    "EVRG": ["10000","18973"],
    "ES":   ["15350","3786","13524","20382"],
    "VST":  ["56798","57410","54802","59918","5517"],
    "TLN":  ["57868","57869","60421","60422","15537","15276"],
    "XIFR": ["57821","55696","54717","55785"],
}

COMPANY_NAMES = {
    "NEE":"NextEra Energy","D":"Dominion Energy","ETR":"Entergy",
    "CMS":"CMS Energy","PPL":"PPL Corporation","AEE":"Ameren",
    "POR":"Portland General Electric","EIX":"Edison International",
    "PCG":"PG&E","HE":"Hawaiian Electric","EVRG":"Evergy",
    "ES":"Eversource Energy","VST":"Vistra Energy",
    "TLN":"Talen Energy","XIFR":"XPLR Infrastructure",
}

def log(msg):
    print(msg)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now().isoformat()}  {msg}\n")

def parse_dbf(data: bytes) -> list:
    if len(data) < 32: return []
    num_records = struct.unpack_from("<I", data, 4)[0]
    header_size = struct.unpack_from("<H", data, 8)[0]
    record_size = struct.unpack_from("<H", data, 10)[0]
    fields = []
    pos = 32
    while pos < header_size - 1 and pos + 32 <= len(data) and data[pos] != 0x0D:
        name = data[pos:pos+11].rstrip(b"\x00").decode("ascii", errors="replace").strip()
        flen = data[pos+16]
        fields.append((name, flen))
        pos += 32
    records = []
    rec_start = header_size
    for _ in range(num_records):
        if rec_start + record_size > len(data): break
        rec_data = data[rec_start:rec_start+record_size]
        if rec_data[0] == 0x2A:
            rec_start += record_size
            continue
        rec = {}
        offset = 1
        for name, flen in fields:
            raw = rec_data[offset:offset+flen]
            rec[name] = raw.decode("ascii", errors="replace").strip()
            offset += flen
        records.append(rec)
        rec_start += record_size
    return records

def parse_shp(data: bytes) -> list:
    pos = 100
    geometries = []
    while pos + 12 <= len(data):
        content_len = struct.unpack_from(">I", data, pos+4)[0]
        pos += 8
        shape_type = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        content_bytes = content_len * 2 - 4
        if shape_type == 0:
            geometries.append(None)
            continue
        if shape_type != 5:
            geometries.append(None)
            pos += content_bytes
            continue
        pos += 32  # bbox
        num_parts  = struct.unpack_from("<I", data, pos)[0]; pos += 4
        num_points = struct.unpack_from("<I", data, pos)[0]; pos += 4
        parts = [struct.unpack_from("<I", data, pos+i*4)[0] for i in range(num_parts)]
        pos += num_parts * 4
        all_pts = []
        for _ in range(num_points):
            x = struct.unpack_from("<d", data, pos)[0]; pos += 8
            y = struct.unpack_from("<d", data, pos)[0]; pos += 8
            all_pts.append([round(x,6), round(y,6)])
        rings = []
        for i, start in enumerate(parts):
            end = parts[i+1] if i+1 < len(parts) else num_points
            ring = all_pts[start:end]
            if len(ring) >= 4: rings.append(ring)
        if rings:
            if len(rings) == 1:
                geometries.append({"type":"Polygon","coordinates":rings})
            else:
                geometries.append({"type":"MultiPolygon","coordinates":[[r] for r in rings]})
        else:
            geometries.append(None)
    return geometries

def main():
    TERR_DIR.mkdir(parents=True, exist_ok=True)
    open(LOG_FILE, 'w').write("")  # clear log

    log("="*60)
    log(f"EIA 861 Shapefile Extractor — {datetime.now().isoformat()}")
    log("="*60)

    if not SHP_ZIP.exists():
        log(f"ERROR: Zip not found at {SHP_ZIP}")
        log("Download from https://www.eia.gov/electricity/data/eia861/")
        log("Save as E:/PowerAcademy/data/eia_cache/eia861_shp.zip")
        return

    # Inspect zip contents
    with zipfile.ZipFile(SHP_ZIP, 'r') as z:
        all_files = z.namelist()
        log(f"Files in zip: {all_files}")

        shp_files = [f for f in all_files if f.lower().endswith('.shp')]
        if not shp_files:
            log("ERROR: No .shp files found in this zip.")
            log("This zip does not contain shapefiles — it may be xlsx-only (2020+).")
            log("Try downloading 2019 or earlier from eia.gov/electricity/data/eia861/")
            return

        log(f"Found {len(shp_files)} shapefile(s): {shp_files}")
        shp_name = shp_files[0]
        dbf_name = shp_name.replace('.shp', '.dbf').replace('.SHP', '.DBF')

        # Try exact match, then case-insensitive
        if dbf_name not in all_files:
            dbf_name = next((f for f in all_files if f.lower().endswith('.dbf')), None)

        if not dbf_name:
            log("ERROR: No .dbf file found — cannot read attribute data")
            return

        log(f"Using: {shp_name} + {dbf_name}")

        shp_bytes = z.read(shp_name)
        dbf_bytes = z.read(dbf_name)

    # Parse
    log("Parsing shapefile...")
    polygons = parse_shp(shp_bytes)
    records  = parse_dbf(dbf_bytes)
    log(f"Polygons: {len(polygons)}, Records: {len(records)}")

    if records:
        log(f"DBF fields: {list(records[0].keys())}")
        log(f"Sample record: {records[0]}")

    # Build utility_id -> polygon mapping
    uid_to_poly = {}
    uid_to_name = {}

    for i, rec in enumerate(records):
        if i >= len(polygons): break
        poly = polygons[i]
        if not poly: continue

        # Find utility ID field
        uid = None
        for field in ["UTILITY_ID","UTILITYID","UTIL_ID","ID","OBJECTID","UTILNUM"]:
            if field in rec and rec[field]:
                uid = str(rec[field]).strip().lstrip("0") or None
                break

        if uid:
            if uid not in uid_to_poly:
                uid_to_poly[uid] = []
            uid_to_poly[uid].append(poly)
            name_val = rec.get("UTIL_NAME", rec.get("UTILITYNAM", rec.get("NAME","")))
            uid_to_name[uid] = str(name_val).strip()

    log(f"Unique utility IDs with polygons: {len(uid_to_poly)}")

    # Build GeoJSON per company
    matched = 0
    unmatched = []

    for ticker, ids in KNOWN_IDS.items():
        features = []
        for uid in ids:
            polys = uid_to_poly.get(uid, [])
            for poly in polys:
                features.append({
                    "type": "Feature",
                    "properties": {
                        "ticker":       ticker,
                        "utility_id":   uid,
                        "utility_name": uid_to_name.get(uid, ""),
                    },
                    "geometry": poly
                })

        if features:
            matched += 1
            log(f"{ticker}: {len(features)} territory polygon(s)")
        else:
            unmatched.append(ticker)
            log(f"{ticker}: no polygons found for IDs {ids}")

        out = {
            "type":      "FeatureCollection",
            "ticker":    ticker,
            "name":      COMPANY_NAMES.get(ticker, ticker),
            "generated": datetime.now().isoformat(),
            "data_source": "EIA-861-2019-shapefile",
            "features":  features,
            # Keep service_states for fallback
            "service_states": []
        }

        with open(TERR_DIR / f"{ticker}.geojson", 'w', encoding='utf-8') as f:
            json.dump(out, f, indent=2)

    log(f"\nSUMMARY: {matched} companies with exact polygon territories")
    if unmatched:
        log(f"No polygons: {unmatched}")
        log("These IDs may not exist in 2019 data (newer entities)")
    log("Done. Territory GeoJSON files updated in E:/PowerAcademy/data/territories/")

if __name__ == "__main__":
    main()