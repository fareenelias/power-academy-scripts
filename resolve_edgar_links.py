r"""
resolve_edgar_links.py  (v2.8) - turn EDGAR *directory* links into DIRECT document
links, and QC the ones that point at the wrong filing entirely.

WHY v2
  v1 asked EDGAR for index.json and every request came back HTTP 403. SEC's WAF
  is fussy: it wants a descriptive User-Agent, an explicit Accept-Encoding, and
  it is markedly happier serving the classic "<accession>-index.htm" page than
  index.json. server.js already fetches www.sec.gov/Archives/...-index.htm
  successfully from this machine, so v2 uses that proven path, with index.json
  only as a secondary attempt.

WHAT IT DOES
  For each deal it finds the EDGAR accession folder, reads the filing index, and
  writes DIRECT urls back into precedents.json:
      links.press_release <- EX-99.1
      links.deck          <- EX-99.2 / EX-99.3
      links.filing        <- the form body (8-K / 425 / S-4 / DEFM14A / 424B3)

  It also QCs the filing and FLAGS (never silently keeps) links that aren't deal
  documents at all:
      * 424B2 / 424B5  = shelf takedown, i.e. a securities OFFERING
      * 10-K / 10-Q    = periodic report
      * quarterly earnings press releases
      * a filing dated more than ~18 months from the announcement
  Those move to links.source_doc with links._link_qc explaining why - which is
  how the Black Hills / NorthWestern merger was caught pointing at a 424B5.

  It NEVER invents a url. If EDGAR doesn't list an exhibit the field stays null:
  most deals genuinely have no EX-99.2 deck.

USAGE
    python resolve_edgar_links.py --diag                 # test fetch + why it fails
    python resolve_edgar_links.py                        # dry run over everything
    python resolve_edgar_links.py --write
    python resolve_edgar_links.py --write --only awk_essential_2025
    python resolve_edgar_links.py --write --refresh      # re-resolve even if direct

NOTES
  * VPN OFF.
  * Still 403? Run --diag: it prints status, response body and the exact headers
    sent, which distinguishes an SEC rejection from a corporate-proxy block.
    You can override the UA:  set SEC_UA=YourName you@yourdomain.com
"""

import argparse, gzip, io, json, os, re, shutil, time
import urllib.request, urllib.error
from datetime import date

VERSION = "2.8"
DATA = r"E:\PowerAcademy\data\precedents.json"

# SEC fair-access policy wants a descriptive UA with a contact. Same string
# server.js already uses successfully against www.sec.gov/Archives.
UA = os.environ.get("SEC_UA", "PowerAcademy/1.0 power-academy@internal")
SLEEP = 0.20                      # SEC asks for <10 req/sec
HEADERS = {
    "User-Agent": UA,
    "Accept-Encoding": "gzip, deflate",     # v1 omitted this -> 403
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Host": "www.sec.gov",
    "Connection": "keep-alive",
}

# Deals whose only stored SEC url pointed at the WRONG filing, so the accession
# folder can't be derived. Verified manually against EDGAR.
KNOWN_ANCHORS = {
    # the stored link was a May-2026 424B5 equity offering; the actual merger
    # 8-K (announced 19 Aug 2025) carries EX-99.1 press release + EX-99.2 deck
    "blackhills_northwestern_2025":
        "https://www.sec.gov/Archives/edgar/data/1130464/000110465925080000/",
    # 2026-07-22 newsroom crawl - announcement 8-Ks located, EX-99.x resolves from here
    # NEE/HEI 3-Dec-2014: joint press release is EX-99.1
    "nee_hawaiian_2014":
        "https://www.sec.gov/Archives/edgar/data/0000753308/000075330814000130/",
    # Eversource/Aquarion 2-Jun-2017: EX-99.1 = newsrelease.htm
    "eversource_aquarion_2017":
        "https://www.sec.gov/Archives/edgar/data/0000072741/000007274117000023/",
    # Dominion/Questar 1-Feb-2016: NOTE the inverted numbering - EX-99.1 is the
    # merger agreement, EX-99.2 the joint press release, EX-99.3 the call deck.
    # Handled by description-first classification (pass 0), not the number.
    "dominion_questar_2016":
        "https://www.sec.gov/Archives/edgar/data/0000715957/000119312516446233/",
    # NextEra/Southern 21-May-2018 (Gulf Power + Florida City Gas + Oleander/
    # Stanton announced together): press release is a bare "Exhibit 99"
    "nextera_fcg_2018":
        "https://www.sec.gov/Archives/edgar/data/0000753308/000075330818000093/",
}

