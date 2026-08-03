#!/usr/bin/env python3
"""
organize_corpus.py — move the downloaded PDFs out of data\\ into Documents\\, foldered by quarter.

    python scripts\\organize_corpus.py                # DRY RUN - prints the plan, moves nothing
    python scripts\\organize_corpus.py --apply        # do it
    python scripts\\organize_corpus.py --undo <log>   # reverse an --apply using its log

  data\\ is the raw-download staging area; documents belong under Documents\\. This moves
  (not copies) every PDF the corpus manifest found under data\\presentations and
  data\\transcripts into:

      Documents\\transcripts\\Q1_2026\\...      doc_type == transcript
      Documents\\presentations\\Q1_2026\\...    doc_type == presentation
      Documents\\<type>\\Undated\\...           no period and no parseable date

  Quarter comes from the manifest's `period` when the document has one - a Q1 2026
  earnings call belongs in Q1_2026 even though it was held in May - and falls back to
  the calendar quarter of `date`. Those are two different meanings and the fallback is
  only used where the reporting period genuinely is not known.

WHAT IT DELIBERATELY DOES NOT TOUCH
  The 51 PDFs already under Documents\\transcripts stay exactly where they are. Their
  folder names ("Q2 2026 Earnings", "Q4 2025 Earnings Call") are stored as
  `source_folder` in earnings_calls.json and are what the Call Notes deep-links are
  built from - renaming them silently breaks 53 page-linked notes. Normalising those
  is a separate job that has to patch the JSON in the same pass.

  Documents\\reports and Documents\\credit are untouched: they are already in Documents,
  and rip.py + the four extraction JSONs reference them by path.

SAFETY
  - Dry run by default. --apply is required to move anything.
  - Never overwrites. Identical bytes at the target -> the source is treated as a
    duplicate and staged for deletion. Different bytes -> a numeric suffix.
  - Byte-identical duplicate paths (101 of them, from the cross-contaminated folders)
    go to _to_delete_2026-08-02\\corpus_dupes\\ rather than being moved twice.
  - Every action is appended to a JSON log so --undo can reverse the whole run.
"""

import os, re, sys, json, shutil, hashlib, argparse
from collections import Counter

ROOT = r'E:\PowerAcademy'
MANIFEST = os.path.join(ROOT, 'data', 'corpus_manifest.json')
DEST = {'transcript':   os.path.join(ROOT, 'Documents', 'transcripts'),
        'presentation': os.path.join(ROOT, 'Documents', 'presentations')}
DUPES = os.path.join(ROOT, '_to_delete_2026-08-02', 'corpus_dupes')
# Compare on forward slashes: the manifest is written on Windows (backslashes) but this
# may be reasoned about anywhere, and os.path.join follows the HOST separator. Getting
# this wrong reports "0 documents to move" - a confident, wrong, and silent answer.
def _norm(p):
    return p.replace('\\', '/').lower()


def _split(p):
    """(parent folder, filename), lowercased, for a path written with EITHER separator.
    os.path.basename follows the HOST separator, so on a non-Windows host it returns a
    Windows path unchanged - folder comes back '' and every comparison against it fails
    silently. That is the third time today this difference produced a confident wrong
    answer (see url_for and SOURCE_PREFIXES), so it is one helper now."""
    q = p.replace('\\', '/').rstrip('/')
    parts = q.split('/')
    base = parts[-1].lower() if parts else ''
    fold = parts[-2].lower() if len(parts) > 1 else ''
    return fold, base

SOURCE_PREFIXES = (_norm(os.path.join(ROOT, 'data', 'presentations')),
                   _norm(os.path.join(ROOT, 'data', 'transcripts')))


def quarter_of(d):
    p = d.get('period') or ''
    m = re.match(r'(Q[1-4]|FY)\s+(20\d{2})$', p)
    if m:
        return f'{m.group(1)}_{m.group(2)}'
    if d.get('date'):
        y, mo, _ = d['date'].split('-')
        return f'Q{(int(mo) - 1) // 3 + 1}_{y}'
    return 'Undated'


