"""
fetch_ferc1_opco_data.py  v5
- Customers: filter to billing_status='total' AND rate_schedule_type='total'
  (one row per utility = true total, e.g. FPL = 5.96M not 11.9M)
- NUP: utility_plant_asset_type='utility_plant_net' from sched200
- Hardcoded entries for opcos that don't file separately in FERC:
    D/DESC: Dominion Energy South Carolina ($8.6B elec, $1.4B gas, 806K cust)
    NEE/Lone Star: no retail customers, ~$2B transmission NUP
    NEE/Gulf Power: merged into FPL in 2021, no longer files separately
- flat_utilities covers all ~217 FERC filers for non-coverage IOU lookup
"""

import argparse, json, os, re, sys, urllib.request

BASE_URL = "https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/nightly/"
PARQUETS = {
    "plant_summary": "out_ferc1__yearly_utility_plant_summary_sched200.parquet",
    "sales":         "out_ferc1__yearly_sales_by_rate_schedules_sched304.parquet",
}

# Hardcoded entries for opcos that file consolidated or are transmission-only
# Sources: FERC balance sheet parquet (v2 run), EIA data, company filings
HARDCODED = {
    "D": {
        "Dominion Energy South Carolina": {
            "customers": 806434,
            "electric_nup_b": 8.6,
            "gas_nup_b": 1.4,
            "source": "FERC Form 1 balance sheet / CapIQ",
        },
    },
    "NEE": {
        "Lone Star Transmission LLC": {
            "electric_nup_b": 2.1,   # transmission plant only, from FERC balance sheet
            "source": "FERC Form 1 balance sheet",
        },
        # Gulf Power merged into FPL 2021 - no separate filing
    },
}

EXTRA_OPCOS = {
    "ETR": ["Entergy Louisiana LLC","Entergy Mississippi LLC","Entergy Texas Inc.",
            "Entergy New Orleans LLC","Entergy Gulf States Louisiana LLC"],
    "ES":  ["The CT Light & Power Co","Western Massachusetts Electric Co","Yankee Gas Services Co"],
    "PPL": ["PPL Electric Utilities Corporation"],
    "EVRG":["Evergy Kansas Central","Evergy Metro","Evergy Missouri West",
            "Kansas City Power & Light","KCP&L Greater Missouri Operations"],
}

parser = argparse.ArgumentParser()
parser.add_argument("--capiq", required=True)
parser.add_argument("--year",  type=int, default=2024)
parser.add_argument("--out",   default=None)
parser.add_argument("--keep-parquets", action="store_true")
args = parser.parse_args()

capiq_dir = os.path.dirname(os.path.abspath(args.capiq))
out_path  = args.out or os.path.join(capiq_dir, "ferc1_opco_data.json")

try:
    import pandas as pd
except ImportError:
    print("pip install pandas pyarrow --break-system-packages"); sys.exit(1)

def get_parquet(key):
    fname = PARQUETS[key]
    local = os.path.join(capiq_dir, fname)
    if os.path.exists(local):
        print(f"  Found: {fname}"); return local
    url = BASE_URL + fname
    print(f"  Downloading {fname}...")
    urllib.request.urlretrieve(url, local)
    print(f"  {os.path.getsize(local)/1e6:.0f} MB")
    return local

def normalize(s):
    s = s.lower()
    for suffix in [' co.', ' corp.', ' inc.', ' llc', ' l.p.', ' lp', ' ltd',
                   ' company', ' corporation', ' incorporated']:
        s = s.replace(suffix, ' ')
    s = s.replace(' and ', ' ').replace(' & ', ' ').replace('&', ' ')
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()

print("Loading FERC Form 1 data...")
dfs = {k: pd.read_parquet(get_parquet(k)) for k in PARQUETS}
year = args.year

# ── 1. NUP from utility_plant_summary ────────────────────────────────────
print(f"\n=== NUP (year={year}) ===")
ps_yr = dfs["plant_summary"][dfs["plant_summary"].report_year == year].copy()
NUP_TYPES = {"utility_plant_net", "utility_plant_net_correction"}
df_nup = ps_yr[ps_yr.utility_plant_asset_type.isin(NUP_TYPES) &
               ps_yr.ending_balance.notna() & (ps_yr.ending_balance > 0)]

nup_lookup = {}
ut_col = "utility_type" if "utility_type" in df_nup.columns else None
for _, row in df_nup.iterrows():
    name = row.utility_name_ferc1
    val  = float(row.ending_balance)
    ut   = str(row[ut_col]).lower() if ut_col else ""
    nup_lookup.setdefault(name, {})
    key = "electric_nup_b" if "electric" in ut else "gas_nup_b" if "gas" in ut else "nup_b"
    if val / 1e9 > nup_lookup[name].get(key, 0):
        nup_lookup[name][key] = round(val / 1e9, 3)

print(f"  {len(nup_lookup)} utilities with NUP")
nup_norm = {normalize(k): (k, v) for k, v in nup_lookup.items()}

# ── 2. Customers: billing_status=total AND rate_schedule_type=total ────────
print(f"\n=== Customers (year={year}) ===")
s_yr = dfs["sales"][dfs["sales"].report_year == year].copy()

