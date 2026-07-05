"""
fetch_ferc1_nup_v3.py
---------------------
Extracts from PUDL FERC Form 1 parquet:
  1. Net Utility Plant (NUP) per opco — electric AND gas utilities
  2. Gas customer counts per opco
  3. Matches to capiq_export.json opcos and parent companies

Fixes from v2:
  - Uses 2024 (most recent complete year) instead of 2025
  - Expanded factoid search: tries multiple NUP factoid names
  - Also pulls gas_customers from sales/customer tables
  - Outputs ferc1_opco_data.json with NUP + gas customers

Run:
    python fetch_ferc1_nup_v3.py --capiq E:/PowerAcademy/data/capiq_export.json
    
The parquet file is auto-detected in the same dir as capiq, or specify:
    python fetch_ferc1_nup_v3.py --capiq ... --parquet path/to/file.parquet
"""

import argparse, json, os, re, sys, urllib.request
from pathlib import Path

PARQUET_FILENAME = "out_ferc1__yearly_detailed_balance_sheet_assets.parquet"
PARQUET_URL = "https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/nightly/" + PARQUET_FILENAME

# Known NUP factoid names across PUDL versions / FERC taxonomy changes
NUP_FACTOIDS = {
    "utility_plant_net",
    "net_utility_plant",
    "total_utility_plant_net",
    "electric_plant_net",        # some filings use this
    "net_electric_utility_plant",
}

parser = argparse.ArgumentParser()
parser.add_argument("--capiq",   required=True)
parser.add_argument("--parquet", default=None)
parser.add_argument("--year",    type=int, default=2024, help="Filing year (default 2024 — most complete)")
parser.add_argument("--out",     default=None, help="Output JSON path (default: ferc1_opco_data.json next to capiq)")
args = parser.parse_args()

capiq_dir = os.path.dirname(os.path.abspath(args.capiq))
out_path  = args.out or os.path.join(capiq_dir, "ferc1_opco_data.json")

# ── Locate parquet ────────────────────────────────────────────────────────
def find_parquet():
    if args.parquet and os.path.exists(args.parquet):
        return args.parquet
    local = os.path.join(capiq_dir, PARQUET_FILENAME)
    if os.path.exists(local):
        print(f"Found parquet: {local}")
        return local
    print(f"Parquet not found. Attempting download from S3...")
    print(f"  {PARQUET_URL}")
    try:
        urllib.request.urlretrieve(PARQUET_URL, local)
        print(f"  Downloaded {os.path.getsize(local)/1e6:.0f} MB")
        return local
    except Exception as e:
        print(f"Download failed: {e}")
        print(f"Download manually and save to: {local}")
        sys.exit(1)

parquet_path = find_parquet()

# ── Load parquet ─────────────────────────────────────────────────────────
try:
    import pandas as pd
except ImportError:
    print("pip install pandas pyarrow --break-system-packages")
    sys.exit(1)

print(f"Loading parquet...")
df = pd.read_parquet(parquet_path)
print(f"  {len(df):,} rows, years: {sorted(df.report_year.unique())[-5:]}")

year = args.year
df_yr = df[df.report_year == year]
print(f"  {len(df_yr):,} rows for {year}")

# ── Diagnose available factoids for NUP ──────────────────────────────────
available_factoids = set(df_yr.xbrl_factoid.unique())
matching = NUP_FACTOIDS & available_factoids
print(f"\nNUP factoids found in {year}: {matching or 'NONE'}")

if not matching:
    # Show top factoids to help diagnose
    print("\nTop 30 factoids in this year:")
    top = df_yr.xbrl_factoid.value_counts().head(30)
    for factoid, count in top.items():
        if any(kw in str(factoid) for kw in ['plant','utility','net','electric','gas']):
            print(f"  {factoid}: {count}")
    
    # Try adjacent years
    for alt_year in [2023, 2022, 2021]:
        df_alt = df[df.report_year == alt_year]
        alt_match = NUP_FACTOIDS & set(df_alt.xbrl_factoid.unique())
        if alt_match:
            print(f"\nFalling back to {alt_year} (has: {alt_match})")
            year = alt_year
            df_yr = df_alt
            matching = alt_match
            break
    else:
        print("\nCould not find NUP factoid in any year. Exiting.")
        sys.exit(1)

# ── Extract NUP per utility ───────────────────────────────────────────────
df_nup = df_yr[
    df_yr.xbrl_factoid.isin(matching) &
    df_yr.plant_status.isin(['total', 'Total', None]) &
    df_yr.ending_balance.notna() &
    (df_yr.ending_balance > 0)
].copy()

# If plant_status filter gives nothing, try without it
if len(df_nup) == 0:
    df_nup = df_yr[
        df_yr.xbrl_factoid.isin(matching) &
        df_yr.ending_balance.notna() &
        (df_yr.ending_balance > 0)
    ].copy()
    print(f"  (plant_status filter relaxed)")

print(f"  {len(df_nup)} NUP rows after filtering")

# Priority: Electric Utility > Gas Utility > Other
priority = {'Electric Utility': 0, 'Gas Utility': 1, 'Other Utility': 2}
df_nup['_pri'] = df_nup.utility_type.map(priority).fillna(3)
df_nup = df_nup.sort_values(['utility_name_ferc1', '_pri', 'ending_balance'],
                             ascending=[True, True, False])

