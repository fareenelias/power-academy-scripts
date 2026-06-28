"""
Power Academy — EIA Data Pipeline v3
Fixes:
  - 2025 Early Release xlsx has headers on row 2 with merged title on row 1
  - Generator file is named 3_1_Generator_Y2025_Early_Release.xlsx (not found in v2)
  - EIA 861 2024 zip has no shapefile — uses xlsx Service_Territory_2024.xlsx instead
  - All column detection rewritten to handle unnamed columns
"""

import os, json, zipfile, pandas as pd, io, logging, struct
from pathlib import Path
from datetime import datetime

BASE_DIR    = Path("E:/PowerAcademy/data")
CACHE_DIR   = BASE_DIR / "eia_cache"
PLANTS_DIR  = BASE_DIR / "plants"
TERR_DIR    = BASE_DIR / "territories"
LOG_FILE    = BASE_DIR / "eia_pipeline_log.txt"
ID_MAP_FILE = BASE_DIR / "eia_utility_id_map.json"

EIA_860_ZIP = CACHE_DIR / "eia860.zip"
EIA_861_ZIP = CACHE_DIR / "eia861.zip"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_FILE), mode="w", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

COMPANIES = {
    "NEE":  {"name":"NextEra Energy",           "type":"electric", "subsidiaries":["Florida Power & Light","FPL","Gulf Power","NextEra Energy Resources"]},
    "D":    {"name":"Dominion Energy",           "type":"electric", "subsidiaries":["Virginia Electric and Power","Virginia Electric","Dominion Energy South Carolina","Dominion Energy Virginia"]},
    "ETR":  {"name":"Entergy",                   "type":"electric", "subsidiaries":["Entergy Arkansas","Entergy Louisiana","Entergy Mississippi","Entergy New Orleans","Entergy Texas"]},
    "CMS":  {"name":"CMS Energy / Consumers",    "type":"electric", "subsidiaries":["Consumers Energy"]},
    "PPL":  {"name":"PPL Corporation",           "type":"electric", "subsidiaries":["PPL Electric Utilities","Louisville Gas and Electric","Kentucky Utilities"]},
    "AEE":  {"name":"Ameren",                    "type":"electric", "subsidiaries":["Ameren Missouri","Ameren Illinois","Union Electric"]},
    "POR":  {"name":"Portland General Electric", "type":"electric", "subsidiaries":["Portland General Electric"]},
    "EIX":  {"name":"Edison International",      "type":"electric", "subsidiaries":["Southern California Edison"]},
    "PCG":  {"name":"PG&E",                      "type":"electric", "subsidiaries":["Pacific Gas and Electric","PG&E"]},
    "HE":   {"name":"Hawaiian Electric",         "type":"electric", "subsidiaries":["Hawaiian Electric","Hawaii Electric Light","Maui Electric"]},
    "EVRG": {"name":"Evergy",                    "type":"electric", "subsidiaries":["Evergy Metro","Evergy Kansas Central","Westar Energy","Kansas City Power & Light","KCP&L"]},
    "ES":   {"name":"Eversource Energy",         "type":"electric", "subsidiaries":["Public Service of New Hampshire","PSNH","Connecticut Light and Power","CL&P","NSTAR Electric","Western Massachusetts Electric","Eversource Energy","Yankee Gas","Northern Utilities"]},
    "VST":  {"name":"Vistra Energy",             "type":"ipp",      "subsidiaries":["Luminant","TXU Energy","Vistra","Dynegy"]},
    "TLN":  {"name":"Talen Energy",             "type":"ipp",      "subsidiaries":["Talen Energy","PPL Susquehanna","Susquehanna Nuclear","Montour","Brunner Island","Martins Creek","Raven Power","H.A. Wagner","C.P. Crane","Brandon Shores","Talen Montana","Colstrip","Jade Renewable","Sapphire Sky"]},
    "XIFR": {"name":"XPLR Infrastructure",       "type":"yieldco",  "subsidiaries":["NextEra Energy Partners","XPLR Infrastructure","NEP","Genesis Solar","Mountain Wind","Duane Arnold","Jericho Rise"]},
    "AWR":  {"name":"American States Water",     "type":"water",    "subsidiaries":[]},
    "CWT":  {"name":"California Water Service",  "type":"water",    "subsidiaries":[]},
    "YORW": {"name":"York Water Company",        "type":"water",    "subsidiaries":[]},
    "GWRS": {"name":"Global Water Resources",    "type":"water",    "subsidiaries":[]},
    "AWK":  {"name":"American Water Works",      "type":"water",    "subsidiaries":[]},
    "WTRG": {"name":"Essential Utilities",       "type":"water",    "subsidiaries":[]},
    "HTO":  {"name":"H2O Americas",              "type":"water",    "subsidiaries":[]},
}

