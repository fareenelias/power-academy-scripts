r"""
resolve_agreements.py — precedents.json  (run locally; needs sec.gov reachable)

Fills two link slots the DB has never had:

  links.agreement        the merger / purchase agreement itself  (EX-2.x on the 8-K)
  links.fairness_opinion the banker's opinion, which lives in the MERGER PROXY
                         (S-4 / DEFM14A) or SC 14D9 -- never in the 8-K

Why the fairness opinion is worth the trouble: that section discloses the advisor's
OWN selected-precedent set, multiple ranges and DCF assumptions. It is both a deal
document and an independent cross-check on this database -- it tells you what
Goldman/Lazard/Evercore actually anchored to for each asset class.

CARRIES FORWARD THE LESSONS FROM THE EARLIER LINK PASS:
  * index.json 403s -- use <accession>-index.htm with browser-style headers
  * EDGAR's Type and Description columns are authoritative; FILENAMES ARE NOT.
    Dominion/Questar filed the merger agreement as EX-99.1.
  * "doesn't classify" != "is wrong" -- never clear a value we cannot re-derive
  * SKIP patterns must be anchored and case-SENSITIVE (R\d+\.htm ate real exhibits)
  * a correction pass must never clobber previously-found links

USAGE
  python resolve_agreements.py --dry-run          # report only, writes nothing
  python resolve_agreements.py                    # agreements only
  python resolve_agreements.py --fairness         # + hunt proxies (slower)
  python resolve_agreements.py --deep             # + pinpoint the opinion section
  python resolve_agreements.py --only nee_dominion_2026
"""

import json, io, re, sys, time, shutil, argparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# ---- data-file locator -----------------------------------------------------
# Resolves against the SCRIPT's location, not the shell's working directory, so
# this runs correctly from scripts\ , from data\ , or from anywhere else.
def _find_precedents():
    import os, sys
    for i, a in enumerate(sys.argv):
        if a == '--file' and i + 1 < len(sys.argv):
            p = os.path.abspath(sys.argv[i + 1])
            if os.path.isfile(p):
                return p
            raise SystemExit('--file given but not found: %s' % p)
    env = os.environ.get('PA_PRECEDENTS')
    if env and os.path.isfile(env):
        return os.path.abspath(env)
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [os.path.join(here, '..', 'data', 'precedents.json'),
             os.path.join(here, 'data', 'precedents.json'),
             os.path.join(here, 'precedents.json'),
             os.path.join(os.getcwd(), 'precedents.json'),
             r'E:\PowerAcademy\data\precedents.json']
    for c in cands:
        c = os.path.normpath(c)
        if os.path.isfile(c):
            return c
    raise SystemExit('precedents.json not found. Looked in:\n  ' +
                     '\n  '.join(os.path.normpath(c) for c in cands) +
                     '\n\nPass --file <path> or set PA_PRECEDENTS.')


SRC = _find_precedents()
# SEC requires a declared identity. EDIT THIS.
UA = 'Power Academy research (fareen.elias@example.com)'
HDRS = {
    'User-Agent': UA,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Encoding': 'gzip, deflate',
    'Accept-Language': 'en-US,en;q=0.9',
    'Host': 'www.sec.gov',
}
THROTTLE = 0.15          # SEC fair-access: <10 req/s

# ---- Type column: authoritative signal for the agreement
AGREEMENT_TYPES = re.compile(r'^EX-2(\.\d+)?$', re.I)
# ---- Description fallback, used ONLY when Type is uninformative (EX-99 cases)
AGREEMENT_DESC = re.compile(
    r'(agreement\s+and\s+plan\s+of\s+(merger|reorganization)|merger\s+agreement|'
    r'(stock|asset|equity)\s+purchase\s+agreement|purchase\s+and\s+sale\s+agreement|'
    r'transaction\s+agreement)', re.I)
# anchored + case-sensitive: R1.htm are EDGAR's rendered viewer files, but a real
# exhibit can legitimately be named r1_ex21.htm
SKIP_DOC = re.compile(r'^R\d+\.htm$')

