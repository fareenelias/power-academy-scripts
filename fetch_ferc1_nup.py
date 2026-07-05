"""
fetch_ferc1_nup.py
------------------
Downloads the PUDL FERC Form 1 balance sheet assets Parquet file from S3
(no AWS credentials needed — public bucket) and extracts Net Utility Plant (NUP)
per opco/respondent for the most recent year available.

Outputs:
  data/ferc1_nup.json   — NUP per respondent, keyed by utility name
  Appends opco_nup to capiq_export.json for each parent company

Run:
    pip install pandas pyarrow --break-system-packages
    python fetch_ferc1_nup.py --capiq E:/PowerAcademy/data/capiq_export.json

What PUDL provides (FERC Form 1, Schedule 200 / Balance Sheet):
  - utility_name_ferc1   : respondent name as filed (e.g. "Florida Power & Light Co")
  - utility_type         : "Electric Utility", "Gas Utility", "Other Utility"
  - xbrl_factoid         : accounting line item name
  - plant_status         : "in_service", "future", "leased", "total"
  - ending_balance       : dollar value (USD)
  - report_year          : 4-digit year

We filter to xbrl_factoid="utility_plant_net", plant_status="total" to get NUP.
"""

import argparse, json, os, sys, urllib.request
from pathlib import Path

PARQUET_URL = (
    "https://pudl.catalyst.coop/nightly/"
    "out_ferc1__yearly_detailed_balance_sheet_assets.parquet"
)
PARQUET_FILENAME = "out_ferc1__yearly_detailed_balance_sheet_assets.parquet"

parser = argparse.ArgumentParser()
parser.add_argument("--capiq",    required=True, help="Path to capiq_export.json")
parser.add_argument("--parquet",  default=None,  help="Path to already-downloaded Parquet file (skips download)")
parser.add_argument("--out-nup",  default=None,  help="Output path for ferc1_nup.json")
parser.add_argument("--year",     type=int, default=None, help="Year to extract (default: most recent)")
parser.add_argument("--no-update-capiq", action="store_true", help="Don't update capiq_export.json")
args = parser.parse_args()

capiq_dir = os.path.dirname(os.path.abspath(args.capiq))
nup_out   = args.out_nup or os.path.join(capiq_dir, "ferc1_nup.json")

# ── Step 1: Locate or download Parquet ────────────────────────────────────
# Check --parquet arg, then capiq_dir, then try download
def find_parquet():
    if args.parquet:
        if os.path.exists(args.parquet):
            return args.parquet
        print(f"ERROR: --parquet file not found: {args.parquet}")
        sys.exit(1)
    # Check if already in data dir
    local = os.path.join(capiq_dir, PARQUET_FILENAME)
    if os.path.exists(local):
        print(f"Found existing Parquet: {local}")
        return local
    # Try downloading
    print(f"Parquet not found locally. Attempting download...")
    print(f"  URL: {PARQUET_URL}")
    print(f"  If this fails, download manually in your browser and save to:")
    print(f"  {local}")
    try:
        urllib.request.urlretrieve(PARQUET_URL, local)
        print(f"  Downloaded: {os.path.getsize(local)/1e6:.1f} MB")
        return local
    except Exception as e:
        print(f"\nERROR: {e}")
        print("\nManual download instructions:")
        print(f"  1. Open in browser: {PARQUET_URL}")
        print(f"  2. Save to: {local}")
        print(f"  3. Re-run this script")
        sys.exit(1)

parquet_path = find_parquet()
cleanup_parquet = (parquet_path == os.path.join(capiq_dir, PARQUET_FILENAME)) and not args.parquet

# ── Step 2: Load and filter ────────────────────────────────────────────────
try:
    import pandas as pd
except ImportError:
    print("ERROR: pandas not installed. Run: pip install pandas pyarrow --break-system-packages")
    sys.exit(1)

print("\nLoading Parquet...")
df = pd.read_parquet(parquet_path)
print(f"  Loaded {len(df):,} rows, columns: {list(df.columns)}")

# Show available years
years = sorted(df['report_year'].unique())
print(f"  Available years: {years}")

target_year = args.year or max(years)
print(f"  Using year: {target_year}")

# Filter to NUP: utility_plant_net, total status
# Also try 'net_utility_plant' as alternate xbrl_factoid name
nup_factoids = {'utility_plant_net', 'net_utility_plant', 'total_utility_plant_net'}

df_nup = df[
    (df['report_year'] == target_year) &
    (df['xbrl_factoid'].isin(nup_factoids)) &
    (df['plant_status'].isin(['total', 'Total', None])) &
    (df['ending_balance'].notna()) &
    (df['ending_balance'] > 0)
].copy()

print(f"\n  After filtering (year={target_year}, NUP rows): {len(df_nup)}")

if len(df_nup) == 0:
    # Diagnose: show what factoids and statuses exist
    print("\n  Available xbrl_factoids (sample):")
    print(df[df['report_year']==target_year]['xbrl_factoid'].value_counts().head(20))
    print("\n  Available plant_status values:")
    print(df[df['report_year']==target_year]['plant_status'].value_counts().head(10))
    sys.exit(1)