# Accessions verified BY HAND to contain no investor presentation. Pre-2005
# filing indexes often carry no Description text, so the classifier can't tell an
# EX-99.3 deck from an EX-99.3 proxy card - these are the ones already checked.
KNOWN_NO_DECK = {
    # Fareen 2026-07-22: this accession holds the S-4 merger proposal, a J.P.
    # Morgan consent (the fairness opinion itself is inside the S-4, not here)
    # and the form of proxy. No presentation.
    "exelon_pseg_2004",
}

# Verified press releases that EDGAR can't supply - typically because the deal
# was announced via a Rule 425 communication or a foreign/private acquirer with
# no EX-99.1 on file. Must satisfy the approved-source rule: company IR/newsroom
# site, SEC EX-99.x, or a newswire carrying the issuer's own release.
KNOWN_PRESS_RELEASE = {
    # Fareen 2026-07-22: the 425 accession carries no EX-99.1; Dominion's own
    # newsroom has the joint announcement.
    "nee_dominion_2026": (
        "https://news.dominionenergy.com/press-releases/press-releases/2026/"
        "NextEra-Energy-and-Dominion-Energy-to-Combine-Creating-the-Worlds-Largest-"
        "Regulated-Electric-Utility-Business-and-North-Americas-Premier-Energy-"
        "Infrastructure-Platform-Benefiting-Customers/default.aspx"),
    # Entergy 30-Oct-2023 gas LDC sale to Bernhard/Delta - PR Newswire
    "bernhard_entergy_lagas_2023":
        "https://www.prnewswire.com/news-releases/entergy-announces-agreement-to-sell-gas-"
        "distribution-business-to-bernhard-capital-partners-301971333.html",
    # TXNM/Blackstone 19-May-2025 - company IR site (announcement release PDF)
    "blackstone_txnm_2025":
        "https://www.txnmenergy.com/~/media/Files/P/PNM-Resources/press-release/"
        "Acquisition%20Investor%20Release.pdf",
}

# Investor decks hosted on the company's own IR site rather than filed as an
# SEC exhibit. Same approved-source rule as press releases.
KNOWN_DECK = {
    # TXNM/Blackstone acquisition investor presentation, 19 May 2025
    "blackstone_txnm_2025":
        "https://www.txnmenergy.com/~/media/Files/P/PNM-Resources/events-and-presentations/"
        "2025/Acquisition%20Investor%20Presentation%20May%2019.pdf",
}

FOLDER_RE = re.compile(r"^(https?://www\.sec\.gov/Archives/edgar/data/([^/]+)/([^/]+))/?$", re.I)
ANYSEC_RE = re.compile(r"^(https?://www\.sec\.gov/Archives/edgar/data/[^/]+/[^/]+)/", re.I)