# MERGER proxies only. "DEF 14A" is the ANNUAL MEETING proxy -- including it was
# the single biggest defect in v1: it matched an annual proxy years after the deal
# and every one of those links was wrong.
PROXY_FORMS = ('DEFM14A', 'DEFS14A', 'PREM14A', 'PRES14A', 'DEFC14A',
               'S-4', 'S-4/A', 'SC 14D9', 'SC 14D9/A')
# a merger proxy follows the announcement by months, not years
# 34 of 37 correct hits landed within 5 months; every wrong one was 7mo+.
MAX_LAG_MONTHS = 12
# CIKs known to be mis-assigned in this DB (caught by verify_ciks.py). Searching
# these returns a real company's filings for the WRONG deal.
BAD_CIKS = {1311370: 'Lazard — was mis-assigned to UIL Holdings'}
GENERIC = {'energy','power','utilities','utility','company','companies','group','holdings',
           'holding','corp','corporation','inc','llc','ltd','natural','gas','electric',
           'water','resources','partners','capital','infrastructure','american','national',
           'the','and','business','businesses','systems','service','services','light'}
# headings that are NOT a banker's fairness opinion
NOT_FAIRNESS = re.compile(
    r'opinion of (such )?(counsel|tax counsel|our counsel|the compensation|the corporate '
    r'governance|his|her|a nationally recognized|shareholders)', re.I)
# LAW FIRMS issue tax/legal opinions, not fairness opinions. "Opinion of Davis
# Polk" and "Opinion of Kirkland" both passed v2 and are both counsel.
LAW_FIRMS = re.compile(
    r'\b(davis polk|kirkland|skadden|wachtell|sullivan\s*&|cravath|latham|jones day|'
    r'morgan lewis|baker botts|mcguirewoods|troutman|hunton|simpson thacher|paul[, ]*weiss|'
    r'weil[, ]|sidley|gibson[, ]*dunn|covington|dentons|k&l gates|balch|cahill|choate|'
    r'husch blackwell|holland\s*&\s*knight|vinson|akin gump|debevoise|willkie|fried[, ]*frank|'
    r'cleary|white\s*&\s*case|norton rose|blake|osler|stikeman|torys|mccarthy|bennett jones|'
    r'davies|dewey|leboeuf|pillsbury|orrick|winston|mayer brown|ropes|shearman|'
    r'milbank|kramer|schulte|richards[, ]*layton|potter anderson|morris[, ]*nichols)\b', re.I)
# banks whose presence makes a heading near-certainly a fairness opinion
BANKS = re.compile(
    r'\b(goldman|morgan stanley|j\.?p\.? ?morgan|jpmorgan|lazard|barclays|citigroup|citi\b|'
    r'bank of america|merrill|credit suisse|ubs|deutsche|wells fargo|rbc|bmo|cibc|scotia|'
    r'td securities|moelis|evercore|centerview|guggenheim|jefferies|houlihan|duff\s*&\s*phelps|'
    r'perella|greenhill|rothschild|blackstone|pj solomon|tudor|keybanc|nomura|mizuho|'
    r'bnp|societe generale|macquarie|truist|pnc|us bancorp|raymond james|stifel|'
    r'donaldson|lufkin|jenrette|salomon|lehman|bear stearns|dresdner|schroder|'
    r'financial advisor|financial advisors)\b', re.I)
# a real one names the bank
FAIRNESS_HEAD = re.compile(
    r'Opinion of ((?:[A-Z][\w&.,\'-]+ ?){1,6})', re.S)
OPINION_PAT = re.compile(r'Opinion\s+of\s+[A-Z][\w&.,\' -]{2,60}', re.I)
ANCHOR_PAT = re.compile(r'<a[^>]+(?:name|id)=["\']([^"\']+)["\'][^>]*>(?:(?!</a>).){0,200}?'
                        r'Opinion\s+of', re.I | re.S)