# Get the single aggregate row per utility: both billing_status=total AND rate_schedule_type=total
if "billing_status" in s_yr.columns and "rate_schedule_type" in s_yr.columns:
    total = s_yr[(s_yr.billing_status == "total") & (s_yr.rate_schedule_type == "total")]
    print(f"  billing+schedule total rows: {len(total)}")
    if len(total) > 10:
        s_yr = total
    else:
        # Fallback: just billing_status=total
        total2 = s_yr[s_yr.billing_status == "total"]
        if len(total2) > 10:
            s_yr = total2
            print(f"  Fallback billing_status=total rows: {len(s_yr)}")

cust_by_util = (s_yr.groupby("utility_name_ferc1")["avg_customers_per_month"]
    .sum().reset_index().rename(columns={"avg_customers_per_month": "total_customers"}))
print(f"  {len(cust_by_util)} utilities")

# Sanity check top 5
for _, r in cust_by_util.nlargest(5, "total_customers").iterrows():
    print(f"    {r.utility_name_ferc1[:45]}: {int(r.total_customers):,}")

cust_norm = {normalize(r.utility_name_ferc1): (r.utility_name_ferc1, int(r.total_customers))
             for _, r in cust_by_util.iterrows()}

# ── Build flat_utilities (all FERC filers, for non-coverage IOU info panel) ──
all_ferc_names = set(nup_lookup.keys()) | set(r.utility_name_ferc1 for _, r in cust_by_util.iterrows())
flat_utilities = {}
for ferc_name in all_ferc_names:
    n = normalize(ferc_name)
    entry = {"ferc1_name": ferc_name, "report_year": year}
    if ferc_name in nup_lookup:
        entry.update(nup_lookup[ferc_name])
    cust_match = cust_norm.get(n)
    if cust_match:
        entry["customers"] = cust_match[1]
    flat_utilities[n] = entry

print(f"  flat_utilities: {len(flat_utilities)} entries")

# ── Match function ─────────────────────────────────────────────────────────
def best_match_nup(name):
    n = normalize(name)
    if len(n) < 5: return None
    if n in nup_norm: return nup_norm[n][1]
    for k, (_, v) in nup_norm.items():
        if len(k) >= 5 and (n in k or k in n): return v
    return None

def best_match_cust(name):
    n = normalize(name)
    if len(n) < 5: return None
    if n in cust_norm: return cust_norm[n][1]
    for k, (_, v) in cust_norm.items():
        if len(k) >= 5 and (n in k or k in n): return v
    return None

# ── Load capiq ─────────────────────────────────────────────────────────────
with open(args.capiq, "r", encoding="utf-8") as f:
    capiq_raw = json.load(f)
companies = capiq_raw.get("companies", capiq_raw)

results = {}
print(f"\n{'Ticker':<6} {'Opco':<44} {'Customers':>12} {'Elec NUP':>10} {'Gas NUP':>9}")
print("-" * 85)

for ticker, co in companies.items():
    opcos = list((co.get("rate_base_opcos") or {}).keys())
    all_names = list(opcos)
    for case in (co.get("pending_rate_cases") or []) + (co.get("past_rate_cases") or []):
        n = case.get("company")
        if n and n not in all_names: all_names.append(n)
    # Add extra opcos not captured in capiq rate cases
    for extra in EXTRA_OPCOS.get(ticker, []):
        if extra not in all_names: all_names.append(extra)
    if not all_names: continue

    ticker_data = {}

    # Start with hardcoded entries for this ticker
    for opco_name, hc_entry in HARDCODED.get(ticker, {}).items():
        entry = {"report_year": year}
        entry.update(hc_entry)
        ticker_data[opco_name] = entry

    # Then match from FERC parquets
    for name in all_names:
        if name in ticker_data: continue  # skip if already hardcoded
        cust  = best_match_cust(name)
        nup_d = best_match_nup(name) or {}
        if cust is not None or nup_d:
            entry = {"report_year": year, "source": "FERC Form 1 via PUDL"}
            if cust is not None: entry["customers"] = cust
            if isinstance(nup_d, dict): entry.update(nup_d)
            ticker_data[name] = entry

    if ticker_data:
        # Print results
        for name, entry in ticker_data.items():
            cust  = entry.get("customers")
            e_nup = entry.get("electric_nup_b") or entry.get("nup_b")
            g_nup = entry.get("gas_nup_b")
            print(f"{ticker:<6} {name[:43]:<44} "
                  f"{str(f'{cust:,}') if cust else '—':>12} "
                  f"{f'${e_nup:.1f}B' if e_nup else '—':>10} "
                  f"{f'${g_nup:.1f}B' if g_nup else '—':>9}")
        results[ticker] = ticker_data
        co["opco_nup_ferc1"] = ticker_data

# ── Write ──────────────────────────────────────────────────────────────────
with open(out_path, "w", encoding="utf-8") as f:
    json.dump({
        "report_year": year,
        "source": "FERC Form 1 via PUDL",
        "companies": results,
        "flat_utilities": flat_utilities,
    }, f, indent=2)
print(f"\nWrote: {out_path}")

with open(args.capiq, "w", encoding="utf-8") as f:
    json.dump(capiq_raw, f, indent=2, ensure_ascii=False)
print(f"Updated: {args.capiq}")

if not args.keep_parquets:
    for fname in PARQUETS.values():
        local = os.path.join(capiq_dir, fname)
        if os.path.exists(local): os.remove(local); print(f"Cleaned: {fname}")