KNOWN_IDS = {
    "NEE":  ["6452","56545"],  "D":    ["19876","17539"],
    "ETR":  ["5416"],          "CMS":  ["4254"],
    "PPL":  ["14827","10171","9417"],  "AEE":  ["18630","814"],
    "POR":  ["15267"],         "EIX":  ["17609"],
    "PCG":  ["14328"],         "HE":   ["8051","8052","12347"],
    "EVRG": ["10000","18973"], "ES":   ["15350","3786","13524","20382"],
    "VST":  ["56798","57410"], "TLN":  ["57868", "57869", "14610", "14611", "57870"],
    "XIFR": ["57821"],
}

TECH_COLORS = {
    "Solar":      "#F4C542", "Wind Onshore":  "#4AABDB",
    "Wind Offshore":"#1A6B9E","Natural Gas":   "#E8834A",
    "Nuclear":    "#9B59B6", "Storage":       "#2ECC71",
    "Hydro":      "#1ABC9C", "Coal":          "#555555",
    "Petroleum":  "#8B4513", "Other":         "#95A5A6",
}

def safe_str(v):
    if v is None: return None
    try:
        if pd.isna(v): return None
    except: pass
    s = str(v).strip()
    return s if s and s.lower() not in ("nan","none","") else None

def safe_float(v):
    try:
        f = float(v)
        import math
        return None if math.isnan(f) else round(f, 2)
    except: return None

def map_tech(raw):
    if not raw: return "Other"
    r = raw.lower()
    if "solar" in r:               return "Solar"
    if "wind" in r and "off" in r: return "Wind Offshore"
    if "wind" in r:                return "Wind Onshore"
    if "nuclear" in r:             return "Nuclear"
    if "natural gas" in r or "ng" in r: return "Natural Gas"
    if "storage" in r or "batter" in r: return "Storage"
    if "hydro" in r or "water" in r:    return "Hydro"
    if "coal" in r:                return "Coal"
    if "petroleum" in r or "oil" in r:  return "Petroleum"
    return "Other"

def ensure_dirs():
    for d in [BASE_DIR, CACHE_DIR, PLANTS_DIR, TERR_DIR]:
        d.mkdir(parents=True, exist_ok=True)

def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