# --- exhibit / form classification (fixed in v2) ---------------------------
# Donnelley writes EX-99.1 as "ex99d1" with no separator - v1 missed those.
# Filenames vary wildly across filing agents and eras: ex99-1 / ex99_1 / ex99d1 /
# exhibit99_1 / ex991nr… Match the family, not one convention.
_E99 = r"(?:ex|exhibit)[-_.]?99"
EX991 = re.compile(_E99 + r"[-_.]?d?1(?!\d)", re.I)
# EX-99.2 is the usual investor deck. EX-99.3 is only *sometimes* a deck - in a
# periodic filing it is typically a SOX certification or financial statements,
# so 99.3 is accepted only as a fallback and never when the name looks like one
# of those. (v2.0 wrongly tagged a CEO certification as Algonquin's deck.)
EX992 = re.compile(_E99 + r"[-_.]?d?2(?!\d)", re.I)
EX993 = re.compile(_E99 + r"[-_.]?d?3(?!\d)", re.I)
EX99_BARE = re.compile(_E99 + r"(?![-_.]?\d)", re.I)   # bare "ex99.txt"
# some agents name the press release descriptively, with no exhibit number
PRESSY = re.compile(r"news[-_]?release|press[-_]?release|newsrel|pressrel", re.I)
NOTADECK = re.compile(
    r"cert|certifica|financialstatement|financialsta|fin[_-]?stmt|consent|auditor|"
    r"comfort|opinion|subsidiar|906|302|sarbanes|"
    # v2.4: exhibits harvested out of QUARTERLY filings that are not decks
    r"\bmd&?a\b|mdanda|xmda|discussion\s*and\s*analysis|regulation\s*btr|regbtr|"
    r"oil\s*and\s*gas|oilandgas|reserve|proxy|ballot|voting", re.I)
# 424B3 is often the merger prospectus; 424B2/424B5 are shelf takedowns = OFFERINGS.
OFFERING = re.compile(r"424b[25]", re.I)
DEALFORM = re.compile(r"(8-?k|d?425|s-?4|def[ma]?14a|dfan14a|pre[rm]14a|sc[-_]?14d9|424b3)", re.I)
# Any "…dex2425.htm" / "…_ex2-1.htm" is an EXHIBIT, not the form body. v2.0 let
# the digits inside "dex2425" match the 425 pattern and mislabelled it a filing.
IS_EXHIBIT = re.compile(r"(^|[^a-z])d?ex[-_]?\d", re.I)
PERIODIC = re.compile(r"10-?q|10-?k|20-?f|(q[1-4]|quarterly)[-_ ]?(20\d\d)?|earnings|results", re.I)
SKIP = re.compile(r"(\.jpg|\.png|\.gif|\.xml|\.xsd|FilingSummary|\.js$|\.css$|-index|"
                  r"\.xlsx?$|\.zip$)", re.I)
SKIP_XBRL = re.compile(r"^R\d+\.htm$")
# the complete-submission dump, e.g. 0001193125-16-449425.txt - not a document
SKIP_FULLSUB = re.compile(r"^\d{10}-\d{2}-\d{6}\.txt$|^\d{18}\.txt$")          # XBRL viewer pages only - anchored, case-SENSITIVE


def http_get(url, timeout=30):
    """GET with SEC-friendly headers; transparently gunzips. Returns (status, text)."""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            return getattr(r, "status", r.getcode()), raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        return e.code, body
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)


def read_index(folder):
    """
    Return (rows, form_type, filed_date) where rows = [(filename, description, type)].

    v2.3: EDGAR's filing-index table carries a Description ("Press Release",
    "Consent of J.P. Morgan", "Form of Proxy") and a Type ("EX-99.1", "8-K")
    for every document. Earlier versions ignored both and guessed from the
    filename, which is how an Exelon/PSEG consent-and-proxy exhibit became a
    "deck". Type and Description are now the primary signals.
    """
    acc = folder.rstrip("/").rsplit("/", 1)[-1]
    st, body = http_get("%s%s-index.htm" % (folder, acc))
    if st == 200 and body:
        rows = []
        for rm in re.finditer(r"<tr[^>]*>(.*?)</tr>", body, re.S | re.I):
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", rm.group(1), re.S | re.I)
            if len(cells) < 3:
                continue
            txt = [re.sub(r"<[^>]+>", " ", c).replace("&nbsp;", " ").strip() for c in cells]
            link = re.search(r'href="([^"]+)"', rm.group(1), re.I)
            if not link:
                continue
            fn = link.group(1).rsplit("/", 1)[-1]
            # locate which cell holds the anchor; description precedes it, type follows
            li = next((i for i, c in enumerate(cells) if "href=" in c.lower()), 1)
            desc = txt[li - 1] if li >= 1 else ""
            typ = txt[li + 1] if li + 1 < len(txt) else ""
            rows.append((fn, desc, typ))
        if not rows:
            for m in re.finditer(r'href="(/Archives/edgar/data/[^"]+\.(?:htm|html|txt|pdf))"', body, re.I):
                rows.append((m.group(1).rsplit("/", 1)[-1], "", ""))
        ft = re.search(r"Type:\s*</[^>]*>\s*([A-Z0-9/\-]+)", body) or re.search(r"type=([A-Z0-9\-]+)", body, re.I)
        fd = re.search(r"Filing Date.*?(\d{4}-\d{2}-\d{2})", body, re.S)
        if rows:
            return rows, (ft.group(1) if ft else ""), (fd.group(1) if fd else "")
    st2, body2 = http_get("%sindex.json" % folder)
    if st2 == 200:
        try:
            it = json.loads(body2)["directory"]["item"]
            return [(i["name"], "", i.get("type", "")) for i in it], "", ""
        except Exception:
            pass
    print("      ! index unavailable (htm %s, json %s)" % (st, st2))
    if st in (401, 403) and body:
        print("        SEC said: %s" % body.strip()[:180])
    return None, "", ""


