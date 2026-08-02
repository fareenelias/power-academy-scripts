r"""
fetch_pudl_ferc.py — pull FERC Form 1 financials for the Power Academy coverage
opcos from PUDL (Catalyst Cooperative) instead of downloading filings one by one.

HOW MATCHING WORKS (v3)
  PUDL's pre-2021 (DBF) and 2021+ (XBRL) filings can sit under DIFFERENT
  respondent ids, with name strings that differ in case/punctuation or are
  null. So each coverage alias is resolved by NORMALIZED-NAME substring across
  all three tables, then closed over ids<->names (any name a matched id
  carries, any id a matched name carries), and era-split respondents are
  merged into one record. Extraction filters on the union (id OR exact name).

USAGE (VPN OFF)
  python fetch_pudl_ferc.py                 # download + show match table
  python fetch_pudl_ferc.py --explore      # dump candidate row labels
  python fetch_pudl_ferc.py --build        # write ferc_opco.json
  Needs:  python -m pip install pandas pyarrow requests

On HE-fixture failure the build auto-prints per-field year availability for
the HE respondents (built-in diagnosis) and writes nothing.

SCOPE NOTES
  - FERC Form 1 = major ELECTRIC utilities only; gas LDCs live in
    ferc_gas_ldc.json (state PUC data via CapIQ). Combination utilities report
    TOTAL COMPANY financials on Form 1 (earned ROE includes gas ops).
  - Stacked ownership handled via standalone columns (HECO->HELCO/MECO;
    Evergy Kansas South under Kansas Central).
  - Westar Generating excluded (generating sub, not a rate-base utility).

VALIDATION FIXTURE (from the CapIQ FERCFin tie-out, $000, FY2023):
  HECO NI 195,031 / prop cap 2,431,402 / pref 22,293
  HELCO NI 29,042 / prop cap 366,791 / pref 7,000
  MECO NI 16,681 / prop cap 367,342 / pref 5,000
"""
import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

PUDL_S3 = "https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop"
S3_PREFIX = "stable/"
DATA_DIR = r"E:\PowerAcademy\data\pudl"
OUT_JSON = r"E:\PowerAcademy\data\ferc_opco.json"

TABLE_HINTS = {
    "income":    {"hints": ["ferc1", "income_statement"], "prefer": "sched114"},
    "liab":      {"hints": ["ferc1", "balance_sheet", "liabilit"], "prefer": "sched110"},
    "assets":    {"hints": ["ferc1", "balance_sheet", "asset"], "prefer": "sched110"},
}

COVERAGE_OPCOS = {
    "NEE":  ["Florida Power & Light"],
    "D":    ["Virginia Electric and Power", "South Carolina Electric"],
    "ETR":  ["Entergy Arkansas", "Entergy Louisiana", "Entergy Mississippi",
             "Entergy New Orleans", "Entergy Texas"],
    "CMS":  ["Consumers Energy"],
    "PPL":  ["PPL Electric", "Louisville Gas and Electric", "Kentucky Utilities",
             "Narragansett"],
    "AEE":  ["Union Electric", "Ameren Illinois", "Ameren Transmission"],
    "POR":  ["Portland General Electric"],
    "EIX":  ["Southern California Edison"],
    "PCG":  ["Pacific Gas and Electric"],
    "HE":   ["Hawaiian Electric", "Hawaii Electric Light", "Maui Electric"],
    "EVRG": ["Westar", "Evergy Kansas Central",
             "Evergy Kansas South",
             "Kansas City Power", "Evergy Metro",
             "Greater Missouri", "Evergy Missouri West"],
    "ES":   ["Connecticut Light and Power", "NSTAR Electric",
             "Public Service Company of New Hampshire"],
}

EXCLUDE_FILERS = ["Westar Generating"]

ROW_MAP = {
    "net_income":            {"table": "income", "candidates": ["net_income_loss", "net_income"], "kw": "income"},
    "equity_in_sub_earnings":{"table": "income", "candidates": ["equity_in_earnings_of_subsidiary_companies"], "kw": "subsidiary"},
    "proprietary_capital":   {"table": "liab",   "candidates": ["proprietary_capital", "total_proprietary_capital"], "kw": "proprietary"},
    "preferred_stock":       {"table": "liab",   "candidates": ["preferred_stock_issued"], "kw": "preferred"},
    "investment_in_subs":    {"table": "assets", "candidates": ["investment_in_subsidiary_companies"], "kw": "subsidiary"},
}

