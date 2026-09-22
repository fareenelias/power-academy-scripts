#!/usr/bin/env python3
r"""build_track_record.py — the I.B historical track-record layer.

  guidance_history.json + broker_research.json + capiq_export.json
      -> data\track_record.json, per ticker:

  eps_track[]   — per fiscal year: the EARLIEST in-year observed adjusted-EPS guide
                  (initiation proxy), the LATEST in-year guide (final), the actual,
                  and the verdict (beat / met / missed vs the initial range) plus the
                  in-year revision path (raised / narrowed / cut / reaffirmed).
  capex_track[] — per year: the capital-plan per-year run-rate from the latest deck
                  vintage stated BEFORE that year whose window covers it, vs actual
                  capex from the CapIQ cash-flow extraction; ratio and both sources.
  reg_lag       — filing -> decision months over the CapIQ past rate cases
                  (`duration_months` as filed by CapIQ), per opco+service and pooled,
                  split pre/post-2022 to show the trend.

HONESTY RULES — the year-attribution trap is the whole game here:
  * guidance_history rows mostly carry `year: null` on the EPS guide, and a Q4 deck's
    first printed range can be EITHER the closing year's final guide or next year's
    initiation (CMS Q4-2023 prints the 2023 range). So a Q4 deck is NEVER assumed to
    guide the following year. A guide is attributed to fiscal year Y only when
    (a) the row prints the year explicitly, or (b) the deck is a Q1–Q3 deck of year Y
    (in-year decks guide the current year) — basis recorded on every row as
    'printed_year' or 'inferred_in_year'. "Initial" therefore means the earliest
    IN-YEAR observation — an initiation PROXY, stated as such (true initiation happens
    on the Q4 prior-year call and is not reliably attributable without a year label).
  * ACTUALS are the cross-broker mean of the '<year>A' cells in broker_research
    financial_estimates (ADJUSTED basis — the basis managements guide on). The GAAP
    capiq eps_diluted series is deliberately NOT used as a fallback: a GAAP actual
    against an adjusted guide manufactures fake misses (the fdso lesson).
  * capex plan (deck, utility plan basis) vs actual (consolidated GAAP CF) are
    different bases — the ratio is a signal, not a reconciliation, and says so.

Usage (PowerShell — one line):
  python E:\PowerAcademy\scripts\build_track_record.py --guidance E:\PowerAcademy\data\guidance_history.json --broker E:\PowerAcademy\data\broker_research.json --capiq E:\PowerAcademy\data\capiq_export.json --out E:\PowerAcademy\data\track_record.json
"""
import argparse, json, os, re, sys, tempfile

Q = re.compile(r"^Q([1-4]) (20\d\d)$")


def atomic_write(path, obj):
    dirn = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=dirn, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def broker_actuals(br, ticker):
    """cross-broker mean of '<year>A' adjusted-EPS cells -> {year: {mean, n, brokers}}"""
    bb = (((br.get(ticker) or {}).get("financial_estimates") or {}).get("metrics") or {}).get("eps") or {}
    out = {}
    for house, rec in (bb.get("by_broker") or {}).items():
        for k, v in (rec.get("values") or {}).items():
            m = re.match(r"^(20\d\d)A$", str(k))
            if m and isinstance(v, (int, float)):
                out.setdefault(int(m.group(1)), []).append((house, float(v)))
    res = {}
    for y, pairs in out.items():
        vals = [v for _, v in pairs]
        res[y] = {"mean": round(sum(vals) / len(vals), 3), "n": len(vals),
                  "brokers": sorted(h for h, _ in pairs)}
    return res


def merge_actuals(co, br_actuals):
    """capiq 'EPS Normalized' FY consensus actuals (primary) + broker '<year>A' means (fallback)."""
    res = {}
    ea = ((co or {}).get("eps_actuals_normalized") or {}).get("values") or {}
    for y, v in ea.items():
        res[int(y)] = {"mean": float(v), "source": "CapIQ 'EPS Normalized' FY consensus actual — adjusted basis"}
    for y, a in br_actuals.items():
        if y not in res:
            res[y] = {"mean": a["mean"], "source": f"adjusted — mean of {a['n']} broker '{y}A' cells ({', '.join(a['brokers'])})"}
    return res


