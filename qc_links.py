r"""
qc_links.py — precedents.json  (read-only)

The lesson from Fareen's 4/4 QC failure: the resolvers optimise for FINDING a
link, not for finding the RIGHT one, and their output was presented with uniform
confidence. A press-release URL that returns 200 on the right domain is
indistinguishable, to a script, from the correct release on that domain -- so a
stale slug ships looking exactly as trustworthy as a verified one.

This does not try to re-guess. It TIERS every link by how much we can actually
trust it, and prints a check-list of the ones that need a human eye -- so QC is
targeted instead of all-118-by-hand.

TIERS
  verified   links._verified[field] == 'human'         you checked it; trusted
  strong     SEC EX-2.x by Type / SEC EX-99.1          document type is pinned
  medium     SEC filing, type not pinned               right filing, maybe wrong exhibit
  weak       company/wire URL, slug not verifiable      <-- Class B: CHECK THESE
  suspect    domain mismatch, 425 as 'agreement', etc.  <-- likely wrong

Writes qc_links.md (a worklist) and per-deal links._link_confidence into a COPY
only if --write is passed; default is report-only.
"""

import json, io, os, re, collections, shutil


def _find():
    import sys
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

SEC = re.compile(r'sec\.gov/Archives', re.I)
EX2 = re.compile(r'(ex-?2[._]|dex2|_ex_?2\b)', re.I)
EX99 = re.compile(r'(ex-?99|dex99|ex_?99)', re.I)
FORM425 = re.compile(r'd?\d*425\.htm|_425\.htm|form425', re.I)
BAMSEC = re.compile(r'bamsec\.com/filing', re.I)   # human-curated agreement links
WIRE = re.compile(r'(prnewswire|businesswire|globenewswire)\.com', re.I)

# fields that carry a URL, and what kind of document each SHOULD be
FIELD_EXPECT = {
    'agreement': 'merger/purchase agreement (EX-2.x or bamsec agreement view)',
    'filing': '8-K / 425 announcement filing',
    'deck': 'investor deck (EX-99.2)',
    'fairness_opinion': 'merger proxy opinion section',
    'press_release': 'EX-99.1 or company/wire release',
    'press_release_target': 'target-side release',
    'press_release_acquirer': 'acquirer-side release',
}


def tier(field, url, verified, extra=None):
    if verified.get(field) == 'human':
        return 'verified', 'human-checked'
    if not url:
        return None, None

    if field == 'agreement':
        if BAMSEC.search(url):
            return 'strong', 'bamsec agreement view'
        if SEC.search(url) and EX2.search(url):
            return 'strong', 'SEC EX-2.x'
        if FORM425.search(url):
            return 'suspect', 'this is a Form 425, NOT the agreement'
        if SEC.search(url) and EX99.search(url):
            return 'suspect', 'EX-99 in the agreement slot (that is a PR/deck)'
        if SEC.search(url):
            return 'medium', 'SEC filing, exhibit type not pinned in URL'
        return 'weak', 'non-SEC URL for an agreement'

    if field in ('press_release', 'press_release_target', 'press_release_acquirer'):
        if SEC.search(url) and EX99.search(url):
            return 'strong', 'SEC EX-99.1'
        if WIRE.search(url):
            return 'medium', 'newswire — issuer release, slug not verified'
        if SEC.search(url):
            return 'medium', 'SEC filing'
        # company IR domain: right source, WRONG-SLUG risk (Class B)
        return 'weak', 'company/IR URL — slug not verifiable by script; CHECK'

    if field == 'deck':
        # tier on HOW the deck was identified, not just where it lives.
        # a description that literally says "investor presentation slides" is
        # decisive; a content score that barely cleared the image threshold is not.
        ev = (extra or '')
        if re.search(r'desc=.*(presentation|slides|deck)', ev, re.I):
            return 'strong', 'description names it a presentation'
        m = re.search(r'image-heavy \((\d+) imgs, (\d+) words\)', ev)
        if m:
            imgs, words = int(m.group(1)), int(m.group(2))
            if imgs >= 15 and words < 5000:
                return 'medium', 'content score: %d images' % imgs
            return 'weak', ('content score borderline: %d imgs / %d words — '
                            'could be a graphics-bearing press release' % (imgs, words))
        if 'presentation wording' in ev:
            return 'weak', 'inferred from wording only, no description — CHECK'
        if SEC.search(url) and EX99.search(url):
            return 'medium', 'SEC EX-99.x, identification method not recorded'
        return 'weak', 'deck URL not SEC-pinned'

    if field == 'fairness_opinion':
        return 'medium', 'proxy — validated to name bank+counterparty, section anchor may be page 1'

    if field == 'filing':
        if SEC.search(url):
            return 'strong', 'SEC filing'
        return 'weak', 'non-SEC filing URL'

    return 'medium', 'unclassified'