# ── EIA 860 — handles both standard and Early Release formats ──────────────────
def load_eia860_plants() -> pd.DataFrame:
    log.info("Loading EIA 860 generator data...")

    with zipfile.ZipFile(EIA_860_ZIP, "r") as z:
        all_files = z.namelist()
        log.info(f"Files in zip: {[f for f in all_files if f.endswith('.xlsx')]}")

        # Find generator file — handles various naming conventions
        gen_file = None
        for name in all_files:
            nl = name.lower()
            if "generator" in nl and nl.endswith(".xlsx"):
                gen_file = name
                break
        # Also check for plant file for lat/lon
        plant_file = None
        for name in all_files:
            nl = name.lower()
            if "plant" in nl and nl.endswith(".xlsx") and "generator" not in nl:
                plant_file = name
                break

        if not gen_file:
            log.error(f"No generator file found. Files: {all_files}")
            return pd.DataFrame()

        log.info(f"Generator file: {gen_file}")

        # Read with skiprows=1 first to check if row 1 is a title row
        raw = pd.read_excel(io.BytesIO(z.read(gen_file)), sheet_name=0,
                            header=None, nrows=3, dtype=str)
        log.info(f"First 3 rows preview:\n{raw.to_string()}")

        # Detect header row by scanning for exact "Utility ID" cell
        header_row = 1  # default for standard EIA 860
        for i in range(min(6, len(raw))):
            row_text = " ".join(str(v) for v in raw.iloc[i].values)
            if "Utility ID" in row_text:
                header_row = i
                log.info(f"Header row found at row {i}")
                break

        log.info(f"Reading generator file with skiprows={header_row}")
        gen_data = pd.read_excel(
            io.BytesIO(z.read(gen_file)),
            sheet_name=0,
            skiprows=header_row,
            dtype=str
        )
        # Clean column names
        gen_data.columns = [
            str(c).strip().lower()
            .replace(" ", "_").replace("(", "").replace(")", "")
            .replace("/", "_").replace("-", "_")
            for c in gen_data.columns
        ]
        log.info(f"Columns after cleaning: {list(gen_data.columns[:30])}")

        # Load plant file for coordinates
        plant_coords = {}
        if plant_file:
            try:
                praw = pd.read_excel(io.BytesIO(z.read(plant_file)), sheet_name=0,
                                     header=None, nrows=3, dtype=str)
                p_header = 1
                for i in range(min(5, len(praw))):
                    row_vals = [str(v).lower() for v in praw.iloc[i].values if str(v) != 'nan']
                    if any("plant" in v or "latitude" in v for v in row_vals):
                        p_header = i; break
                pdata = pd.read_excel(io.BytesIO(z.read(plant_file)), sheet_name=0,
                                      skiprows=p_header, dtype=str)
                pdata.columns = [str(c).strip().lower().replace(" ","_") for c in pdata.columns]
                log.info(f"Plant file columns: {list(pdata.columns[:20])}")

                # Find plant ID, lat, lon columns
                def fc(df, *opts):
                    for o in opts:
                        if o in df.columns: return o
                        matches = [c for c in df.columns if o in c]
                        if matches: return matches[0]
                    return None

                pid_c = fc(pdata, "plant_code","plant_id","plantcode")
                lat_c = fc(pdata, "latitude","lat")
                lon_c = fc(pdata, "longitude","lon","long")
                if pid_c and lat_c and lon_c:
                    for _, row in pdata.iterrows():
                        pid = safe_str(row.get(pid_c))
                        lat = safe_float(row.get(lat_c))
                        lon = safe_float(row.get(lon_c))
                        if pid: plant_coords[pid] = (lat, lon)
                    log.info(f"Loaded {len(plant_coords)} plant coordinates")
            except Exception as e:
                log.warning(f"Plant file error: {e}")

    # ── Column detection ──────────────────────────────────────────────────────
    def fc(df, *opts):
        for o in opts:
            if o in df.columns: return o
            matches = [c for c in df.columns if o in c and "unnamed" not in c]
            if matches: return matches[0]
        return None

    uid_c  = fc(gen_data, "utility_id","entity_id","utilityid","utility_id_eia")
    unm_c  = fc(gen_data, "utility_name","entity_name","utilityname")
    pid_c  = fc(gen_data, "plant_code","plant_id","plantcode","plant_code_eia")
    pnm_c  = fc(gen_data, "plant_name","plantname")
    st_c   = fc(gen_data, "state","plant_state")
    tech_c = fc(gen_data, "technology","technology_description","prime_mover")
    cap_c  = fc(gen_data, "nameplate_capacity_mw","summer_capacity_mw","nameplate_capacity",
                           "net_summer_capacity_mw","capacity_mw")
    stat_c = fc(gen_data, "status","operating_status","current_operating_status")
    yr_c   = fc(gen_data, "operating_year","year_of_commercial_operation")

    log.info(f"Columns: uid={uid_c} unm={unm_c} pid={pid_c} tech={tech_c} cap={cap_c} stat={stat_c}")

    # If all None, the header detection failed — try row 2
    if not any([uid_c, pid_c, tech_c]):
        log.warning("Column detection failed — retrying with skiprows=2")
        with zipfile.ZipFile(EIA_860_ZIP, "r") as z:
            gen_data = pd.read_excel(io.BytesIO(z.read(gen_file)), sheet_name=0,
                                     skiprows=2, dtype=str)
        gen_data.columns = [
            str(c).strip().lower().replace(" ","_").replace("(","").replace(")","")
            for c in gen_data.columns
        ]
        log.info(f"Retry columns: {list(gen_data.columns[:30])}")
        uid_c  = fc(gen_data, "utility_id","entity_id","utilityid")
        unm_c  = fc(gen_data, "utility_name","entity_name")
        pid_c  = fc(gen_data, "plant_code","plant_id")
        pnm_c  = fc(gen_data, "plant_name")
        st_c   = fc(gen_data, "state")
        tech_c = fc(gen_data, "technology","technology_description")
        cap_c  = fc(gen_data, "nameplate_capacity_mw","summer_capacity_mw","nameplate_capacity")
        stat_c = fc(gen_data, "status","operating_status")
        yr_c   = fc(gen_data, "operating_year")
        log.info(f"Retry mapping: uid={uid_c} pid={pid_c} tech={tech_c} cap={cap_c}")

    rows = []
    for _, row in gen_data.iterrows():
        uid  = safe_str(row.get(uid_c))  if uid_c  else None
        unm  = safe_str(row.get(unm_c))  if unm_c  else None
        pid  = safe_str(row.get(pid_c))  if pid_c  else None
        pnm  = safe_str(row.get(pnm_c))  if pnm_c  else None
        st   = safe_str(row.get(st_c))   if st_c   else None
        tech = map_tech(safe_str(row.get(tech_c)) if tech_c else None)
        cap  = safe_float(row.get(cap_c)) if cap_c else None
        stat = safe_str(row.get(stat_c)) if stat_c else None
        yr   = safe_str(row.get(yr_c))   if yr_c   else None
        coords = plant_coords.get(pid, (None, None)) if pid else (None, None)
        rows.append({
            "utility_id": uid, "utility_name": unm,
            "plant_id": pid,   "plant_name": pnm,
            "state": st,       "technology": tech,
            "capacity_mw": cap,"status": stat,
            "operating_year": yr,
            "latitude": coords[0], "longitude": coords[1],
        })

    gen_df = pd.DataFrame(rows)
    log.info(f"Loaded {len(gen_df):,} records. Sample uid values: {gen_df['utility_id'].dropna().head(5).tolist()}")
    return gen_df