REFERENCING_JSONS = ['earnings_calls.json', 'broker_research.json',
                     'moodys_credit.json', 'sp_credit.json', 'fitch_credit.json']

def referenced_files():
    """What the live JSONs point at. These are load-bearing: the Call Notes, Analyst
    View and the three credit panels build Caddy deep-links from `source_file` (and,
    for transcripts, `source_folder`), so the referenced COPY must survive - regardless
    of which copy has the longer filename or the richer extraction.

    Returns (basenames, folder_file_pairs). The pair set matters: the two naming
    conventions sometimes produce the SAME basename in two folders, and then a basename
    alone cannot tell you which path is linked. Seen 2026-08-02 on CMS Q2 2026, where
    basename-only matching picked the unlinked copy purely because it had 6 more words."""
    names, pairs = set(), set()
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == 'source_file' and isinstance(v, str) and v.lower().endswith('.pdf'):
                    b = _split(v)[1]
                    names.add(b)
                    fold = o.get('source_folder')
                    if isinstance(fold, str) and fold:
                        pairs.add((_split(fold.rstrip('\\/') + '/x')[0], b))
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    for fn in REFERENCING_JSONS:
        fp = os.path.join(ROOT, 'data', fn)
        if os.path.exists(fp):
            try:
                walk(json.load(open(fp, encoding='utf-8')))
            except Exception:
                pass
    return names, pairs


def logical_dupes(docs, refs):
    """Same document ingested twice under two naming conventions.

    The content hash cannot see these: S&P re-exports the same call, so the bytes
    differ while the document does not. Measured 2026-08-02: 11 groups / 22 transcripts,
    identical page counts and word counts within 1%.

    Grouping on ticker+date alone would be too eager - a company can publish an earnings
    deck and a separate appendix on the same day - so a group only counts as duplicates
    when the documents also AGREE ON LENGTH. Anything that matches on ticker+date but
    disagrees on length is reported and left alone.

    Keeper, in order: the copy a live JSON references, then the richer extraction,
    then the longer filename (which carries more metadata)."""
    groups = {}
    for d in docs:
        if not d.get('tickers'):
            continue
        key = (tuple(d['tickers']), d.get('date') or d.get('period'), d['doc_type'])
        if key[1]:
            groups.setdefault(key, []).append(d)

    drop, near = [], []
    for key, v in groups.items():
        if len(v) < 2:
            continue
        pages = {d['pages'] for d in v}
        wmax, wmin = max(d['words'] for d in v), min(d['words'] for d in v)
        same_len = len(pages) == 1 and (wmax - wmin) <= max(1, wmax) * 0.05
        if not same_len:
            near.append((key, v))
            continue
        names, pairs = refs
        def rank(d):
            fold, b = _split(d['primary_source'])
            # 0 = this exact folder+file is deep-linked; 1 = the name is referenced
            # somewhere; 2 = not referenced at all. Only rank 0 is proof of THIS path.
            tier = 0 if (fold, b) in pairs else (1 if b in names else 2)
            return (tier, -d['words'], -len(b))
        ordered = sorted(v, key=rank)
        for loser in ordered[1:]:
            drop.append({'doc': loser, 'keeper': ordered[0], 'key': key})
    return drop, near


