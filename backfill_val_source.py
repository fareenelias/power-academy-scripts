# -*- coding: utf-8 -*-
r"""Guarantee every valuation-summary row carries a source page link, and promote
fully-quantified PROSE sum-of-the-parts builds to linked sources.

Fareen, 2026-07-31:
  "you can link to the page number its references"
  "the valuation summary should have a source linking to the page number in the broker
   report if it doesn't already exist"

Two things happen here.

1. `methodology_page` is backfilled on every report that has neither an inline `p.N`
   reference in its `valuation_methodology` prose nor an explicit `methodology_page`.
   Priority order, best evidence first:
       valuation_multiples.{base,low,high}.source_page   (the page the multiple is on)
       sotp.source_page                                   (the exhibit page)
       source_pages[0]                                    (the report's own first page)
   The last is a weaker claim, so it is recorded with `methodology_page_basis` saying
   so - a link that lands on the right report but a best-guess page is honest; a link
   that silently pretends to be exact is not.

2. A prose SOTP that is FULLY QUANTIFIED gets a `sotp` block with `format: "prose"`
   and the page the prose sits on. It is deliberately distinguished from a real
   exhibit (`format: "table"`) so the UI can say which it is - the rule stays that a
   prose mention is not a table, but a prose mention still has a page worth linking.

  python3 backfill_val_source.py <broker_research.json>
"""
import json, os, re, sys, collections

P = sys.argv[1]

# Fully-quantified prose sum-of-the-parts. Components transcribed from the printed
# prose, NOT from a table - hence format 'prose'. Nothing here is derived: every
# figure below appears verbatim in the note.
PROSE_SOTP = {
 'PCG_Ladenburg-20260409.pdf': {
   'exhibit_label': 'Valuation paragraph (prose sum-of-the-parts)',
   'source_page': 3,
   'format': 'prose',
   'components': [
     {'segment': 'Regulated electric utility', 'metric': '2028E EPS', 'value': 1.65,
      'multiple': 12.0, 'implied_value': 20.00,
      'note': 'a 30% discount to the group average; includes a $0.08 addback of '
              'disallowed utility interest'},
     {'segment': 'Regulated gas utility', 'metric': '2028E EPS', 'value': 0.53,
      'multiple': 11.2, 'implied_value': 6.00,
      'note': 'also a 30% discount to the group average'},
     {'segment': 'Parent unallocated and disallowed utility debt', 'metric': 'per share',
      'implied_value': -3.00,
      'note': '$2.1bn of parent unallocated debt plus $6.7bn of estimated utility '
              'disallowed debt'},
   ],
   'total_implied_value': 23.00,
   'note': "Ladenburg prints no SOTP exhibit - the build is written out in prose on "
           "p.3 and is fully quantified, so it is carried with format 'prose' and "
           "linked to that page rather than being dropped. Ladenburg also notes its "
           "targets are dynamic because the group average multiples are recalculated "
           "daily, so the multiples move even when the thesis does not.",
 },
}

# Reports whose note CLAIMS a sum-of-the-parts but prints neither a table nor a
# segment build. These get a page link like everything else, and an explicit
# statement that there is no SOTP to link - so nobody goes looking for one again.
SOTP_CLAIMED_BUT_ABSENT = {
 'POR_Ladenburg-20260601.pdf':
   "The note describes its approach as a sum-of-the-parts but prints no SOTP table "
   "and no segment build anywhere: the $43.00 target is a single-multiple P/E build "
   "(2028 electric-utility EPS of $3.52 at 12.3x, a 25% discount to the electric "
   "utility group), on p.5. No `sotp` block is emitted because there is nothing to "
   "link to - the valuation page link covers it.",
}


def main():
    d = json.load(open(P, encoding='utf-8'), object_pairs_hook=collections.OrderedDict)
    filled = collections.Counter()
    from_ = collections.Counter()

    for t, v in d.items():
        if t.startswith('_') or not isinstance(v, dict):
            continue
        for r in v.get('reports', []):
            sf = r.get('source_file')

            if sf in PROSE_SOTP and not r.get('sotp'):
                r['sotp'] = json.loads(json.dumps(PROSE_SOTP[sf]),
                                       object_pairs_hook=collections.OrderedDict)
                filled['prose_sotp'] += 1
            if sf in SOTP_CLAIMED_BUT_ABSENT:
                r['sotp_note'] = SOTP_CLAIMED_BUT_ABSENT[sf]
                filled['sotp_absent_note'] += 1

            # mark real exhibits explicitly, so 'prose' vs 'table' is never ambiguous
            s = r.get('sotp')
            if s and 'format' not in s:
                s['format'] = 'table'

            vm = r.get('valuation_methodology') or ''
            if re.search(r'p\.\s?\d+', vm) or r.get('methodology_page'):
                continue

            page, basis = None, None
            mult = r.get('valuation_multiples') or {}
            for leg in ('base', 'low', 'high'):
                pg = (mult.get(leg) or {}).get('source_page')
                if pg:
                    page, basis = pg, 'page of the target multiple in valuation_multiples'
                    break
            if page is None and (r.get('sotp') or {}).get('source_page'):
                page, basis = r['sotp']['source_page'], 'page of the SOTP exhibit'
            if page is None and r.get('source_pages'):
                page = r['source_pages'][0]
                basis = ('FALLBACK - first page drawn from for this report, not a '
                         'located valuation page. The link opens the right report; '
                         'the page is a best guess.')
            if page is None:
                continue

            r['methodology_page'] = page
            r['methodology_page_basis'] = basis
            filled['methodology_page'] += 1
            from_['fallback' if basis.startswith('FALLBACK') else 'located'] += 1

    tmp = P + '.tmp'
    json.dump(d, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    json.load(open(tmp, encoding='utf-8'))
    os.replace(tmp, P)

    print('filled:', dict(filled))
    print('methodology_page provenance:', dict(from_))

    # audit: nothing may be left without a link
    d = json.load(open(P, encoding='utf-8'))
    stuck = [(t, r.get('broker'), r.get('source_file'))
             for t, v in d.items() if not t.startswith('_') and isinstance(v, dict)
             for r in v.get('reports', [])
             if not re.search(r'p\.\s?\d+', r.get('valuation_methodology') or '')
             and not r.get('methodology_page')]
    print('reports STILL with no valuation page link:', stuck if stuck else 'none')


main()
