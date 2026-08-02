r"""
resolve_deal_filing.py — precedents.json  (local; needs sec.gov reachable)

A different approach, because scoring documents in isolation does not work.

WHAT WENT WRONG BEFORE
    Every earlier resolver searched broadly, then judged each document on its own
    features (image count, wording, exhibit number). That is why awk_nexus got the
    AWK/Essential deck, why five deals got closing press releases, and why decks
    were XBRL files: a document viewed alone gives you almost nothing to go on.

WHAT THIS DOES INSTEAD
    1. ANCHOR — find THE announcement filing. Candidates are 8-K/425/6-K within a
       few days of the announce date. Each candidate's PRIMARY DOCUMENT (the 8-K
       body, not its exhibits) is fetched and scored:
           + names BOTH counterparties
           + announcement language ("have entered into", "definitive agreement")
           + Item 1.01 (Entry into a Material Definitive Agreement)
           - completion language ("has completed", "closing of")  -> this is the
             closing 8-K, not the announcement
       The best-scoring filing is the anchor. If nothing scores, we stop and say
       so rather than harvesting from an unverified filing.

    2. HARVEST BY CONVENTION — within a VERIFIED announcement filing, SEC exhibit
       numbering is reliable and needs no heuristics:
           EX-2.x   -> merger / purchase agreement
           EX-99.1  -> press release
           EX-99.2+ -> investor deck (or transcript, checked by content)
       The whole point: the filing is verified ONCE, then its contents are trusted
       as a set. That is how an analyst reads a filing index, and it removes the
       per-document guessing that produced every previous error.

    3. CONFIDENCE — every link records the anchor score and what matched, so a weak
       anchor is visible rather than silently trusted.

Human-verified links are never touched.

  python resolve_deal_filing.py --dry-run
  python resolve_deal_filing.py --only <deal_id>
  python resolve_deal_filing.py --force     # re-resolve even where links exist
"""

import json, io, os, re, sys, time, shutil, argparse, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    'ra', os.path.join(HERE, 'resolve_agreements.py'))
ra = importlib.util.module_from_spec(_spec)
_argv = sys.argv; sys.argv = ['rdf']
_spec.loader.exec_module(ra)
sys.argv = _argv

SRC = ra.SRC
for i, _a in enumerate(sys.argv):
    if _a == '--file' and i + 1 < len(sys.argv):
        SRC = os.path.abspath(sys.argv[i + 1])

CACHE_DIR = os.path.join(os.path.dirname(SRC), '_sec_cache')
_raw_get = ra.get


def cached_get(url, timeout=30):
    if not url:
        return None
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        import hashlib
        cp = os.path.join(CACHE_DIR,
                          hashlib.md5(url.encode('utf-8')).hexdigest() + '.txt')
        if os.path.isfile(cp):
            v = io.open(cp, encoding='utf-8').read()
            return v or None
        v = _raw_get(url, timeout=timeout)
        if v is not None:
            io.open(cp, 'w', encoding='utf-8').write(v)
        return v
    except Exception:
        return _raw_get(url, timeout=timeout)


ra.get = cached_get

GENERIC = {'energy', 'power', 'utilities', 'utility', 'company', 'companies',
           'group', 'holdings', 'holding', 'corp', 'corporation', 'inc', 'llc',
           'ltd', 'natural', 'gas', 'electric', 'water', 'resources', 'partners',
           'capital', 'infrastructure', 'american', 'national', 'services',
           'service', 'systems', 'the', 'and', 'new', 'first', 'international'}

ANNOUNCE = re.compile(
    r'(have\s+entered\s+into|has\s+entered\s+into|entered\s+into\s+an?\s+'
    r'(agreement|definitive)|announce[sd]?\s+today|agree[sd]?\s+to\s+acquire|'
    r'definitive\s+(merger\s+)?agreement|agreement\s+and\s+plan\s+of\s+merger|'
    r'to\s+be\s+acquired\s+by)', re.I)
COMPLETION = re.compile(
    r'(ha[sve]+\s+completed\s+(its\s+|the\s+)?(acquisition|merger|sale|purchase)|'
    r'completed\s+(its|the)\s+(previously\s+announced\s+)?(acquisition|merger|sale)|'
    r'transaction\s+ha[sve]+\s+(closed|been\s+completed)|'
    r'announce[sd]?\s+the\s+completion|successfully\s+(closed|completed))', re.I)
ITEM101 = re.compile(r'item\s*1\.01|entry\s+into\s+a\s+material\s+definitive', re.I)
ITEM201 = re.compile(r'item\s*2\.01|completion\s+of\s+acquisition', re.I)