def get(url, timeout=30):
    time.sleep(THROTTLE)
    h = dict(HDRS)
    h['Host'] = re.sub(r'^https?://([^/]+).*$', r'\1', url)
    try:
        with urlopen(Request(url, headers=h), timeout=timeout) as r:
            raw = r.read()
            if r.headers.get('Content-Encoding') == 'gzip':
                import gzip
                raw = gzip.decompress(raw)
            return raw.decode('utf-8', 'replace')
    except (HTTPError, URLError, OSError) as e:
        return None


def accession_index(folder):
    """folder -> the -index.htm url (index.json returns 403)."""
    f = folder.rstrip('/')
    acc = f.rsplit('/', 1)[-1]
    if re.fullmatch(r'\d{18}', acc):
        dashed = '%s-%s-%s' % (acc[:10], acc[10:12], acc[12:])
        return f + '/' + dashed + '-index.htm'
    return f + '/'


ROW = re.compile(r'<tr[^>]*>(.*?)</tr>', re.I | re.S)
CELL = re.compile(r'<t[dh][^>]*>(.*?)</t[dh]>', re.I | re.S)
TAG = re.compile(r'<[^>]+>')
HREF = re.compile(r'href=["\']([^"\']+)["\']', re.I)


def parse_index(html, base):
    """Return [{seq, desc, doc_url, doc_name, type}] from the filing index table."""
    out = []
    for rm in ROW.finditer(html or ''):
        cells = CELL.findall(rm.group(1))
        if len(cells) < 4:
            continue
        txt = [TAG.sub('', c).replace('&nbsp;', ' ').strip() for c in cells]
        href = None
        for c in cells:
            m = HREF.search(c)
            if m:
                href = m.group(1)
                break
        if not href:
            continue
        name = href.rsplit('/', 1)[-1]
        if SKIP_DOC.match(name):
            continue
        url = href if href.startswith('http') else 'https://www.sec.gov' + href
        # columns: Seq | Description | Document | Type | Size
        out.append({'seq': txt[0], 'desc': txt[1] if len(txt) > 1 else '',
                    'doc_name': name, 'type': txt[3] if len(txt) > 3 else '',
                    'url': url})
    return out


def pick_agreement(docs):
    # 1. Type column says EX-2.x -- authoritative
    for d in docs:
        if AGREEMENT_TYPES.match((d['type'] or '').strip()):
            return d, 'Type=%s' % d['type']
    # 2. Description names an agreement (catches the EX-99 filers)
    for d in docs:
        if AGREEMENT_DESC.search(d['desc'] or ''):
            return d, 'Description="%s"' % d['desc'][:60]
    # 3. do NOT guess from filename alone
    return None, None


def _months(a, b):
    return (int(b[:4]) * 12 + int(b[5:7])) - (int(a[:4]) * 12 + int(a[5:7]))


def _iter_filings(cik):
    """All filings, not just the `recent` window.

    v1 read only filings.recent (~1000 entries). For a 1999 deal the merger proxy
    is far outside that window, so nothing matched and it silently fell back to a
    modern annual proxy. The older filings live in sharded files[].
    """
    js = get('https://data.sec.gov/submissions/CIK%010d.json' % int(cik))
    if not js:
        return
    try:
        sub = json.loads(js)
    except ValueError:
        return
    rec = sub.get('filings', {}).get('recent', {})
    yield from zip(rec.get('form', []), rec.get('filingDate', []),
                   rec.get('accessionNumber', []), rec.get('primaryDocument', []))
    for shard in sub.get('filings', {}).get('files', []):
        nm = shard.get('name')
        if not nm:
            continue
        j2 = get('https://data.sec.gov/submissions/' + nm)
        if not j2:
            continue
        try:
            s2 = json.loads(j2)
        except ValueError:
            continue
        yield from zip(s2.get('form', []), s2.get('filingDate', []),
                       s2.get('accessionNumber', []), s2.get('primaryDocument', []))


def name_tokens(deal):
    """Distinctive words identifying the counterparties, for document validation."""
    toks = set()
    for fld in ('target', 'acquirer'):
        for w in re.split(r'[^A-Za-z]+', str(deal.get(fld) or '')):
            w = w.lower()
            if len(w) >= 4 and w not in GENERIC:
                toks.add(w)
    return toks


_CIK_CACHE = {}


