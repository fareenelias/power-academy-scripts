#!/usr/bin/env python3
r"""build_adjacency.py — contiguous service areas from the per-ticker territory GeoJSONs (roadmap I.A).

data\territories\<TICKER>.geojson -> data\service_adjacency.json:
  per ticker: the coverage names whose territories touch or come within TOLERANCE_KM,
  with the minimum gap distance. Names whose file is a placeholder stub (no real
  polygons) are listed under `no_geometry` — absence of geometry is stated, never
  rendered as "no neighbours".

Method (stated because the basis matters): geometries are unioned per ticker and
compared pairwise with a tolerance, because territories digitised from different
sources rarely share exact boundaries. `adjacent` = within 2 km; `near` = within
25 km. Distances in degrees are converted at ~111 km/degree — crude but ample for
a touch/near classification. COVERAGE names only; peer-utility adjacency would come
from data\iou_territories.geojson (HIFLD) and is not built.

Usage: python build_adjacency.py --territories <dir> --out data\service_adjacency.json
Needs shapely (cloud container has it; not required on the desktop — the output JSON is committed).
"""
import argparse, glob, json, os, sys, tempfile
from datetime import date
from shapely.geometry import shape
from shapely.ops import unary_union

ADJ_KM, NEAR_KM = 2.0, 25.0
KM_PER_DEG = 111.0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--territories", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--as-of", default=None)
    args = ap.parse_args()
    if not os.path.basename(args.out).startswith("service_adjacency"):
        sys.exit("REFUSED: --out must be service_adjacency*.json")

    geoms, stubs = {}, []
    for f in sorted(glob.glob(os.path.join(args.territories, "*.geojson"))):
        t = os.path.splitext(os.path.basename(f))[0]
        gj = json.load(open(f, encoding="utf-8"))
        feats = gj.get("features", [])
        shapes = [shape(x["geometry"]) for x in feats if x.get("geometry")]
        if not shapes:
            stubs.append(t); continue
        u = unary_union(shapes)
        if u.area * (KM_PER_DEG ** 2) < 10:   # < ~10 km^2 => placeholder point/box
            stubs.append(t); continue
        geoms[t] = u

    ticks = sorted(geoms)
    pairs = []
    neighbors = {t: [] for t in ticks}
    for i, a in enumerate(ticks):
        for b in ticks[i+1:]:
            d_km = geoms[a].distance(geoms[b]) * KM_PER_DEG
            if d_km <= NEAR_KM:
                rel = "adjacent" if d_km <= ADJ_KM else "near"
                pairs.append({"a": a, "b": b, "relation": rel, "min_gap_km": round(d_km, 1)})
                neighbors[a].append({"ticker": b, "relation": rel, "min_gap_km": round(d_km, 1)})
                neighbors[b].append({"ticker": a, "relation": rel, "min_gap_km": round(d_km, 1)})

    out = {
        "_schema_version": "0.1",
        "_generated": args.as_of or date.today().isoformat(),
        "_method": f"union per ticker; adjacent = min gap <= {ADJ_KM} km, near = <= {NEAR_KM} km, "
                   f"distances at ~{KM_PER_DEG:.0f} km/degree. Coverage names only.",
        "_caveats": [
            "names in no_geometry have placeholder territory files, NOT no neighbours — "
            "water/IPP territories are Backlog E",
            "peer-utility adjacency (who among AEP/DUK/SO borders a coverage name) is NOT here — "
            "it would come from data\\iou_territories.geojson (HIFLD)",
        ],
        "no_geometry": stubs,
        "pairs": sorted(pairs, key=lambda p: p["min_gap_km"]),
        "neighbors": {t: sorted(v, key=lambda x: x["min_gap_km"]) for t, v in neighbors.items()},
    }
    dirn = os.path.dirname(os.path.abspath(args.out)) or "."
    fd, tmp = tempfile.mkstemp(dir=dirn, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    os.replace(tmp, args.out)
    print(f"geometries: {len(ticks)} | stubs: {len(stubs)} {stubs}")
    for p in out["pairs"]:
        print(f"  {p['a']:5s} - {p['b']:5s} {p['relation']:8s} gap {p['min_gap_km']} km")

if __name__ == "__main__":
    main()
