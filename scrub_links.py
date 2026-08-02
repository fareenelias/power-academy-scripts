r"""
scrub_links.py — precedents.json  (local; needs sec.gov reachable)

A HARD SCRUB across all 118 deals, not a patch of the ones that got QC'd.

Fareen's QC of 6 deals found the same handful of defects repeatedly, which means
they are patterns, not incidents. Each one below is applied to EVERY deal:

  P1 JOINT RELEASE MISLABELLED (64 deals)
     press_release_target == press_release_acquirer means ONE joint release was
     linked twice and presented as two-sided coverage. Relabel it honestly as
     `press_release_joint` and clear the fake per-side fields.

  P2 BAMSEC -> SEC (global rule)
     bamsec is a paywalled wrapper. Convert /filing/<accession>/<n>?cik=<cik>
     to the underlying sec.gov Archives document.

  P3 DECKS MISSED (only 24/118 had one)
     Root cause: the agreement often lives in a SEPARATE 8-K from the
     announcement; the resolver found that accession, took ONE document, and
     discarded the rest. The deck, press release and any transcript are usually
     in that SAME accession. So: harvest EVERY document from every accession we
     know about, and classify all of them.

  P4 DEAD LINKS NEVER CHECKED (SCANA's press release is a 404)
     Validate every URL; demote 404s and record what broke.

  P5 WRONG DOC CLASSIFIED AS A DECK (ALLETE got a dividend declaration)
     An EX-99.2 is not automatically a deck. Require presentation-like wording
     and reject dividend/earnings/routine notices.

Never touches links._verified[field] == 'human'.

  python scrub_links.py --dry-run          # full report, writes nothing
  python scrub_links.py                    # apply
  python scrub_links.py --no-net           # offline fixes only (P1, dup detection)
  python scrub_links.py --only <deal_id>
"""

import json, io, os, re, sys, time, shutil, argparse, importlib.util
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    'ra', os.path.join(HERE, 'resolve_agreements.py'))
ra = importlib.util.module_from_spec(_spec)
_argv = sys.argv
sys.argv = ['scrub']
_spec.loader.exec_module(ra)
sys.argv = _argv

SRC = ra.SRC

# --file must be honoured by THIS script: the ra import masks sys.argv so the
# shared locator never sees it, which silently wrote to the default file.
def _src_override(default):
    import sys, os
    for i, a in enumerate(sys.argv):
        if a == '--file' and i + 1 < len(sys.argv):
            p = os.path.abspath(sys.argv[i + 1])
            if not os.path.isfile(p):
                raise SystemExit('--file not found: %s' % p)
            return p
    return default


SRC = _src_override(SRC)

# ---------------------------------------------------------------- fetch cache
# A full pass makes thousands of throttled SEC requests. Without a cache, any
# interruption throws all of that away and the restart is as slow as the first
# run. Cache on disk, keyed by URL, so re-runs replay instantly.
CACHE_DIR = os.path.join(os.path.dirname(SRC), '_sec_cache')


def _cache_path(url):
    import hashlib
    return os.path.join(CACHE_DIR, hashlib.md5(url.encode('utf-8')).hexdigest() + '.txt')


_raw_get = ra.get


def cached_get(url, timeout=30):
    if not url:
        return None
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        cp = _cache_path(url)
        if os.path.isfile(cp):
            with io.open(cp, encoding='utf-8') as f:
                v = f.read()
            return v if v else None
        v = _raw_get(url, timeout=timeout)
        if v is not None:
            with io.open(cp, 'w', encoding='utf-8') as f:
                f.write(v)
        return v
    except Exception:
        return _raw_get(url, timeout=timeout)


ra.get = cached_get      # every helper inherits the cache

PR_FIELDS = ('press_release', 'press_release_target', 'press_release_acquirer')

# ---------------------------------------------------------------- classifiers
EX2 = re.compile(r'^EX-2(\.\d+)?$', re.I)
EX99 = re.compile(r'^EX-99(\.\d+)?$', re.I)
# XBRL + technical exhibits are machine-readable plumbing, never deal documents.
# EX-101.PRE is the "XBRL TAXONOMY EXTENSION PRESENTATION LINKBASE" -- the word
# 'PRESENTATION' in it matched the deck pattern and produced fake decks.
TECHNICAL_TYPE = re.compile(r'^(EX-101(\.\w+)?|EX-104|GRAPHIC|XML|EX-100(\.\w+)?|JSON)$', re.I)
TECHNICAL_DESC = re.compile(
    r'(xbrl|taxonomy|linkbase|inline\s+xbrl|instance\s+document|schema\s+document|'
    r'cover\s+page\s+interactive|calculation\s+link|definition\s+link|label\s+link)', re.I)