FIXTURE = {
    "hawaiianelectric":    {"net_income": 195031, "proprietary_capital": 2431402, "preferred_stock": 22293},
    "hawaiielectriclight": {"net_income": 29042, "proprietary_capital": 366791, "preferred_stock": 7000},
    "mauielectric":        {"net_income": 16681, "proprietary_capital": 367342, "preferred_stock": 5000},
}

# ── QC guards (post-build) ───────────────────────────────────────────────────
# A "stacked" intermediate holdco (e.g. Evergy Kansas Central owns Evergy Kansas
# South) carries a large investment_in_subs, so the standalone strip
# (common_equity - investment_in_subs) leaves a tiny residual and the earned ROE
# blows out to 20-30%. Above this ratio we treat the filer on an AS-REPORTED
# basis (standalone := as-reported) and suppress the wholly-owned sub's earned
# value to avoid double-counting in the ticker rollup. Auto-detects on every run
# so a fresh PUDL pull can't reintroduce the blow-out.
STACKED_INV_RATIO = 0.25   # investment_in_subs / common_equity above this = intermediate holdco
STACKED_SUB_MATCH = 0.10   # fallback only: sibling common_equity within this of the parent's inv = the sub

# Authoritative parent->sub roll-ups (normalized-name substrings). The equity-match
# heuristic below is a logged fallback for novel cases; this map is preferred because
# a loose band can grab a same-size SIBLING (e.g. Evergy Metro sits under Evergy Inc,
# not under Kansas Central). Add entries here as stacked structures are confirmed.
ROLLED_UP_SUBS = {
    "EVRG": ["evergykansassouth"],   # Evergy Kansas South is wholly owned by Evergy Kansas Central (Westar)
}

# Analyst one-time-item annotations (Form 1 can't derive these — real values, but
# not run-rate). Keyed by a normalized-name substring -> {year: note}. Re-applied
# on every build so the flags survive a re-pull. Edit here when new one-timers land.
ONE_TIME_FLAGS = {
    "entergyneworleans": {
        "2023": "One-time-item spike (NI 4x normal; Ida securitization/tax). Not run-rate; normalized ~8-9%.",
        "2024": "Depressed vs trend after the 2023 one-time item. Not run-rate.",
    },
    "entergylouisiana": {
        "2020": "Single-year NI spike ($691M->$1,082M; TCJA/storm regulatory items). Elevated vs run-rate.",
    },
    "narragansett": {
        "2022": "PPL closed the Rhode Island (Narragansett) acquisition May 2022 -> transition/partial year "
                "(purchase accounting + deal costs). Not a clean operating ROE.",
    },
}


