#!/usr/bin/env python3
r"""build_sponsor_universe.py — seed data\sponsor_universe.json from precedents.json.

Financial-sponsor layer for the Origination screen: who buys regulated assets, what
they hold, how long they've held it. Seeded ENTIRELY from precedents.json — no new
data source needed. Inframation/Infralogic fields are declared with _missing reasons
and filled by a later enrichment pass when exports exist.

Usage (PowerShell — one line; `^` is cmd-only and backtick is the PS continuation):
    python E:\PowerAcademy\scripts\build_sponsor_universe.py --precedents E:\PowerAcademy\data\precedents.json --out E:\PowerAcademy\data\sponsor_universe.json --infralogic-funds E:\PowerAcademy\data\infralogic_funds.json --infralogic-assets E:\PowerAcademy\data\infralogic_assets.json

Rules honoured (from the tracker):
  * merge-safe: atomic write; if --out exists, hand-entered `inframation` blocks and
    `_manual` keys are carried forward, never clobbered.
  * routing guard: --out must be a sponsor_universe*.json; --precedents must name
    precedents.json. Never opens the coverage JSONs.
  * record what the source states: EV/equity figures are the DEAL's, never apportioned
    between consortium members — stated in _caveats, repeated on every consortium deal.
  * absence != no exit: the deal book is 118 deals, not the sponsor's portfolio.
    Exits are only asserted where BOTH legs are in the book; otherwise `possible_exit`.
"""
import argparse, json, os, re, sys, tempfile
from datetime import date

# ---------------------------------------------------------------- sponsor canon
# canonical name -> {type, patterns (lowercase substrings matched against the raw
# acquirer string), notes}. A raw string can map to SEVERAL sponsors (consortiums).
SPONSORS = {
    "Brookfield": {
        "type": "infrastructure fund",
        "patterns": ["brookfield"],
        "notes": "Super-Core vehicle on Duke FL; BIP/BAM legs not distinguished by the deal book.",
    },
    "Global Infrastructure Partners (BlackRock)": {
        "type": "infrastructure fund",
        "patterns": ["global infrastructure partners", "gip"],
        "notes": "Acquired by BlackRock 2024; ALLETE and AES legs.",
    },
    "Blackstone Infrastructure": {
        "type": "infrastructure fund",
        "patterns": ["blackstone"],
        "notes": "Minority-stake specialist in this book (NIPSCO 19.9%, TXNM 100% pending).",
    },
    "Stonepeak": {"type": "infrastructure fund", "patterns": ["stonepeak"], "notes": ""},
    "Bernhard Capital Partners": {
        "type": "PE (services/utility platform)",
        "patterns": ["bernhard", "delta utilities"],
        "notes": "Delta Utilities is its LDC roll-up platform; deals under either name are one sponsor.",
    },
    "KKR": {"type": "infrastructure fund", "patterns": ["kkr"], "notes": ""},
    "EQT": {"type": "infrastructure fund", "patterns": ["eqt consortium", "eqt"], "notes": ""},
    "Macquarie (MIRA/MIP)": {
        "type": "infrastructure fund",
        "patterns": ["macquarie", "mira"],
        "notes": "MIRA, MIP and Macquarie-led consortiums treated as one house.",
    },
    "J.P. Morgan IIF": {
        "type": "infrastructure fund",
        "patterns": ["iif", "infrastructure investments fund"],
        "notes": "Does not publish its own deal PRs (confirmed in the 07-22 press-release sweep).",
    },
    "Argo Infrastructure Partners": {"type": "infrastructure fund", "patterns": ["argo infrastructure"], "notes": ""},
    "CPP Investments": {"type": "pension", "patterns": ["cpp"], "notes": "Publishes own releases."},
    "CDPQ": {"type": "pension", "patterns": ["cdpq"], "notes": ""},
    "PSP Investments": {"type": "pension", "patterns": ["psp"], "notes": ""},
    "OMERS": {"type": "pension", "patterns": ["omers", "borealis"], "notes": ""},
    "BCI (bcIMC)": {"type": "pension", "patterns": ["bcimc"], "notes": ""},
    "ATRF": {"type": "pension", "patterns": ["atrf"], "notes": ""},
    "GIC": {"type": "sovereign wealth", "patterns": ["gic"], "notes": "Publishes own releases."},
    "Babcock & Brown Infrastructure": {
        "type": "infrastructure fund (defunct)",
        "patterns": ["babcock"],
        "notes": "Collapsed 2009; historical precedent only (NorthWestern 2006, terminated).",
    },
}

