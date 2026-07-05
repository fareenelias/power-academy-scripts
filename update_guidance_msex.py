"""
update_guidance_msex.py  —  July 5 2026
Adds MSEX guidance entry to guidance_ip.json.
Source: Middlesex Water Company May 2026 Investor Presentation

Run:  python update_guidance_msex.py
"""

import json, os

GUIDANCE_FILE = r"E:\PowerAcademy\data\guidance_ip.json"

def load():
    with open(GUIDANCE_FILE, encoding="utf-8") as f:
        return json.load(f)

def save(data):
    with open(GUIDANCE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[✓] Saved {GUIDANCE_FILE}")

def show_existing_schema(data):
    """Print one existing non-IPP entry so we can confirm schema match."""
    sample = next((v for k, v in data.items()
                   if k not in {"VST","TLN","XIFR"} and isinstance(v, dict)), None)
    if sample:
        print("Existing schema keys:", list(sample.keys()))

# ── MSEX guidance data ────────────────────────────────────────────────────────
# Extracted from Middlesex Water Company May 2026 Investor Presentation
# Slide 5:  Rate base $842M (2025, excl. CWIP); 12.0% CAGR since 2019
# Slide 7:  Capex plan $506M (2026-2028); $249M base + $257M PFAS/compliance
# Slide 8:  NJ GRC: auth rate base $643M, 9.6% ROE, 54.25% equity
#           DSIC surcharge $7.1M + RESIC surcharge $3.6M (2026-2028)
# Slide 10: DPS $1.38 (2025); 53 consecutive annual increases; 5.8% 5-yr CAGR
# Slide 11: Q1 2026 EPS $0.57 (+7.5% YoY); Q1 2026 revenue $48.7M (+9.9%)
# Slide 12: S&P A issuer rating / Stable; equity 54.0%; debt $426M
# Slide 9:  Tidewater (DE): 62,873 connections; 4.6% CAGR customer growth

MSEX_GUIDANCE = {
    # No formal annual EPS guidance range published in this IP (it shows Q1
    # 2026 actuals, not a FY guidance range). Q1 2026 EPS = $0.57/share.
    "eps_guidance": None,

    # No explicit LT EPS growth target stated; implied by 12% rate base CAGR
    # and constructive NJ/DE regulatory environment.
    "lt_eps_growth": None,

    # Rate base CAGR from slide 5 (2019-2025 historical; forward implied similar)
    "rate_base_cagr": "12.0% (2019–2025 historical; excl. CWIP)",

    # Capital plan from slide 7
    "capital_plan": "$506M planned 2026–2028 ($249M base construction + $257M PFAS & environmental compliance)",

    # No explicit FFO/debt guidance disclosed in this IP
    "ffo_debt_guidance": None,

    # Dividend from slide 10
    "dividend_guidance": "$1.38/share paid in 2025; 53 consecutive annual increases; 5.8% CAGR (2020–2025); Dividend King",

    # No specific equity/debt issuance plan disclosed beyond credit facility details
    "financing_plan": "S&P A / Stable; $180M aggregate credit facilities; 54% equity / 46% debt capital structure (March 2026)",

    # Key investment themes
    "key_themes": [
        "Rate base $842M (2025, excl. CWIP); 12.0% CAGR since 2019 — one of the highest in the water sector",
        "NJ consolidated GRC: $643M authorized rate base, 9.6% ROE, 54.25% equity; DSIC ($7.1M) + RESIC ($3.6M) surcharges 2026-2028",
        "PFAS compliance: $255M for Carl J. Olsen surface water treatment plant (largest single capex item); $74M already invested 2021–2025",
        "Tidewater (DE): 62,873 connections growing at 4.6% CAGR; Delaware provides ~25% of revenues",
        "53 consecutive years of dividend increases; Dividend King status; dividends paid since 1912",
        "Pinelands Water and Pinelands Wastewater merged into Middlesex effective April 1, 2026 — all three NJ utilities now under one consolidated rate base",
        "S&P A issuer rating / Stable outlook; strong balance sheet with 54% equity ratio"
    ]
}

def main():
    data = load()

    # Print schema of a reference entry to verify field alignment
    show_existing_schema(data)

    if "MSEX" in data:
        print(f"  Updating MSEX (existing entry found)")
    else:
        print(f"  Adding MSEX (new)")

    data["MSEX"] = MSEX_GUIDANCE
    save(data)

    # Verify
    entry = data["MSEX"]
    print("\n── MSEX Guidance Entry ───────────────────────────────────────────────")
    for k, v in entry.items():
        if k == "key_themes":
            print(f"  key_themes ({len(v)} items):")
            for t in v:
                print(f"    • {t[:85]}{'...' if len(t)>85 else ''}")
        else:
            val = str(v)[:80] if v else "null"
            print(f"  {k:<22} {val}")

    print(f"\n[✓] guidance_ip.json now has {len(data)} entries")
    print("\n⚠  Remember to git commit after verifying the Guidance tab renders correctly!")

if __name__ == "__main__":
    main()