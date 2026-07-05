"""
diagnose_opco_data.py
Checks:
1. ETR's rate_base_opcos and past_rate_case field names in capiq_export.json
2. NEE docket D-20250011-EI — shows all fields to confirm what's extracted
"""
import json, os

CAPIQ = r"E:\PowerAcademy\data\capiq_export.json"

with open(CAPIQ, 'r', encoding='utf-8') as f:
    data = json.load(f)

companies = data.get('companies', data)

# ── 1. ETR rate_base_opcos ────────────────────────────────────────────────────
etr = companies.get('ETR', {})
print("=== ETR rate_base_opcos ===")
rbo = etr.get('rate_base_opcos', {})
if rbo:
    for k, v in rbo.items():
        print(f"  {k}: {v}")
else:
    print("  EMPTY — no rate_base_opcos for ETR")

print()
print("=== ETR past_rate_cases (first 2, all fields) ===")
for case in (etr.get('past_rate_cases') or [])[:2]:
    for k, v in case.items():
        print(f"  {k}: {v!r}")
    print()

# ── 2. NEE docket D-20250011-EI ───────────────────────────────────────────────
nee = companies.get('NEE', {})
print("=== NEE docket D-20250011-EI (all fields) ===")
found = False
for case in (nee.get('past_rate_cases') or []):
    if 'D-20250011' in str(case.get('docket', '')):
        found = True
        for k, v in case.items():
            print(f"  {k}: {v!r}")
        print()
if not found:
    print("  Docket D-20250011-EI NOT found in NEE past_rate_cases")
    print(f"  Total NEE past cases: {len(nee.get('past_rate_cases') or [])}")
    print("  First 3 NEE dockets:")
    for case in (nee.get('past_rate_cases') or [])[:3]:
        print(f"    {case.get('docket')} | {case.get('company')} | {case.get('decision_date')}")