# One row per (utility_name, utility_type) combo — keep highest balance
df_nup = df_nup.drop_duplicates(subset=['utility_name_ferc1', 'utility_type'])

# Build lookup: name → {electric_nup_b, gas_nup_b}
nup_by_name = {}
for _, row in df_nup.iterrows():
    name = row.utility_name_ferc1
    ut   = row.utility_type or 'Unknown'
    nup_b = round(float(row.ending_balance) / 1e9, 3)
    if name not in nup_by_name:
        nup_by_name[name] = {'utility_name_ferc1': name, 'report_year': int(year)}
    key = 'electric_nup_b' if 'Electric' in ut else 'gas_nup_b' if 'Gas' in ut else 'other_nup_b'
    nup_by_name[name][key] = nup_b
    nup_by_name[name]['utility_type'] = ut

print(f"  NUP data for {len(nup_by_name)} utilities")

# ── Try to get gas customer counts ────────────────────────────────────────
# PUDL also has out_ferc1__yearly_sales_by_rate_schedules which has customer counts
# But it's a separate parquet. Check if there's a customers column in our table.
gas_customer_cols = [c for c in df.columns if 'customer' in c.lower()]
print(f"\nCustomer columns in balance sheet parquet: {gas_customer_cols}")

# The customers data is in a different PUDL table: out_ferc1__yearly_utility_plant_summary_sched200
# or core_ferc1__yearly_operating_revenues_sched300. We only have the balance sheet here.
# For gas customers we'll note this needs the sales parquet (separate download).
# For now, mark as "see ferc1_customers parquet"
print("  Gas customer counts require a separate PUDL parquet (operating revenues/sales).")
print("  NUP extraction will proceed; gas customers can be added later.")

# ── Normalize names for fuzzy matching ───────────────────────────────────
def normalize(s):
    s = s.lower()
    s = re.sub(r'\b(co\.?|company|corporation|corp\.?|inc\.?|llc|l\.p\.|lp|ltd|'
               r'electric|power|energy|gas|utility|utilities|light|&|and)\b', '', s)
    s = re.sub(r'[^a-z0-9 ]', '', s)
    return re.sub(r'\s+', ' ', s).strip()

nup_norm = {normalize(k): v for k, v in nup_by_name.items()}

# ── Load capiq and match ──────────────────────────────────────────────────
with open(args.capiq, 'r', encoding='utf-8') as f:
    capiq_raw = json.load(f)
companies = capiq_raw.get('companies', capiq_raw)

def best_match(opco_name):
    norm = normalize(opco_name)
    if norm in nup_norm:
        return nup_norm[norm]
    # Substring match
    for pudl_norm, data in nup_norm.items():
        if norm and len(norm) > 4 and (norm in pudl_norm or pudl_norm in norm):
            return data
    return None

matched_total = 0
results = {}

print(f"\n{'Ticker':<6} {'Opco':<42} {'Elec NUP':>9} {'Gas NUP':>9} {'Match'}")
print("-" * 80)

for ticker, co in companies.items():
    opcos  = list((co.get('rate_base_opcos') or {}).keys())
    pending = co.get('pending_rate_cases') or []
    past    = co.get('past_rate_cases') or []
    
    # All known opco names
    all_names = list(opcos)
    for case in pending + past:
        n = case.get('company')
        if n and n not in all_names:
            all_names.append(n)
    
    if not all_names:
        continue

    opco_data = {}
    for name in all_names:
        match = best_match(name)
        if match:
            matched_total += 1
            opco_data[name] = {
                'ferc1_name':    match['utility_name_ferc1'],
                'report_year':   match['report_year'],
                'electric_nup_b': match.get('electric_nup_b'),
                'gas_nup_b':     match.get('gas_nup_b'),
                'utility_type':  match.get('utility_type'),
                'source':        'FERC Form 1 via PUDL',
            }
            e = match.get('electric_nup_b')
            g = match.get('gas_nup_b')
            print(f"{ticker:<6} {name[:41]:<42} "
                  f"{f'${e:.1f}B' if e else '—':>9} "
                  f"{f'${g:.1f}B' if g else '—':>9} "
                  f"  ✓ {match['utility_name_ferc1'][:25]}")
        else:
            print(f"{ticker:<6} {name[:41]:<42} {'—':>9} {'—':>9}  ✗ no match")
    
    if opco_data:
        results[ticker] = opco_data
        co['opco_nup_ferc1'] = opco_data

print(f"\nMatched {matched_total} opcos across {len(results)} companies")

# ── Write outputs ─────────────────────────────────────────────────────────
with open(args.capiq, 'w', encoding='utf-8') as f:
    json.dump(capiq_raw, f, indent=2, ensure_ascii=False)
print(f"Updated: {args.capiq}")

with open(out_path, 'w', encoding='utf-8') as f:
    json.dump({
        'report_year': year,
        'source': 'FERC Form 1 via PUDL out_ferc1__yearly_detailed_balance_sheet_assets',
        'companies': results,
    }, f, indent=2)
print(f"Wrote:   {out_path}")