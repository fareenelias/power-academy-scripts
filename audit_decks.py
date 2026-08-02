r"""
audit_decks.py — precedents.json  (read-only)

The deck field has been written by several passes, some of them BEFORE the
classifier was tightened (XBRL exclusion, content scoring, EX-99.1 never a deck).
Coverage now reads ~47 but only ~19 came from the current, checked logic -- the
rest carry no recorded provenance and have never been validated.

This lists every deck link grouped by the strength of the evidence behind it, so
QC starts with the ones that were never checked rather than the whole set.

  STATED      description literally says presentation / slides / deck
  SCORED      content check: image-heavy or presentation wording (this pass)
  UNKNOWN     no _deck_src recorded -- written by an earlier pass, NEVER CHECKED
  SUSPECT     looks wrong on its face (EX-99.1, .xml/.xsd, dividend wording)

  python audit_decks.py
  python audit_decks.py --md     # writes deck_audit.md
"""

import json, io, os, re, sys, collections


def _find():
    for i, a in enumerate(sys.argv):
        if a == '--file' and i + 1 < len(sys.argv):
            return os.path.abspath(sys.argv[i + 1])
    env = os.environ.get('PA_PRECEDENTS')
    if env and os.path.isfile(env):
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    for c in [os.path.join(here, '..', 'data', 'precedents.json'),
              os.path.join(here, 'precedents.json'),
              r'E:\PowerAcademy\data\precedents.json']:
        if os.path.isfile(os.path.normpath(c)):
            return os.path.normpath(c)
    raise SystemExit('precedents.json not found; pass --file')


SRC = _find()

STATED = re.compile(r'desc=.*(presentation|slides|deck)', re.I)
SCORED = re.compile(r'content:', re.I)
BAD_URL = re.compile(r'\.(xml|xsd|json)$', re.I)
EX991 = re.compile(r'ex-?99[._-]?1\b', re.I)
BAD_WORD = re.compile(r'(dividend|earnings|taxonomy|linkbase|xbrl)', re.I)


def classify(url, src, verified):
    if verified:
        return 'VERIFIED', 'human-checked'
    if BAD_URL.search(url or ''):
        return 'SUSPECT', 'technical file extension'
    if BAD_WORD.search(src or '') or BAD_WORD.search(url or ''):
        return 'SUSPECT', 'dividend/XBRL wording in source'
    if EX991.search(url or '') and 'ex-99.2' not in (url or '').lower():
        return 'SUSPECT', 'EX-99.1 is the press-release slot, not the deck'
    if not src:
        return 'UNKNOWN', 'no provenance recorded — written by an earlier pass'
    if STATED.search(src):
        return 'STATED', 'description names it a presentation'
    if SCORED.search(src):
        m = re.search(r'image-heavy \((\d+) imgs, (\d+) words\)', src)
        if m:
            imgs, words = int(m.group(1)), int(m.group(2))
            if imgs < 10 or words > 5000:
                return 'SCORED-WEAK', '%d imgs / %d words — borderline' % (imgs, words)
            return 'SCORED', '%d images' % imgs
        return 'SCORED-WEAK', 'wording only, no description'
    return 'UNKNOWN', 'provenance string not recognised'


def main():
    md = '--md' in sys.argv
    db = json.load(open(SRC, encoding='utf-8'))
    groups = collections.defaultdict(list)
    for d in db['deals']:
        L = d.get('links') or {}
        url = L.get('deck')
        if not url:
            continue
        src = str(L.get('_deck_src') or '')
        ver = (L.get('_verified') or {}).get('deck') == 'human'
        tier, why = classify(url, src, ver)
        groups[tier].append((d['id'], d.get('asset_class'), why, url))

    order = ['SUSPECT', 'UNKNOWN', 'SCORED-WEAK', 'SCORED', 'STATED', 'VERIFIED']
    total = sum(len(v) for v in groups.values())

    out = []
    w = out.append
    w('# Deck audit — %d deck links\n' % total)
    w('Grouped by the evidence that identified each one. Work top-down: SUSPECT '
      'and UNKNOWN were never validated by the current classifier.\n')
    for t in order:
        items = groups.get(t) or []
        if not items:
            continue
        w('\n## %s (%d)\n' % (t, len(items)))
        for did, cls, why, url in sorted(items):
            w('- [ ] **%s** (%s) — %s  \n      %s' % (did, cls, why, url))

    txt = '\n'.join(out)
    print('=' * 60)
    print('DECK AUDIT — %d deck links' % total)
    print('=' * 60)
    for t in order:
        if groups.get(t):
            print('  %-12s %d' % (t, len(groups[t])))
    unchecked = len(groups.get('SUSPECT') or []) + len(groups.get('UNKNOWN') or [])
    weak = len(groups.get('SCORED-WEAK') or [])
    print('\n  %d never validated by the current logic (SUSPECT + UNKNOWN)' % unchecked)
    print('  %d validated but BORDERLINE (SCORED-WEAK) — checked, just thin evidence'
          % weak)
    print('  %d solid (SCORED + STATED + VERIFIED)'
          % (len(groups.get('SCORED') or []) + len(groups.get('STATED') or [])
             + len(groups.get('VERIFIED') or [])))
    if md:
        dst = os.path.join(os.path.dirname(SRC), 'deck_audit.md')
        io.open(dst, 'w', encoding='utf-8').write(txt + '\n')
        print('  wrote %s' % dst)
    else:
        print('\n(run with --md to write deck_audit.md as a checklist)')


if __name__ == '__main__':
    main()