def apply_stacked_guard(out):
    """Switch stacked-holdco filers to as-reported basis; suppress rolled-up subs."""
    for ticker, recs in out["opcos"].items():
        for parent in recs:
            yrs = sorted(parent["years"])
            if not yrs:
                continue
            ly = parent["years"][yrs[-1]]
            ce, inv = ly.get("common_equity_k") or 0, ly.get("investment_in_subs_k") or 0
            if not ce or inv / ce <= STACKED_INV_RATIO:
                continue
            # rewrite parent to as-reported basis (standalone := as-reported)
            prev = None
            for y in yrs:
                r = parent["years"][y]
                r["ni_standalone_k"] = r["net_income_k"]
                r["common_equity_standalone_k"] = r["common_equity_k"]
                r.pop("earned_roe_pct", None)
                if prev is not None and r["net_income_k"] is not None:
                    avg = (r["common_equity_k"] + prev) / 2
                    if avg:
                        r["earned_roe_pct"] = round(r["net_income_k"] / avg * 100, 2)
                prev = r["common_equity_k"]
            parent["_basis"] = "as_reported_combined"
            parent["_combined_dagger"] = True
            parent["_qc_note"] = ("Stacked intermediate holdco (investment_in_subs/common_equity "
                                  f"= {inv/ce:.0%}). Standalone strip invalid; ROE + equity weight on "
                                  "as-reported basis, incl. rolled-up sub(s).")

            def suppress(sub):
                for r in sub["years"].values():
                    if isinstance(r.get("earned_roe_pct"), (int, float)):
                        r["earned_roe_pct_rolled"] = r.pop("earned_roe_pct")
                sub["_earned_suppressed"] = True
                sub["_roll_up"] = f'{ticker}:{parent["ferc_name"]}'
                sub["_qc_note"] = ("Wholly owned by the stacked parent above; equity/earnings inside "
                                   "its as-reported ROE. earned_roe_pct suppressed to avoid double-counting.")

            explicit = ROLLED_UP_SUBS.get(ticker)
            if explicit:
                # authoritative: suppress exactly the named subs
                for sub in recs:
                    if sub is parent or not sub["years"]:
                        continue
                    if any(name in norm(sub["ferc_name"]) for name in explicit):
                        suppress(sub)
                        print(f"  [guard] {ticker}: '{parent['ferc_name']}' stacked holdco "
                              f"({inv/ce:.0%}) -> as-reported; rolled up '{sub['ferc_name']}' (mapped)")
            else:
                # fallback: single closest sibling within the tight band (logged, so it's never silent)
                cand = None
                for sub in recs:
                    if sub is parent or not sub["years"]:
                        continue
                    sy = sorted(sub["years"])[-1]
                    sub_ce = sub["years"][sy].get("common_equity_k") or 0
                    if not sub_ce:
                        continue
                    diff = abs(sub_ce - inv) / inv
                    if diff <= STACKED_SUB_MATCH and (cand is None or diff < cand[1]):
                        cand = (sub, diff)
                if cand:
                    suppress(cand[0])
                    print(f"  [guard] {ticker}: '{parent['ferc_name']}' stacked holdco ({inv/ce:.0%}) "
                          f"-> as-reported; rolled up '{cand[0]['ferc_name']}' (heuristic, {cand[1]:.0%} eq match "
                          f"— add to ROLLED_UP_SUBS to make authoritative)")
                else:
                    print(f"  [guard] {ticker}: '{parent['ferc_name']}' stacked holdco ({inv/ce:.0%}) "
                          f"-> as-reported; NO sub matched — verify manually if inv covers multiple subs")


def apply_annotations(out):
    """Re-apply analyst one-time-item flags (survive a fresh PUDL pull)."""
    for recs in out["opcos"].values():
        for rec in recs:
            nn = norm(rec["ferc_name"])
            for key, yrmap in ONE_TIME_FLAGS.items():
                if key in nn:
                    for y, txt in yrmap.items():
                        if y in rec["years"]:
                            rec["years"][y]["_flag"] = txt


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def list_bucket(prefix):
    import requests
    keys, token = [], None
    while True:
        params = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if token:
            params["continuation-token"] = token
        r = requests.get(PUDL_S3, params=params, timeout=60)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        ns = {"s3": root.tag.split("}")[0].strip("{")}
        for c in root.findall("s3:Contents", ns):
            keys.append(c.find("s3:Key", ns).text)
        trunc = root.find("s3:IsTruncated", ns)
        if trunc is not None and trunc.text == "true":
            token = root.find("s3:NextContinuationToken", ns).text
        else:
            return keys


def pick_table_keys(keys):
    picked = {}
    for name, spec in TABLE_HINTS.items():
        hints, prefer = spec["hints"], spec.get("prefer")
        cands = [k for k in keys if k.endswith(".parquet") and all(h in k for h in hints)]
        outs = [k for k in cands if "out_" in k]
        pool = outs or cands
        if not pool:
            print(f"[ERR] no bucket key matches hints {hints}.")
            for k in [k for k in keys if "ferc1" in k][:40]:
                print("       ", k)
            sys.exit(1)
        preferred = [k for k in pool if prefer and prefer in k]
        pool = preferred or pool
        pool.sort(key=len)
        picked[name] = pool[0]
        print(f"[i] {name}: using '{pool[0]}'")
    return picked


