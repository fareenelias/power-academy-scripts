#!/usr/bin/env python3
"""extract_infralogic.py — Infralogic Funds-Export workbooks -> two JSONs.

  data\infralogic\*Infralogic-Funds-Export*.xlsx
      -> data\infralogic_funds.json   (GP -> funds: vintage, status, size, IRR,
                                       deployed, funded/unfunded, NAV)
      -> data\infralogic_assets.json  (asset -> owner legs: fund, GP, entry/exit,
                                       direct/indirect, equity share, live bids)

The export is one row per FUND x INVESTMENT, so the same fund repeats — fund-level
values verified identical across a fund's rows before collapsing (the script aborts
if they ever disagree).

Dependencies: pandas + python-calamine.
  ⚠️ openpyxl CANNOT read these files — Infralogic writes the literal string 'NaN'
  into numeric cells and openpyxl's number cast raises ValueError. Install:
      pip install python-calamine --break-system-packages

Rules honoured:
  * record what the export states: Equity Percentage is stored as the export prints
    it (a FRACTION — 0.175 means 17.5%) under `equity_share_fraction`. IRR fields
    likewise fractions. Nothing is rescaled.
  * routing guards: --src must contain 'infralogic'; outputs must be
    infralogic_*.json. Never touches the coverage JSONs.
  * atomic writes; provenance (_files, per-row source file) carried.

Usage:
  python extract_infralogic.py --src E:\\PowerAcademy\\data\\infralogic ^
      --out-funds E:\\PowerAcademy\\data\\infralogic_funds.json ^
      --out-assets E:\\PowerAcademy\\data\\infralogic_assets.json
"""
import argparse, glob, json, os, re, sys, tempfile
from datetime import date

try:
    import pandas as pd
except ImportError:
    sys.exit("pandas is required")

FUND_FIELDS = {
    "Fund Geography": "fund_geography",
    "Fund Description": "description",
    "Type": "fund_type",
    "Structure": "structure",
    "Listing": "listing",
    "Vintage": "vintage",
    "Fund Length": "fund_length",
    "Fund Currency": "currency",
    "Fund Status": "fund_status",
    "Status Date": "status_date",
    "Asset Class": "asset_class",
    "Current Direct Investments": "current_direct_investments",
    "Current Indirect Investments": "current_indirect_investments",
    "Realised Direct Investments": "realised_direct_investments",
    "Realised Indirect Investments": "realised_indirect_investments",
    "Live Bids": "live_bids_count",
    "Fundraising Status": "fundraising_status",
    "Final Close Date": "final_close_date",
    "First Announced Date": "first_announced_date",
    "Hard Cap (USD m)": "hard_cap_usd_m",
    "Current Size (USD m)": "current_size_usd_m",
    "Target Size (USD m)": "target_size_usd_m",
    "Target IRR": "target_irr_fraction",
    "Achieved Net IRR": "achieved_net_irr_fraction",
    "Net IRR since inception (%)": "net_irr_inception_fraction",
    "Gross IRR since inception (%)": "gross_irr_inception_fraction",
    "Asset Geography": "asset_geography",
    "Geographic Focus": "geographic_focus",
    "Sector": "sector",
    "Sector Focus": "sector_focus",
    "Deployed": "deployed_ratio",
    "Total Distributed (USD m)": "total_distributed_usd_m",
    "Funded (USD m)": "funded_usd_m",
    "Unfunded (USD m)": "unfunded_usd_m",
    "NAV (USD m)": "nav_usd_m",
    "Fair Value (USD m)": "fair_value_usd_m",
    "Investment Period": "investment_period",
}

INV_FIELDS = {
    "Type.1": "type",                       # direct / indirect
    "Status": "status_raw",                 # current / realised / Live Bid - ...
    "Initial Investment Date": "entry_date",
    "Live Bid Status Date": "live_bid_status_date",
    "Realisation Date": "realisation_date",
    "Investment Region": "region",
    "Investment Country": "country",
    "Investment Sector": "sector",
    "Investment Subsector": "subsector",
    "Equity Volume (USD m)": "equity_usd_m",
    "Equity Percentage (%)": "equity_share_fraction",  # printed as a fraction
    "Commitment (USD m)": "commitment_usd_m",
}


def clean(v):
    if v is None:
        return None
    if isinstance(v, float) and (v != v):  # NaN
        return None
    if isinstance(v, str):
        v = v.strip()
        return None if v in ("", "NaN", "-") else v
    if hasattr(v, "isoformat"):
        try:
            return v.date().isoformat() if hasattr(v, "date") else v.isoformat()
        except Exception:
            return str(v)
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def status_bucket(raw):
    r = (raw or "").lower()
    if r.startswith("live bid"):
        return "live_bid"
    if r in ("current", "realised"):
        return r
    return "other"