ORDER = ['suspect', 'weak', 'medium', 'strong', 'verified']


def main():
    write = '--write' in os.sys.argv
    db = json.load(open(SRC, encoding='utf-8'))
    deals = db['deals']

    counts = collections.Counter()
    worklist = collections.defaultdict(list)   # tier -> [(deal, field, url, why)]

    for d in deals:
        L = d.get('links') or {}
        ver = L.get('_verified') or {}
        conf = {}
        for field in FIELD_EXPECT:
            url = L.get(field)
            t, why = tier(field, url, ver, (L.get('_%s_src' % field) or ''))
            if t is None:
                continue
            conf[field] = t
            counts[t] += 1
            if t in ('suspect', 'weak'):
                worklist[t].append((d['id'], field, url, why))
        if write and conf:
            L['_link_confidence'] = conf

    # report
    print('=' * 62)
    print('LINK QC — confidence tiers across %d deals' % len(deals))
    print('=' * 62)
    for t in ORDER:
        print('  %-9s %d' % (t, counts[t]))
    print('\n  suspect + weak = %d links need a human check' % (counts['suspect'] + counts['weak']))

    out = io.StringIO()
    out.write('# Link QC worklist\n\n')
    out.write('Tiered by how much a script can trust each link. Work the SUSPECT '
              'list first (likely wrong), then WEAK (unverifiable slug — the Class B '
              'failure mode from the 4/4 QC).\n\n')

    # deals with a known-wrong link that was CLEARED and needs a fresh find
    needs = [(d['id'], (d.get('links') or {}).get('_needs_find') or [],
              (d.get('links') or {}).get('_agreement_qc') or '')
             for d in deals if (d.get('links') or {}).get('_needs_find')]
    if needs:
        out.write('## NEEDS FIND (%d) — link was found WRONG and cleared; hunt the real one\n\n'
                  % len(needs))
        for did, fields, note in sorted(needs):
            out.write('- [ ] **%s** · `%s`\n      %s\n' % (did, ', '.join(fields), note))
        out.write('\n')

    for t in ('suspect', 'weak'):
        items = worklist[t]
        out.write('## %s (%d)\n\n' % (t.upper(), len(items)))
        for did, field, url, why in sorted(items):
            out.write('- [ ] **%s** · `%s` — %s\n      %s\n' % (did, field, why, url))
        out.write('\n')
    dst = os.path.join(os.path.dirname(SRC), 'qc_links.md')
    io.open(dst, 'w', encoding='utf-8').write(out.getvalue())
    print('\nwrote %s' % dst)

    if write:
        shutil.copyfile(SRC, SRC + '.bak_qcconf')
        with io.open(SRC, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
            f.write('\n')
        print('wrote links._link_confidence into %s (backup .bak_qcconf)' % os.path.basename(SRC))
    else:
        print('(report only — pass --write to store per-link confidence in the file)')


if __name__ == '__main__':
    main()