# EDGAR Type strings -> our buckets
T991 = re.compile(r"^ex-?99\.?1$", re.I)
T992 = re.compile(r"^ex-?99\.?2$", re.I)
T993 = re.compile(r"^ex-?99\.?3$", re.I)
TDEAL = re.compile(r"^(8-?k.*|425|s-?4.*|def[ma]?14a|dfan14a|pre[rm]14a|sc\s?14d9|424b3)$", re.I)
TOFFER = re.compile(r"^424b[25]$", re.I)
# a description that means "this is a presentation"
DECKY = re.compile(r"present|slide|deck|investor\s*day|roadshow", re.I)
# v2.7: exhibit NUMBERING is a convention, not a rule. Dominion/Questar filed the
# merger agreement as EX-99.1, the press release as EX-99.2 and the call deck as
# EX-99.3 - trusting the number alone would file a contract as the press release.
# When EDGAR gives a Description, it decides.
DESC_PR   = re.compile(r"press\s*release|news\s*release|joint\s*release|joint\s*press", re.I)
DESC_DECK = re.compile(r"present|slide|deck|conference\s*call\s*material|investor\s*day|roadshow", re.I)
DESC_NOTDOC = re.compile(r"merger\s*agreement|agreement\s*and\s*plan|purchase\s*agreement|"
                         r"credit\s*agreement|indenture|e-?mail|video|employee|letter\s*to|"
                         r"transcript\s*of\s*video", re.I)


def looks_periodic(rows):
    """
    True when the accession is a quarterly/annual report rather than a deal
    announcement. Its EX-99.x exhibits are MD&A, financial statements,
    certifications, Reg-BTR notices - never a deal press release or deck, so
    they must not be harvested as such. (v2.4)
    """
    if not rows:
        return False
    if any(re.match(r"^10-?[QK]", t or "", re.I) for _f, _d, t in rows):
        return True
    hits = sum(1 for fn, desc, _t in rows if PERIODIC.search(fn) or PERIODIC.search(desc or ""))
    return hits >= max(2, len(rows) * 0.4)