def atomic_write(path, obj):
    dirn = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=dirn, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out-funds", required=True)
    ap.add_argument("--out-assets", required=True)
    ap.add_argument("--as-of", default=None)
    args = ap.parse_args()

    if "infralogic" not in args.src.lower():
        sys.exit("REFUSED: --src must be the infralogic folder")
    for p in (args.out_funds, args.out_assets):
        if not re.match(r"infralogic_.*\.json$", os.path.basename(p)):
            sys.exit(f"REFUSED: output must be infralogic_*.json, got {os.path.basename(p)}")

    files = sorted(f for f in glob.glob(os.path.join(args.src, "*.xlsx"))
                   if "infralogic-funds-export" in os.path.basename(f).lower()
                   and not os.path.basename(f).startswith("~$"))
    if not files:
        sys.exit(f"no *Infralogic-Funds-Export*.xlsx found in {args.src}")

    frames = []
    for f in files:
        try:
            df = pd.read_excel(f, sheet_name="Funds", engine="calamine")
        except ImportError:
            sys.exit("python-calamine is required (openpyxl fails on Infralogic's literal-'NaN' "
                     "cells): pip install python-calamine --break-system-packages")
        df["_file"] = os.path.basename(f)
        frames.append(df)
    a = pd.concat(frames, ignore_index=True)
    a = a[a["Fund Name"].notna()]

    # ---- consistency gate: a fund's fund-level values must not vary across its rows
    check_cols = [c for c in FUND_FIELDS if c in a.columns]
    varies = a.groupby(["GP Name", "Fund Name"])[check_cols].nunique(dropna=True)
    bad = varies[(varies > 1).any(axis=1)]
    if len(bad):
        sys.exit(f"ABORT: fund-level values vary across rows for {len(bad)} fund(s): "
                 f"{list(bad.index)[:5]} — the one-row-per-investment assumption is broken")

    asof = args.as_of or date.today().isoformat()

    # ---------------- funds file
    gps = {}
    for (gp, fund), grp in a.groupby(["GP Name", "Fund Name"], sort=True):
        row = grp.iloc[0]
        rec = {"fund_name": fund}
        rec.update({out: clean(row.get(src)) for src, out in FUND_FIELDS.items()})
        rec["investments_in_export"] = int(grp["Investments"].notna().sum())
        rec["_files"] = sorted(grp["_file"].unique())
        gps.setdefault(gp, []).append(rec)
    for gp in gps:
        gps[gp].sort(key=lambda r: (r["vintage"] or 0), reverse=True)

    funds_out = {
        "_schema_version": "0.1",
        "_generated": asof,
        "_source": f"Infralogic Funds-Export workbooks in data\\infralogic ({len(files)} files)",
        "_units": "all *_usd_m fields are USD millions as exported; *_fraction fields are "
                  "printed as fractions (0.14 = 14%) and NOT rescaled; deployed_ratio can "
                  "exceed 1.0 (capital recycling)",
        "_caveats": [
            "coverage is the GPs Fareen exported, not the sponsor universe",
            "Funded/Unfunded present on only a subset of funds — a missing unfunded figure "
            "is absence of disclosure, not zero dry powder",
            "fund-level values verified identical across each fund's rows before collapsing",
        ],
        "gp_count": len(gps),
        "fund_count": sum(len(v) for v in gps.values()),
        "gps": gps,
    }

    # ---------------- assets file
    assets = {}
    inv = a[a["Investments"].notna()]
    for _, row in inv.iterrows():
        name = str(row["Investments"]).strip()
        asset = assets.setdefault(name, {
            "name": name,
            "region": clean(row.get("Investment Region")),
            "country": clean(row.get("Investment Country")),
            "sector": clean(row.get("Investment Sector")),
            "subsector": clean(row.get("Investment Subsector")),
            "owners": [],
        })
        leg = {"gp": row["GP Name"], "fund": row["Fund Name"]}
        leg.update({out: clean(row.get(src)) for src, out in INV_FIELDS.items()
                    if out not in ("region", "country", "sector", "subsector")})
        leg["status"] = status_bucket(leg.get("status_raw"))
        leg["_file"] = row["_file"]
        # dedupe identical legs across export files
        if not any(o["gp"] == leg["gp"] and o["fund"] == leg["fund"] for o in asset["owners"]):
            asset["owners"].append(leg)

    for asset in assets.values():
        asset["owner_count"] = len(asset["owners"])
        asset["cross_gp"] = len({o["gp"] for o in asset["owners"]}) > 1
        st = {o["status"] for o in asset["owners"]}
        asset["any_current"] = "current" in st
        asset["any_live_bid"] = "live_bid" in st

    assets_out = {
        "_schema_version": "0.1",
        "_generated": asof,
        "_source": funds_out["_source"],
        "_units": "equity_share_fraction as printed (0.175 = 17.5%); equity_usd_m / "
                  "commitment_usd_m in USD millions",
        "_caveats": [
            "an asset appears only if one of the exported GPs' funds holds or held it — "
            "this is not the asset's full cap table",
            "asset names are Infralogic deal-style labels (e.g. 'Duquesne Light Company "
            "25.1% Stake...'), so the same underlying company can appear under multiple "
            "labels across different transactions — match on substrings, not equality",
        ],
        "asset_count": len(assets),
        "owner_leg_count": sum(x["owner_count"] for x in assets.values()),
        "assets": dict(sorted(assets.items())),
    }

    atomic_write(args.out_funds, funds_out)
    atomic_write(args.out_assets, assets_out)

    print(f"funds:  {funds_out['fund_count']} across {funds_out['gp_count']} GPs -> {args.out_funds}")
    print(f"assets: {assets_out['asset_count']} ({assets_out['owner_leg_count']} owner legs) -> {args.out_assets}")
    lb = [(x['name'], o['gp']) for x in assets.values() for o in x['owners'] if o['status'] == 'live_bid']
    print(f"live bids: {len(lb)}")
    for n, g in lb:
        print(f"   {g}: {n}")


if __name__ == "__main__":
    main()