def eps_track(rows, actuals):
    """rows: guidance_history[ticker] period->row. Attribute guides to years, honestly."""
    obs = {}   # year -> list of (sortkey, period, guide-dict, basis)
    for period, r in rows.items():
        m = Q.match(period)
        if not m:
            continue
        q, yr = int(m.group(1)), int(m.group(2))
        eg = r.get("eps_guidance") or {}
        if eg.get("low") is None or eg.get("high") is None:
            continue
        if eg.get("year"):
            y, basis = int(eg["year"]), "printed_year"
        elif q <= 3:
            y, basis = yr, "inferred_in_year"    # in-year decks guide the current year
        else:
            continue   # Q4 deck with no printed year: ambiguous, refused
        obs.setdefault(y, []).append((yr * 10 + q, period, eg, basis, r.get("source_url")))
    track = []
    for y in sorted(obs):
        seq = sorted(obs[y])
        first, last = seq[0], seq[-1]
        f, l = first[2], last[2]
        a = actuals.get(y)
        verdict = None
        if a:
            av = a["mean"]
            verdict = "beat" if av > f["high"] + 1e-9 else ("missed" if av < f["low"] - 1e-9 else "met")
        # in-year revision path vs the first observation
        if len(seq) > 1:
            if l["low"] > f["low"] + 1e-9 and l["high"] >= f["high"] - 1e-9:
                rev = "raised"
            elif l["high"] < f["high"] - 1e-9 and l["low"] <= f["low"] + 1e-9:
                rev = "cut"
            elif l["low"] >= f["low"] - 1e-9 and l["high"] <= f["high"] + 1e-9 and \
                 (l["high"] - l["low"]) < (f["high"] - f["low"]) - 1e-9:
                rev = "narrowed"
            elif abs(l["low"] - f["low"]) < 1e-9 and abs(l["high"] - f["high"]) < 1e-9:
                rev = "reaffirmed"
            else:
                rev = "shifted"
        else:
            rev = None
        row = {
            "year": y,
            "initial_guide": {"low": f["low"], "high": f["high"], "period": first[1],
                              "basis": first[3], "source_url": first[4]},
            "final_guide": {"low": l["low"], "high": l["high"], "period": last[1]} if len(seq) > 1 else None,
            "observations": len(seq),
            "revision": rev,
            "actual": ({"eps": a["mean"], "basis": a["source"]} if a else None),
            "verdict": verdict,
            "_actual_missing": None if a else "no adjusted-basis actual on file for this year (CapIQ normalized "
                                              "actuals start 2023) — GAAP deliberately not substituted",
        }
        # plausibility tell: an actual wildly off the guide mid means a year-attribution
        # or basis problem, not a business outcome — flag, never silently keep
        if a and f["low"] and abs(a["mean"] - (f["low"] + f["high"]) / 2) > 0.6 * max(abs((f["low"] + f["high"]) / 2), 0.5):
            row["_flag"] = "actual >60% away from the initial guide midpoint — check year attribution / basis before quoting"
        track.append(row)
    return track


def capex_track(rows, cf):
    """plan run-rate (latest vintage stated BEFORE year y whose window covers y) vs actual |capex|."""
    vintages = []
    for period, r in rows.items():
        m = Q.match(period)
        if not m:
            continue
        tot, yrs = r.get("capital_plan_total_b"), r.get("capital_plan_years")
        if tot is None or not yrs:
            continue
        ym = re.match(r"^\s*(20\d\d)\s*[-–]\s*(20\d\d)\s*$", str(yrs))
        if not ym:
            continue
        y0, y1 = int(ym.group(1)), int(ym.group(2))
        if y1 <= y0 or y1 - y0 > 9:
            continue
        skey = int(m.group(2)) * 10 + int(m.group(1))
        vintages.append({"skey": skey, "period": period, "total_b": tot, "y0": y0, "y1": y1,
                         "per_year_b": round(tot / (y1 - y0 + 1), 2), "source_url": r.get("source_url")})
    per = (cf or {}).get("periods") or []
    cap = ((cf or {}).get("canonical") or {}).get("capex", {}).get("values") or []
    actual = {}
    for p, v in zip(per, cap):
        m = re.match(r"^(20\d\d) FY", str(p))
        if m and v is not None:
            actual[int(m.group(1))] = round(abs(v) / 1e6, 2)   # $000 -> $B
    out = []
    for y in sorted(actual):
        cands = [v for v in vintages if v["y0"] <= y <= v["y1"] and v["skey"] < y * 10 + 1]
        if not cands:
            continue
        v = max(cands, key=lambda x: x["skey"])
        out.append({"year": y, "plan_per_year_b": v["per_year_b"],
                    "plan": {"total_b": v["total_b"], "window": f"{v['y0']}-{v['y1']}",
                             "stated": v["period"], "source_url": v["source_url"]},
                    "actual_capex_b": actual[y],
                    "actual_vs_plan_x": round(actual[y] / v["per_year_b"], 2) if v["per_year_b"] else None,
                    "_basis": "plan = deck capital-plan run-rate (window average, often utility-only); "
                              "actual = consolidated GAAP CF capex — different bases, ratio is a signal not a reconciliation"})
    return out


