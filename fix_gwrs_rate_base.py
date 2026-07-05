"""
fix_gwrs_rate_base.py  —  July 5 2026
GWRS had consolidated_b=null because no explicit rate base was disclosed.
The FY2025 earnings call (Mar 5 2026) stated:
  "We have increased the collective rate baseable assets of our company
   by $70 million or 59%"
  → Prior rate base ≈ $70M / 0.59 ≈ $118.6M
  → Post-capex rate baseable assets ≈ $188.6M (~$0.189B)
  Rate case pending at Arizona Corporation Commission.

This sets consolidated_b to 0.189 so TradingMetricsPanel can display it.
Run:  python fix_gwrs_rate_base.py
"""

import json, os

DATA_FILE = r"E:\PowerAcademy\data\rate_base_ip.json"

with open(DATA_FILE, encoding='utf-8') as f:
    data = json.load(f)

if 'GWRS' not in data:
    print('ERROR: GWRS not found in rate_base_ip.json — run update_rate_base_ip.py first')
    exit(1)

data['GWRS']['consolidated_b'] = 0.189
data['GWRS']['label'] = 'Est. ~2025 (rate baseable assets; rate case pending at ACC)'
data['GWRS']['opcos']['Global Water Resources (AZ)']['rate_base_b'] = 0.189
data['GWRS']['opcos']['Global Water Resources (AZ)']['label'] = 'Est. ~$189M: $70M added in 2025 (+59%); rate case pending'

with open(DATA_FILE, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print('[✓] GWRS updated:')
print(f'    consolidated_b = {data["GWRS"]["consolidated_b"]}')
print(f'    label          = {data["GWRS"]["label"]}')
print()
print('⚠  Remember: this is an estimate from the earnings call transcript.')
print('   Update once the ACC rate case is decided with the actual authorized rate base.')