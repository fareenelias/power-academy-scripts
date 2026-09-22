#!/usr/bin/env python3
r"""extract_infralogic_tx.py — Infralogic TRANSACTIONS exports -> transactions + portcos.

  data\infralogic\<N>__North_America_...xlsx
      -> data\infralogic_transactions.json  (merged transaction records)
      -> data\sponsor_portcos.json          (per tracked sponsor: current portfolio
                                             companies + live pipeline bids)

TWO EXPORT FORMATS, SAME TRANSACTIONS (verified 2026-08-25; the filename number is the
ROW count, not the transaction count):
  * LONG / participant format ('Stage'+'Organisation' columns): one header row per
    transaction followed by participant rows; Stage and SPV forward-fill within the
    block (a blank stage continues the consortium above).
  * WIDE / detail format ('Current Equity Providers' column): ONE row per transaction —
    description, grantors/vendors, equity at FC, CURRENT EQUITY PROVIDERS, EV,
    EV/EBITDA, leverage, DSCRs, loan tranches and capital-market debt.
The two are exported in pairs over the same screens and are MERGED BY TRANSACTION NAME.

Provider strings parse as 'Name(USD400.00m | 65%)' / 'Name(65%)' / bare 'Name'; a
trailing parenthetical WITHOUT a % or currency amount is part of the name itself
('Kohlberg Kravis Roberts (KKR)'). Comma-splitting re-joins fragments that start
lowercase — the same GIP-name-contains-a-comma trap as the funds export.

'%age' and parsed percentages are FRACTIONS (0.2 = 20%). Contributions stay in their
printed currency, never converted. Sponsor attribution imports the canon from
build_sponsor_universe (import, don't copy) + the fund-name map from
infralogic_funds.json + direct investors (NBIM).

Usage (PowerShell — one line):
  python E:\PowerAcademy\scripts\extract_infralogic_tx.py --src E:\PowerAcademy\data\infralogic --funds E:\PowerAcademy\data\infralogic_funds.json --out-tx E:\PowerAcademy\data\infralogic_transactions.json --out-portcos E:\PowerAcademy\data\sponsor_portcos.json
"""
import argparse, glob, json, os, re, sys, tempfile
from datetime import date

try:
    import pandas as pd
except ImportError:
    sys.exit("pandas is required")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from build_sponsor_universe import SPONSORS, GP_MAP, match_sponsors  # noqa: E402
except ImportError:
    sys.exit("build_sponsor_universe.py must sit in the same folder (imports its sponsor canon)")

EXTRA_SPONSORS = {
    "Norges Bank Investment Management (NBIM)": ["nbim", "norges"],
    "AustralianSuper": ["australiansuper", "australian super"],
    "LS Power Group": ["ls power"],
    "Hull Street Energy": ["hull street"],
    "Tenaska Capital Management (TCM)": ["tenaska capital", "tenaska power fund"],
    "Partners Group": ["partners group"],
    "IFM Investors": ["ifm investors", "ifm global", "ifm australian"],
    "Ares Management": ["ares management", "ares energy", "ares infrastructure", "ares climate",
                        "energy investors fund", "united states power fund"],
    "Blackstone Infrastructure": ["blackstone"],
    "Macquarie (MIRA/MIP)": ["macquarie"],
    "Global Infrastructure Partners (BlackRock)": ["global infrastructure partners", "gip"],
    "KKR": ["kohlberg kravis"],
    "Bernhard Capital Partners": ["delta utilities"],
}

CURRENT = "current equity"
PIPELINE_STAGES = {"preferred", "shortlisted", "expressions of interest",
                   "rfq returned", "rfp returned", "pre-qualified"}


def clean(v):
    if v is None or (isinstance(v, float) and v != v):
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


def money(v):
    """'USD 1300.00' -> ('USD', 1300.0); numbers pass through with no ccy."""
    v = clean(v)
    if v is None:
        return None, None
    if isinstance(v, (int, float)):
        return None, float(v)
    m = re.match(r"^([A-Z]{3})\s*([\d,]+(?:\.\d+)?)$", str(v))
    if m:
        return m.group(1), float(m.group(2).replace(",", ""))
    return None, None


def num(v):
    v = clean(v)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        m = re.search(r"-?[\d,]+(?:\.\d+)?", str(v))
        return float(m.group(0).replace(",", "")) if m else None