AGREEMENT_DESC = re.compile(
    r'(agreement\s+and\s+plan\s+of\s+(merger|reorganization)|merger\s+agreement|'
    r'(stock|asset|equity|membership\s+interest)\s+purchase\s+agreement|'
    r'purchase\s+and\s+sale\s+agreement|transaction\s+agreement)', re.I)

# a DECK says presentation/slides/investor. ALLETE's mislink was a dividend notice.
DECK_DESC = re.compile(
    r'(investor\s+present|analyst\s+present|conference\s+present|merger\s+present|'
    r'transaction\s+present|investor\s+update|slide\s*(deck|show|presentation)?\b|'
    r'\bdeck\b|presentation\s+(materials|slides)|^present(ation)?s?$)', re.I)
NOT_DECK = re.compile(
    r'(dividend|earnings\s+release|quarterly\s+result|annual\s+report|'
    r'certification|consent|opinion|indenture|by-?laws|charter|'
    r'financial\s+statement|pro\s*forma|credit\s+agreement|'
    r'xbrl|taxonomy|linkbase|instance\s+document|schema)', re.I)

# EDGAR very often writes the description as just the exhibit number
# ("EX-99.2", "EXHIBIT 99.2") or leaves it blank. A deck filed that way is
# invisible to any description-based rule, which is why the first harvest
# returned zero decks. Those cases get a content check instead.
UNINFORMATIVE = re.compile(r'^\s*(ex-?|exhibit\s*)?\d{1,3}(\.\d+)?\s*$', re.I)
DECK_FILENAME = re.compile(r'(pres|deck|slide|invpres|ip\d|investor)', re.I)
# NB: "forward-looking statements" was in this list and is USELESS as a signal --
# every press release, 8-K and 10-K carries that disclaimer, so any short document
# containing it scored as a deck. Only wording that is actually distinctive of a
# presentation belongs here.
# Terms must be DISTINCTIVE of a slide deck. "synergies", "value creation" and
# "compelling strategic rationale" are standard merger press-release language and
# were letting press releases score as decks -- the same failure as
# "forward-looking statements", one revision later. What survives here is wording
# that appears in deck section headers and essentially nowhere else.
# Wording is now TIERED, because a single flat list keeps admitting boilerplate.
# Three revisions taught this the hard way: "forward-looking statements" is in
# every filing; "synergies"/"value creation" are in every merger press release;
# "page N of M" is a document footer (a deck says "Slide 4", a 3-page document
# says "Page 2 of 3" -- the opposite signal).
#
# STRONG: names the document a presentation. Stands alone, because pre-2005 decks
#         were often filed as text with no images at all.
DECK_STRONG = re.compile(
    r'(investor\s+present\w*|analyst\s+present\w*|management\s+present\w*|'
    r'investor\s+day|slide\s+presentation|presentation\s+slides)', re.I)
# WEAK: deck section headers that also occur in prose documents. Only counts
#       alongside real slide imagery.
DECK_WEAK = re.compile(
    r'(transaction\s+overview|combination\s+overview|agenda\b|appendix\b|'
    r'non-?gaap\s+reconciliation|slide\s+\d)', re.I)
DECK_BODY = DECK_STRONG      # back-compat for anything referencing the old name
PR_BODY = re.compile(r'(for\s+immediate\s+release|media\s+contact|investor\s+contact|'
                     r'##\s*$|about\s+the\s+company)', re.I)


def looks_like_deck(url):
    """Content check for an EX-99.x whose description tells us nothing.

    A deck is mostly slides: many images, short text, presentation wording.
    A press release is prose with wire-service furniture. Returns (bool, why).
    """
    html = ra.get(url, timeout=45)
    if not html:
        return False, 'fetch failed'
    imgs = len(re.findall(r'<img\b', html, re.I))
    text = ra.TAG.sub(' ', html)
    text = re.sub(r'\s+', ' ', text).strip()
    words = len(text.split())
    _s = DECK_STRONG.search(text[:20000])
    _w = DECK_WEAK.search(text[:20000])
    pr_hit = bool(PR_BODY.search(text[:6000]))
    if pr_hit and imgs < 5:
        return False, 'reads as a press release'
    # 1. genuinely image-heavy: slides exported as pictures
    if imgs >= 10:
        return True, 'image-heavy (%d imgs, %d words)' % (imgs, words)
    # 2. the document calls itself a presentation — decisive on its own
    if _s and words < 8000:
        return True, 'names itself "%s" (%d imgs, %d words)' % (_s.group(0)[:26], imgs, words)
    # 3. deck section headers only count with real slide imagery behind them
    if _w and imgs >= 5 and words < 5000:
        return True, 'section "%s" + %d imgs' % (_w.group(0)[:22], imgs)
    if imgs >= 8:
        return True, 'image-heavy (%d imgs, %d words)' % (imgs, words)
    return False, '%d imgs / %d words — not deck-like' % (imgs, words)