def cik_by_name(name):
    """Look up a CIK from a company name via EDGAR company search.

    Needed because many deals only carry the ACQUIRER's CIK in their links, and
    the merger proxy is filed by the target. Returns None on any failure -- a
    miss must never become a wrong answer.
    """
    if not name:
        return None
    key = name.lower().strip()
    if key in _CIK_CACHE:
        return _CIK_CACHE[key]
    q = re.sub(r'[^A-Za-z0-9 ]', ' ', name)
    q = re.sub(r'\b(inc|llc|ltd|corp|corporation|company|co|holdings|group|the)\b',
               ' ', q, flags=re.I)
    q = ' '.join(q.split())
    if not q:
        _CIK_CACHE[key] = None
        return None
    url = ('https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=%s'
           '&type=DEF&dateb=&owner=include&count=10&output=atom'
           % q.replace(' ', '+'))
    xml = get(url)
    cik = None
    if xml:
        m = re.search(r'<cik>(\d+)</cik>', xml, re.I)
        if m:
            cik = int(m.group(1))
    if cik in BAD_CIKS:
        cik = None
    _CIK_CACHE[key] = cik
    return cik


def find_proxy(cik, announced, deal):
    """Merger proxies filed within MAX_LAG_MONTHS of announcement, oldest first."""
    if not cik or not announced:
        return []
    out = []
    for form, date, acc, prim in _iter_filings(cik):
        if form not in PROXY_FORMS or not date or not prim:
            continue
        lag = _months(announced, date)
        if lag < -1 or lag > MAX_LAG_MONTHS:
            continue
        a = acc.replace('-', '')
        out.append(('https://www.sec.gov/Archives/edgar/data/%d/%s/%s'
                    % (int(cik), a, prim), date, form, lag))
    out.sort(key=lambda x: x[1])
    return out[:4]


def validate_fo(url, deal):
    """A link is only written if the document proves it belongs to THIS deal.

    Two independent checks, both must pass:
      1. the document names a counterparty (kills annual proxies outright)
      2. it contains a real 'Opinion of <bank>' heading, not counsel boilerplate
    """
    html = get(url, timeout=60)
    if not html:
        return None, 'fetch failed'
    text = TAG.sub(' ', html[:8_000_000])
    low = text.lower()

    toks = name_tokens(deal)
    hit = [t for t in toks if t in low]
    if toks and not hit:
        return None, 'rejected: does not name %s' % ('/'.join(sorted(toks)[:3]))

    heads = [m for m in FAIRNESS_HEAD.finditer(text)
             if not NOT_FAIRNESS.search(m.group(0))
             and not LAW_FIRMS.search(m.group(1))]
    if not heads:
        return None, 'rejected: no banker fairness-opinion heading (counsel/tax only)'

    # prefer a heading that names an actual bank over a generic one
    banked = [m for m in heads if BANKS.search(m.group(1))]
    if not banked:
        return None, 'rejected: heading names neither a bank nor "financial advisor"'
    who = re.sub(r'\s+', ' ', banked[0].group(1)).strip(' ,.')

    tok = hit[0] if hit else 'no-token-check'
    m = ANCHOR_PAT.search(html)
    if m:
        return url + '#' + m.group(1), 'Opinion of %s (anchored, names %s)' % (who, tok)
    return url, 'Opinion of %s (names %s)' % (who, tok)


def find_agreement_filing(cik, announced):
    """Walk a company's 8-K filings for the one carrying EX-2.x.

    The announcement 8-K frequently does NOT contain the merger agreement -- it is
    filed a few days later in its own 8-K (this is why NEE, Black Hills and ALLETE
    all reported 'no agreement' from the announcement accession). This scans every
    8-K within a window of the announcement and checks each accession's index for
    an EX-2 document.
    """
    if not cik or not announced:
        return None
    hits = []
    for form, date, acc, prim in _iter_filings(cik):
        if not form.startswith('8-K') or not date:
            continue
        lag = _months(announced, date)
        if lag < -1 or lag > 6:                 # agreement filed within ~6mo
            continue
        a = acc.replace('-', '')
        idx = 'https://www.sec.gov/Archives/edgar/data/%d/%s/' % (int(cik), a)
        html = get(accession_index(idx))
        if not html:
            continue
        docs = parse_index(html, idx)
        pick, why = pick_agreement(docs)
        if pick:
            hits.append((abs(lag), pick['url'], pick['type'] or '?', date, why))
    hits.sort()
    return hits[0] if hits else None