def split_list(v):
    v = clean(v)
    if not v:
        return None
    parts = [p.strip() for p in re.split(r"[;\n]+", str(v)) if p.strip()]
    return parts or None


def smart_split_commas(s):
    """Split on commas, re-joining fragments that start lowercase (a name like
    'Global Infrastructure Partners (GIP), a part of BlackRock' stays whole)."""
    parts = [p.strip() for p in str(s).split(",")]
    out = []
    for p in parts:
        if out and (not p or p[:1].islower()):
            out[-1] = (out[-1] + ", " + p).strip(", ")
        else:
            out.append(p)
    return [p for p in out if p]


def parse_providers(s):
    """'A(USD400.00m | 65%),B(30%),C' -> provider dicts. A trailing parenthetical
    with no % and no currency amount is part of the NAME ('...Roberts (KKR)')."""
    s = clean(s)
    if not s:
        return []
    out = []
    for m in smart_split_commas(s):
        name, ccy, amt, pct = m, None, None, None
        tail = re.search(r"\(([^()]*)\)\s*$", m)
        if tail:
            inner = tail.group(1)
            if "%" in inner or re.search(r"[A-Z]{3}\s*[\d,.]", inner):
                name = m[:tail.start()].strip()
                cm = re.search(r"([A-Z]{3})\s*([\d,.]+)", inner)
                if cm:
                    ccy, amt = cm.group(1), float(cm.group(2).replace(",", "").rstrip("."))
                pm = re.search(r"([\d.]+)\s*%", inner)
                if pm:
                    pct = round(float(pm.group(1)) / 100.0, 6)
        if name:
            out.append({"organisation": name, "contribution_m": amt,
                        "contribution_ccy": ccy, "pct_fraction": pct})
    return out


def build_org_map(funds_doc):
    exact = {}
    if funds_doc:
        for gp, funds in funds_doc.get("gps", {}).items():
            canon = GP_MAP.get(gp, gp)
            exact[gp.lower()] = canon
            for f in funds:
                exact[str(f["fund_name"]).lower()] = canon
    for raw, canon in GP_MAP.items():
        exact[raw.lower()] = canon

    def resolve(org):
        o = str(org or "").strip().lower()
        if not o:
            return None
        if o in exact:
            return exact[o]
        for canon, spec in SPONSORS.items():
            for p in spec["patterns"]:
                if re.search(r"(?<![a-z])" + re.escape(p) + r"(?![a-z])", o):
                    return canon
        for canon, pats in EXTRA_SPONSORS.items():
            for p in pats:
                if re.search(r"(?<![a-z])" + re.escape(p) + r"(?![a-z])", o):
                    return canon
        hits = match_sponsors(org)
        return hits[0] if hits else None
    return resolve


LONG_TX_FIELDS = {
    "Region": "region", "Geography": "geography", "States/provinces": "states",
    "Type": "tx_type", "PPP": "ppp", "Delivery Model": "delivery_model",
    "Commercial Operation Date": "cod", "Sector": "sector", "Sub-Sector": "subsector",
    "MW": "mw", "Status": "status", "Original currency": "currency",
}


def parse_long(df, fname):
    txs = {}
    cur, stage, spv = None, None, None
    for _, row in df.iterrows():
        name = clean(row.get("Transaction Name"))
        if name:
            _, usd = money(row.get("Transaction size USD(m)"))
            rec = {"name": name, "date": clean(row.get("Date")), "size_usd_m": usd,
                   "participants": [],
                   "financial_advisors": split_list(row.get("Financial Advisors")),
                   "legal_advisors": split_list(row.get("Legal Advisors")),
                   "technical_advisors": split_list(row.get("Technical Advisors")),
                   "_files": [fname]}
            for src, out in LONG_TX_FIELDS.items():
                rec[out] = clean(row.get(src))
            if name in txs:                       # same tx in both long exports
                txs[name]["_files"].append(fname)
                cur = txs[name]
            else:
                txs[name] = rec
                cur = rec
            stage, spv = None, None
            continue
        if cur is None:
            continue
        st = clean(row.get("Stage"))
        if st:
            stage = st
        sp = clean(row.get("SPV"))
        if sp:
            spv = sp
        org = clean(row.get("Organisation"))
        if not org:
            continue
        ccy, amt = money(row.get("Contribution (m)"))
        p = {"stage": stage, "spv": spv, "organisation": org,
             "contribution_m": amt, "contribution_ccy": ccy,
             "pct_fraction": num(row.get("%age")),
             "stage_date": clean(row.get("Date"))}
        if not any(q["organisation"] == org and q["stage"] == stage for q in cur["participants"]):
            cur["participants"].append(p)
    return txs


