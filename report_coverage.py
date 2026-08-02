r"""
report_coverage.py — precedents.json  (read-only)

Prints what the database ACTUALLY contains right now: link coverage by field and
asset class, confidence mix, basis-vintage coverage, and the open QC queue.

Exists because coverage numbers were repeatedly quoted from memory or from a
stale copy and were wrong -- "24 decks" was really ~4 once XBRL files were
stripped out. Read the number off the file instead of trusting a note.

  python report_coverage.py
  python report_coverage.py --md      # markdown, for pasting into the tracker
"""

import json, io, os, sys, collections


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
LINK_FIELDS = ['agreement', 'deck', 'fairness_opinion', 'transcript',
               'press_release', 'press_release_joint',
               'press_release_target', 'press_release_acquirer',
               'filing', 'filing_index']
BASIS_METRICS = [('rate_base_mult', 'EV/RB'), ('ev_ebitda', 'EV/EBITDA'),
                 ('pe', 'P/E'), ('premium_pct', 'Premium')]


def main():
    md = '--md' in sys.argv
    db = json.load(open(SRC, encoding='utf-8'))
    deals = db['deals']
    n = len(deals)
    whole = [d for d in deals if d.get('deal_scope') == 'whole_company']

    out = []
    w = out.append
    bar = (lambda t: w('\n## ' + t + '\n')) if md else (lambda t: w('\n' + t + '\n' + '-' * 62))

    w('# Precedents coverage — %d deals (schema %s)' % (n, db.get('_schema_version'))
      if md else '=' * 62)
    if not md:
        w('PRECEDENTS COVERAGE — %d deals (schema %s)' % (n, db.get('_schema_version')))
        w('=' * 62)

    # ---- links
    bar('Link coverage')
    if md:
        w('| Field | Deals | % |')
        w('|---|---|---|')
    for f in LINK_FIELDS:
        c = sum(1 for d in deals if (d.get('links') or {}).get(f))
        if md:
            w('| %s | %d | %.0f%% |' % (f, c, 100.0 * c / n))
        else:
            w('  %-24s %3d / %d  (%3.0f%%)' % (f, c, n, 100.0 * c / n))

    # ---- confidence
    bar('Link confidence')
    conf = collections.Counter()
    for d in deals:
        for k, v in ((d.get('links') or {}).get('_link_confidence') or {}).items():
            conf[v] += 1
    for t in ('verified', 'strong', 'medium', 'weak', 'suspect'):
        if md:
            w('- **%s** %d' % (t, conf[t]))
        else:
            w('  %-10s %d' % (t, conf[t]))

    # ---- open QC queue
    nf = [(d['id'], (d.get('links') or {}).get('_needs_find'))
          for d in deals if (d.get('links') or {}).get('_needs_find')]
    bar('Open QC queue')
    line = '  needs a fresh find : %d deals' % len(nf)
    w(('- ' + line.strip()) if md else line)
    for did, fields in nf[:12]:
        s = '      %-34s %s' % (did, ', '.join(fields or []))
        w(('  - `%s` — %s' % (did, ', '.join(fields or []))) if md else s)
    line2 = '  weak/suspect links : %d  (see qc_links.md)' % (conf['weak'] + conf['suspect'])
    w(('- ' + line2.strip()) if md else line2)

    # ---- basis
    bar('Multiple-basis coverage (documented vintage)')
    if md:
        w('| Class | ' + ' | '.join(l for _, l in BASIS_METRICS) + ' |')
        w('|---' * (len(BASIS_METRICS) + 1) + '|')
    byc = collections.defaultdict(lambda: collections.Counter())
    for d in deals:
        B = d.get('basis') or {}
        for k, lab in BASIS_METRICS:
            if k in B:
                byc[d['asset_class']][(lab, 'tot')] += 1
                if B[k].get('status') == 'documented':
                    byc[d['asset_class']][(lab, 'doc')] += 1
    for cls in sorted(byc):
        cells = []
        for _, lab in BASIS_METRICS:
            t = byc[cls][(lab, 'tot')]
            dd = byc[cls][(lab, 'doc')]
            cells.append('%d/%d' % (dd, t) if t else '-')
        if md:
            w('| %s | %s |' % (cls, ' | '.join(cells)))
        else:
            w('  %-24s %s' % (cls, '  '.join('%-9s' % c for c in cells)))

    # ---- whole-company subset
    bar('Whole-company deals (%d) — where a proxy/agreement should exist' % len(whole))
    for f in ('agreement', 'fairness_opinion', 'deck'):
        c = sum(1 for d in whole if (d.get('links') or {}).get(f))
        line = '  %-20s %3d / %d  (%3.0f%%)' % (f, c, len(whole), 100.0 * c / len(whole))
        w(('- **%s** %d / %d (%.0f%%)' % (f, c, len(whole), 100.0 * c / len(whole)))
          if md else line)

    txt = '\n'.join(out)
    print(txt)
    if md:
        dst = os.path.join(os.path.dirname(SRC), 'coverage_report.md')
        io.open(dst, 'w', encoding='utf-8').write(txt + '\n')
        print('\nwrote %s' % dst)


if __name__ == '__main__':
    main()