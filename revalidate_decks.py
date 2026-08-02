r"""
revalidate_decks.py — precedents.json  (local; needs sec.gov reachable)

audit_decks.py found that most deck links carry no provenance: they were written
by passes that ran BEFORE the classifier was fixed (XBRL exclusion, EX-99.1 is
never a deck, content scoring). Leaving ~34 links unvalidated and calling the
field 40% covered would repeat the mistake that made "24 decks" mean ~4.

So: fetch every deck whose provenance is UNKNOWN / SUSPECT / SCORED-WEAK and put
it through the CURRENT check.

  passes -> keep, and record the evidence so it never needs re-checking
  fails  -> CLEAR the link and queue it in _needs_find (a wrong link is worse
            than an empty field; an empty field is honest)

Human-verified decks are never touched.

  python revalidate_decks.py --dry-run
  python revalidate_decks.py
  python revalidate_decks.py --only <deal_id>
"""

import json, io, os, re, sys, time, shutil, argparse, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    'sc', os.path.join(HERE, 'scrub_links.py'))
sc = importlib.util.module_from_spec(_spec)
_argv = sys.argv; sys.argv = ['reval']
_spec.loader.exec_module(sc)
sys.argv = _argv

SRC = sc.SRC
for i, _a in enumerate(sys.argv):
    if _a == '--file' and i + 1 < len(sys.argv):
        SRC = os.path.abspath(sys.argv[i + 1])

STATED = re.compile(r'desc=.*(presentation|slides|deck)', re.I)
BAD_URL = re.compile(r'\.(xml|xsd|json)$', re.I)


def needs_check(url, src):
    """True unless the link already carries strong, current evidence."""
    if not url:
        return False
    if BAD_URL.search(url):
        return True
    if not src:
        return True                      # no provenance at all
    if STATED.search(src):
        return False                     # description names it — already decisive
    m = re.search(r'image-heavy \((\d+) imgs, (\d+) words\)', src)
    if m and int(m.group(1)) >= 10 and int(m.group(2)) <= 5000:
        return False                     # solid content score from this pass
    # anything kept on "presentation wording" was scored while the wording list
    # still contained "forward-looking statements" -- boilerplate present in every
    # corporate document. Those all need re-checking against the corrected list.
    # anything scored on wording needs re-checking whenever the wording list is
    # revised -- and it has been revised twice now, so re-check on any of the
    # older evidence formats.
    if 'presentation wording' in src or 'wording' in src:
        return True
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--only')
    ap.add_argument('--file')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()

    db = json.load(open(SRC, encoding='utf-8'))
    deals = db['deals']
    if a.only:
        deals = [d for d in deals if d['id'] == a.only]

    todo = []
    for d in deals:
        L = d.get('links') or {}
        if (L.get('_verified') or {}).get('deck') == 'human':
            continue
        url = L.get('deck')
        if url and needs_check(url, str(L.get('_deck_src') or '')):
            todo.append(d)

    print('re-checking %d deck links against the current classifier\n' % len(todo))
    kept = cleared = failed = 0
    t0 = time.time()
    for i, d in enumerate(deals, 1):
        L = d.setdefault('links', {})
        if d not in todo:
            continue
        url = L['deck']
        if not a.quiet:
            el = time.time() - t0
            sys.stdout.write('\r  [%3d/%3d] %-32s  %4.0fs   '
                             % (i, len(deals), d['id'][:32], el))
            sys.stdout.flush()

        if BAD_URL.search(url):
            ok, why = False, 'technical file (.xml/.xsd/.json)'
        else:
            ok, why = sc.looks_like_deck(url)

        sys.stdout.write('\r' + ' ' * 78 + '\r')

        # A FETCH FAILURE IS NOT EVIDENCE THE LINK IS WRONG. Clearing on a network
        # error would destroy good links on any transient blip -- the same mistake
        # that once recorded unreachable filings as "no agreement exists".
        if not ok and 'fetch failed' in why:
            failed += 1
            print('  ...   %-32s unreachable — LEFT ALONE, re-run later' % d['id'])
            continue

        if ok:
            kept += 1
            print('  KEEP  %-32s %s' % (d['id'], why[:44]))
            if not a.dry_run:
                L['_deck_src'] = 'revalidated — content: %s' % why
        else:
            cleared += 1
            print('  CLEAR %-32s %s' % (d['id'], why[:44]))
            if not a.dry_run:
                L['_deck_was'] = url
                L['deck'] = None
                L.pop('_deck_src', None)
                nf = L.setdefault('_needs_find', [])
                if 'deck' not in nf:
                    nf.append('deck')

    if not a.dry_run:
        shutil.copyfile(SRC, SRC + '.bak_deckreval')
        with io.open(SRC, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
            f.write('\n')

    remaining = sum(1 for d in db['deals'] if (d.get('links') or {}).get('deck'))
    print('\n' + '=' * 58)
    print('  re-checked %d   kept %d   cleared %d   unreachable %d'
          % (len(todo), kept, cleared, failed))
    if failed:
        print('  %d could not be fetched — untouched; re-run to finish them.' % failed)
    print('  deck links remaining: %d' % remaining)
    print('  cleared links are queued in _needs_find — an empty field is honest,')
    print('  a wrong one is not.')
    print('DRY RUN — nothing written' if a.dry_run else 'written (backup .bak_deckreval)')


if __name__ == '__main__':
    main()