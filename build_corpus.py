#!/usr/bin/env python3
"""
build_corpus.py — one searchable, linkable corpus over every PDF in Power Academy.

    python scripts\\build_corpus.py                      # default roots, incremental
    python scripts\\build_corpus.py --force              # re-extract everything
    python scripts\\build_corpus.py --include-library    # add Documents\\library (books)
    python scripts\\build_corpus.py --report             # what WOULD change; writes nothing

Writes exactly two things and nothing else:
    data\\corpus\\text\\<sha1>.txt     page-marked text, one file per UNIQUE document
    data\\corpus_manifest.json        one record per unique document

WHY A SEPARATE SCRIPT AND A SEPARATE OUTPUT NAMESPACE
  rip.py owns the extraction pipeline for coverage transcripts and broker/credit
  reports, and names its output from ticker+period off the cover page. That is right
  for those and wrong here: 525 conference decks have no quarter, many share a company
  and a year, and a ticker+period naming scheme would collide dozens of times. So this
  writes into its own `corpus\\` namespace keyed by CONTENT HASH, never touches the
  coverage JSONs, and refuses any --out that is not under data\\corpus.
  (Same routing-guard shape as extract_peers.py, and for the same reason.)

WHY CONTENT HASH RATHER THAN FILENAME
  The source folders are cross-contaminated. Verified 2026-08-02: a J.P. Morgan
  conference deck sits inside data\\transcripts, and Ameren's Q4 2025 deck exists
  byte-identically in BOTH data\\presentations and data\\transcripts. Filename also
  cannot be trusted across folders — Documents\\transcripts uses the old S&P
  convention (`X_Earnings Call_2026-07-30_English.pdf`) for the SAME call that
  data\\transcripts holds under the CapIQ convention (`X,_Q2_2026_Earnings_Call,
  _Jul_30,_2026.pdf`). Hashing the bytes collapses all of that automatically, and
  every path a document was found at is kept in `sources[]`.

WHY doc_type IS CLASSIFIED FROM CONTENT, NOT THE FOLDER
  Measured on a 2026-08-02 sample: transcripts run 400-580 words/page and always
  carry "call participants"; decks run 5-148 words/page and never do. The folder name
  is not evidence — see the cross-contamination note above. Rule 9 of the extraction
  skill, applied to a new document class: trust the document over the filename.
"""

import os, re, sys, json, hashlib, argparse, unicodedata

ROOT = r'E:\PowerAcademy'
CORPUS_DIR   = os.path.join(ROOT, 'data', 'corpus')
TEXT_DIR     = os.path.join(CORPUS_DIR, 'text')
MANIFEST     = os.path.join(ROOT, 'data', 'corpus_manifest.json')

# Caddy serves E:\PowerAcademy\documents at :8080 and (after the Caddyfile change)
# E:\PowerAcademy\data at :8080/corpus/. Two prefixes, so both trees deep-link.
CADDY = 'http://100.86.108.51:8080'

DEFAULT_ROOTS = [
    (os.path.join(ROOT, 'Documents', 'reports'),       'broker_report'),
    (os.path.join(ROOT, 'Documents', 'credit'),        'credit'),
    (os.path.join(ROOT, 'Documents', 'transcripts'),   None),   # None = classify from content
    (os.path.join(ROOT, 'Documents', 'presentations'), None),
    # data\ is the raw-download staging area, kept as a root so anything newly dropped
    # there is still indexed. organize_corpus.py moves it into Documents\ by quarter;
    # after that these two are normally empty.
    (os.path.join(ROOT, 'data', 'transcripts'),        None),
    (os.path.join(ROOT, 'data', 'presentations'),      None),
    # Sell-side research downloaded straight into data\. 33 unique documents sat
    # here unindexed until 2026-08-03 - sector work (PJM backstop, AI load, the NEE
    # M&A target screen) that exists nowhere else in the corpus.
    (os.path.join(ROOT, 'data', 'EquityResearch'),     'broker_report'),
    # Investor-presentation decks filed outside Documents\presentations.
    (os.path.join(ROOT, 'Documents', 'special_presentations'), None),
]
LIBRARY_ROOT = (os.path.join(ROOT, 'Documents', 'library'), 'library')

