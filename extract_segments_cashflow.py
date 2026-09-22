#!/usr/bin/env python3
r"""extract_segments_cashflow.py — the two unextracted CapIQ workbook sheets (roadmap I.A).

  data\reports\*.xlsx  (Segment Analysis + Cash Flow Statement sheets)
      -> merged into data\capiq_export.json per company as:
         `segment_analysis`  — per-segment revenue / operating income / assets / D&A /
                               capex etc., FY series, business + geographic blocks,
                               with EBITDA-by-segment DERIVED (= OI + D&A) and labelled
         `cash_flow`         — the full CF ladder verbatim + a canonical block (cfo,
                               capex, dividends, debt/equity flows) + DERIVED fcf and
                               fcf_post_dividends with the derivation spelled out

Rules honoured (the assemble.py lessons are law here):
  * MERGE-ONLY, atomic write, and a before/after key audit: the script refuses to
    finish if any pre-existing key on any company changed or vanished — it may only
    ADD `segment_analysis` / `cash_flow` (or replace those two).
  * record what the sheet prints: values stay in thousands as printed, 'NA' -> null,
    segment names verbatim. Every derived number carries `basis: 'derived'` + formula.
  * a company whose sheet prints "not currently available" gets an explicit _missing
    reason, never a silent absence.
  * legacy `segments` blocks (raw sheet dumps) are left untouched — deprecated, not
    clobbered.

Usage (PowerShell — one line):
  python E:\PowerAcademy\scripts\extract_segments_cashflow.py --reports E:\PowerAcademy\data\reports --capiq E:\PowerAcademy\data\capiq_export.json --write
Without --write: parses and prints per-ticker coverage, touches nothing.
"""
import argparse, copy, glob, json, os, re, sys, tempfile

try:
    import openpyxl
except ImportError:
    sys.exit("openpyxl is required")

TICKER_RE = re.compile(r"(?:NYSE|NASDAQGS|NASDAQGM|NASDAQCM|TSX)([A-Z]+)_Report", re.I)

SEG_SECTIONS = {  # printed section label prefix -> canonical key
    "Total Revenue": "revenue",
    "Operating Income": "operating_income",
    "EBT": "ebt",
    "Net Income": "net_income",
    "Total Assets": "assets",
    "Depreciation & Amort": "d_and_a",
    "Capital Expenditure": "capex",
    "Interest Expense": "interest_expense",
    "Income Tax": "income_tax",
    "EBITDA": "ebitda_printed",
    "Gross Profit": "gross_profit",
}
SEG_SKIP_ROWS = {"period ended", "reported currency code", "current/restated"}

CF_CANON = {  # canonical key -> printed label prefixes, tried in order
    "cfo": ["Cash from Ops"],
    "cfi": ["Cash from Investing"],
    "cff": ["Cash from Financing"],
    "capex": ["Capital Expenditure"],
    "dividends_common": ["Common Dividends Paid"],
    "dividends_total": ["Total Dividends Paid"],
    "dividends_pref": ["Pref. Dividends Paid", "Preferred Dividends Paid"],
    "debt_issued": ["Total Debt Issued"],
    "debt_repaid": ["Total Debt Repaid"],
    "equity_issued": ["Issuance of Common Stock"],
    "buybacks": ["Repurchase of Common Stock"],
    "net_change_in_cash": ["Net Change in Cash"],
    "net_income_cf": ["Net Income - CF", "Net Income"],
    "d_and_a_total": ["Depreciation & Amort., Total", "Depreciation & Amort."],
    "asset_sales": ["Sale of Property, Plant"],
    "acquisitions": ["Cash Acquisitions", "Acquisitions"],
}


def clean(v):
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        if s in ("", "NA", "-", "NM"):
            return None
        try:
            return float(s.replace(",", ""))
        except ValueError:
            return s
    if isinstance(v, (int, float)):
        return float(v)
    return None


def label_of(row):
    for c in row[:2]:
        if isinstance(c, str) and c.strip():
            return c.strip()
    return None


def series_of(row, cols):
    return [clean(row[i]) if i < len(row) else None for i in cols]


def find_grid(ws):
    """Locate the FY header row -> (period labels, value column indexes, rows below)."""
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    for ri, row in enumerate(rows):
        cols, labels = [], []
        for ci, c in enumerate(row):
            if isinstance(c, str) and re.match(r"\s*(20\d{2} FY|LTM)", c):
                cols.append(ci)
                labels.append(c.strip())
        if len(cols) >= 3:
            return labels, cols, rows[ri + 1:]
    return None, None, rows