# Near-misses that must NOT classify as sponsors — recorded in meta so the
# exclusion is a visible decision, not a silent gap.
EXCLUDED_AS_STRATEGIC = {
    "Berkshire Hathaway Energy / MidAmerican": "strategic holdco, permanent capital — belongs with peers, not sponsors",
    "ENMAX": "Calgary municipally-owned utility — strategic buyer",
    "Fortis / Iberdrola / National Grid / Hydro One / Emera / AltaGas / Enbridge / TransCanada": "foreign strategics",
    "Oregon Trail Electric Cooperative": "co-op",
    "Regional Water Authority (RWA)": "quasi-municipal",
}

# Hand-verified exit links (both legs in the book). Everything else is detected
# and reported as possible_exit, never asserted.
VERIFIED_EXITS = {
    # entry deal id -> exit deal id
    "mira_bcimc_cleco_2014": "stonepeak_bernhard_cleco_2026",
}

WORD = re.compile(r"[a-z0-9]+")
STOP = {"the", "of", "and", "corp", "corporation", "inc", "llc", "lp", "group",
        "company", "co", "holdings", "energy", "utilities", "utility", "gas",
        "electric", "power", "interest"}


def norm_tokens(name):
    return {t for t in WORD.findall((name or "").lower()) if t not in STOP}


def match_sponsors(acquirer):
    """Return canonical sponsor names present in a raw acquirer string."""
    a = (acquirer or "").lower()
    hits = []
    for canon, spec in SPONSORS.items():
        for p in spec["patterns"]:
            # word-boundary match so 'gip' doesn't fire inside other words
            if re.search(r"(?<![a-z])" + re.escape(p) + r"(?![a-z])", a):
                hits.append(canon)
                break
    # GIC vs GIP guard: 'gic' must not match 'logic' etc. (boundary regex covers it)
    return hits


def parse_when(deal):
    """Best available date string for entry timing: closed if parseable, else announced.
    Returns (iso-ish string, basis)."""
    closed = deal.get("closed")
    if closed:
        m = re.match(r"(\d{4})[-/]?(\d{2})?", str(closed))
        if m:
            y, mo = m.group(1), m.group(2)
            if mo and 1 <= int(mo) <= 12:
                return f"{y}-{mo}", "closed"
            # '2025-H1' / '2025-Q1' style
            hq = re.search(r"(\d{4}).*?[HQ](\d)", str(closed))
            if hq:
                approx = {"1": "03", "2": "06", "3": "09", "4": "12"}[hq.group(2)] if "Q" in str(closed).upper() else ("06" if hq.group(2) == "1" else "12")
                return f"{hq.group(1)}-{approx}", "closed (H/Q approximated to period end)"
            return y, "closed (year only)"
    ann = deal.get("announced")
    if ann:
        return str(ann)[:7], "announced (deal not yet closed or close date absent)"
    return None, "no date in record"


def years_between(when, asof):
    if not when:
        return None
    parts = when.split("-")
    y = int(parts[0]); mo = int(parts[1]) if len(parts) > 1 else 6
    return round((asof.year - y) + (asof.month - mo) / 12.0, 1)


def deal_row(deal, members):
    raw = deal.get("raw") or {}
    return {
        "deal_id": deal["id"],
        "target": deal.get("target"),
        "target_ticker": deal.get("target_ticker"),
        "announced": deal.get("announced"),
        "closed": deal.get("closed"),
        "status": deal.get("status"),
        "pct_acquired": deal.get("pct_acquired"),
        "control_type": deal.get("control_type"),
        "asset_class": deal.get("asset_class"),
        "deal_scope": deal.get("deal_scope"),
        "fv_usd_b": raw.get("fv_usd_b"),
        "equity_value_usd_b": raw.get("equity_value_usd_b"),
        "consortium": members if len(members) > 1 else None,
        "_ev_note": ("deal-level figure, NOT apportioned between consortium members"
                     if len(members) > 1 else None),
        "acquirer_as_printed": deal.get("acquirer"),
    }


def inframation_shell():
    reason = "not derivable from precedents.json — fill from Inframation/Infralogic export"
    return {
        "aum_usd_b": None,
        "dry_powder_usd_b": None,
        "latest_fund": {"name": None, "vintage": None, "size_usd_b": None},
        "sector_mandate": None,
        "current_infra_holdings_full": None,
        "live_processes": None,
        "_missing": {k: reason for k in ["aum_usd_b", "dry_powder_usd_b", "latest_fund",
                                          "sector_mandate", "current_infra_holdings_full",
                                          "live_processes"]},
    }


# Infralogic GP name -> canonical sponsor name where the sponsor already exists.
# GPs not in this map and not in SPONSORS become NEW sponsor entries (deals_in_book 0).
GP_MAP = {
    "Blackstone Group": "Blackstone Infrastructure",
    "Macquarie Asset Management": "Macquarie (MIRA/MIP)",
}