# ── EIA 861 — xlsx-based territory data (no shapefile in 2024 release) ────────
def load_eia861_territories_xlsx() -> dict:
    """
    EIA 861 2024 release uses xlsx instead of shapefile.
    Service_Territory_2024.xlsx has utility ID, name, state, county data.
    We can't draw polygons from this, but we can build state-level GeoJSON
    approximations using known state boundaries for each utility's service states.
    """
    log.info("Loading EIA 861 territory data from xlsx (2024 format)...")

    territories = {}  # utility_id -> {name, states: []}

    with zipfile.ZipFile(EIA_861_ZIP, "r") as z:
        all_files = z.namelist()
        terr_file = next((f for f in all_files if "service_territory" in f.lower()), None)
        util_file = next((f for f in all_files if "utility_data" in f.lower()), None)

        if not terr_file:
            log.warning(f"No service territory file found. Files: {all_files}")
            return {}

        log.info(f"Territory file: {terr_file}")
        # Try skiprows=0 first (no title row), fall back to 1
        terr_data = pd.read_excel(io.BytesIO(z.read(terr_file)), skiprows=0, dtype=str)
        # If first column looks like a year (e.g. '2024'), it's data not a header — re-read with header=None
        first_col = str(terr_data.columns[0]).strip()
        if first_col.isdigit() and len(first_col) == 4:
            terr_data = pd.read_excel(io.BytesIO(z.read(terr_file)), header=None, dtype=str)
            # Row 0 is data, assign column names from known EIA 861 structure
            # EIA 861 Service Territory columns: Year, Utility Number, Utility Name, State, County
            n_cols = len(terr_data.columns)
            col_names = ['year','utility_number','utility_name','state','county'] + [f'col_{i}' for i in range(5, n_cols)]
            terr_data.columns = col_names[:n_cols]
        else:
            terr_data.columns = [str(c).strip().lower().replace(" ","_") for c in terr_data.columns]
        log.info(f"Territory columns: {list(terr_data.columns[:15])}")

        def fc(df, *opts):
            for o in opts:
                if o in df.columns: return o
                matches = [c for c in df.columns if o in c]
                if matches: return matches[0]
            return None

        uid_c  = fc(terr_data, "utility_number","utility_id","utilityid","id")
        unm_c  = fc(terr_data, "utility_name","name","utilityname")
        st_c   = fc(terr_data, "state","state_abbreviation")
        cty_c  = fc(terr_data, "county","county_name")

        log.info(f"Territory column mapping: uid={uid_c} name={unm_c} state={st_c}")

        for _, row in terr_data.iterrows():
            uid  = safe_str(row.get(uid_c))  if uid_c  else None
            unm  = safe_str(row.get(unm_c))  if unm_c  else None
            st   = safe_str(row.get(st_c))   if st_c   else None
            if not uid: continue
            uid = uid.lstrip("0") or uid
            if uid not in territories:
                territories[uid] = {"utility_id": uid, "utility_name": unm, "states": set()}
            if st:
                territories[uid]["states"].add(st)

    # Convert sets to lists
    for uid in territories:
        territories[uid]["states"] = sorted(territories[uid]["states"])

    log.info(f"Loaded {len(territories):,} utility service territory records")
    return territories