EX2 = re.compile(r'^EX-2(\.\d+)?$', re.I)
EX99 = re.compile(r'^EX-99(\.\d+)?$', re.I)
TECHNICAL = re.compile(r'^(EX-101|EX-104|GRAPHIC|XML|JSON|EX-100)', re.I)
TRANSCRIPT_BODY = re.compile(
    r'(operator[:\s]|question[- ]and[- ]answer|q\s*&\s*a\s+session|'
    r'your\s+first\s+question|\[\s*operator\s+instructions)', re.I)


def toks(deal, side):
    out = set()
    for w in re.split(r'[^A-Za-z]+', str(deal.get(side) or '')):
        w = w.lower()
        if len(w) >= 4 and w not in GENERIC:
            out.add(w)
    return out


def cik_lookup(nm):
    """EDGAR company search, with fallbacks for the names that defeat it.

    'South Jersey Industries (SJI)' fails on the parenthetical; 'UNS Energy
    Corporation' can fail on the suffix. Strip and retry before giving up --
    11 deals reported 'no CIK' purely because of formatting like this.
    """
    if not nm:
        return None
    c = ra.cik_by_name(nm)
    if c:
        return c
    base = re.sub(r'\(.*?\)', ' ', str(nm))
    base = re.sub(r'[^A-Za-z0-9 ]', ' ', base)
    base = ' '.join(base.split())
    if base and base.lower() != str(nm).lower():
        c = ra.cik_by_name(base)
        if c:
            return c
    words = [w for w in base.split()
             if len(w) >= 3 and w.lower() not in GENERIC]
    if words:
        c = ra.cik_by_name(' '.join(words[:2]))
        if c:
            return c
        if len(words) > 1:
            c = ra.cik_by_name(words[0])
    return c


def days(a, b):
    import datetime as dt
    try:
        return abs((dt.date(int(b[:4]), int(b[5:7]), int(b[8:10]))
                    - dt.date(int(a[:4]), int(a[5:7]), int(a[8:10]))).days)
    except Exception:
        return 9999


def score_filing(body, deal, lag):
    """Score a candidate as THE announcement filing. Returns (score, why)."""
    if not body:
        return -99, 'no body'
    text = re.sub(r'\s+', ' ', ra.TAG.sub(' ', body))[:80000]
    low = text.lower()
    t, a = toks(deal, 'target'), toks(deal, 'acquirer')
    ht = [x for x in t if x in low]
    ha = [x for x in a if x in low]

    sc, why = 0, []
    # When BOTH sides are separately identifiable, a filing that names only one is
    # very likely a DIFFERENT deal by the same filer -- that is exactly how the
    # AWK/Essential deck ended up on awk_nexus. Naming one is not weak evidence,
    # it is evidence against. Only forgive it where the other side has no
    # distinctive name at all (an asset, or a private target).
    both_identifiable = bool(t) and bool(a)
    if ht and ha:
        sc += 6
        why.append('names both')
    elif (ht or ha) and both_identifiable:
        sc -= 3
        missing = 'target' if not ht else 'acquirer'
        why.append('names %s only — likely a different deal' % ('acquirer' if not ht else 'target'))
    elif ht or ha:
        sc += 2
        why.append('names the identifiable side')
    else:
        sc -= 6
        why.append('names NEITHER')

    if ITEM101.search(text):
        sc += 4
        why.append('Item 1.01')
    if ANNOUNCE.search(text):
        sc += 3
        why.append('announcement language')
    if COMPLETION.search(text) and not ANNOUNCE.search(text):
        sc -= 6
        why.append('COMPLETION language')
    if ITEM201.search(text) and not ITEM101.search(text):
        sc -= 3
        why.append('Item 2.01 (completion)')

    if lag <= 3:
        sc += 3
        why.append('%dd from announce' % lag)
    elif lag <= 10:
        sc += 1
        why.append('%dd from announce' % lag)
    return sc, ', '.join(why)


def find_anchor(deal, window=21, verbose=False):
    """THE announcement filing, verified before anything is taken from it."""
    ann = deal.get('announced')
    if not ann:
        return None, 'no announce date'
    ciks = ra.all_ciks(deal)
    if not ciks:
        for nm in (deal.get('target'), deal.get('acquirer')):
            c = cik_lookup(nm)
            if c and c not in ciks:
                ciks.append(c)
    if not ciks:
        return None, 'no CIK'

    best, seen = None, set()
    for cik in ciks[:3]:
        for form, date, acc, prim in ra._iter_filings(cik):
            if not date or form.split('/')[0] not in ('8-K', '425', '6-K'):
                continue
            lag = days(ann, date)
            if lag > window:
                continue
            a2 = acc.replace('-', '')
            if a2 in seen:
                continue
            seen.add(a2)
            folder = 'https://www.sec.gov/Archives/edgar/data/%d/%s/' % (int(cik), a2)
            body = ra.get(folder + prim) if prim else None
            if body is None:
                # pre-2001 filings often carry NO primaryDocument in the
                # submissions JSON, which scored them -99 before any test ran --
                # that alone killed every 1999-2000 deal. Fall back to the first
                # document in the accession index (old 8-Ks are one .txt).
                idx = ra.get(ra.accession_index(folder))
                if idx:
                    dd = ra.parse_index(idx, folder)
                    if dd:
                        body = ra.get(dd[0]['url'])
            sc, why = score_filing(body, deal, lag)
            if verbose:
                print('        cand %s %-6s score %3d  %s' % (date, form, sc, why))
            if sc >= 8 and (best is None or sc > best[0]):
                best = (sc, folder, date, form, why)
    if not best:
        return None, 'no filing scored high enough to be the announcement'
    return best, 'anchored'