PR_DESC = re.compile(r'(press\s+release|news\s+release|joint\s+release|announcement)', re.I)
# Deal-announcement call transcripts are filed as 8-K exhibits far less often than
# decks, but where they exist they are the richest source in the filing: analysts
# ask the awkward questions about the multiple that the deck never addresses.
TRANSCRIPT_DESC = re.compile(
    r'(transcript|conference\s+call|investor\s+call|analyst\s+call|'
    r'earnings\s+call|call\s+with\s+(investors|analysts)|'
    r'prepared\s+remarks|webcast)', re.I)
TRANSCRIPT_BODY = re.compile(
    r'(operator[:\s]|question[- ]and[- ]answer|q\s*&\s*a\s+session|'
    r'thank\s+you.{0,30}operator|your\s+first\s+question|'
    r'\[\s*operator\s+instructions)', re.I)


def looks_like_transcript(url):
    """Content check: a transcript has an operator, questions and speaker turns."""
    html = ra.get(url, timeout=45)
    if not html:
        return False, 'fetch failed'
    text = re.sub(r'\s+', ' ', ra.TAG.sub(' ', html))
    hits = len(TRANSCRIPT_BODY.findall(text[:60000]))
    if hits >= 2:
        return True, 'transcript markers x%d' % hits
    return False, 'no operator/Q&A markers'


def norm_text(html):
    """Strip to comparable prose for joint-release detection."""
    if not html:
        return ''
    t = re.sub(r'(?is)<(script|style).*?</\1>', ' ', html)
    t = ra.TAG.sub(' ', t)
    t = re.sub(r'&[a-z#0-9]+;', ' ', t)
    t = re.sub(r'[^a-z0-9 ]+', ' ', t.lower())
    return ' '.join(t.split())


def same_release(u1, u2):
    """True when two urls are the SAME press release hosted in two places.

    Fareen's Black Hills case: target and acquirer point at different URLs but
    it is one joint release (the target hosts a PDF, the acquirer files the
    EX-99.1). Labelling those 'target release' and 'acquirer release' implies
    two documents with different framing, which overstates the coverage.
    Compared on shingled token overlap; short/failed fetches return None.
    """
    a, b = norm_text(ra.get(u1, timeout=45)), norm_text(ra.get(u2, timeout=45))
    if len(a) < 400 or len(b) < 400:
        return None, 'could not compare (fetch/short)'
    A = set(zip(a.split(), a.split()[1:], a.split()[2:]))
    B = set(zip(b.split(), b.split()[1:], b.split()[2:]))
    if not A or not B:
        return None, 'no shingles'
    j = len(A & B) / float(min(len(A), len(B)))
    return (j >= 0.80), 'trigram overlap %.0f%%' % (100 * j)


def _months(a, b):
    return (int(b[:4]) * 12 + int(b[5:7])) - (int(a[:4]) * 12 + int(a[5:7]))


# ---------------------------------------------------------------- bamsec -> SEC
BAMSEC = re.compile(r'bamsec\.com/filing/(\d+)(?:/(\d+))?[^0-9]*(?:cik=(\d+))?', re.I)


def bamsec_to_sec(url, fetch=True):
    """Convert a bamsec filing URL to the underlying sec.gov document URL.

    bamsec /filing/<accession-no-dashes>/<docnum>?cik=<cik>
    The docnum is the row position in EDGAR's filing index.
    """
    m = BAMSEC.search(url or '')
    if not m:
        return None, 'not a bamsec url'
    acc_raw, docnum, cik = m.group(1), m.group(2), m.group(3)
    acc = acc_raw.zfill(18)
    if not cik:
        return None, 'bamsec url has no cik'
    folder = 'https://www.sec.gov/Archives/edgar/data/%d/%s/' % (int(cik), acc)
    if not fetch:
        return folder, 'folder only (no fetch)'
    html = ra.get(ra.accession_index(folder))
    if not html:
        return folder, 'index fetch failed — folder link'
    docs = ra.parse_index(html, folder)
    if not docs:
        return folder, 'index parsed empty — folder link'
    if docnum:
        i = int(docnum) - 1
        if 0 <= i < len(docs):
            return docs[i]['url'], 'doc #%s (%s)' % (docnum, docs[i].get('type') or '?')
    return folder, 'docnum out of range — folder link'