def tranches(row, kind):
    out = []
    for i in range(1, 14):
        if kind == "loan":
            t = clean(row.get(f"Loan Debt Tranche {i} Type"))
            if not t:
                continue
            out.append({"type": t, "debtclass": clean(row.get(f"Tranche {i} Debtclass")),
                        "volume_usd_m": num(row.get(f"Tranche {i} Volume USD (m)")),
                        "lenders": split_list(row.get(f"Tranche {i} Lenders")),
                        "tenor": clean(row.get(f"Tranche {i} Tenor")),
                        "margin": clean(row.get(f"Tranche {i} Margin and Benchmark"))})
        else:
            t = clean(row.get(f"Capital Market Debt {i} Type/Market"))
            if not t:
                continue
            sfx = "" if i == 1 else f".{i-1}"
            out.append({"market": t,
                        "bond_type": clean(row.get(f"Bond Type 2{sfx}" if i > 1 else "Bond Type 2")),
                        "volume_usd_m": num(row.get(f"Capital Market Debt {i} Volume USD (m)")),
                        "underwriters": split_list(row.get(f"Capital Market Debt {i} Underwriters")),
                        "coupon": clean(row.get(f"Coupon{sfx}")),
                        "spread": clean(row.get(f"Spread and Benchmark{sfx}")),
                        "pricing_date": clean(row.get(f"Pricing Date{sfx}")),
                        "maturity_date": clean(row.get(f"Maturity Date{sfx}")),
                        "rating": clean(row.get(f"Rating{sfx}"))})
    return out or None


def parse_wide(df, fname):
    out = {}
    for _, row in df.iterrows():
        name = clean(row.get("Transaction Name"))
        if not name:
            continue
        _, eqfc = money(row.get("Equity at FC USD(m)"))
        _, ev = money(row.get("EV"))
        d = {
            "description": clean(row.get("Description")),
            "transaction_type_detail": clean(row.get("Transaction Type")),
            "payment_mechanism": clean(row.get("Payment Mechanism")),
            "grantors": split_list(row.get("Grantors")),
            "vendors": split_list(row.get("Vendors")),
            "duration": clean(row.get("Duration")),
            "current_status": clean(row.get("Current status")),
            "current_status_date": clean(row.get("Current status date")),
            "financial_close_date": clean(row.get("Financial close")),
            "spv": clean(row.get("SPV")),
            "equity_at_fc_usd_m": eqfc,
            "equity_providers_at_fc": parse_providers(row.get("Equity Providers at FC")) or None,
            "current_equity_providers": parse_providers(row.get("Current Equity Providers")) or None,
            "ev_usd_m": ev if ev is not None else num(row.get("EV")),
            "ev_ebitda": num(row.get("EV/EBITDA")),
            "net_debt_ebitda": num(row.get("Net Debt/EBITDA")),
            "d_e_ratio": clean(row.get("D/E Ratio")),
            "total_loan_debt_usd_m": num(row.get("Total Loan Debt USD (m)")),
            "total_capital_market_usd_m": num(row.get("Total Capital Market Financing USD (m)")),
            "loan_tranches": tranches(row, "loan"),
            "capital_market_debt": tranches(row, "cmd"),
            "_file": fname,
        }
        out[name] = {k: v for k, v in d.items() if v is not None}
    return out