def parse_segments(ws):
    joined = " ".join(str(c) for r in ws.iter_rows(max_row=25, values_only=True) for c in r if c)
    if "not currently available" in joined:
        return {"_missing": "CapIQ prints 'This information is not currently available for this report'"}
    periods, cols, body = find_grid(ws)
    if not periods:
        return {"_missing": "no FY header grid found on the Segment Analysis sheet"}
    out = {"periods": periods, "business": {}, "geographic": {}, "_units": "thousands, reported currency, as printed"}
    scope, metric = "business", None
    for row in body:
        lab = label_of(row)
        if not lab:
            continue
        low = lab.lower()
        if low in SEG_SKIP_ROWS or low.startswith(("source:", "note:", "s&p capital iq")):
            continue
        if low.startswith("geographic data"):
            scope, metric = "geographic", None
            continue
        if low.startswith(("line of business", "financials", "segments")):
            scope, metric = "business", None
            continue
        vals = series_of(row, cols)
        has_vals = any(v is not None for v in vals)
        canon = next((v for k, v in SEG_SECTIONS.items() if lab.startswith(k)), None)
        if canon and not has_vals:
            metric = canon
            continue
        if metric and has_vals and not lab.startswith("SubTotal"):
            out[scope].setdefault(metric, {})[lab] = vals
    # derived EBITDA by segment where OI and D&A both exist and no printed EBITDA
    biz = out["business"]
    if "ebitda_printed" not in biz and "operating_income" in biz and "d_and_a" in biz:
        der = {}
        for seg, oi in biz["operating_income"].items():
            da = biz["d_and_a"].get(seg)
            if da:
                der[seg] = [ (a + b) if (a is not None and b is not None) else None
                             for a, b in zip(oi, da) ]
        if der:
            biz["ebitda_derived"] = der
            out["_ebitda_basis"] = "derived: operating_income + d_and_a per segment (CapIQ prints no segment EBITDA row)"
    if not biz and not out["geographic"]:
        return {"_missing": "grid found but no segment rows parsed — inspect the sheet"}
    return out


def parse_eps_actuals(ws):
    """'Mean Estimates and Actuals Summ' -> FY EPS Normalized ACTUALS by year.
    Consensus-actual (normalized/adjusted) basis — the basis managements guide on,
    which is why this exists: GAAP eps_diluted vs an adjusted guide manufactures
    fake misses. Cells print like '2.77 A' (actual) / '3.59 E' (estimate); only
    'A' cells are taken."""
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    fy_col = None
    vals = {}
    for row in rows:
        cells = [c for c in row]
        if fy_col is None:
            for i, c in enumerate(cells):
                if isinstance(c, str) and c.strip().startswith("FY/NTM"):
                    fy_col = i
                    break
            continue
        y = cells[0] if cells else None
        ym = re.match(r"^(20\d\d)$", str(y).strip()) if y is not None else None
        if not ym or fy_col >= len(cells):
            continue
        m = re.match(r"^\s*([\d.]+)\s*A\s*$", str(cells[fy_col] or ""))
        if m:
            vals[int(ym.group(1))] = float(m.group(1))
    if not vals:
        return {"_missing": "no FY 'A' cells found on the Mean Estimates and Actuals sheet"}
    return {"values": {str(k): v for k, v in sorted(vals.items())},
            "_basis": "CapIQ 'EPS Normalized' FY consensus ACTUALS — adjusted basis, comparable to management guidance"}


def parse_cashflow(ws):
    periods, cols, body = find_grid(ws)
    if not periods:
        return {"_missing": "no FY header grid found on the Cash Flow Statement sheet"}
    rows = {}
    for row in body:
        lab = label_of(row)
        if not lab:
            continue
        low = lab.lower()
        if low in SEG_SKIP_ROWS or low.startswith(("source:", "note:", "s&p capital iq", "financial filing")):
            continue
        vals = series_of(row, cols)
        if any(v is not None for v in vals) and lab not in rows:
            rows[lab] = vals
    canon = {}
    for key, prefixes in CF_CANON.items():
        for p in prefixes:
            hit = next((l for l in rows if l.startswith(p)), None)
            if hit:
                canon[key] = {"label": hit, "values": rows[hit]}
                break
    out = {"periods": periods, "canonical": canon, "rows": rows,
           "_units": "thousands, reported currency, signs as printed (outflows negative)"}
    cfo = canon.get("cfo", {}).get("values")
    cap = canon.get("capex", {}).get("values")
    div = (canon.get("dividends_common") or canon.get("dividends_total") or {}).get("values")
    if cfo and cap:
        fcf = [ (a + b) if (a is not None and b is not None) else None for a, b in zip(cfo, cap) ]
        out["fcf_pre_dividends"] = {"values": fcf, "basis": "derived: cfo + capex (capex printed negative)"}
        if div:
            out["fcf_post_dividends"] = {
                "values": [ (f + d) if (f is not None and d is not None) else None for f, d in zip(fcf, div) ],
                "basis": f"derived: fcf_pre_dividends + {(canon.get('dividends_common') or canon.get('dividends_total'))['label']} (printed negative)"}
    return out