def infralogic_block(gp, funds, assets_by_gp, asof):
    """Build the enrichment block for one GP from infralogic_funds/assets."""
    fund_rows = [{
        "name": f["fund_name"], "vintage": f.get("vintage"),
        "status": f.get("fund_status"), "fundraising_status": f.get("fundraising_status"),
        "size_usd_m": f.get("current_size_usd_m"),
        "net_irr_fraction": f.get("achieved_net_irr_fraction"),
        "unfunded_usd_m": f.get("unfunded_usd_m"),
    } for f in funds]
    with_unfunded = [f for f in fund_rows if f["unfunded_usd_m"] is not None]
    dry_powder = round(sum(f["unfunded_usd_m"] for f in with_unfunded), 1) if with_unfunded else None
    latest = max((f for f in fund_rows if f["vintage"]), key=lambda f: (f["vintage"], f["size_usd_m"] or 0), default=None)
    fundraising = [f["name"] for f in fund_rows
                   if "fundraising" in str(f.get("status") or "").lower()
                   or "fundraising" in str(f.get("fundraising_status") or "").lower()]
    legs = assets_by_gp.get(gp, [])
    live = sorted({a for a, st in legs if st == "live_bid"})
    return {
        "_as_of": asof, "_source": "infralogic_funds.json / infralogic_assets.json",
        "fund_count": len(fund_rows),
        "funds": fund_rows,
        "latest_fund": latest,
        "dry_powder_proxy_usd_m": dry_powder,
        "_dry_powder_note": (f"sum of Unfunded over the {len(with_unfunded)} of {len(fund_rows)} funds "
                             "that disclose it — a floor, not the GP's dry powder"),
        "fundraising_now": fundraising or None,
        "current_holdings_count": sum(1 for _, st in legs if st == "current"),
        "realised_count": sum(1 for _, st in legs if st == "realised"),
        "live_processes": live or None,
        "holdings_ref": "infralogic_assets.json (per-asset owner legs — one system, not copied here)",
        "aum_usd_b": None,
        "sector_mandate": None,
        "_missing": {"aum_usd_b": "in the GP profile PDFs in data\\infralogic — rip.py route, not yet extracted",
                     "sector_mandate": "same"},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--precedents", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--as-of", default=None, help="YYYY-MM-DD; defaults to today")
    ap.add_argument("--infralogic-funds", default=None, help="infralogic_funds.json for enrichment")
    ap.add_argument("--infralogic-assets", default=None, help="infralogic_assets.json for enrichment")
    args = ap.parse_args()

    # ---- routing guards
    if "precedents" not in os.path.basename(args.precedents).lower():
        sys.exit("REFUSED: --precedents must point at precedents.json")
    if not re.match(r"sponsor_universe.*\.json$", os.path.basename(args.out)):
        sys.exit("REFUSED: --out must be a sponsor_universe*.json")

    asof = date(*map(int, args.as_of.split("-"))) if args.as_of else date.today()

    with open(args.precedents, encoding="utf-8") as f:
        prec = json.load(f)
    deals = prec["deals"]

    # carry-forward of manual/enriched blocks if the out file already exists
    prior = {}
    if os.path.exists(args.out):
        with open(args.out, encoding="utf-8") as f:
            old = json.load(f)
        for s in old.get("sponsors", []):
            prior[s["name"]] = s

    by_sponsor = {}
    for d in deals:
        members = match_sponsors(d.get("acquirer"))
        for m in members:
            by_sponsor.setdefault(m, []).append((d, members))

    # target-token index for exit detection
    sponsors_out = []
    for canon in sorted(by_sponsor, key=lambda c: -len(by_sponsor[c])):
        rows = sorted((deal_row(d, mem) for d, mem in by_sponsor[canon]),
                      key=lambda r: r["announced"] or "")
        holdings, exits = [], []
        for r in rows:
            if str(r["status"] or "").lower().startswith("terminated"):
                continue
            # exit resolution
            exit_id = VERIFIED_EXITS.get(r["deal_id"])
            if exit_id:
                exit_deal = next((d for d in deals if d["id"] == exit_id), None)
                when, basis = parse_when({k: r[k] for k in ("closed", "announced")})
                exits.append({
                    "target": r["target"], "entry_deal": r["deal_id"],
                    "exit_deal": exit_id,
                    "entry": when,
                    "exit_announced": exit_deal.get("announced") if exit_deal else None,
                    "hold_years": (years_between(when, date(*map(int, exit_deal["announced"].split("-")[:3])))
                                   if exit_deal and exit_deal.get("announced") else None),
                    "basis": "both legs in precedents.json (verified)",
                })
                continue
            # possible exits: any LATER deal on an overlapping target name by others
            tk = norm_tokens(r["target"])
            poss = [d2["id"] for d2 in deals
                    if d2["id"] != r["deal_id"]
                    and (d2.get("announced") or "") > (r["announced"] or "")
                    and canon not in match_sponsors(d2.get("acquirer"))
                    and tk and (lambda t2: bool(t2) and (tk <= t2 or t2 <= tk))(norm_tokens(d2.get("target")))]
            when, basis = parse_when({k: r[k] for k in ("closed", "announced")})
            holdings.append({
                "target": r["target"],
                "pct": r["pct_acquired"],
                "entry": when,
                "entry_basis": basis,
                "hold_years_asof": (years_between(when, asof)
                                    if not str(r["status"] or "").lower().startswith("pending") else None),
                "status": r["status"],
                "deal_id": r["deal_id"],
                "possible_exit_deals": poss or None,
                "_caveat": "held per the deal book; absence of an exit in a 118-deal DB is NOT evidence the asset is still held",
            })
        spec = SPONSORS[canon]
        entry = {
            "name": canon,
            "type": spec["type"],
            "notes": spec["notes"] or None,
            "deals_in_book": len(rows),
            "deals": rows,
            "holdings": holdings,
            "exits": exits or None,
            "inframation": prior.get(canon, {}).get("inframation") or inframation_shell(),
        }
        if prior.get(canon, {}).get("_manual"):
            entry["_manual"] = prior[canon]["_manual"]
        sponsors_out.append(entry)

    # ---- Infralogic enrichment (optional)
    if args.infralogic_funds:
        with open(args.infralogic_funds, encoding="utf-8") as f:
            il_funds = json.load(f)
        assets_by_gp = {}
        if args.infralogic_assets:
            with open(args.infralogic_assets, encoding="utf-8") as f:
                il_assets = json.load(f)
            for a in il_assets["assets"].values():
                for o in a["owners"]:
                    assets_by_gp.setdefault(o["gp"], []).append((a["name"], o["status"]))
        by_name = {s["name"]: s for s in sponsors_out}
        for gp, funds in il_funds["gps"].items():
            block = infralogic_block(gp, funds, assets_by_gp, il_funds["_generated"])
            # hand-entered values in a prior block survive the enrichment
            prior_blk = (prior.get(GP_MAP.get(gp, gp), {}) or {}).get("inframation") or {}
            for k in ("aum_usd_b", "sector_mandate"):
                if prior_blk.get(k) is not None:
                    block[k] = prior_blk[k]
                    block["_missing"].pop(k, None)
            canon = GP_MAP.get(gp)
            if canon and canon in by_name:
                block["_scope_note"] = (f"Infralogic GP '{gp}' spans more vehicles than the "
                                        f"'{canon}' entity in the deal book — fund list is GP-wide")
                by_name[canon]["inframation"] = block
            elif gp in by_name:
                by_name[gp]["inframation"] = block
            else:
                sponsors_out.append({
                    "name": gp,
                    "type": "fund manager (from Infralogic export)",
                    "notes": "no deal in precedents.json — sourced from the Infralogic funds export",
                    "deals_in_book": 0, "deals": [], "holdings": [], "exits": None,
                    "inframation": block,
                })

    out = {
        "_schema_version": "0.1",
        "_generated": asof.isoformat(),
        "_source": (f"precedents.json ({len(deals)} deals, _generated {prec.get('_generated')}) — sponsor-side deals only"
                    + ("; enriched from " + os.path.basename(args.infralogic_funds) if args.infralogic_funds else "")),
        "_method": "acquirer strings matched to a canonical sponsor list; consortiums split into members; "
                   "EV/equity never apportioned between members; exits asserted only where both legs are in the book",
        "_excluded_as_strategic": EXCLUDED_AS_STRATEGIC,
        "_caveats": [
            "the deal book is 118 deals, not any sponsor's portfolio — holdings and exits reflect ONLY what the book contains",
            "consortium EV credited to every member in full (same convention as bank_scorecard.json); do not sum across members",
            "hold_years_asof computed at generation date; regenerate to refresh",
            "Inframation fields are declared, not populated — every one carries a _missing reason",
        ],
        "sponsor_count": len(sponsors_out),
        "sponsors": sponsors_out,
    }

    # atomic write
    dirn = os.path.dirname(os.path.abspath(args.out)) or "."
    fd, tmp = tempfile.mkstemp(dir=dirn, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    os.replace(tmp, args.out)

    print(f"sponsors: {len(sponsors_out)}")
    for s in sponsors_out:
        print(f"  {s['name']:44s} deals={s['deals_in_book']} holdings={len(s['holdings'])} exits={len(s['exits'] or [])}")


if __name__ == "__main__":
    main()
