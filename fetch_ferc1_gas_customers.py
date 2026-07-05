"""
fetch_ferc1_gas_customers.py
-----------------------------
Downloads PUDL FERC Form 1 sales by rate schedules parquet and extracts
gas customer counts per LDC respondent.

The table out_ferc1__yearly_sales_by_rate_schedules_sched304 contains:
  - utility_name_ferc1, report_year
  - rate_schedule_type (residential, commercial, industrial, etc.)
  - customer_count (number of customers on that rate schedule)
  - revenue_per_kwh, sales_mwh, etc.

We sum customer_count across all rate schedules per utility per year
to get total customers, separately for electric and gas utilities.

Run:
    python fetch_ferc1_gas_customers.py --capiq E:/PowerAcademy/data/capiq_export.json

Output: updates ferc1_opco_data.json with gas_customers field per opco
"""

import argparse, json, os, re, sys, urllib.request

PARQUET_FILENAME = "out_ferc1__yearly_sales_by_rate_schedules_sched304.parquet"
PARQUET_URL = "https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/nightly/" + PARQUET_FILENAME

parser = argparse.ArgumentParser()
parser.add_argument("--capiq",   required=True)
parser.add_argument("--parquet", default=None)
parser.add_argument("--year",    type=int, default=2024)
parser.add_argument("--opco-data", default=None, help="Path to ferc1_opco_data.json to update")
args = parser.parse_args()

capiq_dir  = os.path.dirname(os.path.abspath(args.capiq))
opco_path  = args.opco_data or os.path.join(capiq_dir, "ferc1_opco_data.json")

# ── Locate parquet ────────────────────────────────────────────────────────
def find_parquet():
    if args.parquet and os.path.exists(args.parquet):
        return args.parquet
    local = os.path.join(capiq_dir, PARQUET_FILENAME)
    if os.path.exists(local):
        print(f"Found: {local}")
        return local
    print(f"Downloading {PARQUET_FILENAME}...")
    print(f"  {PARQUET_URL}")
    print(f"  (If VPN blocks this, download manually and save to {local})")
    try:
        urllib.request.urlretrieve(PARQUET_URL, local)
        print(f"  Downloaded {os.path.getsize(local)/1e6:.0f} MB")
        return local
    except Exception as e:
        print(f"Download failed: {e}")
        print(f"Manual download URL: {PARQUET_URL}")
        sys.exit(1)

parquet_path = find_parquet()

try:
    import pandas as pd
except ImportError:
    print("pip install pandas pyarrow --break-system-packages")
    sys.exit(1)

print("Loading parquet...")
df = pd.read_parquet(parquet_path)
print(f"  {len(df):,} rows, columns: {list(df.columns)}")
print(f"  Years: {sorted(df.report_year.unique())[-5:]}")

year = args.year
df_yr = df[df.report_year == year].copy()
print(f"  {len(df_yr):,} rows for {year}")

# ── Diagnose utility_type values ─────────────────────────────────────────
if 'utility_type' in df_yr.columns:
    print(f"\nutility_type values: {df_yr.utility_type.value_counts().to_dict()}")
else:
    print("\nNo utility_type column — will use all records")

# ── Sum customer counts per utility ──────────────────────────────────────
cust_col = next((c for c in df_yr.columns if 'customer' in c.lower()), None)
print(f"\nCustomer count column: {cust_col}")

if not cust_col:
    print("Available columns:", list(df_yr.columns))
    sys.exit(1)

df_yr = df_yr[df_yr[cust_col].notna() & (df_yr[cust_col] > 0)]

# Group by utility_name and utility_type
group_cols = ['utility_name_ferc1']
if 'utility_type' in df_yr.columns:
    group_cols.append('utility_type')

customers = (df_yr.groupby(group_cols)[cust_col]
             .sum()
             .reset_index()
             .rename(columns={cust_col: 'total_customers'}))

print(f"  Customer data for {len(customers)} utilities")