def classify(rows, folder):
    """
    rows = [(filename, description, type)]. Type/Description win; filename is the
    fallback for old filings that predate a populated index table.
    """
    out = {"press_release": None, "deck": None, "filing": None,
           "offering": None, "periodic": None}
    base = folder.rstrip("/") + "/"
    rows = [r for r in rows if not SKIP.search(r[0]) and not SKIP_XBRL.match(r[0])
            and not SKIP_FULLSUB.match(r[0])]

    if looks_periodic(rows):
        # record where the figures came from, but claim no deal documents
        out["periodic"] = base + rows[0][0] if rows else None
        for fn, desc, typ in rows:
            if re.match(r"^10-?[QK]", typ or "", re.I) or PERIODIC.search(fn):
                out["periodic"] = base + fn
                break
        out["_periodic_accession"] = True
        return out

    def bad(desc, fn):
        return bool(NOTADECK.search(desc) or NOTADECK.search(fn))

    def periodic_doc(desc, fn):
        """This individual exhibit is a quarterly/annual document, not a deal doc."""
        return bool(PERIODIC.search(fn) or PERIODIC.search(desc or ""))

    # ---- pass 0: the DESCRIPTION is definitive when EDGAR supplies one ----
    for fn, desc, _typ in rows:
        if not desc or DESC_NOTDOC.search(desc):
            continue
        if DESC_PR.search(desc) and not out["press_release"] and not periodic_doc(desc, fn):
            out["press_release"] = base + fn
        elif DESC_DECK.search(desc) and not out["deck"] and not bad(desc, fn) and not periodic_doc(desc, fn):
            out["deck"] = base + fn

    # ---- pass 1: fall back to the Type column ----------------------------
    for fn, desc, typ in rows:
        if desc and DESC_NOTDOC.search(desc):
            continue                      # a contract/email, whatever its exhibit number
        if T991.match(typ) and not out["press_release"]:
            if periodic_doc(desc, fn):
                out["periodic"] = out["periodic"] or base + fn
            else:
                out["press_release"] = base + fn
        elif T992.match(typ) and not out["deck"] and not bad(desc, fn) and not periodic_doc(desc, fn):
            out["deck"] = base + fn
        elif TOFFER.match(typ) and not out["offering"]:
            out["offering"] = base + fn
        elif TDEAL.match(typ) and not out["filing"] and not IS_EXHIBIT.search(fn):
            out["filing"] = base + fn
    # EX-99.3 only when its DESCRIPTION actually says presentation
    if not out["deck"]:
        for fn, desc, typ in rows:
            if T993.match(typ) and DECKY.search(desc) and not bad(desc, fn):
                out["deck"] = base + fn
                break

    # ---- pass 2: filename fallback (older filings, empty index table) -----
    names = [r[0] for r in rows]
    descs = {r[0]: r[1] for r in rows}
    for n in names:
        dn = descs.get(n, "")
        if EX991.search(n) and not out["press_release"]:
            if periodic_doc(dn, n):
                out["periodic"] = out["periodic"] or base + n
            else:
                out["press_release"] = base + n
        elif EX992.search(n) and not out["deck"] and not bad(dn, n) and not periodic_doc(dn, n):
            out["deck"] = base + n
    if not out["press_release"]:
        for n in names:
            if (EX99_BARE.search(n) or PRESSY.search(n)) and not periodic_doc(descs.get(n, ""), n):
                out["press_release"] = base + n
                break
    if not out["deck"]:
        for n in names:
            d = descs.get(n, "")
            if EX993.search(n) and not bad(d, n):
                if d and not DECKY.search(d):
                    continue          # description says it is something else
                out["deck"] = base + n
                out["_deck_is_993"] = True
                break
    for n in names:
        if not n.lower().endswith((".htm", ".html", ".txt", ".pdf")) or IS_EXHIBIT.search(n):
            continue
        if OFFERING.search(n) and not out["offering"]:
            out["offering"] = base + n
        elif PERIODIC.search(n) and not out["periodic"]:
            out["periodic"] = base + n
        elif DEALFORM.search(n) and not out["filing"]:
            out["filing"] = base + n
    return out


def folder_of(links, deal_id=None):
    if deal_id and deal_id in KNOWN_ANCHORS:
        return KNOWN_ANCHORS[deal_id]
    fi = links.get("filing_index")
    if fi:
        m = FOLDER_RE.match(fi.rstrip("/") + "/")
        if m:
            return m.group(1) + "/"
    for k in ("press_release", "deck", "filing", "source_doc", "_legacy_deck_8k"):
        u = links.get(k)
        if u and "sec.gov" in u:
            m = ANYSEC_RE.match(u)
            if m:
                return m.group(1) + "/"
    return None