# ---------------------------------------------------------------- link check
def check(url):
    """Return (ok, note). A 404 is a real failure; a timeout is not evidence."""
    if not url or not url.startswith('http'):
        return True, 'skipped'
    try:
        time.sleep(0.12)
        req = Request(url, headers={'User-Agent': ra.UA,
                                    'Accept': '*/*',
                                    'Accept-Encoding': 'gzip, deflate'})
        with urlopen(req, timeout=25) as r:
            return (200 <= r.status < 400), 'HTTP %d' % r.status
    except HTTPError as e:
        if e.code in (403, 429):
            return True, 'HTTP %d (blocked/throttled — not treated as dead)' % e.code
        return False, 'HTTP %d' % e.code
    except (URLError, OSError) as e:
        return True, 'unreachable (%s) — not treated as dead' % type(e).__name__


# ---------------------------------------------------------------- accession harvest
def accessions_of(d):
    """Every EDGAR accession folder we know about for a deal."""
    L = d.get('links') or {}
    out, seen = [], set()
    for k in ('filing_index', 'agreement', 'filing', 'deck', 'press_release',
              'press_release_target', 'press_release_acquirer', 'source_doc'):
        u = L.get(k)
        if not isinstance(u, str) or 'sec.gov/Archives' not in u:
            continue
        m = re.match(r'(https://www\.sec\.gov/Archives/edgar/data/\d+/\d+)/', u)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            out.append(m.group(1) + '/')
    return out


def classify_docs(docs, deep=True):
    """Classify EVERY document in an accession listing.

    Previous passes took one document and threw the rest away -- which is why
    decks sat unlinked in the very accession the agreement came from.
    """
    found = {}
    for doc in docs:
        typ = (doc.get('type') or '').strip()
        desc = doc.get('desc') or ''
        url = doc['url']
        # XBRL/technical exhibits are never agreements, decks, PRs or transcripts
        if TECHNICAL_TYPE.match(typ) or TECHNICAL_DESC.search(desc):
            continue
        if re.search(r'\.(xsd|xml|json)$', url, re.I):
            continue
        if 'agreement' not in found and (EX2.match(typ) or AGREEMENT_DESC.search(desc)):
            found['agreement'] = (url, 'Type=%s desc=%s' % (typ, desc[:40]))
            continue
        if EX99.match(typ) or desc:
            # deck must LOOK like a deck and must not be a routine notice
            if ('deck' not in found and DECK_DESC.search(desc)
                    and not NOT_DECK.search(desc)):
                found['deck'] = (url, 'Type=%s desc=%s' % (typ, desc[:40]))
                continue
            # description says nothing: EX-99.2+ is a deck candidate (99.1 is the
            # press release). Decide on the document's own content.
            if ('deck' not in found and deep and EX99.match(typ)
                    and not typ.lower().endswith('.1')
                    and (UNINFORMATIVE.match(desc.strip()) or not desc.strip())):
                ok, why = looks_like_deck(url)
                if ok:
                    found['deck'] = (url, 'Type=%s content: %s' % (typ, why))
                    continue
            if 'transcript' not in found and TRANSCRIPT_DESC.search(desc):
                found['transcript'] = (url, 'desc=%s' % desc[:40])
                continue
            # description says nothing: a late EX-99 in a deal filing may still be
            # the call transcript — decide on the document's own content.
            if ('transcript' not in found and deep and EX99.match(typ)
                    and not typ.lower().endswith('.1')
                    and (UNINFORMATIVE.match(desc.strip()) or not desc.strip())):
                okt, whyt = looks_like_transcript(url)
                if okt:
                    found['transcript'] = (url, 'content: %s' % whyt)
                    continue
            if 'press_release' not in found and PR_DESC.search(desc):
                found['press_release'] = (url, 'Type=%s desc=%s' % (typ, desc[:40]))
                continue
    return found


def harvest(folder):
    """Classify every document in ONE known accession."""
    html = ra.get(ra.accession_index(folder))
    if not html:
        return None
    return classify_docs(ra.parse_index(html, folder))


# ------------------------------------------------- P3b: full history harvest
GENERIC_TOK = {'energy','power','utilities','utility','company','companies','group',
               'holdings','holding','corp','corporation','inc','llc','ltd','natural',
               'gas','electric','water','resources','partners','capital','the','and',
               'infrastructure','american','national','services','service','systems'}