def all_ciks(deal):
    """Every CIK associated with the deal, TARGET side first.

    The merger proxy is filed by the company whose shareholders vote -- the
    TARGET. v2 took whichever CIK appeared first, which is often the acquirer,
    so real proxies (Vectren, TECO, UIL, NV Energy) were reported as absent.
    """
    L = deal.get('links') or {}
    out, seen = [], set()
    order = ['press_release_target', 'press_release_target_ir',
             'filing_index', 'filing', 'agreement',
             'press_release_acquirer', 'press_release_acquirer_ir', 'press_release']
    for k in order:
        u = L.get(k)
        if not u:
            continue
        m = re.search(r'/edgar/data/(\d+)', str(u))
        if m:
            c = int(m.group(1))
            if c not in seen and c not in BAD_CIKS:
                seen.add(c)
                out.append(c)
    for u in (L.get('news') or []):
        m = re.search(r'/edgar/data/(\d+)', str(u))
        if m and int(m.group(1)) not in seen:
            seen.add(int(m.group(1)))
            out.append(int(m.group(1)))
    return out


def cands_ok(ciks):
    """True when we already hold a plausible filer CIK."""
    return bool(ciks)


def main():
    global MAX_LAG_MONTHS
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--fairness', action='store_true', help='hunt merger proxies')
    ap.add_argument('--deep', action='store_true', help='pinpoint the opinion section')
    ap.add_argument('--only', help='single deal id')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--file', help='explicit path to precedents.json')
    ap.add_argument('--all-scopes', action='store_true',
                    help='also hunt proxies for asset/portfolio deals (usually pointless)')
    ap.add_argument('--max-lag', type=int, default=MAX_LAG_MONTHS)
    a = ap.parse_args()
    if a.deep:
        a.fairness = True

    MAX_LAG_MONTHS = a.max_lag
    db = json.load(open(SRC, encoding='utf-8'))
    deals = db['deals']
    if a.only:
        deals = [d for d in deals if d['id'] == a.only]
        if not deals:
            print('no such deal'); return

    got = skipped = failed = fo_got = fetch_fail = 0
    fo_rej = fo_none = fo_skip = 0
    chosen = {}
    n = 0
    for d in deals:
        L = d.setdefault('links', {})
        idx = L.get('filing_index')

        # ---------------- merger agreement
        verified = (L.get('_verified') or {})
        if L.get('agreement') or verified.get('agreement') == 'human':
            skipped += 1                      # never clobber an existing/verified link
        elif not idx:
            pass
        else:
            n += 1
            if a.limit and n > a.limit:
                break
            html = get(accession_index(idx))
            if html is None:
                # a FETCH FAILURE is not evidence of absence. Record nothing,
                # count it separately, leave the deal for the next run.
                fetch_fail += 1
                print('  ...  %-32s fetch failed — retry, NOT recorded as absent' % d['id'])
                continue
            docs = parse_index(html, idx)
            pick, why = pick_agreement(docs)
            src_note = 'linked accession'
            if not pick:
                # the agreement is often in a SEPARATE 8-K from the announcement.
                # search the company's 8-K history for the one carrying EX-2.x.
                for cik in all_ciks(d):
                    res = find_agreement_filing(cik, d.get('announced'))
                    if res:
                        _lag, url, typ, dt, why2 = res
                        pick = {'url': url, 'type': typ}
                        why = '%s (separate 8-K %s)' % (why2, dt)
                        src_note = 'searched history'
                        break
            if pick:
                got += 1
                print('  AGR  %-32s %-14s %s [%s]' % (d['id'], pick['type'] or '?', why, src_note))
                if not a.dry_run:
                    L['agreement'] = pick['url']
                    L['_agreement_src'] = why
            else:
                failed += 1
                if not a.dry_run and docs:
                    L['_agreement_qc'] = ('no EX-2 in the linked accession OR any 8-K '
                                          'within 6mo of announcement — likely filed as '
                                          'Annex A to the S-4')
                print('  ---  %-32s no agreement in accession or 8-K history' % d['id'])

        # ---------------- fairness opinion
        # An asset carve-out or portfolio purchase has no target shareholder vote,
        # so no merger proxy exists. Hunting one only finds the PARENT's proxy for
        # a DIFFERENT deal -- which is how AWK/Nexus picked up the AWK/Essential
        # S-4 and NorthWestern/Energy West picked up the Black Hills proxy.
        if (a.fairness and not L.get('fairness_opinion')
                and d.get('deal_scope') not in ('whole_company',) and not a.all_scopes):
            fo_skip += 1
        elif a.fairness and not L.get('fairness_opinion'):
            ciks = all_ciks(d)
            if not ciks or not cands_ok(ciks):
                for nm in (d.get('target'), d.get('acquirer')):
                    c = cik_by_name(nm)
                    if c and c not in ciks:
                        ciks.append(c)
            cands = []
            for cik in ciks:
                cands += find_proxy(cik, d.get('announced'), d)
                if len(cands) >= 6:
                    break
            cands.sort(key=lambda x: x[1])
            if not cands:
                fo_none += 1
                print('  fo-  %-32s no merger proxy within %dmo of %s'
                      % (d['id'], MAX_LAG_MONTHS, d.get('announced')))
            else:
                accepted = False
                for url, dt, fm, lag in cands:
                    ok_url, why = validate_fo(url, d)
                    if ok_url:
                        fo_got += 1
                        accepted = True
                        print('  FO   %-32s %-9s %s (+%2dmo)  %s'
                              % (d['id'], fm, dt, lag, why))
                        chosen[d['id']] = (ok_url, fm, dt, lag, why, L)
                        break
                if not accepted:
                    fo_rej += 1
                    print('  fo!  %-32s %d candidate(s) ALL REJECTED — %s'
                          % (d['id'], len(cands), why))

    # ---- duplicate backstop -------------------------------------------------
    # Two deals cannot share one merger proxy. Where they do, the smaller lag is
    # the real one and the other is a company's later proxy that merely mentions
    # the older counterparty somewhere in 400 pages.
    bykey = {}
    for did, rec in chosen.items():
        bykey.setdefault(rec[0].split('#')[0], []).append((rec[3], did))
    dropped = 0
    for url, lst in bykey.items():
        if len(lst) < 2:
            continue
        lst.sort()
        keep = lst[0][1]
        for lag, did in lst[1:]:
            print('  DUP  %-32s +%dmo shares a proxy with %s (+%dmo) — DROPPED'
                  % (did, lag, keep, lst[0][0]))
            chosen.pop(did, None)
            dropped += 1
            fo_got -= 1
            fo_rej += 1
    if dropped:
        print('  %d duplicate proxy link(s) dropped\n' % dropped)

    if not a.dry_run:
        for did, (url, fm, dt, lag, why, L) in chosen.items():
            L['fairness_opinion'] = url
            L['_fo_src'] = '%s filed %s (+%dmo) — %s' % (fm, dt, lag, why)
        shutil.copyfile(SRC, SRC + '.bak_resolve')
        with io.open(SRC, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
            f.write('\n')

    print('\nagreements found %d · already had %d · unidentified %d · fetch failed %d'
          % (got, skipped, failed, fetch_fail))
    if fetch_fail:
        print('  %d deals could not be reached — re-run; they are untouched.' % fetch_fail)
    if a.fairness:
        print('fairness opinions ACCEPTED %d · rejected %d · no proxy in window %d '
              '· skipped (no shareholder vote) %d'
              % (fo_got, fo_rej, fo_none, fo_skip))
        print('  (v1 wrote 68, of which 53 were wrong. A rejection here is the '
              'script working, not failing.)')
    print('DRY RUN — nothing written' if a.dry_run else 'written (backup .bak_resolve)')


if __name__ == '__main__':
    main()