def is_wrong_for(key, url):
    """
    Only clear a value we can POSITIVELY identify as the wrong kind of document.
    v2.1 cleared anything the classifier failed to recognise, which wiped valid
    .txt-era filings, DFAN14A proxies and oddly-named press releases. Absence of
    a match is ignorance, not evidence.
    """
    n = url.rsplit("/", 1)[-1]
    if key == "deck":
        return bool(NOTADECK.search(n))
    if key == "filing":
        return bool(OFFERING.search(n) or IS_EXHIBIT.search(n)) or n.lower().endswith((".xlsx", ".xls", ".zip"))
    if key == "press_release":
        return n.lower().endswith((".xlsx", ".xls", ".zip"))
    return False


def is_dir_link(u):
    return bool(u) and bool(FOLDER_RE.match(u.rstrip("/") + "/"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DATA)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--diag", action="store_true")
    ap.add_argument("--report", action="store_true", help="link-coverage summary + gap list, no fetching")
    a = ap.parse_args()

    if a.diag:
        base = "https://www.sec.gov/Archives/edgar/data/78128/000155278125000341/"
        print("version :", VERSION)
        print("UA      :", UA)
        print("headers :", json.dumps(HEADERS, indent=10))
        for u in (base + "0001552781-25-000341-index.htm", base + "index.json"):
            st, body = http_get(u)
            print("\nGET %s\n  -> status %s, %d bytes" % (u, st, len(body)))
            print("  " + body[:300].replace("\n", " "))
        return

    print("resolve_edgar_links.py v%s\n" % VERSION)
    doc = json.load(open(a.data, encoding="utf-8"))
    deals = doc["deals"]

    if a.report:
        n = len(deals)
        def has(k):
            return sum(1 for x in deals if (x.get("links") or {}).get(k))
        print("LINK COVERAGE (n=%d)" % n)
        for k in ("press_release", "deck", "filing", "filing_index", "source_doc"):
            print("  %-14s %3d  (%d%%)" % (k, has(k), round(100.0 * has(k) / n)))
        src = {}
        for x in deals:
            p = (x.get("links") or {}).get("_pr_source")
            if p:
                src[p] = src.get(p, 0) + 1
        print("\n  press_release by approved source:")
        for k, v in sorted(src.items(), key=lambda t: -t[1]):
            print("    %-22s %3d" % (k, v))
        gaps = [x for x in deals if not (x.get("links") or {}).get("press_release")]
        print("\nNO PRESS RELEASE (%d) - candidates for a manual IR-site link:" % len(gaps))
        for x in sorted(gaps, key=lambda y: (y.get("announced") or ""), reverse=True):
            qc = (x.get("links") or {}).get("_link_qc")
            print("  %-40s %-12s %s" % (x["id"][:40], (x.get("announced") or "")[:10],
                                        "[flagged: " + qc[:44] + "]" if qc else ""))
        flagged = [x for x in deals if (x.get("links") or {}).get("_link_qc")]
        print("\nQC-FLAGGED ACCESSIONS (%d) - figures came from a non-announcement filing" % len(flagged))
        for x in flagged:
            print("  %-40s %s" % (x["id"][:40], x["links"]["_link_qc"][:70]))
        return

    targets = [d for d in deals if (not a.only or d["id"] == a.only)]
    print("%d deal(s) to inspect\n" % len(targets))

    changed = resolved = skipped = flagged = 0
    for d in targets:
        L = d.setdefault("links", {})
        folder = folder_of(L, d["id"])
        if not folder:
            skipped += 1
            continue
        need = a.refresh or any((not L.get(k)) or is_dir_link(L.get(k))
                                for k in ("press_release", "deck", "filing"))
        if not need:
            skipped += 1
            continue

        print("  %s" % d["id"])
        items, _form, filed = read_index(folder)
        time.sleep(SLEEP)
        if not items:
            continue
        resolved += 1
        if d["id"] in KNOWN_ANCHORS:
            L["filing_index"] = folder
        found = classify(items, folder)
        if d["id"] in KNOWN_PRESS_RELEASE and not found["press_release"]:
            u = KNOWN_PRESS_RELEASE[d["id"]]
            if L.get("press_release") != u:
                print("      press_release  -> (manual) %s" % u.split("/")[2])
                L["press_release"] = u
                L["_pr_source"] = "ir_site"
                changed += 1
        if d["id"] in KNOWN_DECK and not found["deck"]:
            u = KNOWN_DECK[d["id"]]
            if L.get("deck") != u:
                print("      deck           -> (manual) %s" % u.split("/")[2])
                L["deck"] = u
                changed += 1
        if d["id"] in KNOWN_NO_DECK:
            found["deck"] = None
            found.pop("_deck_is_993", None)
            if L.get("deck"):
                print("      deck           CLEARED (verified: no presentation in this accession)")
                L["deck"] = None
                changed += 1
            L.pop("_deck_qc", None)

        for k in ("press_release", "deck", "filing"):
            v, cur = found[k], L.get(k)
            # on --refresh, drop a stale value the corrected logic no longer finds
            if a.refresh and cur and not v and "sec.gov" in str(cur) and is_wrong_for(k, cur):
                print("      %-14s CLEARED (%s)" % (k, cur.rsplit("/", 1)[-1]))
                L[k] = None
                changed += 1
                continue
            if v and (a.refresh or not cur or is_dir_link(cur)) and cur != v:
                print("      %-14s -> %s" % (k, v.rsplit("/", 1)[-1]))
                L[k] = v
                changed += 1
                if k == "press_release":
                    L["_pr_source"] = "sec_ex99"

        # ---- QC: is this accession even the deal's filing? -----------------
        qc = []
        if not found["filing"] and not found["press_release"]:
            if found["offering"]:
                qc.append("accession is a 424B2/B5 securities OFFERING, not a deal filing")
                L.setdefault("source_doc", found["offering"])
            elif found["periodic"]:
                qc.append("accession is a periodic/earnings filing, not a deal announcement")
                L.setdefault("source_doc", found["periodic"])
        ann = (d.get("announced") or "")[:10]
        if filed and ann:
            try:
                fy, fm, fdd = map(int, filed.split("-"))
                ay, am, ad = map(int, ann.split("-"))
                months = (date(fy, fm, fdd) - date(ay, am, ad)).days / 30.44
                if abs(months) > 18:
                    qc.append("filing dated %s is %.0f months from announcement %s" % (filed, abs(months), ann))
            except Exception:
                pass
        if qc:
            L["_link_qc"] = "; ".join(qc)
            flagged += 1
            for q in qc:
                print("      [!] %s" % q)
        elif "_link_qc" in L:
            del L["_link_qc"]

        if found.get("_periodic_accession"):
            print("      (periodic accession - no deal documents harvested)")
        if found.get("_deck_is_993"):
            L["_deck_qc"] = "deck sourced from EX-99.3 (ambiguous exhibit) - verify it is a presentation"
            print("      [!] deck is EX-99.3 - verify it is actually a presentation")
        elif "_deck_qc" in L:
            del L["_deck_qc"]
        if not found["deck"]:
            print("      deck           - none filed (no EX-99.2/99.3 in this accession)")

    print("\nresolved %d | %d link(s) updated | %d flagged | %d skipped"
          % (resolved, changed, flagged, skipped))

    if a.write and (changed or flagged):
        shutil.copy2(a.data, a.data + ".bak")
        doc.setdefault("_merge_meta", {})["edgar_direct_links"] = (
            "links.press_release / deck / filing resolved to DIRECT document urls via the EDGAR filing "
            "index (resolve_edgar_links.py v2). filing_index kept as folder fallback. Nulls mean the "
            "exhibit genuinely isn't in the filing - most deals have no EX-99.2 deck. links._link_qc "
            "flags accessions that are NOT deal documents (424B2/B5 offerings, periodic reports, or "
            "filings dated far from announcement).")
        json.dump(doc, open(a.data, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        print("written %s  (backup: %s.bak)" % (a.data, os.path.basename(a.data)))
    elif changed or flagged:
        print("dry run - re-run with --write to apply")


if __name__ == "__main__":
    main()