def deal_tokens(d):
    """Distinctive counterparty words, used to tell a DEAL 8-K from a routine one."""
    toks = set()
    for fld in ('target', 'acquirer'):
        for w in re.split(r'[^A-Za-z]+', str(d.get(fld) or '')):
            w = w.lower()
            if len(w) >= 4 and w not in GENERIC_TOK:
                toks.add(w)
    return toks


DEAL_DESC = re.compile(
    r'(merger|acquisition|acquire|purchase\s+agreement|combination|'
    r'business\s+combination|definitive\s+agreement)', re.I)
# routine corporate 8-Ks that must never be mined for deal documents
ROUTINE = re.compile(
    r'(dividend|earnings|quarterly\s+result|annual\s+result|results\s+of\s+operation|'
    r'financial\s+result|monthly\s+operating|director\s+election|'
    r'annual\s+meeting|officer\s+appointment|retirement\s+of)', re.I)


def _days(a, b):
    import datetime as _dt
    try:
        d1 = _dt.date(int(a[:4]), int(a[5:7]), int(a[8:10]))
        d2 = _dt.date(int(b[:4]), int(b[5:7]), int(b[8:10]))
        return abs((d2 - d1).days)
    except Exception:
        return 9999


def is_deal_filing(docs, toks, filed=None, announced=None):
    """Relevance gate for walking a company's 8-K history.

    Naming ONE party is not evidence of a deal filing -- a dividend 8-K filed by
    ALLETE obviously says "ALLETE". That is precisely how a "stub period dividend"
    notice ended up linked as ALLETE's deal deck. So routine-filing wording VETOES,
    and a name match only counts when BOTH sides appear or deal wording is present.
    """
    blob = ' '.join((doc.get('desc') or '') for doc in docs).lower()

    # 1. an EX-2 is decisive — merger agreements are not filed with routine 8-Ks
    for doc in docs:
        if EX2.match((doc.get('type') or '').strip()):
            return True, 'has EX-2'

    # 1b. EDGAR often gives no prose description at all (desc == "EX-99.2"), which
    # left deck-only filings unreachable by any wording test. A filing made within
    # days of the announcement IS the deal filing, whatever its descriptions say.
    if filed and announced and _days(announced, filed) <= 5:
        if not ROUTINE.search(' '.join((d.get('desc') or '') for d in docs).lower()):
            return True, 'filed %dd from announcement' % _days(announced, filed)

    # 2. routine corporate filings VETO, regardless of whose name is on them
    if ROUTINE.search(blob) and not DEAL_DESC.search(blob):
        return False, 'routine filing (dividend/earnings/results)'

    # 3. explicit transaction wording
    if DEAL_DESC.search(blob):
        return True, 'deal wording'

    # 4. BOTH counterparties named in the same filing
    hits = [t for t in toks if t in blob]
    if len(hits) >= 2:
        return True, 'names both parties'

    return False, 'no deal signal'


def harvest_history(d, months=6, max_filings=25):
    """Every deal-related 8-K near announcement -> best doc per field.

    This is the general form of the fix. Harvesting only ALREADY-LINKED
    accessions reaches 82 of 118 deals and finds a deck only if it happens to
    sit in the one filing already on record -- but deal documents are routinely
    split across several 8-Ks.
    """
    ann = d.get('announced')
    if not ann:
        return {}, 'no announce date'
    ciks = ra.all_ciks(d)
    if not ciks:
        for nm in (d.get('target'), d.get('acquirer')):
            c = ra.cik_by_name(nm)
            if c:
                ciks.append(c)
    if not ciks:
        return {}, 'no CIK'

    toks = deal_tokens(d)
    best, seen, checked = {}, set(), 0
    for cik in ciks[:2]:
        for form, date, acc, prim in ra._iter_filings(cik):
            if not form.startswith('8-K') or not date:
                continue
            lag = _months(ann, date)
            if lag < -1 or lag > months:
                continue
            a2 = acc.replace('-', '')
            if a2 in seen:
                continue
            seen.add(a2)
            checked += 1
            if checked > max_filings:
                break
            folder = 'https://www.sec.gov/Archives/edgar/data/%d/%s/' % (int(cik), a2)
            html = ra.get(ra.accession_index(folder))
            if not html:
                continue
            docs = ra.parse_index(html, folder)
            ok, why = is_deal_filing(docs, toks, filed=date, announced=ann)
            if not ok:
                continue
            got = classify_docs(docs)
            for k, v in got.items():
                if k not in best:
                    best[k] = (v[0], '%s [8-K %s, %s]' % (v[1], date, why))
    return best, 'checked %d filings' % checked