def download(key):
    import requests
    os.makedirs(DATA_DIR, exist_ok=True)
    dest = os.path.join(DATA_DIR, os.path.basename(key))
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        print(f"[skip] {os.path.basename(dest)} already present")
        return dest
    url = f"{PUDL_S3}/{key}"
    print(f"[dl] {url}")
    try:
        import requests
        with requests.get(url, stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
    except Exception as e:
        print(f"[ERR] download failed ({e}). Download manually into {DATA_DIR}:")
        print(f"      {url}")
        sys.exit(1)
    print(f"      -> {dest} ({os.path.getsize(dest)/1e6:.0f} MB)")
    return dest


def load(path):
    import pandas as pd
    df = pd.read_parquet(path)
    nc = name_col(df)
    if nc:
        df["_normname"] = df[nc].map(lambda v: norm(v) if v is not None else "")
    return df


def name_col(df):
    for c in df.columns:
        if "utility_name" in c:
            return c
    return None


def id_col(df):
    for c in df.columns:
        if c == "utility_id_ferc1" or c.endswith("utility_id_ferc1"):
            return c
    return None


def discover_groups(dfs):
    """Per ticker: alias -> closure of (ids, exact names) across all tables,
    then merge overlapping alias groups. Returns list of group dicts."""
    excl = [norm(x) for x in EXCLUDE_FILERS]
    # gather (id, name, normname, year) universe across tables
    universe = []
    for tname, df in dfs.items():
        ic, nc = id_col(df), name_col(df)
        if not ic or not nc:
            continue
        cols = [ic, nc, "_normname"] + (["report_year"] if "report_year" in df.columns else [])
        sub = df[cols].drop_duplicates()
        for r in sub.itertuples(index=False):
            uid, nm, nn = r[0], r[1], r[2]
            yr = r[3] if len(r) > 3 else None
            universe.append((uid, nm, nn, yr))
    # index
    ids_by_norm = {}
    norms_by_id = {}
    for uid, nm, nn, yr in universe:
        if nn:
            ids_by_norm.setdefault(nn, set()).add(uid)
        norms_by_id.setdefault(uid, set()).add(nn)
    groups = []
    for tkr, pats in COVERAGE_OPCOS.items():
        alias_groups = []
        for pat in pats:
            np_ = norm(pat)
            ids, names = set(), set()
            for nn, uids in ids_by_norm.items():
                if np_ in nn and not any(x in nn for x in excl):
                    ids |= uids
                    names.add(nn)
            # closure: ids -> all their norm names; names -> all their ids
            changed = True
            while changed:
                changed = False
                for uid in list(ids):
                    for nn in norms_by_id.get(uid, ()):  # nn may be '' for null names
                        if nn and nn not in names and not any(x in nn for x in excl):
                            names.add(nn); changed = True
                for nn in list(names):
                    for uid in ids_by_norm.get(nn, ()):
                        if uid not in ids:
                            ids.add(uid); changed = True
            alias_groups.append({"ticker": tkr, "aliases": [pat], "ids": ids, "normnames": names})
        # merge overlapping groups within ticker
        merged = []
        for g in alias_groups:
            hit = None
            for m in merged:
                if (g["ids"] & m["ids"]) or (g["normnames"] & m["normnames"]):
                    hit = m
                    break
            if hit:
                hit["aliases"] += g["aliases"]
                hit["ids"] |= g["ids"]
                hit["normnames"] |= g["normnames"]
            else:
                merged.append(g)
        groups += merged
    # canonical display name = name at max report_year among group's rows
    for g in groups:
        best = (-1, None)
        for uid, nm, nn, yr in universe:
            if (uid in g["ids"] or (nn and nn in g["normnames"])) and nm:
                y = int(yr) if yr is not None and str(yr).isdigit() or isinstance(yr, (int, float)) else -1
                try:
                    y = int(yr) if yr is not None else -1
                except (TypeError, ValueError):
                    y = -1
                if y >= best[0]:
                    best = (y, str(nm))
        g["canonical"] = best[1] or (g["aliases"][0] if g["aliases"] else "?")
        g["display_names"] = sorted({str(nm) for uid, nm, nn, yr in universe
                                     if nm and (uid in g["ids"] or (nn and nn in g["normnames"]))})
    return groups


def print_groups(groups):
    print(f"\n{'TKR':5} {'aliases':44} {'ids':16} respondent (canonical)")
    print("-" * 112)
    matched_aliases = set()
    for g in groups:
        if not g["ids"] and not g["normnames"]:
            continue
        ali = ", ".join(g["aliases"])[:44]
        ids = ",".join(str(i) for i in sorted(g["ids"], key=lambda x: str(x)))[:16]
        extra = f"  [{len(g['display_names'])} name variants]" if len(g["display_names"]) > 1 else ""
        print(f"{g['ticker']:5} {ali:44} {ids:16} {g['canonical']}{extra}")
        matched_aliases |= set(g["aliases"])
    misses = [(t, p) for t, pats in COVERAGE_OPCOS.items() for p in pats if p not in matched_aliases]
    for t, p in misses:
        print(f"{t:5} {p:44} {'—':16} *** NO MATCH ***")
    if misses:
        print(f"\n[!] {len(misses)} aliases matched nothing (fine if another alias covers the same respondent).")


def type_cols(df):
    return [c for c in df.columns if c.endswith("_type")]


def value_col(df, tcol):
    import pandas as pd
    pref = ["ending_balance", "income", "amount", "value", "balance"]
    for c in pref:
        if c in df.columns and pd.api.types.is_numeric_dtype(df[c]):
            return c
    num = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])
           and c not in ("report_year",) and not c.endswith("_id_ferc1")
           and not c.endswith("_id")]
    return num[-1] if num else None