# Deliberately NOT indexed. data\Scans\ is the Epson's raw output: multi-document
# bundles that are afterwards split into Documents\reports\. Verified 2026-08-03 by
# 6-word shingle overlap - 78-91% of every bundle's pages already exist as individual
# named reports, and the residue is OCR drift between the two passes, not missing
# documents. Indexing the bundles would return every broker note twice, once under a
# title like `Scans-20260729` carrying no ticker and no date. The stray guard below
# knows about these so they are reported as staging, not as an accident.
STAGING_DIRS = [os.path.join(ROOT, 'data', 'Scans')]

# ── ticker resolution ────────────────────────────────────────────────────────
# Coverage (24) + the peer names that appear in the presentation set. Longest key
# wins, so "American Water Works" beats "American States Water" on the right file.
NAME_TICKER = {
    'algonquin power': 'AQN', 'ameren': 'AEE', 'american states water': 'AWR',
    'american water works': 'AWK', 'california water service': 'CWT',
    'cms energy': 'CMS', 'consumers energy': 'CMS', 'dominion energy': 'D',
    'edison international': 'EIX', 'entergy': 'ETR', 'essential utilities': 'WTRG',
    'eversource': 'ES', 'evergy': 'EVRG', 'global water resources': 'GWRS',
    'h2o america': 'HTO', 'sjw group': 'HTO', 'hawaiian electric': 'HE',
    'middlesex water': 'MSEX', 'nextera energy partners': 'XIFR',
    'xplr infrastructure': 'XIFR', 'nextera energy': 'NEE', 'pg&e': 'PCG',
    'pacific gas': 'PCG', 'pg and e': 'PCG', 'pge corporation': 'PCG',
    # CapIQ writes PG&E as "PGAndE_Corporation" - no separators, so neither
    # 'pg and e' nor 'pg&e' matches it. Verified 2026-08-02: this single gap left
    # PCG with 3 documents instead of ~50.
    'pgande': 'PCG', 'pg e corp': 'PCG',
    'portland general': 'POR', 'ppl corporation': 'PPL', 'talen energy': 'TLN',
    'vistra': 'VST', 'york water': 'YORW',
    # peers seen in the deck set
    'american electric power': 'AEP', 'atmos energy': 'ATO', 'avista': 'AVA',
    'black hills': 'BKH', 'constellation energy': 'CEG', 'centerpoint': 'CNP',
    'chesapeake utilities': 'CPK', 'dte energy': 'DTE', 'duke energy': 'DUK',
    'consolidated edison': 'ED', 'exelon': 'EXC', 'firstenergy': 'FE',
    'idacorp': 'IDA', 'alliant energy': 'LNT', 'nisource': 'NI',
    'new jersey resources': 'NJR', 'nrg energy': 'NRG', 'northwestern': 'NWE',
    'oge energy': 'OGE', 'one gas': 'OGS', 'public service enterprise': 'PEG',
    'pinnacle west': 'PNW', 'southern company': 'SO', 'spire': 'SR',
    'sempra': 'SRE', 'southwest gas': 'SWX', 'txnm energy': 'TXNM',
    'pnm resources': 'TXNM', 'wec energy': 'WEC', 'xcel energy': 'XEL',
}
_KEYS = sorted(NAME_TICKER, key=len, reverse=True)
KNOWN = set(NAME_TICKER.values())

# Explicit per-file overrides, for filenames that are simply wrong. Same pattern as
# resolve_edgar_links.py's KNOWN_ANCHORS: state the exception and why, rather than
# widening a matcher until it swallows the error silently.
KNOWN_FILE_TICKERS = {
    # 'HW' is a transposition of 'HE' - Hawaiian Electric. Logged in the tracker on
    # 2026-07-30. Note this is NOT a duplicate of HE-HECO_Moodys-20260425.pdf: the two
    # differ in bytes (2,049,960 vs 2,072,386), so the content hash keeps them apart.
    'hw-heco_moodys-20260425': ['HE'],
}