def harvest(folder, deal, deep=True):
    """Exhibits of a VERIFIED announcement filing, read by SEC convention."""
    html = ra.get(ra.accession_index(folder))
    if not html:
        return {}
    docs = ra.parse_index(html, folder)
    out = {}
    ex99 = []
    for d in docs:
        typ = (d.get('type') or '').strip()
        desc = (d.get('desc') or '')
        url = d['url']
        if TECHNICAL.match(typ) or re.search(r'\.(xml|xsd|json)$', url, re.I):
            continue
        if EX2.match(typ) and 'agreement' not in out:
            out['agreement'] = (url, 'EX-2 in the verified announcement filing')
            continue
        if EX99.match(typ):
            ex99.append((typ, desc, url))
    # EX-99.1 is the press release; 99.2+ are decks/transcripts
    for typ, desc, url in sorted(ex99, key=lambda x: x[0]):
        n = typ.split('.')[-1] if '.' in typ else '1'
        if n == '1' and 'press_release' not in out:
            out['press_release'] = (url, 'EX-99.1 of the announcement filing')
        elif 'deck' not in out or 'transcript' not in out:
            if deep:
                body = ra.get(url)
                text = re.sub(r'\s+', ' ', ra.TAG.sub(' ', body or ''))
                if len(TRANSCRIPT_BODY.findall(text[:60000])) >= 2:
                    out.setdefault('transcript', (url, '%s — operator/Q&A markers' % typ))
                    continue
                imgs = len((body or '').split('<img')) - 1
                if 'deck' not in out and (imgs >= 8 or re.search(
                        r'(investor|analyst|management)\s+present', text[:20000], re.I)):
                    out['deck'] = (url, '%s — %d imgs in the announcement filing'
                                   % (typ, imgs))
            elif 'deck' not in out:
                out['deck'] = (url, '%s of the announcement filing' % typ)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--only')
    ap.add_argument('--file')
    ap.add_argument('--force', action='store_true',
                    help='re-resolve even where a link already exists (not verified ones)')
    ap.add_argument('--window', type=int, default=21)
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args()

    db = json.load(open(SRC, encoding='utf-8'))
    deals = [d for d in db['deals'] if not a.only or d['id'] == a.only]
    FIELDS = ('agreement', 'press_release', 'deck', 'transcript')

    anchored = noanchor = wrote = kept = 0
    t0 = time.time()
    for i, d in enumerate(deals, 1):
        L = d.setdefault('links', {})
        ver = L.get('_verified') or {}
        need = [f for f in FIELDS
                if (a.force or not L.get(f)) and ver.get(f) != 'human']
        if not need:
            continue
        sys.stdout.write('\r  [%3d/%3d] %-32s %4.0fs  ' % (i, len(deals), d['id'][:32],
                                                           time.time() - t0))
        sys.stdout.flush()
        res, note = find_anchor(d, a.window, a.verbose)
        sys.stdout.write('\r' + ' ' * 74 + '\r')
        if not res:
            noanchor += 1
            print('  ---  %-32s %s' % (d['id'], note))
            continue
        sc, folder, date, form, why = res
        anchored += 1
        print('  ANCH %-32s %s %-5s score %2d  (%s)' % (d['id'], date, form, sc, why))
        got = harvest(folder, d)
        for f in need:
            if f in got:
                url, w = got[f]
                if L.get(f) and not a.force:
                    kept += 1
                    continue
                print('       %-12s %s' % (f, w))
                wrote += 1
                if not a.dry_run:
                    L[f] = url
                    L['_%s_src' % f] = '%s [anchor %s, score %d]' % (w, date, sc)
                    L.setdefault('_anchor', {})['filing'] = folder
                    L['_anchor']['score'] = sc
                    L['_anchor']['why'] = why

    if not a.dry_run:
        shutil.copyfile(SRC, SRC + '.bak_anchor')
        with io.open(SRC, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
            f.write('\n')

    print('\n' + '=' * 62)
    print('  announcement filings anchored : %d' % anchored)
    print('  no filing scored high enough  : %d  (nothing taken from these)' % noanchor)
    print('  links written                 : %d' % wrote)
    print('DRY RUN — nothing written' if a.dry_run else 'written (backup .bak_anchor)')


if __name__ == '__main__':
    main()