# Filter to gas utilities
if 'utility_type' in customers.columns:
    gas_customers = customers[customers.utility_type.str.contains('Gas', case=False, na=False)]
    elec_customers = customers[customers.utility_type.str.contains('Electric', case=False, na=False)]
    print(f"  Gas utilities: {len(gas_customers)}, Electric: {len(elec_customers)}")
else:
    gas_customers = customers
    elec_customers = customers

# Build lookups
def normalize(s):
    s = s.lower()
    s = re.sub(r'\b(co\.?|company|corporation|corp\.?|inc\.?|llc|l\.p\.|lp|ltd|'
               r'electric|power|energy|gas|utility|utilities|light|&|and)\b', '', s)
    s = re.sub(r'[^a-z0-9 ]', '', s)
    return re.sub(r'\s+', ' ', s).strip()

gas_lookup  = {normalize(r.utility_name_ferc1): int(r.total_customers)
               for _, r in gas_customers.iterrows()}
elec_lookup = {normalize(r.utility_name_ferc1): int(r.total_customers)
               for _, r in elec_customers.iterrows()}

def best_match(opco_name, lookup):
    norm = normalize(opco_name)
    if norm in lookup:
        return lookup[norm]
    for k, v in lookup.items():
        if norm and len(norm) > 4 and (norm in k or k in norm):
            return v
    return None

# ── Load capiq and update ────────────────────────────────────────────────
with open(args.capiq, 'r', encoding='utf-8') as f:
    capiq_raw = json.load(f)
companies = capiq_raw.get('companies', capiq_raw)

# Load existing opco_data if present
opco_data_all = {}
if os.path.exists(opco_path):
    with open(opco_path, 'r', encoding='utf-8') as f:
        existing = json.load(f)
    opco_data_all = existing.get('companies', {})
    print(f"\nLoaded existing ferc1_opco_data.json")

print(f"\n{'Ticker':<6} {'Opco':<42} {'Gas Cust':>10} {'Elec Cust':>10}")
print("-" * 72)

for ticker, co in companies.items():
    opcos   = list((co.get('rate_base_opcos') or {}).keys())
    pending = co.get('pending_rate_cases') or []
    past    = co.get('past_rate_cases') or []
    all_names = list(opcos)
    for case in pending + past:
        n = case.get('company')
        if n and n not in all_names:
            all_names.append(n)

    if not all_names:
        continue

    ticker_opco_data = opco_data_all.get(ticker, {})
    
    for name in all_names:
        gas_cust  = best_match(name, gas_lookup)
        elec_cust = best_match(name, elec_lookup)
        
        if gas_cust or elec_cust:
            if name not in ticker_opco_data:
                ticker_opco_data[name] = {}
            if gas_cust:
                ticker_opco_data[name]['gas_customers'] = gas_cust
            if elec_cust:
                ticker_opco_data[name]['electric_customers'] = elec_cust
            ticker_opco_data[name]['customers_year'] = year

            print(f"{ticker:<6} {name[:41]:<42} "
                  f"{f'{gas_cust:,}' if gas_cust else '—':>10} "
                  f"{f'{elec_cust:,}' if elec_cust else '—':>10}")

    if ticker_opco_data:
        opco_data_all[ticker] = ticker_opco_data
        co['opco_nup_ferc1'] = ticker_opco_data

# ── Write outputs ────────────────────────────────────────────────────────
with open(opco_path, 'w', encoding='utf-8') as f:
    json.dump({
        'report_year': year,
        'source': 'FERC Form 1 via PUDL',
        'companies': opco_data_all,
    }, f, indent=2)
print(f"\nWrote: {opco_path}")

with open(args.capiq, 'w', encoding='utf-8') as f:
    json.dump(capiq_raw, f, indent=2, ensure_ascii=False)
print(f"Updated: {args.capiq}")

# Cleanup
if not args.parquet:
    local = os.path.join(capiq_dir, PARQUET_FILENAME)
    if os.path.exists(local):
        os.remove(local)
        print("Cleaned up temp parquet")