def _tickers_from_prefix(name):
    """The broker and credit scans are named by TICKER, not by company name:
    `AEE_Argus-20260323`, `GWRS-Roth_20260306`, `ETR-25.06.2026`, and multi-ticker
    notes like `PPL_AWK_WF-20260617` / `NEE_PCG_TDCowen-...`. Name matching alone
    left 326 of 1,396 files unattributed. Read the leading tokens as tickers."""
    out = []
    for tok in re.split(r'[-_.\s]+', name):
        if not tok:
            continue
        if tok.upper() in KNOWN:
            if tok.upper() not in out:
                out.append(tok.upper())
            continue
        # `AEEHoldco`, `PPLElectric`, `EVRGMetro` - ticker glued to an entity name.
        # Require >=3 chars so a single-letter ticker (D) cannot swallow every word
        # beginning with that letter.
        hit = next((t for t in sorted(KNOWN, key=len, reverse=True)
                    if len(t) >= 3 and tok.upper().startswith(t) and len(tok) > len(t)), None)
        if hit and hit not in out:
            out.append(hit)
        break                      # only the LEADING run of tokens is a ticker list
    return out

def tickers_from_name(name, path=None):
    """All tickers named in a filename. Multi-company files are real and matter:
    `Dominion_Energy,_Inc.,_NextEra_Energy,_Inc._-_MAndA_Call` is the live megadeal,
    and it belongs under BOTH names."""
    ov = KNOWN_FILE_TICKERS.get(os.path.splitext(os.path.basename(name))[0].lower())
    if ov:
        return list(ov)
    pre = _tickers_from_prefix(name)
    if pre:
        return pre
    low = re.sub(r'[_]+', ' ', name).lower()
    low = low.replace('&', ' and ') if 'pg&e' not in low else low
    hits, spans = [], []
    for k in _KEYS:
        i = low.find(k)
        if i < 0:
            continue
        if any(s <= i < e for s, e in spans):     # already covered by a longer key
            continue
        spans.append((i, i + len(k)))
        t = NAME_TICKER[k]
        if t not in hits:
            hits.append(t)
    if not hits and path:
        # `data\EquityResearch\GWRS\Document_20260305_0001.pdf` - the ticker is the
        # FOLDER, not the filename. Fallback only: it can never override a real hit.
        segs = os.path.dirname(str(path)).replace('\\', '/').split('/')[-2:]
        for seg in reversed(segs):
            if seg.upper() in KNOWN:
                return [seg.upper()]
    return hits

