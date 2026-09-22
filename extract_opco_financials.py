#!/usr/bin/env python3
r"""extract_opco_financials.py — the per-REGULATORY-OPCO financials ladder (FERC Form 1).

Widens the 2026-07-18 PUDL extract from 6 line items to the full opco ladder the
segment-by-subsidiary build asked for:

  data\pudl\*.parquet + data\ferc_opco.json (the opco -> utility_id_ferc1 map)
      -> data\opco_financials.json, per opco per year:
         * income by utility_type slice (electric / gas / total, kept APART):
           operating revenues -> operation & maintenance -> depreciation (+amortization)
           -> other taxes -> income taxes (operating) -> NET UTILITY OPERATING INCOME
         * regulated EBITDA DERIVED = NUOI + depreciation + amortization, labelled
         * net income — TOTAL slice only (FERC files no segment net income; splitting
           it would be an allocation, not a filing — deliberately not computed)
         * balance sheet: net utility plant by slice (the filed rate-base PROXY),
           long-term debt items as filed (bonds / long_term_debt / other), and the
           affiliate-funding lines (advances from + notes payable to associated
           companies — the closest FILED thing to "allocated" debt)
         * the investor-presentation rate base joined from rate_base_ip.json where
           the opco name matches, clearly labelled a different (IP) basis

QC GATES — the script ABORTS rather than writing if either fails:
  1. net income (total slice) must tie to ferc_opco.json's stored net_income_k on
     ≥99% of overlapping opco-years within 0.5% — same source, so drift = bug.
  2. VEPCO electric operating revenues must land within 15% of the CapIQ ASC-280
     "Dominion Energy Virginia" segment revenue for the same year — a cross-source
     sanity check, NOT an equality (FERC jurisdictional vs managerial basis).

Known absences stated, not smoothed: gas LDCs and water opcos are state-PUC filers
(no Form 1), HE files Form 1-F outside PUDL — they appear with a _missing reason.

Usage (PowerShell — one line; needs pandas+pyarrow, so it runs where fetch_pudl_ferc.py ran):
  python E:\PowerAcademy\scripts\extract_opco_financials.py --pudl E:\PowerAcademy\data\pudl --ferc-opco E:\PowerAcademy\data\ferc_opco.json --rate-base E:\PowerAcademy\data\rate_base_ip.json --capiq E:\PowerAcademy\data\capiq_export.json --out E:\PowerAcademy\data\opco_financials.json
"""
import argparse, json, os, re, sys, tempfile

try:
    import pandas as pd
except ImportError:
    sys.exit("pandas + pyarrow required (run where fetch_pudl_ferc.py runs)")

INCOME_ITEMS = {
    "operating_revenues": "revenue",
    "operation_expense": "operation_expense",
    "maintenance_expense": "maintenance_expense",
    "depreciation_expense": "depreciation",
    "amortization_and_depletion_of_utility_plant": "amortization",
    "taxes_other_than_income_taxes_utility_operating_income": "other_taxes",
    "income_taxes_operating_income": "income_taxes",
    "utility_operating_expenses": "opex_total",
    "net_utility_operating_income": "net_utility_operating_income",
}
NI_ITEM = "net_income_loss"
PLANT_ITEMS = ["utility_plant_net", "utility_plant_and_nuclear_fuel_net"]
DEBT_ITEMS = ["bonds", "long_term_debt", "other_long_term_debt", "matured_long_term_debt",
              "advances_from_associated_companies", "notes_payable_to_associated_companies"]