def resolve_row(df, spec, field):
    tcols = type_cols(df)
    if not tcols:
        print(f"[ERR] {field}: no *_type column; columns = {list(df.columns)[:15]}")
        sys.exit(1)
    for tcol in tcols:
        labels = set(df[tcol].dropna().unique())
        for cand in spec["candidates"]:
            if cand in labels:
                return tcol, cand
    print(f"[ERR] {field}: none of {spec['candidates']} found in any *_type column.")
    for tcol in tcols:
        near = sorted(l for l in df[tcol].dropna().unique() if spec["kw"] in str(l))[:20]
        print(f"      {tcol}: labels containing '{spec['kw']}': {near or '(none)'}")
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--explore", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--skip-fixture", action="store_true",
                    help="write output even if the HE fixture fails (use only after "
                         "auto-diag confirms PUDL lacks the HE rows; HE then comes "
                         "from the manual CapIQ pulls instead)")
    ap.add_argument("--years", default="2019-2024")
    args = ap.parse_args()

    print("[1/4] listing PUDL bucket...")
    keys = list_bucket(S3_PREFIX)
    if not keys:
        print(f"[!] nothing under '{S3_PREFIX}'; bucket roots:",
              sorted({k.split('/')[0] for k in list_bucket('')}))
        sys.exit(1)
    tables = pick_table_keys(keys)

    print("[2/4] downloading tables (skips existing)...")
    paths = {n: download(k) for n, k in tables.items()}

    print("[3/4] loading + matching (normalized names + id closure across eras)...")
    dfs = {n: load(p) for n, p in paths.items()}
    groups = discover_groups(dfs)
    print_groups(groups)

    if args.explore:
        print("\n[explore] candidate row labels per field:")
        for field, spec in ROW_MAP.items():
            df = dfs[spec["table"]]
            for tcol in type_cols(df):
                near = sorted(l for l in df[tcol].dropna().unique() if spec["kw"] in str(l))
                print(f"\n  {field} (table={spec['table']}, column={tcol}):")
                for l in near:
                    print("    ", l)
        return

    if not args.build:
        print("\nMatch table above. Run --build to write ferc_opco.json.")
        return

    print("[4/4] building ferc_opco.json...")
    y0, y1 = (int(x) for x in args.years.split("-"))
    resolved = {f: resolve_row(dfs[s["table"]], s, f) for f, s in ROW_MAP.items()}

    def series(df, tcol, label, g, vcol):
        ic = id_col(df)
        mask = (df[tcol] == label)
        idmask = df[ic].isin(g["ids"]) if ic else False
        nmask = df["_normname"].isin(g["normnames"]) if "_normname" in df.columns else False
        sub = df[mask & (idmask | nmask)]
        if "report_year" not in sub.columns:
            return {}
        sub = sub[(sub.report_year >= y0) & (sub.report_year <= y1)]
        out_ = {}
        for r in sub.itertuples():
            v = getattr(r, vcol)
            if isinstance(v, (int, float)) and v == v:
                y = int(r.report_year)
                if y in out_ and abs(out_[y] - float(v)) > 0.5:
                    print(f"      [!] duplicate year {y} for {g['canonical']} / {label}: "
                          f"{out_[y]:,.0f} vs {float(v):,.0f} — keeping first")
                    continue
                out_[y] = float(v)
        return out_

    out = {"_unit": "$000 (converted from PUDL dollars)",
           "_source": "FERC Form 1 via PUDL (pudl.catalyst.coop); era-split respondents merged by name+id closure",
           "opcos": {}}
    fixture_results = []
    group_vals = []
    for g in groups:
        if not g["ids"] and not g["normnames"]:
            continue
        rec = {"ticker": g["ticker"], "ferc_name": g["canonical"],
               "utility_ids_ferc1": sorted(int(i) if str(i).isdigit() else str(i) for i in g["ids"]),
               "years": {}}
        if len(g["display_names"]) > 1:
            rec["name_variants"] = g["display_names"]
        vals = {}
        for field, (tcol, label) in resolved.items():
            df = dfs[ROW_MAP[field]["table"]]
            vc = value_col(df, tcol)
            vals[field] = series(df, tcol, label, g, vc)
        group_vals.append((g, vals))
        yrs = sorted(set().union(*[set(v) for v in vals.values()]))
        prev_eq = None
        for y in yrs:
            k = lambda f: vals[f].get(y)
            ni, pc, pf = k("net_income"), k("proprietary_capital"), k("preferred_stock")
            eis, inv = k("equity_in_sub_earnings") or 0.0, k("investment_in_subs") or 0.0
            if pc is None:
                continue
            common = pc - (pf or 0.0)
            ni_sa = (ni - eis) if ni is not None else None
            common_sa = common - inv
            row = {"net_income_k": round(ni/1000, 1) if ni is not None else None,
                   "common_equity_k": round(common/1000, 1),
                   "equity_in_sub_earnings_k": round(eis/1000, 1) if eis else 0,
                   "investment_in_subs_k": round(inv/1000, 1) if inv else 0,
                   "ni_standalone_k": round(ni_sa/1000, 1) if ni_sa is not None else None,
                   "common_equity_standalone_k": round(common_sa/1000, 1)}
            if prev_eq is not None and ni_sa is not None:
                avg = (common_sa + prev_eq) / 2
                if avg:
                    row["earned_roe_pct"] = round(ni_sa / avg * 100, 2)
            prev_eq = common_sa
            rec["years"][str(y)] = row
        if rec["years"]:
            out["opcos"].setdefault(g["ticker"], []).append(rec)
        for fx_key, fx in FIXTURE.items():
            if any(fx_key in nn for nn in g["normnames"]):
                for f, expect in fx.items():
                    got = vals[f].get(2023)
                    ok = got is not None and abs(got/1000 - expect) <= max(2, expect*0.001)
                    fixture_results.append((g["canonical"], f, expect,
                                            None if got is None else round(got/1000), ok))

    bad = 0
    if fixture_results:
        print("\nHE fixture cross-check (FY2023, $000, vs CapIQ FERCFin tie-out):")
        for util, f, exp, got, ok in fixture_results:
            print(f"  {'PASS' if ok else 'FAIL':4} {util[:28]:28} {f:22} expect {exp:>10,} got {got if got is not None else '—':>10}")
            bad += (not ok)
    else:
        print("[!] HE respondents not found — fixture not checked.")
        bad = 1

    if bad and args.skip_fixture:
        print(f"\n[!] fixture failed but --skip-fixture set — writing output anyway.")
        print("    HE records may be incomplete; HE earned ROE comes from the manual")
        print("    CapIQ FERCFin pulls (already tied out) rather than this file.")
        bad = 0
    if bad:
        print("\n[auto-diag] HE group availability (year: value in $000):")
        for g, vals in group_vals:
            if g["ticker"] != "HE":
                continue
            print(f"  {g['canonical']}  ids={sorted(str(i) for i in g['ids'])}  "
                  f"variants={g['display_names']}")
            for f, ser in vals.items():
                pretty = {y: round(v/1000) for y, v in sorted(ser.items())}
                print(f"      {f}: {pretty or 'NO ROWS in years window'}")
        print(f"\n[ERR] fixture failed — NOT writing {OUT_JSON}.")
        print("      If the auto-diag shows years ending pre-2021, PUDL's sched tables lack")
        print("      the HE XBRL-era rows: pull HE manually (already have the CapIQ FERCFin")
        print("      set) and rerun with --skip-fixture once we confirm the rest.")
        sys.exit(1)

    apply_stacked_guard(out)
    apply_annotations(out)
    out["_qc"] = {
        "guards": "stacked-holdco -> as-reported (auto-detected); rolled-up subs suppressed; "
                  "analyst one-time-item flags re-applied",
        "checks": "standalone-derivation + avg-equity ROE formula are internally consistent by construction",
    }

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    n = sum(len(v) for v in out["opcos"].values())
    print(f"\n[OK] wrote {OUT_JSON}: {n} opcos across {len(out['opcos'])} tickers.")


if __name__ == "__main__":
    main()