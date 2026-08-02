r"""
split_broker_json.py — derive per-ticker broker research files for fast remote loads.

Reads  E:\PowerAcademy\data\broker_research.json   (canonical, hand-versioned)
Writes E:\PowerAcademy\data\broker_research\<TICKER>.json   (derived — never hand-edit)

The React Equity Research panel fetches /api/eia/broker_research/<TICKER>.json first
and falls back to the monolithic file on 404, so this step is optional but makes
remote (Tailscale) loads ~10x lighter per ticker.

Run after any broker_research.json update:
    python split_broker_json.py
(or wire into extract_all.py after the CapIQ pass)

NOTE: not to be confused with the legacy split_broker_research.py, which splits
bulk-scanned PDF files. This script only splits the JSON.
"""
import json
import os
import sys

SRC = r"E:\PowerAcademy\data\broker_research.json"
OUT_DIR = r"E:\PowerAcademy\data\broker_research"

def main():
    src = sys.argv[1] if len(sys.argv) > 1 else SRC
    out_dir = sys.argv[2] if len(sys.argv) > 2 else OUT_DIR
    if not os.path.exists(src):
        print(f"[ERR] source not found: {src}")
        sys.exit(1)

    with open(src, encoding="utf-8") as f:
        data = json.load(f)

    os.makedirs(out_dir, exist_ok=True)

    meta = {k: v for k, v in data.items() if k.startswith("_")}
    tickers = [k for k in data if not k.startswith("_")]

    written, total_bytes = 0, 0
    for t in tickers:
        obj = data[t]
        if meta:
            # carry any top-level meta into each split so consumers never miss schema notes
            obj = {**meta, **obj} if isinstance(obj, dict) else obj
        out_path = os.path.join(out_dir, f"{t}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        sz = os.path.getsize(out_path)
        total_bytes += sz
        written += 1
        print(f"  {t:6} -> {out_path}  ({sz/1024:.0f} KB)")

    # remove stale per-ticker files for tickers no longer in the master
    stale = [f for f in os.listdir(out_dir)
             if f.endswith(".json") and f[:-5] not in tickers]
    for f in stale:
        os.remove(os.path.join(out_dir, f))
        print(f"  removed stale {f}")

    mono = os.path.getsize(src)
    print(f"\n[OK] {written} tickers split. Monolithic {mono/1024:.0f} KB -> "
          f"avg per-ticker {total_bytes/max(written,1)/1024:.0f} KB.")
    print("Derived folder — safe to gitignore; regenerate any time from the master.")

if __name__ == "__main__":
    main()