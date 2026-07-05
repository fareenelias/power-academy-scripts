"""
Builds grouped IOU list with parent company assignments.
Output: E:\PowerAcademy\data\iou_grouped.json
"""
import json
from pathlib import Path

INPUT = Path(r"E:\PowerAcademy\data\iou_list.json")

# Parent company groupings — name fragment -> parent
# Order matters: more specific first
PARENT_MAP = [
    # Your coverage companies first
    ("FLORIDA POWER & LIGHT",          "NEE — NextEra Energy"),
    ("FPL ",                           "NEE — NextEra Energy"),
    ("GULF POWER",                     "NEE — NextEra Energy"),
    ("NEXTERA ENERGY",                 "NEE — NextEra Energy"),
    ("VIRGINIA ELECTRIC",              "D — Dominion Energy"),
    ("DOMINION ENERGY SOUTH CAROLINA", "D — Dominion Energy"),
    ("DOMINION HOPE",                  "D — Dominion Energy"),
    ("QUESTAR GAS",                    "D — Dominion Energy"),
    ("ENTERGY ARKANSAS",               "ETR — Entergy"),
    ("ENTERGY LOUISIANA",              "ETR — Entergy"),
    ("ENTERGY MISSISSIPPI",            "ETR — Entergy"),
    ("ENTERGY NEW ORLEANS",            "ETR — Entergy"),
    ("ENTERGY TEXAS",                  "ETR — Entergy"),
    ("CONSUMERS ENERGY",               "CMS — CMS Energy"),
    ("PPL ELECTRIC",                   "PPL — PPL Corporation"),
    ("LOUISVILLE GAS AND ELECTRIC",    "PPL — PPL Corporation"),
    ("KENTUCKY UTILITIES",             "PPL — PPL Corporation"),
    ("AMEREN MISSOURI",                "AEE — Ameren"),
    ("AMEREN ILLINOIS",                "AEE — Ameren"),
    ("UNION ELECTRIC",                 "AEE — Ameren"),
    ("PORTLAND GENERAL ELECTRIC",      "POR — Portland General Electric"),
    ("SOUTHERN CALIFORNIA EDISON",     "EIX — Edison International"),
    ("PACIFIC GAS & ELECTRIC",         "PCG — PG&E"),
    ("PACIFIC GAS AND ELECTRIC",       "PCG — PG&E"),
    ("HAWAIIAN ELECTRIC",              "HE — Hawaiian Electric"),
    ("HAWAII ELECTRIC LIGHT",          "HE — Hawaiian Electric"),
    ("MAUI ELECTRIC",                  "HE — Hawaiian Electric"),
    ("EVERGY",                         "EVRG — Evergy"),
    ("KANSAS CITY POWER & LIGHT",      "EVRG — Evergy"),
    ("WESTAR ENERGY",                  "EVRG — Evergy"),
    ("KCP&L",                          "EVRG — Evergy"),
    ("PUBLIC SERVICE OF NEW HAMPSHIRE","ES — Eversource"),
    ("CONNECTICUT LIGHT AND POWER",    "ES — Eversource"),
    ("NSTAR ELECTRIC",                 "ES — Eversource"),
    ("WESTERN MASSACHUSETTS ELECTRIC", "ES — Eversource"),
    ("EVERSOURCE",                     "ES — Eversource"),
    # Other major holding companies
    ("ALABAMA POWER",                  "Southern Company"),
    ("GEORGIA POWER",                  "Southern Company"),
    ("GULF POWER CO",                  "Southern Company"),
    ("MISSISSIPPI POWER",              "Southern Company"),
    ("SOUTHERN POWER",                 "Southern Company"),
    ("AEP TEXAS",                      "AEP — American Electric Power"),
    ("APPALACHIAN POWER",              "AEP — American Electric Power"),
    ("INDIANA MICHIGAN POWER",         "AEP — American Electric Power"),
    ("KENTUCKY POWER",                 "AEP — American Electric Power"),
    ("OHIO POWER",                     "AEP — American Electric Power"),
    ("PUBLIC SERVICE CO OF OKLAHOMA",  "AEP — American Electric Power"),
    ("SOUTHWESTERN ELECTRIC POWER",    "AEP — American Electric Power"),
    ("WHEELING POWER",                 "AEP — American Electric Power"),
    ("DUKE ENERGY CAROLINAS",          "Duke Energy"),
    ("DUKE ENERGY FLORIDA",            "Duke Energy"),
    ("DUKE ENERGY INDIANA",            "Duke Energy"),
    ("DUKE ENERGY KENTUCKY",           "Duke Energy"),
    ("DUKE ENERGY OHIO",               "Duke Energy"),
    ("DUKE ENERGY PROGRESS",           "Duke Energy"),
    ("PIEDMONT NATURAL GAS",           "Duke Energy"),
    ("EXELON",                         "Exelon"),
    ("COMMONWEALTH EDISON",            "Exelon"),
    ("PECO ENERGY",                    "Exelon"),
    ("BALTIMORE GAS AND ELECTRIC",     "Exelon"),
    ("PEPCO",                          "Exelon"),
    ("DELMARVA POWER",                 "Exelon"),
    ("ATLANTIC CITY ELECTRIC",         "Exelon"),
    ("OHIO EDISON",                    "FirstEnergy"),
    ("PENNSYLVANIA ELECTRIC",          "FirstEnergy"),
    ("METROPOLITAN EDISON",            "FirstEnergy"),
    ("JERSEY CENTRAL POWER",           "FirstEnergy"),
    ("MON POWER",                      "FirstEnergy"),
    ("WEST PENN POWER",                "FirstEnergy"),
    ("FIRSTENERGY",                    "FirstEnergy"),
    ("XCEL ENERGY",                    "Xcel Energy"),
    ("NORTHERN STATES POWER",          "Xcel Energy"),
    ("PUBLIC SERVICE CO OF COLORADO",  "Xcel Energy"),
    ("SOUTHWESTERN PUBLIC SERVICE",    "Xcel Energy"),
    ("WEC ENERGY",                     "WEC Energy Group"),
    ("WISCONSIN ELECTRIC",             "WEC Energy Group"),
    ("WISCONSIN GAS",                  "WEC Energy Group"),
    ("MICHIGAN GAS",                   "WEC Energy Group"),
    ("MINNESOTA ENERGY",               "WEC Energy Group"),
    ("PEOPLES ENERGY",                 "WEC Energy Group"),
    ("OTTER TAIL",                     "Otter Tail Corporation"),
    ("IDAHO POWER",                    "IDACORP"),
    ("NEVADA POWER",                   "NV Energy"),
    ("SIERRA PACIFIC POWER",           "NV Energy"),
    ("NV ENERGY",                      "NV Energy"),
    ("PUGET SOUND ENERGY",             "Puget Energy"),
    ("PACIFIC POWER",                  "PacifiCorp"),
    ("ROCKY MOUNTAIN POWER",           "PacifiCorp"),
    ("PACIFICORP",                     "PacifiCorp"),
    ("AVISTA",                         "Avista Corporation"),
    ("EL PASO ELECTRIC",               "El Paso Electric"),
    ("EMPIRE DISTRICT",                "Liberty Utilities"),
    ("NEW ENGLAND GAS",                "Liberty Utilities"),
    ("UNITIL",                         "Unitil Corporation"),
    ("GREEN MOUNTAIN POWER",           "Green Mountain Power"),
    ("CENTRAL VERMONT",                "Green Mountain Power"),
    ("CLECO",                          "Cleco Corporation"),
    ("LACLEDE GAS",                    "Spire Inc"),
    ("SPIRE",                          "Spire Inc"),
    ("ALLIANT ENERGY",                 "Alliant Energy"),
    ("INTERSTATE POWER",               "Alliant Energy"),
    ("IOWA POWER",                     "Alliant Energy"),
    ("MADISON GAS AND ELECTRIC",       "Madison Gas & Electric"),
    ("MGE",                            "Madison Gas & Electric"),
    ("BLACK HILLS",                    "Black Hills Corporation"),
    ("SOUTHWESTERN PUBLIC SERVICE",    "Xcel Energy"),
    ("ARIZONA PUBLIC SERVICE",         "Pinnacle West"),
    ("APS",                            "Pinnacle West"),
    ("TUCSON ELECTRIC",                "Fortis"),
    ("UNS ELECTRIC",                   "Fortis"),
    ("CENTRAL HUDSON",                 "Fortis"),
    ("CON EDISON",                     "Consolidated Edison"),
    ("CONSOLIDATED EDISON",            "Consolidated Edison"),
    ("ORANGE AND ROCKLAND",            "Consolidated Edison"),
    ("NIAGARA MOHAWK",                 "National Grid"),
    ("NATIONAL GRID",                  "National Grid"),
    ("KEYSPAN",                        "National Grid"),
    ("LONG ISLAND POWER",              "PSEG — Public Service Enterprise Group"),
    ("PSEG",                           "PSEG — Public Service Enterprise Group"),
    ("PUBLIC SERVICE ELECTRIC",        "PSEG — Public Service Enterprise Group"),
    ("JERSEY CENTRAL",                 "FirstEnergy"),
    ("ROCHESTER GAS AND ELECTRIC",     "Avangrid"),
    ("NEW YORK STATE ELECTRIC",        "Avangrid"),
    ("CENTRAL MAINE POWER",            "Avangrid"),
    ("AVANGRID",                       "Avangrid"),
    ("IBERDOLA",                       "Avangrid"),
    ("SOUTHWESTERN ENERGY",            "Southwestern Energy"),
    ("VECTREN",                        "CenterPoint Energy"),
    ("CENTERPOINT",                    "CenterPoint Energy"),
    ("RELIANT ENERGY",                 "CenterPoint Energy"),
    ("OHIO GAS",                       "Columbia Gas / NiSource"),
    ("NISOURCE",                       "NiSource"),
    ("COLUMBIA GAS",                   "NiSource"),
    ("BAY STATE GAS",                  "Eversource"),
    ("YANKEE GAS",                     "Eversource"),
    ("NORTHERN UTILITIES",             "Unitil Corporation"),
    ("EMPIRE STATE ELECTRIC",          "Other IOU"),
    ("AES",                            "AES Corporation"),
    ("INDIANA POWER",                  "AES Corporation"),
    ("DAYTON POWER",                   "AES Corporation"),
    ("TALEN",                          "TLN — Talen Energy"),
    ("VISTRA",                         "VST — Vistra"),
    ("LUMINANT",                       "VST — Vistra"),
    ("TXU ENERGY",                     "VST — Vistra"),
]