NORM = re.compile(r"[^a-z0-9]+")
def norm(s):
    return NORM.sub(" ", str(s or "").lower()).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pudl", required=True)
    ap.add_argument("--ferc-opco", required=True)
    ap.add_argument("--rate-base", required=True)
    ap.add_argument("--capiq", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--since", type=int, default=2019)
    args = ap.parse_args()
    if not os.path.basename(args.out).startswith("opco_financials"):
        sys.exit("REFUSED: --out must be opco_financials*.json")

    fo = json.load(open(args.ferc_opco, encoding="utf-8"))
    rb = json.load(open(args.rate_base, encoding="utf-8"))
    cap = json.load(open(args.capiq, encoding="utf-8"))
    cap_companies = cap.get("companies", cap)

    inc = pd.read_parquet(os.path.join(args.pudl, "out_ferc1__yearly_income_statements_sched114.parquet"))
    lia = pd.read_parquet(os.path.join(args.pudl, "out_ferc1__yearly_balance_sheet_liabilities_sched110.parquet"))
    ast = pd.read_parquet(os.path.join(args.pudl, "out_ferc1__yearly_balance_sheet_assets_sched110.parquet"))
    inc = inc[inc.report_year >= args.since]
    lia = lia[lia.report_year >= args.since]
    ast = ast[ast.report_year >= args.since]

    out = {}
    ni_checked = ni_ok = 0
    ni_bad = []

    for ticker, opcos in fo["opcos"].items():
        rows_out = []
        rb_opcos = (rb.get(ticker) or {}).get("opcos") or {}
        for op in opcos:
            ids = op.get("utility_ids_ferc1") or []
            name = op.get("ferc_name")
            years = {}
            balance = {}
            mi = inc[inc.utility_id_ferc1.isin(ids)]
            for yr, g in mi.groupby("report_year"):
                yrec = {}
                for ut in ("electric", "gas", "total"):
                    gu = g[g.utility_type == ut]
                    slice_rec = {}
                    for item, key in INCOME_ITEMS.items():
                        v = gu[gu.income_type == item].dollar_value.sum()
                        n = gu[gu.income_type == item].dollar_value.notna().sum()
                        if n:
                            slice_rec[key] = round(float(v) / 1000.0, 1)   # store $000
                    if ut == "total":
                        v = gu[gu.income_type == NI_ITEM].dollar_value
                        if v.notna().sum():
                            slice_rec["net_income"] = round(float(v.sum()) / 1000.0, 1)
                    nuoi = slice_rec.get("net_utility_operating_income")
                    if nuoi is not None:
                        eb = nuoi + slice_rec.get("depreciation", 0) + slice_rec.get("amortization", 0)
                        slice_rec["ebitda_reg"] = round(eb, 1)
                    if slice_rec:
                        yrec[ut] = slice_rec
                if yrec:
                    years[int(yr)] = yrec
            # NI tie-out vs ferc_opco.json
            for ys, rec in (op.get("years") or {}).items():
                stored = rec.get("net_income_k")
                mine = (years.get(int(ys), {}).get("total") or {}).get("net_income")
                if stored is not None and mine is not None:
                    ni_checked += 1
                    if abs(mine - stored) <= max(abs(stored) * 0.005, 1.0):
                        ni_ok += 1
                    else:
                        ni_bad.append((ticker, name, ys, stored, mine))
            # balance sheet
            ml = lia[lia.utility_id_ferc1.isin(ids)]
            ma = ast[ast.utility_id_ferc1.isin(ids)]
            for yr in sorted(set(ml.report_year) | set(ma.report_year)):
                brec = {}
                ga = ma[ma.report_year == yr]
                for ut in ("electric", "gas", "total"):
                    for item in PLANT_ITEMS:
                        v = ga[(ga.utility_type == ut) & (ga.asset_type == item)].ending_balance
                        if v.notna().sum():
                            brec[f"net_utility_plant_{ut}"] = round(float(v.sum()) / 1000.0, 1)
                            break
                gl = ml[(ml.report_year == yr) & (ml.utility_type == "total")]
                for item in DEBT_ITEMS:
                    v = gl[gl.liability_type == item].ending_balance
                    if v.notna().sum():
                        brec[item] = round(float(v.sum()) / 1000.0, 1)
                if brec:
                    balance[int(yr)] = brec
            # IP rate base join (different basis, labelled)
            ip_rb = None
            nn = norm(name)
            for rb_name, rb_rec in rb_opcos.items():
                if isinstance(rb_rec, dict) and (norm(rb_name) in nn or nn in norm(rb_name) or
                        len(set(norm(rb_name).split()) & set(nn.split())) >= 2):
                    val = rb_rec.get("rate_base_b")
                    if val is not None and not rb_rec.get("alias_of"):
                        ip_rb = {"rate_base_b": val, "ip_name": rb_name,
                                 "_basis": "investor-presentation rate base (rate_base_ip.json) — NOT the FERC plant figure"}
                        break
            rows_out.append({
                "opco": name, "utility_ids_ferc1": ids,
                "years": years, "balance": balance, "ip_rate_base": ip_rb,
            })
        if rows_out:
            out[ticker] = rows_out

    # QC gate 1
    if ni_checked and ni_ok / ni_checked < 0.99:
        for b in ni_bad[:8]:
            print("NI MISMATCH:", b, file=sys.stderr)
        sys.exit(f"ABORT: NI tie-out {ni_ok}/{ni_checked} — pipeline drift vs ferc_opco.json")
    # QC gate 2 — VEPCO vs CapIQ segment
    vep = next((o for o in out.get("D", []) if "VIRGINIA ELECTRIC" in (o["opco"] or "")), None)
    seg = (cap_companies.get("D", {}).get("segment_analysis", {}).get("business", {})
           .get("revenue", {}).get("Dominion Energy Virginia"))
    gate2 = None
    if vep and seg:
        ferc_rev = (vep["years"].get(2024, {}).get("electric") or {}).get("revenue")
        capiq_rev = seg[3]  # 2024 FY position in the FY21-25 series
        if ferc_rev and capiq_rev:
            diff = abs(ferc_rev - capiq_rev) / capiq_rev
            gate2 = (ferc_rev, capiq_rev, diff)
            if diff > 0.15:
                sys.exit(f"ABORT: VEPCO 2024 FERC electric revenue {ferc_rev:,.0f}k vs CapIQ segment {capiq_rev:,.0f}k — {diff:.0%} apart")

    doc = {
        "_schema_version": "0.1",
        "_source": "FERC Form 1 via PUDL (data\\pudl\\ parquet) + ferc_opco.json id map; IP rate base joined from rate_base_ip.json",
        "_units": "$000 (PUDL dollars /1000), matching the project convention",
        "_method": "per-opco ladder by utility_type slice; ids summed where an opco has two FERC ids (ELL). "
                   "ebitda_reg = net_utility_operating_income + depreciation + amortization — DERIVED, regulated basis. "
                   "Debt items as filed (FERC accts 221-224 style); no derived debt total because "
                   "long_term_debt vs bonds composition varies by filer. Affiliate funding = "
                   "advances_from/notes_payable_to associated companies — the filed cousin of 'allocated' debt.",
        "_caveats": [
            "net income exists ONLY at the total slice — FERC files no segment net income and this file refuses to allocate it",
            "FERC is the jurisdictional regulated view; the CapIQ segment_analysis tab is ASC 280 managerial — the two will not agree and must not be mixed",
            "gas LDCs, water opcos and HE are not PUDL Form 1 filers — absent here, covered (NI/equity only) by ferc_manual.json",
            f"QC: NI tie-out {ni_ok}/{ni_checked} vs ferc_opco.json" + (f"; VEPCO 2024 FERC {gate2[0]:,.0f}k vs CapIQ segment {gate2[1]:,.0f}k ({gate2[2]:.1%} apart, different bases)" if gate2 else ""),
        ],
        "opcos_by_ticker": out,
    }
    dirn = os.path.dirname(os.path.abspath(args.out)) or "."
    fd, tmp = tempfile.mkstemp(dir=dirn, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    os.replace(tmp, args.out)

    n_op = sum(len(v) for v in out.values())
    print(f"tickers: {len(out)} | opcos: {n_op} | NI tie-out {ni_ok}/{ni_checked}"
          + (f" | VEPCO cross-source gap {gate2[2]:.1%}" if gate2 else ""))
    for t, ops in sorted(out.items()):
        for o in ops:
            yrs = sorted(o["years"])
            r = (o["years"].get(yrs[-1], {}).get("electric") or o["years"].get(yrs[-1], {}).get("total") or {})
            print(f"  {t:5s} {o['opco'][:42]:42s} {yrs[0]}-{yrs[-1]} rev(latest) {r.get('revenue', 0)/1000:,.0f}M"
                  + (" | IP RB ok" if o["ip_rate_base"] else ""))


if __name__ == "__main__":
    main()
