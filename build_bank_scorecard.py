#!/usr/bin/env python3
"""
build_bank_scorecard.py — regenerate data/bank_scorecard.json from data/precedents.json.

Why this script exists
----------------------
bank_scorecard.json was hand-built on 2026-07-22 over the pre-merge book and went
wrong on its face for three reasons (see precedents.json ->
_merge_meta._counter_recon_2026_08_06.regeneration_required):

  1. It was built over 118 deals / 239 role slots, the 2026-07-23 bad merge took the
     book to 117 / 236, and the 2026-08-06 h2o split restored it to 118 / 239. Counts
     are right again, but its two deal references (h2o_quadvest_2025,
     h2o_southcentral_2025) were dangling for two weeks and only just resolve.
  2. It predates advisor normalisation and still keyed on 'Citigroup', 'Wells Fargo',
     'Greenhill (Mizuho)' and 'Blackstone' — spellings now collapsed by _advisor_canon.
  3. Its league_table used a THIRD naming convention matching neither supported view:
     it silently rolled Merrill Lynch + BofA Merrill Lynch + BofA Securities into
     'BofA / Merrill', Morgan Stanley Dean Witter into 'Morgan Stanley' and UBS Warburg
     into 'UBS' (a successor rollup), while abbreviating live houses to 'RBC', 'Moelis',
     'Centerview', 'Guggenheim', 'CIBC', 'BMO', 'Truist' (neither canon spelling).

This script carries BOTH supported views with an explicit view flag, and never invents
a third convention: every displayed house name comes verbatim from
_advisor_canon.map[<string>].as_of_deal_date or .successor_2026.

Display default is as_of_deal_date (user decision, 2026-08-06): every advisor
attribution in this book is sourced to a document, so the as-of name keeps the table
falsifiable against that document. 'Merrill Lynch on a 1999 deal' is accurate;
'BofA' on a 1999 deal is an anachronism.

Usage:  python3 scripts/build_bank_scorecard.py [--check]
        --check  validate and print the report without writing the file.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRECEDENTS = os.path.join(REPO, "data", "precedents.json")
OUT = os.path.join(REPO, "data", "bank_scorecard.json")

VIEWS = ("as_of_deal_date", "successor_2026")
SIDE_FIELDS = (("target_advisors", "target"), ("acquirer_advisors", "acquirer"))

# ---------------------------------------------------------------------------
# Caveats carried forward VERBATIM from the 2026-07-22 file. These are the two
# things a reader must know before quoting any number here, and they survive
# regeneration by construction rather than by memory.
# ---------------------------------------------------------------------------
CAVEATS = (
    "Advisers were sourced from press releases, 8-K exhibits and law-firm "
    "announcements and are not exhaustive - older deals in particular under-report. "
    "Absence of a bank from a deal is NOT evidence it had no role. Financial advisers "
    "only; legal counsel sits in advisors._note."
)

METHOD_BASE = (
    'Adviser names are resolved through precedents.json._advisor_canon - no name is '
    'ever spelled by this script. "Credit" is the full EV of each deal on which the '
    "bank held a role - it is NOT apportioned between co-advisers, so credit sums "
    "exceed total deal value. Roles counted per side; a bank advising both sides of "
    "one deal counts twice."
)

ERAS = (
    ("pre-2005", None, 2004),
    ("2005-2014", 2005, 2014),
    ("2015-2020", 2015, 2020),
    ("2021+", 2021, None),
)

# sell/buy skew thresholds, reproduced from the 2026-07-22 file (all 45 rows agree)
SKEW_SELL_ABOVE = 0.60
SKEW_BUY_BELOW = 0.40

HOUSE_BANK_MIN_DEALS = 2


_TRAILING_PAREN = re.compile(r"\s*\([^()]*\)\s*$")


def client_key(name: str) -> str:
    """Grouping key for house-bank detection.

    precedents.json writes the same corporate client several ways when it needs to
    disambiguate the asset or the seller: 'NextEra Energy' vs 'NextEra Energy (FPL)',
    'Aquarion Water Company (from Eversource)' vs '(from Macquarie)'. A house-bank
    relationship is about the client, not the vehicle, so a single trailing
    parenthetical qualifier is stripped for grouping. Nothing else is normalised - no
    fuzzy matching, no alias table - and the display name is the stripped base string.
    The 2026-07-22 file did this merge for NextEra/FPL; this rule generalises it
    without guessing.
    """
    return _TRAILING_PAREN.sub("", name).strip()


def era_of(announced: str) -> str:
    year = int(announced[:4])
    for label, lo, hi in ERAS:
        if (lo is None or year >= lo) and (hi is None or year <= hi):
            return label
    raise ValueError(f"no era bucket for {announced!r}")


def skew(sell: int, buy: int) -> str:
    total = sell + buy
    if total == 0:
        return "n/a"
    ratio = sell / total
    if ratio > SKEW_SELL_ABOVE:
        return "sell"
    if ratio < SKEW_BUY_BELOW:
        return "buy"
    return "balanced"


def display_name(canon_entry: dict, view: str) -> str:
    """The house name for a view. Never constructs a name that is not in the canon."""
    if view == "as_of_deal_date":
        return canon_entry["as_of_deal_date"]
    successor = canon_entry["successor_2026"]
    if successor is None:
        # Canon rule: successor null means it could not be sourced confidently.
        # Do not fill it with a plausible house; surface it as unresolved, exactly
        # as _advisor_canon.league_table_successor_2026 does.
        return "UNRESOLVED: " + canon_entry["as_of_deal_date"]
    return successor


def deal_ev_usd_b(deal: dict):
    """EV in $B. precedents.json stores it as raw.fv_usd_b on large deals and
    raw.fv_usd_m on smaller ones; a null in either means the figure is genuinely
    absent (e.g. brookfield_fet_2024, whose full-company EV was nulled when the row
    was corrected to a 30% minority stake). Absent EV contributes no credit rather
    than a guess."""
    raw = deal.get("raw") or {}
    if raw.get("fv_usd_b") is not None:
        return round(float(raw["fv_usd_b"]), 2)
    if raw.get("fv_usd_m") is not None:
        return round(float(raw["fv_usd_m"]) / 1000.0, 2)
    return None


def extract_slots(deals: list, canon_map: dict) -> list:
    """One record per advisor role slot. This is the single source of truth for
    every rollup below, so the role-slot total ties to the deals array by design."""
    slots = []
    unmapped = []
    for deal in deals:
        advisors = deal.get("advisors") or {}
        announced = deal["announced"]
        ev = deal_ev_usd_b(deal)
        for field, side in SIDE_FIELDS:
            for raw_name in advisors.get(field) or []:
                entry = canon_map.get(raw_name)
                if entry is None:
                    unmapped.append((deal["id"], raw_name))
                    continue
                slots.append(
                    {
                        "deal": deal["id"],
                        "side": side,
                        # the party this bank advised (target name on a target role)
                        "counterparty": deal["target"] if side == "target" else deal["acquirer"],
                        "ev_usd_b": ev,
                        "announced": announced,
                        "asset_class": deal["asset_class"],
                        "era": era_of(announced),
                        "raw_name": raw_name,
                        "names": {v: display_name(entry, v) for v in VIEWS},
                    }
                )
    if unmapped:
        raise SystemExit(
            "FATAL: advisor strings absent from _advisor_canon.map — refusing to invent "
            "a name for them:\n  " + "\n  ".join(f"{d}: {n!r}" for d, n in unmapped)
        )
    return slots


def build_view(slots: list, view: str) -> dict:
    roles = defaultdict(list)
    sell = defaultdict(int)
    buy = defaultdict(int)
    ev_credit = defaultdict(float)
    by_asset_class = defaultdict(lambda: defaultdict(int))
    by_era = defaultdict(lambda: defaultdict(int))
    client_pairs = defaultdict(dict)  # (client, bank) -> {deal_id: announced}

    for s in slots:
        bank = s["names"][view]
        roles[bank].append(
            {
                "deal": s["deal"],
                "side": s["side"],
                "counterparty": s["counterparty"],
                "ev_usd_b": s["ev_usd_b"],
                "announced": s["announced"],
                # the string the deal document actually used, kept on every role so a
                # successor-view row stays traceable back to its source document
                "as_printed": s["names"]["as_of_deal_date"] if view != "as_of_deal_date" else None,
            }
        )
        if s["side"] == "target":
            sell[bank] += 1
        else:
            buy[bank] += 1
        if s["ev_usd_b"] is not None:
            ev_credit[bank] += s["ev_usd_b"]
        by_asset_class[bank][s["asset_class"]] += 1
        by_era[bank][s["era"]] += 1
        ckey = client_key(s["counterparty"])
        client_pairs[(ckey, bank)][s["deal"]] = (s["announced"], s["counterparty"])

    for bank in roles:
        roles[bank].sort(key=lambda r: (r["announced"], r["deal"]), reverse=True)
        if view == "as_of_deal_date":
            for r in roles[bank]:
                r.pop("as_printed", None)

    league_table = [
        {
            "bank": bank,
            "roles": len(rl),
            "sell_side": sell[bank],
            "buy_side": buy[bank],
            "ev_credit_usd_b": round(ev_credit[bank], 1),
            "sell_buy_skew": skew(sell[bank], buy[bank]),
        }
        for bank, rl in roles.items()
    ]
    league_table.sort(key=lambda e: (-e["roles"], -e["ev_credit_usd_b"], e["bank"]))

    # House-bank relationships: the same adviser retained by the same company across
    # two or more separate deals. Preserved from the 2026-07-22 file.
    house_banks = []
    for (company, bank), deal_map in client_pairs.items():
        if len(deal_map) >= HOUSE_BANK_MIN_DEALS:
            ordered = sorted(deal_map, key=lambda d: (deal_map[d][0], d), reverse=True)
            years = sorted(v[0][:4] for v in deal_map.values())
            variants = sorted({v[1] for v in deal_map.values()})
            entry = {
                "company": company,
                "bank": bank,
                "deals": len(ordered),
                "deal_ids": ordered,
                "span": f"{years[0]}-{years[-1]}",
            }
            if variants != [company]:
                entry["client_names_in_deals"] = variants
            house_banks.append(entry)
    house_banks.sort(key=lambda h: (-h["deals"], h["company"], h["bank"]))

    ordered_banks = [e["bank"] for e in league_table]
    return {
        "view": view,
        "naming_convention": (
            "House name as printed in the deal document at announcement "
            "(_advisor_canon.map[*].as_of_deal_date)."
            if view == "as_of_deal_date"
            else "Firm that owns the franchise in 2026 "
            "(_advisor_canon.map[*].successor_2026); "
            "'UNRESOLVED: <house>' where the canon carries a null successor by decision."
        ),
        "distinct_houses": len(ordered_banks),
        "role_slots": sum(e["roles"] for e in league_table),
        "league_table": league_table,
        "house_banks": house_banks,
        "by_asset_class": {b: dict(by_asset_class[b]) for b in ordered_banks},
        "by_era": {b: dict(by_era[b]) for b in ordered_banks},
        "roles": {b: roles[b] for b in ordered_banks},
    }


def validate(payload: dict, deals: list, canon: dict, slots: list) -> list:
    """Hard checks. Any failure aborts the write."""
    problems = []
    deal_ids = {d["id"] for d in deals}

    # 1. role-slot total ties to the deals array
    slot_total = sum(
        len(d.get("advisors", {}).get(f) or []) for d in deals for f, _ in SIDE_FIELDS
    )
    if slot_total != len(slots):
        problems.append(f"slot extraction lost rows: deals={slot_total} extracted={len(slots)}")
    for view in VIEWS:
        v = payload["views"][view]
        lt_total = sum(e["roles"] for e in v["league_table"])
        roles_total = sum(len(r) for r in v["roles"].values())
        if lt_total != slot_total:
            problems.append(f"{view}: league_table roles {lt_total} != deals slot total {slot_total}")
        if roles_total != slot_total:
            problems.append(f"{view}: roles arrays {roles_total} != deals slot total {slot_total}")
        for view_key in ("by_asset_class", "by_era"):
            for bank, buckets in v[view_key].items():
                got = sum(buckets.values())
                want = len(v["roles"][bank])
                if got != want:
                    problems.append(f"{view}.{view_key}[{bank}] sums to {got}, roles={want}")
        # 2. every deal id referenced must exist
        referenced = {r["deal"] for rl in v["roles"].values() for r in rl}
        referenced |= {i for h in v["house_banks"] for i in h["deal_ids"]}
        dangling = sorted(referenced - deal_ids)
        if dangling:
            problems.append(f"{view}: dangling deal ids {dangling}")
        # 3. no name invented outside the canon
        legal = set()
        for entry in canon["map"].values():
            legal.add(entry["as_of_deal_date"])
            legal.add(
                entry["successor_2026"]
                if entry["successor_2026"] is not None
                else "UNRESOLVED: " + entry["as_of_deal_date"]
            )
        stray = sorted({e["bank"] for e in v["league_table"]} - legal)
        if stray:
            problems.append(f"{view}: house names not present in _advisor_canon: {stray}")
        # 4. league table must agree with the canon's own published table
        reference = canon["league_table_as_of"] if view == "as_of_deal_date" else canon["league_table_successor_2026"]
        mine = {e["bank"]: e["roles"] for e in v["league_table"]}
        if mine != reference:
            diff = {
                k: (mine.get(k), reference.get(k))
                for k in set(mine) | set(reference)
                if mine.get(k) != reference.get(k)
            }
            problems.append(f"{view}: disagrees with _advisor_canon.league_table_* {diff}")

    scale = canon.get("scale", {})
    if scale.get("deals") != len(deals):
        problems.append(f"deal count {len(deals)} != _advisor_canon.scale.deals {scale.get('deals')}")
    if scale.get("role_slots") != slot_total:
        problems.append(f"role slots {slot_total} != _advisor_canon.scale.role_slots {scale.get('role_slots')}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="validate only, do not write")
    args = ap.parse_args()

    with open(PRECEDENTS, encoding="utf-8") as fh:
        prec = json.load(fh)
    deals = prec["deals"]
    canon = prec["_advisor_canon"]
    default_view = canon.get("display_default", "as_of_deal_date")
    if default_view not in VIEWS:
        raise SystemExit(f"unsupported display_default {default_view!r}")

    slots = extract_slots(deals, canon["map"])
    views = {v: build_view(slots, v) for v in VIEWS}

    payload = {
        "_generated": _dt.date.today().isoformat(),
        "_builder": "scripts/build_bank_scorecard.py",
        "_source": (
            f"precedents.json advisors blocks ({len(deals)} deals, {len(slots)} named roles) "
            f"resolved through _advisor_canon (as_of {canon.get('as_of')})"
        ),
        "_method": METHOD_BASE,
        "_caveats": CAVEATS,
        "_view": default_view,
        "default_view": default_view,
        "_view_note": (
            "Two parallel views are carried. as_of_deal_date = the house name the deal "
            "document actually used; successor_2026 = the firm that owns that franchise "
            "today. The as-of view is the display default (user decision, 2026-08-06): "
            "every attribution is sourced to a document, so as-of keeps the table "
            "falsifiable against that document. The successor rollup answers a different "
            "question - how much utility M&A a franchise has done - and must not silently "
            "become the answer to 'who advised on this deal'. The pre-2026-08-06 file "
            "used a third convention that was neither view; it is gone."
        ),
        "_top_level_note": (
            "league_table / house_banks / by_asset_class / by_era / roles at top level "
            "mirror views." + default_view + " for backward compatibility. Both views "
            "always live under views.*."
        ),
        "views": views,
    }
    for key in ("league_table", "house_banks", "by_asset_class", "by_era", "roles"):
        payload[key] = views[default_view][key]

    problems = validate(payload, deals, canon, slots)
    payload["_validation"] = {
        "checked": _dt.date.today().isoformat(),
        "deals": len(deals),
        "role_slots": len(slots),
        "role_slot_total_ties_to_deals": True,
        "all_deal_ids_resolve": True,
        "house_names_all_from_advisor_canon": True,
        "agrees_with_advisor_canon_league_tables": True,
        "checks": [
            "role-slot total == advisor strings in deals[] (both views)",
            "per-bank by_asset_class and by_era sum to that bank's role count",
            "every deal id in roles[] and house_banks[] exists in deals[]",
            "every house name appears in _advisor_canon (no third convention)",
            "league_table role counts equal _advisor_canon.league_table_as_of / _successor_2026",
            "deal + role-slot counts equal _advisor_canon.scale",
        ],
    }

    if problems:
        print("VALIDATION FAILED — file NOT written:", file=sys.stderr)
        for p in problems:
            print("  -", p, file=sys.stderr)
        return 1

    print(f"deals={len(deals)}  role_slots={len(slots)}  default_view={default_view}")
    for v in VIEWS:
        vv = views[v]
        print(
            f"  {v:18s} houses={vv['distinct_houses']:3d} slots={vv['role_slots']:3d} "
            f"house_bank_pairs={len(vv['house_banks']):3d}"
        )
        for e in vv["league_table"][:10]:
            print(
                f"      {e['bank'][:32]:34s} roles={e['roles']:3d} "
                f"s{e['sell_side']:3d}/b{e['buy_side']:3d} "
                f"ev=${e['ev_credit_usd_b']:7.1f}B  {e['sell_buy_skew']}"
            )
    print("validation: PASS")

    if args.check:
        print("--check: not written")
        return 0

    if os.path.exists(OUT):
        os.chmod(OUT, 0o644)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
