# -*- coding: utf-8 -*-
"""
moodys_merge.py
Upserts ONE new Moody's credit opinion (one ticker + one entity + one report_date)
into E:\PowerAcademy\data\moodys_credit.json without disturbing other entities/history.

USAGE (per Fareen's convention, run from anywhere, VPN off if needed):
    python moodys_merge.py --new new_report.json

new_report.json must be a single "report object" as produced in a Claude session
following MOODYS_EXTRACTION_WORKFLOW.md, wrapped like:

{
  "ticker": "ETR",
  "entity": "ENTERGY LOUISIANA, LLC",
  "is_holdco": false,
  "parent_entity": "ENTERGY CORPORATION",
  "report": { ...single report object, same shape as one item in reports[]... }
}

Behavior:
- If ticker/entity does not exist yet -> creates it.
- If a report with the SAME report_date already exists for that entity -> REPLACES
  it in place (idempotent re-runs / corrections), does not duplicate.
- Otherwise -> appends the new report to that entity's reports[] list (preserves
  history so the dashboard can show a report timeline per opco later if desired).
- Always writes with encoding='utf-8', indent=2, ensure_ascii=False.
- Prints a one-line summary + a reminder to git commit if this is a milestone
  (i.e., a brand-new entity or ticker was added).
"""
import json
import argparse
import os
import sys
from datetime import datetime

MASTER_PATH = os.environ.get('MOODYS_JSON_PATH', r'E:\PowerAcademy\data\moodys_credit.json')

def load_master(path):
    if not os.path.exists(path):
        return {
            "_schema_version": "1.0",
            "_schema_note": "Keyed by ticker -> entities{} -> entity name -> {ticker,is_holdco,parent_entity,reports:[...]}. See MOODYS_EXTRACTION_WORKFLOW.md.",
        }
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_master(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--new', required=True, help='Path to the single new report JSON to merge')
    ap.add_argument('--master', default=MASTER_PATH, help='Path to moodys_credit.json (default: env MOODYS_JSON_PATH or E:\\PowerAcademy\\data\\moodys_credit.json)')
    args = ap.parse_args()

    with open(args.new, 'r', encoding='utf-8') as f:
        incoming = json.load(f)

    ticker = incoming['ticker']
    entity = incoming['entity']
    report = incoming['report']
    if 'report_date' not in report:
        print('ERROR: report object must include report_date (YYYY-MM-DD).', file=sys.stderr)
        sys.exit(1)

    master = load_master(args.master)
    is_new_ticker = ticker not in master
    if is_new_ticker:
        master[ticker] = {"entities": {}}
    is_new_entity = entity not in master[ticker]["entities"]
    if is_new_entity:
        master[ticker]["entities"][entity] = {
            "ticker": ticker,
            "is_holdco": incoming.get("is_holdco", False),
            "parent_entity": incoming.get("parent_entity"),
            "reports": [],
        }

    ent_obj = master[ticker]["entities"][entity]
    # keep is_holdco/parent_entity current in case they were unset before
    ent_obj["is_holdco"] = incoming.get("is_holdco", ent_obj.get("is_holdco", False))
    ent_obj["parent_entity"] = incoming.get("parent_entity", ent_obj.get("parent_entity"))

    reports = ent_obj["reports"]
    existing_idx = next((i for i, r in enumerate(reports) if r.get("report_date") == report["report_date"]), None)
    if existing_idx is not None:
        reports[existing_idx] = report
        action = "REPLACED existing report dated " + report["report_date"]
    else:
        reports.append(report)
        reports.sort(key=lambda r: r.get("report_date", ""))
        action = "ADDED new report dated " + report["report_date"]

    save_master(args.master, master)

    print(f"[moodys_merge] {ticker} / {entity}: {action}")
    print(f"[moodys_merge] {entity} now has {len(reports)} report(s) on file.")
    if is_new_ticker or is_new_entity:
        print("=" * 60)
        print("MILESTONE: new ticker/entity added to moodys_credit.json.")
        print("Recommended: git add -A; git commit -m \"Add Moody's credit data: "
              f"{ticker} / {entity}\"")
        print("(Run from E:\\PowerAcademy\\app\\poweracademy\\)")
        print("Note: moodys_credit.json itself lives OUTSIDE the git repo root")
        print("(same convention as broker_research.json) - version it separately")
        print("if you want it in git history.")
        print("=" * 60)

if __name__ == '__main__':
    main()