def atomic_write(path, obj):
    dirn = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=dirn, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--funds", default=None)
    ap.add_argument("--out-tx", required=True)
    ap.add_argument("--out-portcos", required=True)
    ap.add_argument("--as-of", default=None)
    args = ap.parse_args()

    if "infralogic" not in args.src.lower():
        sys.exit("REFUSED: --src must be the infralogic folder")
    if not re.match(r"infralogic_transactions.*\.json$", os.path.basename(args.out_tx)):
        sys.exit("REFUSED: --out-tx must be infralogic_transactions*.json")
    if not re.match(r"sponsor_portcos.*\.json$", os.path.basename(args.out_portcos)):
        sys.exit("REFUSED: --out-portcos must be sponsor_portcos*.json")

    files = sorted(f for f in glob.glob(os.path.join(args.src, "*.xlsx"))
                   if re.match(r"\d+__", os.path.basename(f)) and not os.path.basename(f).startswith("~$"))
    if not files:
        sys.exit(f"no <N>__*.xlsx transaction exports found in {args.src}")

    funds_doc = None
    if args.funds:
        with open(args.funds, encoding="utf-8") as f:
            funds_doc = json.load(f)
    resolve = build_org_map(funds_doc)
    asof = args.as_of or date.today().isoformat()

    long_txs, wide_txs = {}, {}
    n_long = n_wide = 0
    for fpath in files:
        fname = os.path.basename(fpath)[:24]
        try:
            df = pd.read_excel(fpath, sheet_name=0, engine="calamine", header=1)
        except ImportError:
            sys.exit("python-calamine is required: pip install python-calamine --break-system-packages")
        if "Organisation" in df.columns and "Stage" in df.columns:
            n_long += 1
            for k, v in parse_long(df, fname).items():
                if k in long_txs:
                    long_txs[k]["_files"] += v["_files"]
                    have = {(q["organisation"], q["stage"]) for q in long_txs[k]["participants"]}
                    long_txs[k]["participants"] += [q for q in v["participants"]
                                                   if (q["organisation"], q["stage"]) not in have]
                else:
                    long_txs[k] = v
        elif "Current Equity Providers" in df.columns:
            n_wide += 1
            wide_txs.update(parse_wide(df, fname))
        else:
            print(f"WARNING: {fname} matches neither format — skipped", file=sys.stderr)

    # merge wide detail onto long records; wide-only names become records too
    txs = []
    for name, rec in long_txs.items():
        if name in wide_txs:
            rec["detail"] = wide_txs.pop(name)
        txs.append(rec)
    for name, d in wide_txs.items():
        txs.append({"name": name, "date": d.get("current_status_date") or d.get("financial_close_date"),
                    "size_usd_m": None, "status": d.get("current_status"),
                    "participants": [], "detail": d, "_files": [d.get("_file")],
                    "_wide_only": True})
    unmatched_wide = sum(1 for t in txs if t.get("_wide_only"))

    for i, t in enumerate(sorted(txs, key=lambda x: x["name"])):
        slug = re.sub(r"[^a-z0-9]+", "_", t["name"].lower()).strip("_")[:60]
        t["id"] = f"{slug}__{i}"
    for t in txs:
        for p in t["participants"]:
            p["sponsor"] = resolve(p["organisation"])
        det = t.get("detail") or {}
        for key in ("equity_providers_at_fc", "current_equity_providers"):
            for p in det.get(key) or []:
                p["sponsor"] = resolve(p["organisation"])

    tx_out = {
        "_schema_version": "0.2", "_generated": asof,
        "_source": f"Infralogic transaction exports in data\\infralogic — {n_long} participant-format + {n_wide} detail-format files, merged by transaction name",
        "_units": "sizes/volumes in USD millions as exported; pct_fraction as printed or parsed (0.2 = 20%); contribution_m in its contribution_ccy, never converted",
        "_caveats": [
            "participant Stage forward-fills within a block, per the export's own layout",
            f"{unmatched_wide} detail-format transactions had no participant-format match and carry detail only",
            "sponsor attribution covers the tracked canon + fund map; 'sponsor: null' means unmapped, not independent",
        ],
        "transaction_count": len(txs),
        "transactions": sorted(txs, key=lambda x: x.get("date") or "", reverse=True),
    }

    # ---------------- portcos: union of long-format Current Equity rows and the
    # wide format's Current Equity Providers, per tracked sponsor
    sponsors = {}
    for t in txs:
        det = t.get("detail") or {}
        owners = {}
        for p in t["participants"]:
            if (p["stage"] or "").strip().lower() == CURRENT and p["sponsor"]:
                owners.setdefault(p["sponsor"], p)
        for p in det.get("current_equity_providers") or []:
            if p.get("sponsor"):
                owners.setdefault(p["sponsor"], p)
        all_current = sorted({p["organisation"] for p in t["participants"]
                              if (p["stage"] or "").strip().lower() == CURRENT}
                             | {p["organisation"] for p in det.get("current_equity_providers") or []})
        for s, p in owners.items():
            rec = sponsors.setdefault(s, {"portcos": [], "pipeline": []})
            rec["portcos"].append({
                "asset": t["name"], "tx_id": t["id"], "tx_date": t.get("date"),
                "tx_type": t.get("tx_type"), "status": t.get("status") or det.get("current_status"),
                "sector": t.get("sector"), "subsector": t.get("subsector"),
                "geography": t.get("geography"), "states": t.get("states"), "mw": t.get("mw"),
                "tx_size_usd_m": t.get("size_usd_m"),
                "ev_usd_m": det.get("ev_usd_m"), "ev_ebitda": det.get("ev_ebitda"),
                "net_debt_ebitda": det.get("net_debt_ebitda"),
                "financial_close_date": det.get("financial_close_date"),
                "via_org": p["organisation"],
                "pct_fraction": p.get("pct_fraction"),
                "contribution_m": p.get("contribution_m"), "contribution_ccy": p.get("contribution_ccy"),
                "co_owners": [o for o in all_current if o != p["organisation"]] or None,
                "description": (det.get("description") or "")[:280] or None,
            })
        for p in t["participants"]:
            st = (p["stage"] or "").strip().lower()
            if p["sponsor"] and st in PIPELINE_STAGES and \
               str(t.get("status") or det.get("current_status") or "").lower() not in ("financial close", "cancelled"):
                sponsors.setdefault(p["sponsor"], {"portcos": [], "pipeline": []})["pipeline"].append({
                    "asset": t["name"], "tx_id": t["id"], "stage": p["stage"],
                    "tx_date": t.get("date"), "status": t.get("status"),
                    "sector": t.get("sector"), "subsector": t.get("subsector"),
                    "geography": t.get("geography"), "tx_size_usd_m": t.get("size_usd_m"),
                    "via_org": p["organisation"],
                })

    for s, rec in sponsors.items():
        by_asset = {}
        for row in sorted(rec["portcos"], key=lambda r: r["tx_date"] or ""):
            by_asset.setdefault(row["asset"], []).append(row)
        final = []
        for asset, rows in by_asset.items():
            keep = rows[-1]
            if len(rows) > 1:
                keep["other_transactions"] = [r["tx_id"] for r in rows[:-1]]
            final.append(keep)
        rec["portcos"] = sorted(final, key=lambda r: r["tx_date"] or "", reverse=True)
        rec["pipeline"] = sorted(rec["pipeline"], key=lambda r: r["tx_date"] or "", reverse=True)
        rec["portco_count"] = len(rec["portcos"])
        rec["pipeline_count"] = len(rec["pipeline"])

    pc_out = {
        "_schema_version": "0.2", "_generated": asof,
        "_source": "derived from infralogic_transactions.json — union of participant-format "
                   "'Current Equity' rows and detail-format 'Current Equity Providers'",
        "_units": tx_out["_units"],
        "_caveats": [
            "a portco appears only if the exported transactions show current equity — this is "
            "the exports' view, not the sponsor's full portfolio",
            "the same underlying asset can appear under differently-worded transaction names; "
            "only exact-name repeats are collapsed (latest kept, rest in other_transactions)",
            "pipeline = pre-close bid stages on transactions not at Financial Close",
        ],
        "sponsor_count": len(sponsors),
        "sponsors": dict(sorted(sponsors.items())),
    }

    atomic_write(args.out_tx, tx_out)
    atomic_write(args.out_portcos, pc_out)

    print(f"transactions: {len(txs)} ({n_long} long + {n_wide} wide files; {unmatched_wide} wide-only) -> {args.out_tx}")
    print(f"portco sponsors: {len(sponsors)} -> {args.out_portcos}")
    for s in sorted(sponsors, key=lambda k: -sponsors[k]["portco_count"])[:14]:
        r = sponsors[s]
        print(f"   {s:46s} portcos={r['portco_count']:3d} pipeline={r['pipeline_count']}")


if __name__ == "__main__":
    main()
