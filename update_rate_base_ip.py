"""
update_rate_base_ip.py  —  July 5 2026
Adds / updates rate base entries for gap companies from Q4 2025 IPs:
  HE, ES, EVRG, CWT, AWR, GWRS, WTRG, HTO, MSEX
  YORW: no IP published — null entry (falls back to FERC NUP in panel)
Run on Fareen's machine:
    python update_rate_base_ip.py
"""

import json, os

DATA_FILE = r"E:\PowerAcademy\data\rate_base_ip.json"
SOURCE    = "Q4 2025 Earnings Presentation"

# ---------- helpers -----------------------------------------------------------
def load():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}

def save(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[✓] Saved {DATA_FILE}")

def opco(rate_base_b, label, roe=None, equity_pct=None):
    return {
        "rate_base_b":  rate_base_b,
        "label":        label,
        "roe":          roe,
        "equity_pct":   equity_pct
    }

def entry(consolidated_b, label, opcos):
    return {
        "consolidated_b": consolidated_b,
        "source":         SOURCE,
        "label":          label,
        "opcos":          opcos
    }

# ---------- new / updated entries ---------------------------------------------
UPDATES = {

    # ── HE ────────────────────────────────────────────────────────────────────
    # Hawaiian Electric Q4 2025 IP (Feb 27 2026)
    # IP does not disclose a $ rate base figure — regulated under PBR framework.
    # Allowed ROE 9.5% per PBR order (slide 18). Will fall back to FERC NUP.
    "HE": entry(
        consolidated_b = None,
        label          = "No $ disclosed — PBR framework; allowed ROE = 9.5%",
        opcos = {
            "Hawaiian Electric (HI)": opco(
                rate_base_b = None,
                label       = "PBR – no rate base disclosed",
                roe         = 9.5,
                equity_pct  = None
            )
        }
    ),

    # ── ES ────────────────────────────────────────────────────────────────────
    # Eversource Energy Q4 2025 IP (Feb 13 2026) — slide 21
    # ~$35B estimated 2025 rate base (consolidated, excl. ~$2.5B CWIP).
    # Transmission rate base by opco from slide 24 (2025A).
    # Per-opco total rate base not provided; transmission only shown.
    # Segment mix 2024A (slide 13): Transmission 36%, Elec Distrib 44%, Gas 20%.
    # ROEs: PSNH 9.50% (slide 14), Yankee Gas 9.32% (slide 14).
    "ES": entry(
        consolidated_b = 35.0,
        label          = "~2025E (per IP slide 21; excl. CWIP)",
        opcos = {
            "CL&P Transmission (CT)": opco(
                rate_base_b = 4.592,
                label       = "2025A Transmission",
                roe         = None,
                equity_pct  = None
            ),
            "NSTAR Electric Transmission (MA)": opco(
                rate_base_b = 4.668,
                label       = "2025A Transmission",
                roe         = None,
                equity_pct  = None
            ),
            "PSNH Transmission (NH)": opco(
                rate_base_b = 2.312,
                label       = "2025A Transmission",
                roe         = 9.5,
                equity_pct  = None
            ),
            "Yankee Gas (CT Gas)": opco(
                rate_base_b = None,
                label       = "ROE only — no $ disclosed",
                roe         = 9.32,
                equity_pct  = None
            )
        }
    ),

    # ── EVRG ──────────────────────────────────────────────────────────────────
    # Evergy Q4 2025 IP (Feb 19 2026) — slide 25
    # 2025E total: $20.7B; KS 51%, MO 32%, FERC 17%.
    # Subsidiaries: Evergy Kansas Central, Evergy Kansas South,
    #               Evergy Metro (KS+MO), Evergy Missouri West.
    "EVRG": entry(
        consolidated_b = 20.7,
        label          = "2025E (per IP slide 25)",
        opcos = {
            "Kansas (KS Central + KS South + Metro KS)": opco(
                rate_base_b = round(20.7 * 0.51, 2),   # ~$10.56B
                label       = "51% jurisdictional share (2025E)",
                roe         = None,
                equity_pct  = None
            ),
            "Missouri (Metro MO + MO West)": opco(
                rate_base_b = round(20.7 * 0.32, 2),   # ~$6.62B
                label       = "32% jurisdictional share (2025E)",
                roe         = None,
                equity_pct  = None
            ),
            "FERC Transmission": opco(
                rate_base_b = round(20.7 * 0.17, 2),   # ~$3.52B
                label       = "17% jurisdictional share (2025E)",
                roe         = None,
                equity_pct  = None
            )
        }
    ),

    # ── CWT ───────────────────────────────────────────────────────────────────
    # California Water Service Group Q4 2025 IP (Feb 26 2026) — slide 11
    # 2025 rate base: $2.64B; estimated >$3.3B by 2027; CAGR 11.7%.
    # Authorized ROE: 10.27% (retained via WCCM through Jan 2028).
    # Operates in CA (primary), WA, NM, HI, TX; expanding to NV + OR.
    "CWT": entry(
        consolidated_b = 2.64,
        label          = "2025 (per IP slide 11)",
        opcos = {
            "California Water Service (CA)": opco(
                rate_base_b = 2.64,
                label       = "2025; expanding to >$3.3B by 2027",
                roe         = 10.27,
                equity_pct  = None
            )
        }
    ),

    # ── AWR ───────────────────────────────────────────────────────────────────
    # American States Water Company Q4 2025 IP (Feb 19 2026) — slide 17
    # GSWC (Golden State Water Co): Adopted Avg Rate Base 2025 = $1,456.2M
    # (CAGR 11.3%; 2026E $1,673.2M).  WACC = 7.93%.
    # BVES (Bear Valley Electric Service): small electric utility; no $ rate
    # base given; requested ROE 11.30%, equity 60%, WACC 9.15% (slide 19).
    "AWR": entry(
        consolidated_b = 1.456,
        label          = "2025 Adopted Avg (GSWC); BVES electric not broken out",
        opcos = {
            "Golden State Water Company (CA Water)": opco(
                rate_base_b = 1.456,
                label       = "2025 Adopted Avg (2026E: $1.673B)",
                roe         = None,      # WACC authorized, not ROE
                equity_pct  = None
            ),
            "Bear Valley Electric Service (CA Elec)": opco(
                rate_base_b = None,
                label       = "No $ disclosed; req ROE 11.30%, 60% equity",
                roe         = 11.30,
                equity_pct  = 60.0
            )
        }
    ),

    # ── GWRS ──────────────────────────────────────────────────────────────────
    # Global Water Resources Q4 2025 (Mar 5 2026) — earnings call transcript
    # No specific rate base $ disclosed. Small AZ water/WW utility.
    # Revenue $55.8M, Adj EBITDA $26.5M. $70M rate baseable assets into
    # service in 2025. Rate case pending at ACC for Santa Cruz + Palo Verde.
    "GWRS": entry(
        consolidated_b = None,
        label          = "No $ disclosed — rate case pending at ACC",
        opcos = {
            "Global Water Resources (AZ)": opco(
                rate_base_b = None,
                label       = "No $ disclosed; ~$70M added to service in 2025",
                roe         = None,
                equity_pct  = None
            )
        }
    ),

    # ── WTRG ──────────────────────────────────────────────────────────────────
    # Essential Utilities Q4 2025 IP (Feb 26 2026) — slide 26
    # Detailed by state and segment (Water/Wastewater + Gas Distribution).
    # All figures as of Dec 31, 2025.
    "WTRG": entry(
        consolidated_b = round((7806 + 4635) / 1000, 3),   # $12.441B
        label          = "YE 2025 (per IP slide 26)",
        opcos = {
            "Aqua PA (PA Water/WW)": opco(
                rate_base_b = 4.850,
                label       = "YE 2025",
                roe         = None,
                equity_pct  = None
            ),
            "Peoples Natural Gas (PA Gas)": opco(
                rate_base_b = 4.454,
                label       = "YE 2025",
                roe         = None,
                equity_pct  = None
            ),
            "Aqua TX (TX Water/WW)": opco(
                rate_base_b = 0.694,
                label       = "YE 2025",
                roe         = None,
                equity_pct  = None
            ),
            "Aqua OH (OH Water/WW)": opco(
                rate_base_b = 0.585,
                label       = "YE 2025",
                roe         = None,
                equity_pct  = None
            ),
            "Aqua NC (NC Water/WW)": opco(
                rate_base_b = 0.464,
                label       = "YE 2025",
                roe         = None,
                equity_pct  = None
            ),
            "Aqua IL (IL Water/WW)": opco(
                rate_base_b = 0.609,
                label       = "YE 2025",
                roe         = None,
                equity_pct  = None
            ),
            "Aqua NJ (NJ Water/WW)": opco(
                rate_base_b = 0.332,
                label       = "YE 2025",
                roe         = None,
                equity_pct  = None
            ),
            "Peoples KY Gas (KY Gas)": opco(
                rate_base_b = 0.181,
                label       = "YE 2025",
                roe         = None,
                equity_pct  = None
            ),
            "Aqua VA (VA Water/WW)": opco(
                rate_base_b = 0.146,
                label       = "YE 2025",
                roe         = None,
                equity_pct  = None
            ),
            "Aqua IN (IN Water/WW)": opco(
                rate_base_b = 0.126,
                label       = "YE 2025",
                roe         = None,
                equity_pct  = None
            ),
        }
    ),

    # ── HTO ───────────────────────────────────────────────────────────────────
    # H2O America (SJW Group) Q4 2025 IP (Feb 26 2026) — slide 30
    # Per-state rate base + authorized ROE + capital structure.
    # "Estimated rate base at year-end" (incl. NUP not yet in rate base).
    # Rate base CAGR 13% → 2030E ~$5.1B.
    "HTO": entry(
        consolidated_b = round((1461 + 878 + 204 + 212) / 1000, 3),  # $2.755B
        label          = "YE 2025 Est (per IP slide 30)",
        opcos = {
            "San Jose Water (CA)": opco(
                rate_base_b = 1.461,
                label       = "YE 2025 Est (Auth $1,308M)",
                roe         = 9.81,
                equity_pct  = 55.0
            ),
            "Connecticut Water (CT)": opco(
                rate_base_b = 0.878,
                label       = "YE 2025 Est (Auth $784M)",
                roe         = 9.30,
                equity_pct  = 53.0
            ),
            "Maine Water (ME)": opco(
                rate_base_b = 0.204,
                label       = "YE 2025 Est (Auth $149M)",
                roe         = 9.50,
                equity_pct  = 51.0
            ),
            "Texas Water (TX)": opco(
                rate_base_b = 0.212,
                label       = "YE 2025 Est (Auth $96M est.)",
                roe         = 10.88,
                equity_pct  = 58.0
            )
        }
    ),

    # ── MSEX ──────────────────────────────────────────────────────────────────
    # Middlesex Water Company May 2026 Investor Presentation
    # Slide 5: Rate base (excl. CWIP) $842M in 2025; 12.0% CAGR 2019-2025.
    # Slide 8: NJ GRC — Auth rate base $643M, ROE 9.6%, equity 54.25%.
    # Slide 3: Tidewater (DE) = 25% revenues; implied ~$199M rate base.
    # Slide 12: Capital structure March 2026: 54.0% equity; S&P A/Stable.
    # Subsidiaries: Middlesex Water (NJ), Tidewater Utilities (DE + subs).
    # Note: Pinelands Water/Wastewater merged into Middlesex April 1 2026.
    "MSEX": entry(
        consolidated_b = 0.842,
        label          = "2025 (excl. CWIP, per IP slide 5)",
        opcos = {
            "Middlesex Water (NJ)": opco(
                rate_base_b = 0.643,
                label       = "Authorized (GRC; incl. Pinelands from Apr 2026)",
                roe         = 9.6,
                equity_pct  = 54.25
            ),
            "Tidewater Utilities (DE)": opco(
                rate_base_b = round((842 - 643) / 1000, 3),  # ~$0.199B implied
                label       = "Implied ($842M consolidated – $643M NJ auth)",
                roe         = None,
                equity_pct  = None
            )
        }
    ),

    # ── YORW ──────────────────────────────────────────────────────────────────
    # York Water Company — does not publish standalone investor presentations.
    # Rate base will be sourced from rate case filings or FERC NUP.
    # Most recent PA PUC rate case: docket R-2023-3047672 (rates eff. Jan 2024).
    "YORW": entry(
        consolidated_b = None,
        label          = "No IP published — falls back to rate case / FERC NUP",
        opcos = {
            "York Water Company (PA)": opco(
                rate_base_b = None,
                label       = "No IP; use rate case or FERC NUP",
                roe         = None,
                equity_pct  = None
            )
        }
    ),
}

# ---------- main --------------------------------------------------------------
def main():
    data = load()
    print(f"Loaded {len(data)} existing tickers from {DATA_FILE}")

    for ticker, new_entry in UPDATES.items():
        if ticker in data:
            print(f"  Updating {ticker} (was: consolidated_b={data[ticker].get('consolidated_b')})")
        else:
            print(f"  Adding   {ticker} (new)")
        data[ticker] = new_entry

    save(data)

    # Print summary
    print("\n── Rate Base Summary ─────────────────────────────────────────────")
    for ticker in sorted(data.keys()):
        cb = data[ticker].get("consolidated_b")
        n_opcos = len(data[ticker].get("opcos", {}))
        label = data[ticker].get("label", "")[:55]
        cb_str = f"${cb:6.2f}B" if cb is not None else "   N/A  "
        print(f"  {ticker:<6} {cb_str}  {n_opcos} opco(s)  {label}")

    print(f"\nTotal tickers in file: {len(data)}")
    print("\n⚠  Remember to git commit after verifying the panel renders correctly!")

if __name__ == "__main__":
    main()