def atomic_write(path, obj):
    dirn = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=dirn, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports", required=True)
    ap.add_argument("--capiq", required=True)
    ap.add_argument("--tickers", default=None, help="comma list to restrict")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    if os.path.basename(args.capiq) != "capiq_export.json":
        sys.exit("REFUSED: --capiq must be capiq_export.json")
    only = set(t.strip().upper() for t in args.tickers.split(",")) if args.tickers else None

    results = {}
    for f in sorted(glob.glob(os.path.join(args.reports, "*.xlsx"))):
        base = os.path.basename(f)
        if base.startswith("~$"):
            continue
        m = TICKER_RE.search(base)
        if not m:
            print(f"  SKIP (no ticker in name): {base}")
            continue
        t = m.group(1).upper()
        if only and t not in only:
            continue
        wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
        seg_sheet = next((s for s in ("Segment Analysis",) if s in wb.sheetnames), None)
        # water-template workbooks name it 'Cash Flow', the standard one 'Cash Flow Statement'
        cf_sheet = next((s for s in ("Cash Flow Statement", "Cash Flow") if s in wb.sheetnames), None)
        seg = parse_segments(wb[seg_sheet]) if seg_sheet else {"_missing": "workbook has no Segment Analysis sheet"}
        cf = parse_cashflow(wb[cf_sheet]) if cf_sheet else {"_missing": "workbook has no Cash Flow sheet under either template name"}
        ea_sheet = next((sn for sn in wb.sheetnames if sn.startswith("Mean Estimates and Actuals")), None)
        ea = parse_eps_actuals(wb[ea_sheet]) if ea_sheet else {"_missing": "workbook has no Mean Estimates and Actuals sheet"}
        wb.close()
        seg["_source_file"] = base
        cf["_source_file"] = base
        ea["_source_file"] = base
        results[t] = (seg, cf, ea)
        nseg = len(seg.get("business", {}).get("revenue", {}))
        ncf = len(cf.get("rows", {}))
        nea = len(ea.get("values", {}))
        print(f"  {t:5s} segments: " + (f"{nseg} business segs" if nseg else str(seg.get("_missing", "?"))[:48])
              + f" | cash flow: " + (f"{ncf} rows" + (", fcf ok" if "fcf_pre_dividends" in cf else "") if ncf else str(cf.get("_missing", "?"))[:40])
              + f" | eps actuals: {nea or str(ea.get('_missing','?'))[:30]}")

    if not args.write:
        print(f"\n(dry run) parsed {len(results)} workbooks — re-run with --write to merge")
        return

    with open(args.capiq, encoding="utf-8") as f:
        cap = json.load(f)
    companies = cap.get("companies", cap)
    before = {t: set(v.keys()) for t, v in companies.items() if isinstance(v, dict)}

    merged = missing = 0
    for t, (seg, cf, ea) in results.items():
        if t not in companies:
            print(f"  WARN: {t} parsed but absent from capiq_export.json — not merged")
            missing += 1
            continue
        companies[t]["segment_analysis"] = seg
        companies[t]["cash_flow"] = cf
        companies[t]["eps_actuals_normalized"] = ea
        merged += 1

    # key audit: only segment_analysis / cash_flow may be added or replaced
    for t, keys in before.items():
        now = set(companies[t].keys())
        lost = keys - now
        added = now - keys
        assert not lost, f"ABORT: keys LOST on {t}: {lost}"
        assert added <= {"segment_analysis", "cash_flow", "eps_actuals_normalized"}, f"ABORT: unexpected keys added on {t}: {added}"

    bak = args.capiq + ".bak-pre-segcf"
    if not os.path.exists(bak):
        import shutil
        shutil.copy2(args.capiq, bak)
    atomic_write(args.capiq, cap)
    print(f"\nmerged {merged} companies into {args.capiq} (backup: {os.path.basename(bak)}); key audit passed")


if __name__ == "__main__":
    main()