# ---------------------------------------------------------------- main
def diagnose(d, months=6):
    """Print every decision for ONE deal: which filings were checked, whether the
    relevance gate passed, and how each document was classified. Guessing at why
    a harvest found nothing is how bugs survive; this shows the actual path."""
    print('=' * 74)
    print('DIAGNOSE  %s   announced %s   scope=%s'
          % (d['id'], d.get('announced'), d.get('deal_scope')))
    L = d.get('links') or {}
    ver = L.get('_verified') or {}
    print('  current: ' + ', '.join('%s=%s' % (k, 'SET' if L.get(k) else '-')
                                    for k in ('agreement', 'deck', 'press_release', 'transcript')))
    print('  verified: %s   needs_find: %s' % (list(ver), L.get('_needs_find')))
    want = [f for f in ('agreement', 'deck', 'press_release', 'transcript')
            if not L.get(f) and ver.get(f) != 'human'
            and f not in (L.get('_needs_find') or [])]
    print('  WANT: %s' % (want or 'nothing — harvest will be skipped entirely'))
    if not want:
        return
    ciks = ra.all_ciks(d)
    print('  CIKs from links: %s' % (ciks or 'NONE'))
    if not ciks:
        for nm in (d.get('target'), d.get('acquirer')):
            c = ra.cik_by_name(nm)
            print('    name lookup %-28s -> %s' % (nm, c))
            if c:
                ciks.append(c)
    if not ciks:
        print('  -> no CIK, harvest impossible'); return
    toks = deal_tokens(d)
    print('  counterparty tokens: %s' % sorted(toks))
    ann = d.get('announced')
    seen = set()
    for cik in ciks[:2]:
        for form, date, acc, prim in ra._iter_filings(cik):
            if not form.startswith('8-K') or not date:
                continue
            lag = _months(ann, date)
            if lag < -1 or lag > months:
                continue
            a2 = acc.replace('-', '')
            if a2 in seen:
                continue
            seen.add(a2)
            folder = 'https://www.sec.gov/Archives/edgar/data/%d/%s/' % (int(cik), a2)
            html = ra.get(ra.accession_index(folder))
            if not html:
                print('  8-K %s  INDEX FETCH FAILED' % date); continue
            docs = ra.parse_index(html, folder)
            ok, why = is_deal_filing(docs, toks, filed=date, announced=ann)
            print('  8-K %s  %-28s %s' % (date, ('GATE: ' + why), '(%d docs)' % len(docs)))
            if not ok:
                continue
            for doc in docs:
                typ = (doc.get('type') or '').strip()
                desc = (doc.get('desc') or '')[:44]
                mark = ''
                if TECHNICAL_TYPE.match(typ) or TECHNICAL_DESC.search(desc):
                    mark = 'skip: technical'
                elif EX2.match(typ) or AGREEMENT_DESC.search(desc):
                    mark = '-> AGREEMENT'
                elif EX99.match(typ) and not typ.lower().endswith('.1') and (
                        UNINFORMATIVE.match(desc.strip()) or not desc.strip()):
                    okd, whyd = looks_like_deck(doc['url'])
                    mark = ('-> DECK (%s)' % whyd) if okd else ('no deck: %s' % whyd)
                elif DECK_DESC.search(desc) and not NOT_DECK.search(desc):
                    mark = '-> DECK (desc)'
                elif PR_DESC.search(desc):
                    mark = '-> PRESS'
                print('        %-12s %-46s %s' % (typ, desc, mark))
    print('=' * 74)


