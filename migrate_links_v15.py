"""
migrate_links_v15.py — precedents.json  (schema 1.4 -> 1.5)

PROBLEM: one link slot was doing several jobs. `links.filing` holds the 8-K BODY
on 42 of 54 deals, not the merger agreement -- so a column labelled "8-K" was
promising a document it wasn't delivering.

Each slot now means exactly one thing:

  agreement         merger / purchase agreement          EX-2.1 (or EX-2.x)
  filing            the 8-K body itself                  the announcement filing
  deck              announcement investor deck           EX-99.2 typically
  fairness_opinion  banker's opinion section             S-4 / DEFM14A / SC 14D9
  press_release_target / _acquirer                       one per side
  filing_index      the accession folder                 everything else hangs off this

agreement and fairness_opinion are created EMPTY and populated by
resolve_agreements.py, which must run where sec.gov is reachable. Anything this
script can migrate with certainty (an existing EX-2 link) is moved across; nothing
is guessed.

Idempotent.
"""

import json, io, re, shutil, collections

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
EX2 = re.compile(r'(ex-?2[._]?\d*|dex2\d*|_ex_?2|merger.?agreement)', re.I)
# EX-2.1 is the convention, not the rule -- Dominion/Questar filed the agreement
# as EX-99.1. Filename matching alone is why the earlier link pass mis-sorted
# documents; the resolver must read EDGAR's Type/Description columns.
PROXY = re.compile(r'(defm?14a|s-?4|sc.?14d9|dprem14a|424b3)', re.I)


def main():
    db = json.load(open(SRC, encoding='utf-8'))
    deals = db['deals']

    if db.get('_schema_version') == '1.5':
        print('already migrated — no-op')
        return

    moved = collections.Counter()
    for d in deals:
        L = d.setdefault('links', {})
        L.setdefault('agreement', None)
        L.setdefault('fairness_opinion', None)

        f = L.get('filing')
        # only reclassify when the filename is unambiguous
        if f and L['agreement'] is None and EX2.search(f.rsplit('/', 1)[-1]):
            L['agreement'] = f
            moved['filing -> agreement'] += 1

        # a proxy sitting in source_doc is where an opinion would live, but the
        # SECTION url is what we want, not the whole document -- flag, don't claim
        sd = L.get('source_doc')
        if sd and PROXY.search(sd.rsplit('/', 1)[-1]):
            L['_fo_candidate'] = sd
            moved['proxy flagged as FO candidate'] += 1

        # reorder canonically so the file reads predictably
        order = ['filing_index', 'agreement', 'filing', 'deck', 'fairness_opinion',
                 'press_release', 'press_release_target', 'press_release_acquirer',
                 'press_release_target_ir', 'press_release_acquirer_ir',
                 'source_doc', 'news', 'milestones']
        new = {k: L[k] for k in order if k in L}
        for k in L:
            if k not in new:
                new[k] = L[k]
        d['links'] = new

    db['_schema_version'] = '1.5'
    db.setdefault('_merge_meta', {})['link_semantics_v15'] = {
        'agreement': 'merger or purchase agreement — EX-2.x on the announcement 8-K. '
                     'The legally operative document: consideration, conditions, '
                     'termination fees, closing covenants.',
        'filing': 'the 8-K body itself — the announcement filing, not the agreement.',
        'deck': 'announcement investor presentation — EX-99.2 typically. The deal '
                'as management pitched it, incl. the multiples they chose to show.',
        'fairness_opinion': "financial advisor's opinion section in the merger proxy "
                            '(S-4 / DEFM14A) or SC 14D9 for tender offers. Discloses the '
                            "banker's own selected-precedent set, multiple ranges and DCF "
                            '— doubles as a cross-check on this database.',
        'press_release_target / press_release_acquirer': 'one release per side; buyer and '
                                                        'seller frame the same deal differently.',
        '_note': 'agreement + fairness_opinion created empty at v1.5; populate via '
                 'resolve_agreements.py (needs sec.gov reachable). Filename patterns are '
                 'a hint only — EDGAR Type/Description columns are authoritative.',
    }

    shutil.copyfile(SRC, SRC + '.bak3')
    with io.open(SRC, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
        f.write('\n')

    print('schema -> 1.5')
    for k, v in moved.items():
        print('  %-32s %d' % (k, v))
    print('  agreement populated        : %d / %d' % (
        sum(1 for d in deals if d['links'].get('agreement')), len(deals)))
    print('  fairness_opinion populated : %d / %d  (resolver pending)' % (
        sum(1 for d in deals if d['links'].get('fairness_opinion')), len(deals)))
    print('  deck populated             : %d / %d' % (
        sum(1 for d in deals if d['links'].get('deck')), len(deals)))
    print('  8-K body populated         : %d / %d' % (
        sum(1 for d in deals if d['links'].get('filing')), len(deals)))


if __name__ == '__main__':
    main()