def build_territory_geojson_from_xlsx(ticker, match, territories):
    """
    Build GeoJSON using state-level approximation from xlsx territory data.
    Note: exact polygon shapefiles require EIA 861 shapefile edition (older years).
    The dashboard map component can use these state lists to shade states,
    while we pursue exact polygons separately.
    """
    if not match["utility_ids"]:
        write_json(TERR_DIR / f"{ticker}.geojson", {
            "type": "FeatureCollection", "ticker": ticker, "name": match["name"],
            "note": match.get("note","No territory data"), "features": [],
            "service_states": [], "data_source": "none"
        })
        return

    all_states = set()
    matched_utilities = []
    for uid in match["utility_ids"]:
        terr = territories.get(uid)
        if terr:
            all_states.update(terr.get("states", []))
            matched_utilities.append({"id": uid, "name": terr.get("utility_name"), "states": terr.get("states",[])})

    write_json(TERR_DIR / f"{ticker}.geojson", {
        "type": "FeatureCollection",
        "ticker": ticker,
        "name": match["name"],
        "generated": datetime.now().isoformat(),
        "data_source": "EIA-861-2024-xlsx",
        "note": "State-level territory data. Exact polygon shapefiles available in EIA 861 editions prior to 2023.",
        "service_states": sorted(all_states),
        "utilities": matched_utilities,
        "features": []  # populated by map component using service_states + state boundary GeoJSON
    })
    if all_states:
        log.info(f"{ticker}: service states: {sorted(all_states)}")
    else:
        log.info(f"{ticker}: no territory data found for IDs {match['utility_ids']}")

def match_companies(gen_df: pd.DataFrame, territories: dict) -> dict:
    log.info("Matching companies to EIA utility IDs...")

    gen_utils = {}
    if not gen_df.empty and "utility_id" in gen_df.columns:
        for _, row in gen_df[["utility_id","utility_name"]].drop_duplicates().iterrows():
            if row["utility_id"] and row["utility_name"]:
                gen_utils[row["utility_id"]] = row["utility_name"]
    for uid, t in territories.items():
        if uid not in gen_utils and t.get("utility_name"):
            gen_utils[uid] = t["utility_name"]

    log.info(f"Total utilities in EIA data: {len(gen_utils):,}")

    results = {}
    for ticker, company in COMPANIES.items():
        if company["type"] == "water":
            results[ticker] = {"ticker":ticker,"name":company["name"],"type":"water",
                                "utility_ids":[],"matched_names":[],"confidence":"n/a",
                                "note":"Water utility — no EIA data"}
            continue

        matched_ids, matched_names = [], []
        # Exclusion patterns — reject these even if they substring-match
        EXCLUDE_PATTERNS = [
            "corps of engineers", "army corps", "usce", "bureau of reclamation",
            "tva", "bonneville", "western area power", "southwestern power",
            "southeastern power", "coop", "cooperative", "municipal", "city of",
            "town of", "county of", "rural electric",
        ]

        for uid, uname in gen_utils.items():
            if not isinstance(uname, str): continue
            uname_lower = uname.lower()
            # Skip obvious false positives
            if any(excl in uname_lower for excl in EXCLUDE_PATTERNS): continue
            for sub in company.get("subsidiaries",[]):
                if sub.lower() in uname_lower or uname_lower in sub.lower():
                    if uid not in matched_ids:
                        matched_ids.append(uid); matched_names.append(uname)
                    break

        if not matched_ids and ticker in KNOWN_IDS:
            for kid in KNOWN_IDS[ticker]:
                if kid not in matched_ids:
                    matched_ids.append(kid)
                    matched_names.append(gen_utils.get(kid, f"ID:{kid}"))
            confidence = "known_id_fallback"
            log.info(f"{ticker}: known ID fallback: {matched_ids}")
        elif matched_ids:
            confidence = "high"
            log.info(f"{ticker}: matched {len(matched_ids)} IDs: {matched_names[:2]}")
        else:
            confidence = "none"
            log.warning(f"{ticker}: no match")

        results[ticker] = {"ticker":ticker,"name":company["name"],"type":company["type"],
                            "utility_ids":matched_ids,"matched_names":matched_names,
                            "confidence":confidence,"note":company.get("note","")}
    return results