def sha(path, buf=1 << 20):
    h = hashlib.sha1()
    with open(path, 'rb') as fh:
        for c in iter(lambda: fh.read(buf), b''):
            h.update(c)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--undo', metavar='LOGFILE')
    ap.add_argument('--manifest', default=MANIFEST)
    args = ap.parse_args()

    if args.undo:
        log = json.load(open(args.undo, encoding='utf-8'))
        n = 0
        for a in reversed(log['actions']):
            if os.path.exists(a['to']) and not os.path.exists(a['from']):
                os.makedirs(os.path.dirname(a['from']), exist_ok=True)
                shutil.move(a['to'], a['from'])
                n += 1
        print(f'reversed {n} of {len(log["actions"])} moves')
        return

    man = json.load(open(args.manifest, encoding='utf-8'))
    docs = man['documents']
    refs = referenced_files()
    drop_docs, near_miss = logical_dupes(docs, refs)
    drop_ids = {d['doc']['id'] for d in drop_docs}

    # The plan is built ENTIRELY from the manifest, so a manifest that no longer
    # describes the disk produces a confidently wrong plan. Seen 2026-08-02: after an
    # --apply followed by --undo, the manifest still described the moved layout, so this
    # found no data\ paths and reported "0 documents to move" - a true statement about
    # the manifest and a false one about the filesystem. Check freshness first.
    missing = sum(1 for d in docs if not os.path.exists(d['primary_source']))
    if missing > len(docs) * 0.05:
        sys.exit(f'REFUSED: the manifest is stale - {missing} of {len(docs)} primary_source paths\n'
                 f'         do not exist on disk. It describes a layout that is no longer there.\n'
                 f'         Rebuild it first:  python scripts\\build_corpus.py --force')

    # Fail loudly if the manifest and this script disagree about where data\ is,
    # rather than reporting an empty plan as if there were nothing to do.
    any_data = sum(1 for d in docs for s in d.get('sources', []) if '/data/' in _norm(s))
    plan, dupes, skipped = [], [], []
    for d in docs:
        if d['doc_type'] not in DEST:
            continue                                   # broker_report / credit stay put
        if d['id'] in drop_ids:
            # Same document as another entry; every one of its paths is staged below.
            continue
        q = quarter_of(d)
        # The primary source is the one that moves; any other path holding the same
        # bytes is redundant by construction (the manifest deduped on content hash).
        srcs = [s for s in d['sources'] if _norm(s).startswith(SOURCE_PREFIXES)]
        if not srcs:
            skipped.append((d['title'], 'already outside data\\'))
            continue
        primary = d['primary_source'] if d['primary_source'] in srcs else srcs[0]
        target = os.path.join(DEST[d['doc_type']], q, os.path.basename(primary))
        plan.append({'id': d['id'], 'from': primary, 'to': target,
                     'type': d['doc_type'], 'quarter': q})
        for extra in srcs:
            if extra != primary:
                dupes.append({'id': d['id'], 'from': extra,
                              'to': os.path.join(DUPES, os.path.basename(extra))})

    # Logical duplicates: every path of the losing copy goes to _to_delete, wherever it
    # sits. A loser already under Documents\ is staged too - it is redundant there just
    # as much as in data\ - UNLESS a live JSON references it, which rank() prevents.
    for item in drop_docs:
        for pth in item['doc']['sources']:
            dupes.append({'id': item['doc']['id'], 'from': pth,
                          'to': os.path.join(DUPES, os.path.basename(pth))})

    if any_data and not plan:
        sys.exit(f'REFUSED: the manifest lists {any_data} paths under data\\ but none matched\n'
                 f'         {SOURCE_PREFIXES}\n'
                 f'         ROOT is {ROOT!r} - is it right for this machine?')
    byq = Counter((p['type'], p['quarter']) for p in plan)
    print(f'  {len(plan)} documents to move')
    print(f'  {len(dupes)} duplicate copies to stage for deletion')
    if drop_docs:
        print(f'    of which {len(drop_docs)} are the SAME document under a second naming')
        print(f'    convention (different bytes, so the content hash could not see them):')
        for it in drop_docs[:8]:
            k = it['key']
            keep = _split(it['keeper']['primary_source'])[1]
            kfold, kbase = _split(it['keeper']['primary_source'])
            linked = (' [DEEP-LINKED]' if (kfold, kbase) in refs[1]
                      else ' [referenced]' if kbase in refs[0] else '')
            print(f'      {"/".join(k[0]):6} {k[1]:12} keep: {keep[:58]}{linked}')
            print(f'      {"":6} {"":12} drop: {_split(it["doc"]["primary_source"])[1][:58]}')
        if len(drop_docs) > 8:
            print(f'      ... and {len(drop_docs)-8} more')
    if near_miss:
        print(f'  {len(near_miss)} ticker+date groups match but DISAGREE on length - left alone:')
        for k, v in near_miss[:5]:
            print(f'      {"/".join(k[0]):6} {k[1]:12} {k[2]}: ' +
                  ', '.join(f'{d["pages"]}p/{d["words"]}w' for d in v))
    if skipped:
        print(f'  {len(skipped)} already outside data\\ (untouched)')
    print()
    for t in sorted(DEST):
        qs = sorted([q for (tt, q) in byq if tt == t],
                    key=lambda k: (9999, 9) if k == 'Undated'
                    else (int(k.split('_')[1]), 0 if k.startswith('FY') else int(k[1])))
        if not qs:
            continue
        print(f'  Documents\\{os.path.basename(DEST[t])}\\')
        for q in qs:
            print(f'      {q:10} {byq[(t, q)]:>4}')
    print()

    if not args.apply:
        print('  DRY RUN - nothing moved. Re-run with --apply.')
        return

    log = {'_generated': __import__('datetime').datetime.now().isoformat(timespec='seconds'),
           'actions': []}
    moved = staged = collided = 0
    for item in plan + [dict(d, type='dupe', quarter='') for d in dupes]:
        src, dst = item['from'], item['to']
        if not os.path.exists(src):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(dst):
            # Never overwrite. Same bytes -> the source is redundant; different bytes
            # -> keep both under a suffix and say so, rather than picking a winner.
            if sha(src) == sha(dst):
                alt = os.path.join(DUPES, os.path.basename(src))
                os.makedirs(DUPES, exist_ok=True)
                base, ext = os.path.splitext(alt)
                k = 1
                while os.path.exists(alt):
                    alt = f'{base}__{k}{ext}'; k += 1
                shutil.move(src, alt)
                log['actions'].append({'from': src, 'to': alt, 'why': 'identical to target'})
                staged += 1
                continue
            base, ext = os.path.splitext(dst)
            k = 1
            while os.path.exists(dst):
                dst = f'{base}__{k}{ext}'; k += 1
            collided += 1
        shutil.move(src, dst)
        log['actions'].append({'from': src, 'to': dst})
        if item['type'] == 'dupe':
            staged += 1
        else:
            moved += 1

    logpath = os.path.join(ROOT, 'data', 'corpus_move_log.json')
    with open(logpath, 'w', encoding='utf-8') as fh:
        json.dump(log, fh, indent=1, ensure_ascii=False)

    left = []
    for base in (os.path.join(ROOT, 'data', 'presentations'), os.path.join(ROOT, 'data', 'transcripts')):
        for dp, dn, fn in os.walk(base):
            left += [os.path.join(dp, f) for f in fn if f.lower().endswith('.pdf')]

    print(f'  moved            {moved}')
    print(f'  staged as dupes  {staged}')
    if collided:
        print(f'  name collisions  {collided} (kept both, suffixed __1)')
    print(f'  log              {logpath}   (--undo {logpath} reverses it)')
    print(f'  PDFs left in data\\ {len(left)}')
    if left:
        print('    ! not empty. Either these arrived after the last build, or the manifest was')
        print('      stale when the plan was built. Rebuild and re-run:')
        print('        python scripts\\build_corpus.py --force')
        print('        python scripts\\organize_corpus.py --apply')
        print('      first few:')
        for p in left[:10]:
            print('      ', p)
    print()
    print('  NEXT: python scripts\\build_corpus.py --force     (paths changed, so URLs must regenerate)')


if __name__ == '__main__':
    main()