# ── date / period ────────────────────────────────────────────────────────────
MON = {m: i + 1 for i, m in enumerate(
    ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'])}

def _flat(n):
    """CapIQ separates every token with '_'. Underscore is a WORD character, so \b
    never fires next to it and `\bQ1_2021\b` silently matches nothing. Normalise
    once, here, rather than remembering it at each call site."""
    return re.sub(r'[_]+', ' ', n)

def date_from_name(n):
    """CapIQ writes `May_07,_2021` and `Nov-13-2023`; S&P writes `2026-07-30`."""
    n = _flat(n)
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', n)
    if m:
        return f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
    m = re.search(r'([A-Z][a-z]{2})[_\-\s]*(\d{1,2})[,_\-\s]+(20\d{2})', n)
    if m and m.group(1).lower() in MON:
        return f'{m.group(3)}-{MON[m.group(1).lower()]:02d}-{int(m.group(2)):02d}'
    m = re.search(r'([A-Z][a-z]{2})-(\d{1,2})-(20\d{2})', n)
    if m and m.group(1).lower() in MON:
        return f'{m.group(3)}-{MON[m.group(1).lower()]:02d}-{int(m.group(2)):02d}'
    return None

def period_from_name(n):
    n = _flat(n)
    m = re.search(r'\bQ([1-4])\s+(20\d{2})\b', n)
    if m:
        return f'Q{m.group(1)} {m.group(2)}'
    m = re.search(r',\s*(20\d{2})\s+Earnings', n)            # `, 2021 Earnings Call` = FY
    if m:
        return f'FY {m.group(1)}'
    return None

def event_from_name(n):
    low = _flat(n).lower()
    if 'presents at' in low or 'conference' in low or 'forum' in low or 'summit' in low:
        return 'conference'
    if 'investor day' in low or 'analyst day' in low:
        return 'investor_day'
    if 'earnings call' in low:
        return 'earnings_call'
    if 'm and a call' in low or 'mandacall' in low or 'm&a call' in low:
        return 'ma_call'
    if 'shareholder' in low or 'special call' in low or 'analyst call' in low:
        return 'special_call'
    return None

def clean_title(stem):
    t = stem.replace('_', ' ')
    t = re.sub(r'\s+', ' ', t).strip()
    return t

# ── extraction + classification ──────────────────────────────────────────────
def rip_text_for(path):
    """rip.py writes OCR'd, page-marked text to a sibling `text\\<stem>.txt`.
    For an Epson scan with no text layer that file is the ONLY text that exists -
    extracting the PDF again just returns nothing. Verified 2026-08-02: 13 EIX
    broker notes read as image-only here while Documents\\reports\\text\\ held
    8k-24k of ripped text for each. Prefer the ripped text whenever the PDF
    itself is empty."""
    d, fn = os.path.split(path)
    cand = os.path.join(d, 'text', os.path.splitext(fn)[0] + '.txt')
    if os.path.exists(cand):
        try:
            t = open(cand, encoding='utf-8', errors='replace').read()
            if len(t.split()) > 50:
                return t, cand
        except OSError:
            pass
    return None, None

def extract(path):
    """Page-marked text. Markers match rip.py's convention so downstream page
    attribution is identical across the two pipelines."""
    import fitz
    doc = fitz.open(path)
    parts, words = [], 0
    for i, page in enumerate(doc, 1):
        t = page.get_text()
        words += len(t.split())
        parts.append(f'[[PAGE {i}]]\n{t}')
    pages = doc.page_count
    doc.close()
    # No usable text layer -> fall back to rip.py's OCR output if it exists.
    if words < 20 * max(1, pages):
        rt, src = rip_text_for(path)
        if rt:
            rp = rt.count('[[PAGE ')
            return rt, (rp or pages), len(rt.split())
    return '\n'.join(parts), pages, words

def classify(text, pages, words, hinted, name):
    """Content first, folder hint only as a tiebreak."""
    wpp = words / max(1, pages)
    low = text.lower()
    has_participants = 'call participants' in low
    has_qa = 'question and answer' in low
    if has_participants and wpp > 250:
        return 'transcript', wpp
    if hinted in ('broker_report', 'credit', 'library'):
        return hinted, wpp
    if has_participants or (has_qa and wpp > 300):
        return 'transcript', wpp
    return 'presentation', wpp

def url_for(path):
    """Caddy serves Documents\\ at :8080/ and (after the Caddyfile change) data\\ at
    :8080/corpus/. Compare on forward slashes so this is not sensitive to which OS
    built the path."""
    p    = path.replace('\\', '/')
    docs = os.path.join(ROOT, 'Documents').replace('\\', '/').rstrip('/') + '/'
    data = os.path.join(ROOT, 'data').replace('\\', '/').rstrip('/') + '/'
    lp = p.lower()
    # The research filenames carry spaces and en-dashes ("NARUC 2026 Takes - ...").
    # An unencoded href breaks on those; quote() leaves '/' alone so the path shape
    # is unchanged and Caddy decodes the rest.
    from urllib.parse import quote
    if lp.startswith(docs.lower()):
        return CADDY + '/' + quote(p[len(docs):])
    if lp.startswith(data.lower()):
        return CADDY + '/corpus/' + quote(p[len(data):])
    return None

# ── main ─────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true', help='re-extract even if the .txt exists')
    ap.add_argument('--include-library', action='store_true', help='also index Documents\\library (books)')
    ap.add_argument('--report', action='store_true', help='print what would change; write nothing')
    ap.add_argument('--root', default=ROOT)
    ap.add_argument('--out', default=MANIFEST)
    args = ap.parse_args()

    # Routing guard, in the script rather than in discipline: this must never be
    # pointed at a coverage data file. Same pattern and same reason as extract_peers.py.
    outname = os.path.basename(args.out).lower()
    if not outname.startswith('corpus'):
        sys.exit(f'REFUSED: --out must be a corpus_* file, got {outname!r}')

    roots = list(DEFAULT_ROOTS) + ([LIBRARY_ROOT] if args.include_library else [])
    os.makedirs(TEXT_DIR, exist_ok=True)

    # 1. walk
    found = []
    for base, hint in roots:
        if not os.path.isdir(base):
            print(f'  skip (missing): {base}')
            continue
        n = 0
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames
                           if d.lower() not in ('text', '_archive')
                           and not d.lower().startswith('_to_delete')]
            # A `Credit Reports\` subfolder inside a research root holds credit, not
            # equity research. data\EquityResearch\ETR\ splits exactly that way, so
            # the hint has to be per DIRECTORY, not per root.
            leaf  = os.path.basename(dirpath.rstrip('\\/')).lower()
            dhint = 'credit' if 'credit' in leaf else hint
            for fn in filenames:
                if fn.lower().endswith('.pdf'):
                    found.append((os.path.join(dirpath, fn), dhint)); n += 1
        print(f'  {n:>5} pdf under {base}')
    print(f'  {len(found)} pdf paths total')

    # Stray guard. Two folders - Documents\special_presentations and
    # data\EquityResearch - sat outside every root for weeks: filed, backed up, and
    # invisible to search, with nothing anywhere indicating a gap. Walking only the
    # roots it is told about cannot ever surface that. Walk the whole tree instead
    # and name what is not covered.
    covered = {os.path.normcase(os.path.abspath(p)) for p, _ in found}
    strays = []
    for tree in (os.path.join(ROOT, 'Documents'), os.path.join(ROOT, 'data')):
        if not os.path.isdir(tree):
            continue
        for dirpath, dirnames, filenames in os.walk(tree):
            dirnames[:] = [d for d in dirnames
                           if d.lower() not in ('text', '_archive', 'corpus')
                           and not d.lower().startswith('_to_delete')
                           and not (d.lower() == 'library' and not args.include_library)]
            for fn in filenames:
                if fn.lower().endswith('.pdf'):
                    q = os.path.join(dirpath, fn)
                    if os.path.normcase(os.path.abspath(q)) not in covered:
                        strays.append(q)
    _stag = [os.path.normcase(os.path.abspath(d)) for d in STAGING_DIRS]
    known  = [p for p in strays if any(os.path.normcase(os.path.abspath(p)).startswith(d) for d in _stag)]
    unknown = [p for p in strays if p not in known]
    if known:
        print(f'  ({len(known)} PDF(s) under known staging - deliberately not indexed)')
    if unknown:
        from collections import Counter as _C
        print(f'  !! {len(unknown)} PDF(s) sit OUTSIDE every indexed root - not searchable:')
        for d, c in sorted(_C(os.path.dirname(p) for p in unknown).items()):
            print(f'       {c:>5}  {d}')
        print('     Add the folder to DEFAULT_ROOTS, move the files under one, or')
        print('     add it to STAGING_DIRS if it is raw input that should stay out.')

    # 2. hash -> dedupe. Cross-folder copies collapse here.
    by_hash = {}
    for path, hint in found:
        try:
            h = hashlib.sha1()
            with open(path, 'rb') as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b''):
                    h.update(chunk)
            sid = h.hexdigest()[:16]
        except OSError as e:
            print(f'  !! unreadable {path}: {e}');  continue
        rec = by_hash.setdefault(sid, {'sources': [], 'hint': hint})
        rec['sources'].append(path)
        if rec['hint'] is None and hint is not None:
            rec['hint'] = hint
    dupes = sum(len(v['sources']) - 1 for v in by_hash.values())
    print(f'  {len(by_hash)} unique documents ({dupes} duplicate paths collapsed by content hash)')

    if args.report:
        todo = [s for s in by_hash if args.force or not os.path.exists(os.path.join(TEXT_DIR, s + '.txt'))]
        print(f'  would extract: {len(todo)}   already done: {len(by_hash) - len(todo)}')
        return

    # 3. extract + classify
    manifest, no_text, errors = [], [], []
    for i, (sid, rec) in enumerate(sorted(by_hash.items()), 1):
        # Prefer the most descriptive path as primary: the longest filename usually
        # carries the company, the quarter AND the date, where the short one does not.
        primary = sorted(rec['sources'], key=lambda p: (-len(os.path.basename(p)), p))[0]
        stem = os.path.splitext(os.path.basename(primary))[0]
        txt_path = os.path.join(TEXT_DIR, sid + '.txt')
        try:
            if args.force or not os.path.exists(txt_path):
                text, pages, words = extract(primary)
                with open(txt_path, 'w', encoding='utf-8') as fh:
                    fh.write(text)
            else:
                text = open(txt_path, encoding='utf-8').read()
                pages = text.count('[[PAGE ')
                words = len(text.split()) - pages * 2
        except Exception as e:
            errors.append((primary, str(e)));  continue

        dtype, wpp = classify(text, pages, words, rec['hint'], stem)
        tk = tickers_from_name(stem, primary)
        flags = []
        if wpp < 20:
            flags.append('NO_TEXT_LAYER: %d words over %d pages - image-only, and no rip.py OCR text '
                         'alongside it. Run rip.py on this file to make it searchable.' % (words, pages))
            no_text.append(stem)
        if not tk and dtype != 'library':
            flags.append('NO_TICKER_MATCHED: filename did not resolve to a covered or peer name')

        manifest.append({
            'id': sid,
            'title': clean_title(stem),
            'tickers': tk,
            'doc_type': dtype,
            'event': event_from_name(stem),
            'date': date_from_name(stem),
            'period': period_from_name(stem),
            'pages': pages,
            'words': words,
            'words_per_page': round(wpp, 1),
            'text_layer': wpp >= 20,
            'primary_source': primary,
            'sources': sorted(rec['sources']),
            'url': url_for(primary),
            'text_file': f'corpus/text/{sid}.txt',
            '_flags': flags,
        })
        if i % 50 == 0:
            print(f'    ...{i}/{len(by_hash)}')

    # 4. write (atomic)
    manifest.sort(key=lambda r: (r['tickers'][0] if r['tickers'] else 'zz',
                                 r['date'] or '', r['title']))
    out = {
        '_generated': __import__('datetime').datetime.now().isoformat(timespec='seconds'),
        '_note': ('Unique documents across Documents\\{reports,credit,transcripts,'
                  'presentations,special_presentations} and data\\{transcripts,presentations,'
                  'EquityResearch}. Deduped by CONTENT HASH because the '
                  'source folders are cross-contaminated and the same call exists under two '
                  'naming conventions. doc_type is classified from the text, not the folder.'),
        '_counts': {},
        'documents': manifest,
    }
    from collections import Counter
    out['_counts'] = {
        'documents': len(manifest),
        'by_type': dict(Counter(r['doc_type'] for r in manifest)),
        'no_text_layer': len(no_text),
        'no_ticker': sum(1 for r in manifest if not r['tickers'] and r['doc_type'] != 'library'),
        'duplicate_paths_collapsed': dupes,
        'total_text_mb': round(sum(os.path.getsize(os.path.join(TEXT_DIR, r['id'] + '.txt'))
                                   for r in manifest) / 1e6, 1),
    }
    tmp = args.out + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, args.out)

    print()
    print(f'  wrote {args.out}')
    for k, v in out['_counts'].items():
        print(f'    {k:28} {v}')
    if no_text:
        print(f'\n  !! {len(no_text)} documents have NO TEXT LAYER and are NOT searchable.')
        print('     These are image-only PDFs (older CapIQ deck exports). Re-run with OCR')
        print('     or re-download them; they are flagged NO_TEXT_LAYER in the manifest so')
        print('     the UI can say so rather than silently returning nothing.')
        for s in no_text[:8]:
            print(f'       - {s[:90]}')
        if len(no_text) > 8:
            print(f'       ... and {len(no_text)-8} more')
    if errors:
        print(f'\n  !! {len(errors)} failed to open:')
        for p, e in errors[:5]:
            print(f'       - {os.path.basename(p)}: {e}')

if __name__ == '__main__':
    main()
