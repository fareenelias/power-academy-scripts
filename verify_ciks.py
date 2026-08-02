r"""
verify_ciks.py - check the CIK -> filer names used for press-release side
attribution against SEC's OFFICIAL company list.

WHY
  precedents.json now records which SIDE of each deal issued the press release,
  worked out from the CIK in the sec.gov url (the CIK identifies the filer).
  Most of those filer names were inferred - either from the party common to every
  deal a CIK filed for, or from a hand-written map. This script checks them
  against SEC's own data so nothing rests on assumption.

WHAT IT DOES
  * pulls https://www.sec.gov/files/company_tickers.json (official CIK/ticker/name)
  * extracts every CIK appearing in a sec.gov url in precedents.json
  * prints SEC's registered name next to the name we assumed
  * flags MISMATCHes and any CIK marked links._cik_unverified
  * --write stamps links._cik_verified_name so the check is auditable later

USAGE
    python verify_ciks.py                 # report only
    python verify_ciks.py --write         # also record SEC's name into the file

NOTES
  * VPN OFF.
  * company_tickers.json only covers filers with a ticker, so older/private
    filers (Niagara Mohawk, CILCORP, New Century Energies) will come back
    "not listed" - that is expected, not an error. For those, the submissions
    API is tried as a fallback: https://data.sec.gov/submissions/CIK##########.json
"""

import argparse, gzip, io, json, os, re, time
import urllib.request, urllib.error

DATA = r"E:\PowerAcademy\data\precedents.json"
UA = os.environ.get("SEC_UA", "PowerAcademy/1.0 power-academy@internal")
HEAD = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate", "Accept": "application/json"}
CIKRE = re.compile(r"sec\.gov/Archives/edgar/data/0*(\d+)/", re.I)


def get(url, host="www.sec.gov"):
    req = urllib.request.Request(url, headers=dict(HEAD, Host=host))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            return json.loads(raw.decode("utf-8", "replace"))
    except Exception as e:
        print("   ! %s: %s" % (type(e).__name__, e))
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DATA)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    doc = json.load(open(a.data, encoding="utf-8"))
    deals = doc["deals"]

    print("fetching SEC company_tickers.json ...")
    tick = get("https://www.sec.gov/files/company_tickers.json")
    lookup = {}
    if tick:
        for v in tick.values():
            lookup[str(v["cik_str"])] = v["title"]
        print("  %d filers loaded\n" % len(lookup))

    seen = {}
    for x in deals:
        L = x.get("links") or {}
        for k in ("press_release", "press_release_target", "press_release_acquirer",
                  "filing", "filing_index", "deck", "source_doc"):
            u = L.get(k)
            if isinstance(u, str) and "sec.gov" in u:
                m = CIKRE.search(u)
                if m:
                    seen.setdefault(m.group(1), []).append((x["id"], L.get("_pr_filer"),
                                                            bool(L.get("_cik_unverified"))))

    print("%d distinct CIKs in precedents.json\n" % len(seen))
    print("%-10s %-42s %-42s %s" % ("CIK", "SEC REGISTERED NAME", "NAME WE ASSUMED", "STATUS"))
    print("-" * 130)

    mism = notfound = ok = 0
    for cik, uses in sorted(seen.items(), key=lambda t: -len(t[1])):
        sec_name = lookup.get(str(int(cik)))
        if not sec_name:
            j = get("https://data.sec.gov/submissions/CIK%010d.json" % int(cik), host="data.sec.gov")
            time.sleep(0.15)
            sec_name = (j or {}).get("name")
        assumed = next((u[1] for u in uses if u[1]), "") or ""
        flagged = any(u[2] for u in uses)

        if not sec_name:
            status = "NOT LISTED (old/private filer)"; notfound += 1
        elif assumed:
            aw = set(re.findall(r"[a-z]{3,}", assumed.lower()))
            sw = set(re.findall(r"[a-z]{3,}", sec_name.lower()))
            status = "ok" if (aw & sw) else "*** MISMATCH ***"
            if aw & sw: ok += 1
            else: mism += 1
        else:
            status = "(no assumed name)"
        if flagged:
            status += "  [was _cik_unverified]"
        print("%-10s %-42s %-42s %s" % (cik, (sec_name or "-")[:42], assumed[:42], status))
        if a.write and sec_name:
            for did, _n, _f in uses:
                for y in deals:
                    if y["id"] == did:
                        y.setdefault("links", {})["_cik_verified_name"] = sec_name

    print("\nok %d | MISMATCH %d | not listed %d" % (ok, mism, notfound))
    if mism:
        print("Investigate every MISMATCH - a wrong filer means the press release is "
              "attributed to the wrong SIDE of the deal.")
    if a.write:
        json.dump(doc, open(a.data, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        print("written %s" % a.data)


if __name__ == "__main__":
    main()