# Group by utility name and utility type, take the row with highest balance
# (in case of duplicates, prefer Electric Utility)
priority = {'Electric Utility': 0, 'Gas Utility': 1, 'Other Utility': 2}
df_nup['_priority'] = df_nup['utility_type'].map(priority).fillna(3)
df_nup = df_nup.sort_values(['utility_name_ferc1', '_priority', 'ending_balance'], ascending=[True, True, False])
df_nup = df_nup.drop_duplicates(subset=['utility_name_ferc1', 'utility_type'])

# ── Step 3: Build NUP lookup ──────────────────────────────────────────────
nup_data = {}
for _, row in df_nup.iterrows():
    name = row['utility_name_ferc1']
    nup_data[name] = {
        "utility_name_ferc1": name,
        "utility_type":       row.get('utility_type', ''),
        "report_year":        int(row['report_year']),
        "nup_usd":            float(row['ending_balance']),  # dollars
        "nup_b":              round(float(row['ending_balance']) / 1e9, 3),
        "xbrl_factoid":       row.get('xbrl_factoid', ''),
        "plant_status":       row.get('plant_status', ''),
        "source":             "FERC Form 1 via PUDL",
    }

print(f"\nExtracted NUP for {len(nup_data)} utilities")

# Save standalone NUP file
with open(nup_out, 'w', encoding='utf-8') as f:
    json.dump({
        "report_year": target_year,
        "source": "FERC Form 1 via PUDL (out_ferc1__yearly_detailed_balance_sheet_assets)",
        "pudl_url": PARQUET_URL,
        "utilities": nup_data,
    }, f, indent=2)
print(f"Wrote {nup_out}")

# ── Step 4: Match to capiq opcos and update capiq_export.json ─────────────
if args.no_update_capiq:
    print("\nSkipping capiq_export.json update (--no-update-capiq)")
    sys.exit(0)

with open(args.capiq, 'r', encoding='utf-8') as f:
    capiq_raw = json.load(f)

companies = capiq_raw.get('companies', capiq_raw)

# Build a normalized name lookup for fuzzy matching
import re

def normalize(s):
    s = s.lower()
    s = re.sub(r'\b(co\.|company|corporation|corp\.?|inc\.?|llc|l\.p\.|lp|ltd|electric|power|energy|gas|utility|utilities|light|&|and)\b', '', s)
    s = re.sub(r'[^a-z0-9 ]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

nup_norm = {normalize(k): v for k, v in nup_data.items()}

matched = 0
unmatched_opcos = []

for ticker, co in companies.items():
    opcos = co.get('rate_base_opcos', {}) or {}
    pending = co.get('pending_rate_cases', []) or []
    past    = co.get('past_rate_cases', []) or []

    # Collect all known opco names for this parent
    all_opco_names = list(opcos.keys())
    for case in pending + past:
        name = case.get('company')
        if name and name not in all_opco_names:
            all_opco_names.append(name)

    opco_nup = {}
    for opco_name in all_opco_names:
        norm_name = normalize(opco_name)
        # Try exact normalized match first
        match = nup_norm.get(norm_name)
        if not match:
            # Try substring match
            for pudl_norm, pudl_data in nup_norm.items():
                if norm_name and (norm_name in pudl_norm or pudl_norm in norm_name):
                    match = pudl_data
                    break
        if match:
            opco_nup[opco_name] = {
                "ferc1_name":  match['utility_name_ferc1'],
                "utility_type": match['utility_type'],
                "nup_b":       match['nup_b'],
                "report_year": match['report_year'],
                "source":      "FERC Form 1 via PUDL",
            }
            matched += 1
        else:
            unmatched_opcos.append(f"{ticker}/{opco_name}")

    if opco_nup:
        co['opco_nup_ferc1'] = opco_nup

print(f"\nMatched {matched} opcos to FERC Form 1 NUP data")
if unmatched_opcos:
    print(f"Unmatched opcos ({len(unmatched_opcos)}):")
    for u in unmatched_opcos[:20]:
        print(f"  {u}")

# Write updated capiq
with open(args.capiq, 'w', encoding='utf-8') as f:
    json.dump(capiq_raw, f, indent=2, ensure_ascii=False)
print(f"\nUpdated {args.capiq} with opco_nup_ferc1 fields")

# ── Step 5: Summary table ─────────────────────────────────────────────────
print(f"\n{'Ticker':<6} {'Opco':<40} {'NUP ($B)':>10} {'Type':<20} {'FERC Name'}")
print("-" * 110)
for ticker, co in companies.items():
    for opco_name, nup_info in (co.get('opco_nup_ferc1') or {}).items():
        print(f"{ticker:<6} {opco_name[:39]:<40} {nup_info['nup_b']:>9.2f}B {nup_info['utility_type']:<20} {nup_info['ferc1_name'][:30]}")

# Cleanup downloaded file (keep if user specified --parquet)
if not args.parquet and os.path.exists(parquet_path):
    os.remove(parquet_path)
    print(f"\nCleaned up temp Parquet. Done.")
else:
    print(f"\nDone. Parquet kept at: {parquet_path}")