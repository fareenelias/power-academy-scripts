"""
diagnose_ferc.py - run locally to see what DESC and Lone Star look like in FERC parquets
python diagnose_ferc.py --capiq E:/PowerAcademy/data/capiq_export.json
"""
import argparse, os, urllib.request
import pandas as pd

parser = argparse.ArgumentParser()
parser.add_argument("--capiq", required=True)
args = parser.parse_args()
capiq_dir = os.path.dirname(os.path.abspath(args.capiq))

BASE = "https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/nightly/"

def get(fname):
    local = os.path.join(capiq_dir, fname)
    if not os.path.exists(local):
        print(f"Downloading {fname}...")
        urllib.request.urlretrieve(BASE + fname, local)
    return pd.read_parquet(local)

ps = get("out_ferc1__yearly_utility_plant_summary_sched200.parquet")
sales = get("out_ferc1__yearly_sales_by_rate_schedules_sched304.parquet")

ps24 = ps[ps.report_year == 2024]
s24  = sales[sales.report_year == 2024]

search_terms = ['dominion energy south carolina', 'lone star', 'gulf power', 'desc']

print("=== PLANT SUMMARY matches ===")
for term in search_terms:
    hits = ps24[ps24.utility_name_ferc1.str.lower().str.contains(term, na=False)]
    if len(hits):
        print(f"\n'{term}':")
        for _, r in hits[['utility_name_ferc1','utility_plant_asset_type','utility_type','ending_balance']].drop_duplicates('utility_name_ferc1').iterrows():
            print(f"  {r.utility_name_ferc1} | {r.utility_plant_asset_type} | {r.utility_type} | {r.ending_balance}")

print("\n=== SALES matches ===")
for term in search_terms:
    hits = s24[s24.utility_name_ferc1.str.lower().str.contains(term, na=False)]
    if len(hits):
        print(f"\n'{term}':")
        for _, r in hits[['utility_name_ferc1','billing_status','avg_customers_per_month']].iterrows():
            print(f"  {r.utility_name_ferc1} | {r.billing_status} | {int(r.avg_customers_per_month)}")

# Also check FPL customer count - should be ~5.8M not 11.9M
fpl = s24[s24.utility_name_ferc1.str.lower().str.contains('florida power', na=False)]
print("\n=== FPL all rows ===")
print(fpl[['utility_name_ferc1','billing_status','rate_schedule_type','avg_customers_per_month']].to_string())