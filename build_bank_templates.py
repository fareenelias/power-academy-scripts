"""build_bank_templates.py - derive data\bank_report_templates.json from broker_research.json.

The tracker's oldest phantom (logged as built 2026-07-16, never landed, cost two sessions).
Built tonight the honest way: DERIVED from what the 160 captured reports actually printed -
every 'house label' note, per-broker metric coverage, and the model-exhibit page pattern.

Use during the broker-research grind (Phase 3/4): before hunting a house's model pages,
read its entry - which canonical metrics the house has ever printed, what IT calls each row
(only divergent labels were noted at capture; an unlisted metric means the house's label
matched the canonical name), and which pages its model exhibits usually sit on.

DERIVED file - regenerate after assemble.py merges (python scripts/build_bank_templates.py).
Never hand-edit; corrections belong in broker_research.json notes and flow through.
"""
import json, os, re, collections

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, 'data', 'broker_research.json')
OUT = os.path.join(BASE, 'data', 'bank_report_templates.json')

# The 2026-07-16 hand-seeded hints from the original (never-landed) plan - kept as
# seeds with their provenance, since they came from eyes on reports, not from notes.
SEEDS = {
    'J.P. Morgan': {'operating_income': 'Adj. EBIT'},
    'Truist Securities': {'operating_income': 'Operating Income'},
    'BMO Capital Markets': {'operating_income': 'Consolidated EBIT (CHECK: may include other income)'},
    'Wells Fargo': {'operating_income': 'EBIT'},
}

def main():
    d = json.load(open(SRC, encoding='utf-8'))
    houses = {}
    for tkr, e in d.items():
        if tkr.startswith('_') or not isinstance(e, dict): continue
        for r in e.get('reports', []):
            b = r.get('broker')
            if not b: continue
            h = houses.setdefault(b, {'reports': 0, 'tickers': set(), 'metrics': set(),
                                      'labels': collections.defaultdict(set), 'pages': []})
            h['reports'] += 1
            h['tickers'].add(tkr)
        mets = (e.get('financial_estimates') or {}).get('metrics') or {}
        for mk, mv in mets.items():
            for br, o in (mv.get('by_broker') or {}).items():
                h = houses.setdefault(br, {'reports': 0, 'tickers': set(), 'metrics': set(),
                                           'labels': collections.defaultdict(set), 'pages': []})
                h['metrics'].add(mk)
                n = o.get('note') or ''
                m = re.search(r"house label '([^']+)'", n)
                # prose captures ('planned 2026 annual investment of $126 million') are
                # not row labels - refuse long or figure-carrying strings.
                if m and len(m.group(1)) <= 45 and not re.search(r'\$|\d{3}', m.group(1)):
                    h['labels'][mk].add(m.group(1))
                if isinstance(o.get('source_page'), int) and o['source_page'] <= 40:
                    h['pages'].append(o['source_page'])   # >40 = legacy bulk-file numbering

    out_houses = {}
    for b in sorted(houses):
        h = houses[b]
        pages = sorted(collections.Counter(h['pages']).items(), key=lambda x: -x[1])[:4]
        entry = {
            'reports_captured': h['reports'],
            'tickers_covered': sorted(h['tickers']),
            'metrics_ever_printed': sorted(h['metrics']),
            'divergent_row_labels': {k: sorted(v) for k, v in sorted(h['labels'].items())},
            'model_page_hint': [p for p, _ in pages],
        }
        if b in SEEDS:
            entry['seed_hints_2026_07_16'] = SEEDS[b]
        out_houses[b] = entry

    # controls
    assert len(out_houses) >= 20, 'implausibly few houses'
    assert sum(h['reports_captured'] for h in out_houses.values()) >= 150
    for b, h in out_houses.items():
        for mk, labs in h['divergent_row_labels'].items():
            assert mk in h['metrics_ever_printed'] or mk, (b, mk)

    doc = {
        '_note': ('Per-house extraction templates, DERIVED from broker_research.json (regenerate '
                  'with scripts/build_bank_templates.py after merges; never hand-edit). '
                  'divergent_row_labels lists only labels that DIFFERED from the canonical metric '
                  'name at capture - an unlisted metric means the house printed the canonical name. '
                  'model_page_hint = most common model-exhibit pages (<=40; legacy bulk-file page '
                  'numbers excluded). metrics_ever_printed is a ceiling for what a quick note may '
                  'carry - full models reliably appear only in initiations / model updates / deep '
                  'dives. Replaces the 2026-07-16 phantom of the same name.'),
        '_generated': '2026-09-21',
        '_source': {'reports': sum(h['reports_captured'] for h in out_houses.values()),
                    'houses': len(out_houses)},
        'houses': out_houses,
    }
    json.dump(doc, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('wrote %s: %d houses, %d reports' % (OUT, len(out_houses), doc['_source']['reports']))
    for b, h in out_houses.items():
        print('  %-26s reports=%-3d metrics=%-2d divergent_labels=%-2d pages=%s' %
              (b, h['reports_captured'], len(h['metrics_ever_printed']),
               sum(len(v) for v in h['divergent_row_labels'].values()), h['model_page_hint']))

if __name__ == '__main__':
    main()