def reg_lag(company_rec):
    cases = company_rec.get("past_rate_cases") or []
    if isinstance(cases, dict):
        cases = cases.get("cases") or []
    rows = []
    for c in cases:
        d = c.get("duration_months")
        dd = str(c.get("decision_date") or "")
        ym = re.match(r"^(\d{1,2})/(\d{4})$", dd)
        if d is None or not ym:
            continue
        rows.append({"months": float(d), "year": int(ym.group(2)),
                     "company": c.get("company"), "state": c.get("state"),
                     "service": c.get("service_type")})
    if not rows:
        return None
    def stats(sub):
        v = sorted(x["months"] for x in sub)
        mid = v[len(v)//2] if len(v) % 2 else (v[len(v)//2 - 1] + v[len(v)//2]) / 2
        return {"n": len(v), "median_months": round(mid, 1), "mean_months": round(sum(v)/len(v), 1)}
    by_opco = {}
    for r in rows:
        by_opco.setdefault(f"{r['company']} · {r['state']} · {r['service']}", []).append(r)
    return {
        "all": stats(rows),
        "decided_2022_on": stats([r for r in rows if r["year"] >= 2022]) if any(r["year"] >= 2022 for r in rows) else None,
        "decided_pre_2022": stats([r for r in rows if r["year"] < 2022]) if any(r["year"] < 2022 for r in rows) else None,
        "by_opco": {k: stats(v) for k, v in sorted(by_opco.items()) if len(v) >= 3},
        "_basis": "CapIQ past_rate_cases `duration_months` (filing to decision) as filed; by_opco shown only at n≥3",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--guidance", required=True)
    ap.add_argument("--broker", required=True)
    ap.add_argument("--capiq", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if not os.path.basename(args.out).startswith("track_record"):
        sys.exit("REFUSED: --out must be track_record*.json")

    gh = json.load(open(args.guidance, encoding="utf-8"))
    br = json.load(open(args.broker, encoding="utf-8"))
    cap = json.load(open(args.capiq, encoding="utf-8"))
    companies = cap.get("companies", cap)

    out, flags = {}, 0
    for t in sorted(set(list(gh) + list(companies)) - {"_note"}):
        if t.startswith("_"):
            continue
        rows = {k: v for k, v in (gh.get(t) or {}).items() if not k.startswith("_")}
        co = companies.get(t) or {}
        et = eps_track(rows, merge_actuals(co, broker_actuals(br, t))) if rows else []
        ct = capex_track(rows, co.get("cash_flow")) if rows else []
        rl = reg_lag(co)
        flags += sum(1 for r in et if r.get("_flag"))
        if et or ct or rl:
            out[t] = {"eps_track": et, "capex_track": ct, "reg_lag": rl}

    doc = {
        "_schema_version": "0.1",
        "_source": "guidance_history.json (guides) + capiq eps_actuals_normalized / broker '<year>A' cells (adjusted actuals) + capiq_export.json (cash_flow capex, past_rate_cases)",
        "_method": "guides attributed to a year only via a printed year or an in-year Q1–Q3 deck (Q4 decks without a "
                   "printed year are refused as ambiguous); 'initial' = earliest in-year observation (initiation PROXY); "
                   "verdict struck vs the initial range on adjusted-basis broker actuals",
        "_caveats": [
            "true initiation happens on the Q4 prior-year call and is not reliably attributable without a printed year — "
            "the initiation proxy understates early-guide drift",
            "actuals are adjusted-basis broker means; years with no '<year>A' broker cell show no verdict rather than a GAAP substitute",
            "capex plan vs actual compares different bases (deck plan vs consolidated GAAP CF) — a signal, not a reconciliation",
            f"{flags} eps rows carry a _flag (actual >60% off guide mid) — inspect before quoting",
        ],
        "tickers": out,
    }
    atomic_write(args.out, doc)
    ne = sum(len(v["eps_track"]) for v in out.values())
    nv = sum(1 for v in out.values() for r in v["eps_track"] if r.get("verdict"))
    nc = sum(len(v["capex_track"]) for v in out.values())
    nr = sum(1 for v in out.values() if v.get("reg_lag"))
    print(f"tickers: {len(out)} | eps-years: {ne} ({nv} with verdicts, {flags} flagged) | capex-years: {nc} | reg-lag: {nr}")
    for t, v in sorted(out.items()):
        vs = [f"{r['year']}:{(r['verdict'] or '?')[0].upper()}{'!' if r.get('_flag') else ''}" for r in v["eps_track"]]
        if vs:
            print(f"  {t:5s} {' '.join(vs)}")


if __name__ == "__main__":
    main()