def get_parent(name):
    name_upper = name.upper()
    for fragment, parent in PARENT_MAP:
        if fragment.upper() in name_upper:
            return parent
    return "Other IOU"

# Load IOU list
with open(INPUT) as f:
    ious = json.load(f)

# Assign parents
for iou in ious:
    iou["parent"] = get_parent(iou["name"])

# Group by parent
groups = {}
for iou in ious:
    p = iou["parent"]
    if p not in groups:
        groups[p] = []
    groups[p].append(iou)

# Sort: coverage companies first, then alphabetical
coverage_prefixes = ["NEE","D ","ETR","CMS","PPL","AEE","POR","EIX","PCG","HE ","EVRG","ES "]
def sort_key(parent):
    for i, prefix in enumerate(coverage_prefixes):
        if parent.startswith(prefix):
            return (0, i, parent)
    return (1, 0, parent)

sorted_groups = dict(sorted(groups.items(), key=lambda x: sort_key(x[0])))

# Stats
print(f"Total IOUs: {len(ious)}")
print(f"Unique parents: {len(groups)}")
print(f"\nCoverage companies:")
for k, v in sorted_groups.items():
    if k.split(" — ")[0] in ["NEE","D","ETR","CMS","PPL","AEE","POR","EIX","PCG","HE","EVRG","ES"]:
        print(f"  {k}: {[u['name'] for u in v]}")
print(f"\nOther major groups (top 10 by size):")
others = [(k,v) for k,v in sorted_groups.items() if sort_key(k)[0] == 1 and k != "Other IOU"]
for k, v in sorted(others, key=lambda x: -len(x[1]))[:10]:
    print(f"  {k}: {len(v)} entities — {[u['name'] for u in v[:2]]}")

# Save
out_path = Path(r"E:\PowerAcademy\data\iou_grouped.json")
with open(out_path, "w") as f:
    json.dump({"groups": sorted_groups, "total": len(ious)}, f, indent=2)
print(f"\nSaved to {out_path}")