def _p(msg):
    """Print a finding on a clean line, above the progress indicator."""
    sys.stdout.write('\r' + ' ' * 100 + '\r')
    print(msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--no-net', action='store_true', help='offline fixes only')
    ap.add_argument('--only')
    ap.add_argument('--file')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--skip-check', action='store_true', help='skip 404 validation')
    ap.add_argument('--quiet', action='store_true', help='no progress line')
    ap.add_argument('--diagnose', help='show every decision for ONE deal id, then exit')
    ap.add_argument('--phase', choices=['purge', 'dedup', 'harvest', 'check'],
                    help='run ONE phase only (purge+dedup are offline and fast)')
    ap.add_argument('--no-history', action='store_true',
                    help='skip the 8-K history walk (much faster, finds fewer decks)')
    a = ap.parse_args()
    net = not a.no_net

    db = json.load(open(SRC, encoding='utf-8'))
    deals = db['deals']
    if a.diagnose:
        d = next((x for x in db['deals'] if x['id'] == a.diagnose), None)
        if not d:
            raise SystemExit('no such deal: %s' % a.diagnose)
        diagnose(d)
        return
    if a.only:
        deals = [d for d in deals if d['id'] == a.only]

    n_joint = n_bam = n_deck = n_agr = n_pr = n_tr = n_dead = 0
    n_redundant = n_twosided = n_deck_hist = n_purged = 0
    dead_list = []
    n = 0

    total = len(deals)
    t0 = time.time()
    for di, d in enumerate(deals, 1):
        L = d.setdefault('links', {})
        ver = L.get('_verified') or {}
        if not a.quiet:
            el = time.time() - t0
            eta = (el / di) * (total - di) if di else 0
            sys.stdout.write('\r  [%3d/%3d] %-34s  elapsed %4.0fs  eta %4.0fs   '
                             % (di, total, d['id'][:34], el, eta))
            sys.stdout.flush()

        # checkpoint: a long pass must not lose everything to one interruption
        if not a.dry_run and di % 10 == 0:
            with io.open(SRC, 'w', encoding='utf-8', newline='\n') as f:
                json.dump(db, f, indent=2, ensure_ascii=False)
                f.write('\n')

        # ---------- P0: purge technical/XBRL urls written by an earlier pass -
        if a.phase in (None, 'purge'):
        # a prior run classified EX-101.PRE ("XBRL TAXONOMY EXTENSION PRESENTATION
        # LINKBASE") as a deck because its description contains 'PRESENTATION'.
        # Those are machine-readable accounting files, never deal documents.
            for k in ('deck', 'agreement', 'press_release', 'transcript',
                      'press_release_target', 'press_release_acquirer'):
                u = L.get(k)
                if not isinstance(u, str) or ver.get(k) == 'human':
                    continue
                src = str(L.get('_%s_src' % k) or '')
                if (re.search(r'\.(xsd|xml|json)$', u, re.I)
                        or TECHNICAL_DESC.search(src)
                        or re.search(r'EX-10[14]', src, re.I)):
                    n_purged += 1
                    _p('  PURGE %-34s %s was an XBRL/technical file' % (d['id'], k))
                    if not a.dry_run:
                        L[k] = None
                        L.pop('_%s_src' % k, None)

        # ---------- P1: press-release duplication ---------------------------
        # three distinct cases, all of which overstated coverage:
        #   A the two side fields hold the SAME url        -> one joint release
        #   B the generic field just echoes a side field   -> redundant, drop it
        #   C the sides differ but are the same TEXT       -> joint, hosted twice
        t, ac = L.get('press_release_target'), L.get('press_release_acquirer')
        gen = L.get('press_release')
        if a.phase not in (None, 'dedup'):
            t = ac = gen = None

        if t and ac and t == ac:                                   # case A
            n_joint += 1
            _p('  JOINT %-34s identical url in both side slots' % d['id'])
            if not a.dry_run:
                L['press_release_joint'] = t
                L.pop('press_release_target', None)
                L.pop('press_release_acquirer', None)
                L['_pr_note'] = ('ONE joint release — was linked in both per-side '
                                 'slots, overstating two-sided coverage.')
        elif gen and ((t and gen == t) or (ac and gen == ac)):      # case B
            n_redundant += 1
            if not a.dry_run:
                L.pop('press_release', None)
                L['_pr_note'] = ('generic press_release removed: it duplicated the '
                                 '%s link.' % ('target' if gen == t else 'acquirer'))
            _p('  DUP   %-34s generic press_release echoed a side field' % d['id'])

        # case C needs the documents themselves
        t, ac = L.get('press_release_target'), L.get('press_release_acquirer')
        if net and not a.skip_check and t and ac and t != ac:
            same, why = same_release(t, ac)
            if same:
                n_joint += 1
                _p('  JOINT %-34s two hostings of ONE release (%s)' % (d['id'], why))
                if not a.dry_run:
                    L['press_release_joint'] = ac if 'sec.gov' in ac else t
                    L['_pr_alt_hosting'] = t if 'sec.gov' in ac else ac
                    L.pop('press_release_target', None)
                    L.pop('press_release_acquirer', None)
                    L['_pr_note'] = ('ONE joint release hosted in two places (%s) — '
                                     'not two separately-framed releases.' % why)
            elif same is False:
                n_twosided += 1

        if not net:
            continue

        n += 1
        if a.limit and n > a.limit:
            break

        # ---------- P2: bamsec -> SEC ---------------------------------------
        for k, v in list(L.items()):
            if isinstance(v, str) and 'bamsec' in v:
                sec_url, how = bamsec_to_sec(v)
                if sec_url:
                    n_bam += 1
                    _p('  SEC   %-34s %s -> %s [%s]' % (d['id'], k, sec_url[-46:], how))
                    if not a.dry_run:
                        L[k] = sec_url
                        L['_bamsec_converted_' + k] = v

        # ---------- P3: harvest EVERY doc in EVERY known accession -----------
        for folder in (accessions_of(d) if a.phase in (None, 'harvest') else []):
            got = harvest(folder)
            if not got:
                continue
            for field, (url, why) in got.items():
                if field == 'transcript':
                    if not L.get('transcript'):
                        n_tr += 1
                        _p('  TRSC  %-34s %s' % (d['id'], why[:44]))
                        if not a.dry_run:
                            L['transcript'] = url
                            L['_transcript_src'] = why
                    continue
                if ver.get(field) == 'human':
                    continue                      # never touch a verified link
                if L.get(field):
                    continue                      # don't clobber an existing link
                if field == 'agreement':
                    n_agr += 1
                elif field == 'deck':
                    n_deck += 1
                elif field == 'press_release':
                    n_pr += 1
                _p('  %-5s %-34s %s' % (field[:5].upper(), d['id'], why[:44]))
                if not a.dry_run:
                    L[field] = url
                    L['_%s_src' % field] = why + ' [accession harvest]'

        # ---------- P3b: history harvest for ANYTHING still missing ---------
        # the accession harvest above only reaches documents sitting in a filing
        # already on record. Deal documents are routinely split across several
        # 8-Ks, so anything still absent gets a full history walk.
        want = [f for f in ('agreement', 'deck', 'press_release', 'transcript')
                if not L.get(f) and ver.get(f) != 'human'
                and f not in (L.get('_needs_find') or [])]
        if want and not a.no_history and a.phase in (None, 'harvest'):
            best, note = harvest_history(d)
            for f in want:
                if f in best:
                    url, why = best[f]
                    if f == 'agreement':
                        n_agr += 1
                    elif f == 'deck':
                        n_deck_hist += 1
                    elif f == 'press_release':
                        n_pr += 1
                    else:
                        n_tr += 1
                    _p('  %-5s %-34s %s' % (f[:5].upper(), d['id'], why[:52]))
                    if not a.dry_run:
                        L[f] = url
                        L['_%s_src' % f] = why + ' [history harvest]'

        # ---------- P4: validate links --------------------------------------
        if not a.skip_check and a.phase in (None, 'check'):
            for k in ('agreement', 'deck', 'filing', 'fairness_opinion',
                      'press_release', 'press_release_joint',
                      'press_release_target', 'press_release_acquirer'):
                u = L.get(k)
                if not isinstance(u, str) or ver.get(k) == 'human':
                    continue
                ok, note = check(u)
                if not ok:
                    n_dead += 1
                    dead_list.append((d['id'], k, note, u))
                    _p('  DEAD  %-34s %s %s' % (d['id'], k, note))
                    if not a.dry_run:
                        L['_dead_' + k] = u
                        L[k] = None
                        L.setdefault('_needs_find', [])
                        if k not in L['_needs_find']:
                            L['_needs_find'].append(k)

    if not a.dry_run:
        shutil.copyfile(SRC, SRC + '.bak_scrub')
        with io.open(SRC, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
            f.write('\n')

    print('\n' + '=' * 64)
    print('SCRUB SUMMARY (all %d deals)' % len(deals))
    print('=' * 64)
    print('  P0 XBRL/technical links purged   %d' % n_purged)
    print('  P1 joint releases relabelled     %d' % n_joint)
    print('     redundant generic PR dropped  %d' % n_redundant)
    print('     genuinely two-sided (verified) %d' % n_twosided)
    print('  P2 bamsec -> SEC converted       %d' % n_bam)
    print('  P3 harvested from accessions:')
    print('       agreements                  %d' % n_agr)
    print('       decks (linked accession)    %d' % n_deck)
    print('       decks (8-K history walk)    %d' % n_deck_hist)
    print('       press releases              %d' % n_pr)
    print('       transcripts                 %d' % n_tr)
    print('  P4 dead links found (404)        %d' % n_dead)
    for did, k, note, u in dead_list[:15]:
        print('       %-30s %-22s %s' % (did, k, note))
    print('\n' + ('DRY RUN — nothing written' if a.dry_run
                  else 'written (backup .bak_scrub)'))


if __name__ == '__main__':
    main()