def build_plant_json(ticker, match, gen_df):
    if not match["utility_ids"]:
        write_json(PLANTS_DIR / f"{ticker}_plants.json", {
            "ticker":ticker,"name":match["name"],"type":match["type"],
            "generated":datetime.now().isoformat(),"note":match.get("note",""),
            "plants":[],"tech_summary":{},"state_summary":{},"total_mw":0
        })
        return

    mask = gen_df["utility_id"].isin(match["utility_ids"]) if "utility_id" in gen_df.columns else pd.Series([False]*len(gen_df))
    df   = gen_df[mask].copy()

    # Operating status filter — "OP" prefix or contains "operating"
    if "status" in df.columns:
        op_mask = df["status"].str.upper().str.startswith("OP", na=False)
        df = df[op_mask]

    plant_groups = {}
    for _, row in df.iterrows():
        key = (row.get("plant_id"), row.get("plant_name"), row.get("state"), row.get("technology"))
        if key not in plant_groups:
            plant_groups[key] = {
                "plant_id": row.get("plant_id"), "plant_name": row.get("plant_name"),
                "state": row.get("state"),         "technology": row.get("technology"),
                "capacity_mw": 0,
                "latitude": row.get("latitude"),   "longitude": row.get("longitude"),
                "operating_year": row.get("operating_year"),
                "color": TECH_COLORS.get(row.get("technology","Other"), "#95A5A6"),
            }
        plant_groups[key]["capacity_mw"] = round(
            (plant_groups[key]["capacity_mw"] or 0) + (row.get("capacity_mw") or 0), 1)

    plants = sorted(plant_groups.values(), key=lambda p: p["capacity_mw"] or 0, reverse=True)
    tech_summary  = {}
    state_summary = {}
    for p in plants:
        t = p["technology"] or "Other"
        s = p["state"] or "UNK"
        tech_summary[t]  = round(tech_summary.get(t, 0)  + (p["capacity_mw"] or 0), 1)
        state_summary[s] = round(state_summary.get(s, 0) + (p["capacity_mw"] or 0), 1)

    total_mw = round(sum(p["capacity_mw"] or 0 for p in plants), 1)
    write_json(PLANTS_DIR / f"{ticker}_plants.json", {
        "ticker":ticker,"name":match["name"],"type":match["type"],
        "generated":datetime.now().isoformat(),"utility_ids":match["utility_ids"],
        "total_mw":total_mw,"plant_count":len(plants),
        "tech_summary": dict(sorted(tech_summary.items(),  key=lambda x:x[1], reverse=True)),
        "state_summary":dict(sorted(state_summary.items(), key=lambda x:x[1], reverse=True)),
        "tech_colors":TECH_COLORS,"plants":plants
    })
    log.info(f"{ticker}: {len(plants)} plants, {total_mw:,.0f} MW")

def main():
    log.info("="*60)
    log.info(f"Power Academy EIA Pipeline v3 — {datetime.now().isoformat()}")
    log.info("="*60)
    ensure_dirs()

    if not EIA_860_ZIP.exists():
        log.error(f"EIA 860 zip not found at {EIA_860_ZIP}. Please download manually.")
        return
    if not EIA_861_ZIP.exists():
        log.error(f"EIA 861 zip not found at {EIA_861_ZIP}. Please download manually.")
        return

    gen_df      = load_eia860_plants()
    territories = load_eia861_territories_xlsx()
    id_map      = match_companies(gen_df, territories)

    write_json(ID_MAP_FILE, id_map)

    for ticker, match in id_map.items():
        build_plant_json(ticker, match, gen_df)
        build_territory_geojson_from_xlsx(ticker, match, territories)

    log.info("\n" + "="*60 + "\nSUMMARY\n" + "="*60)
    for ticker, match in id_map.items():
        mw = ""
        pf = PLANTS_DIR / f"{ticker}_plants.json"
        if pf.exists():
            try:
                d = json.loads(pf.read_text())
                if d.get("total_mw"): mw = f"  {d['total_mw']:>8,.0f} MW"
            except: pass
        log.info(f"  {ticker:<8} {match['confidence']:<30}{mw}")
    log.info(f"\nOutput: {BASE_DIR}\nDone.")

if __name__ == "__main__":
    main()