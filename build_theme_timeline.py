"""build_theme_timeline.py - guidance item 6: theme first-mention timeline off the transcripts.

When did each name first say "data center", first QUANTIFY large load in GW, and first
name a specific hyperscaler? The corpus search answers this per query; this file turns
it into a per-name dated strip so nobody has to think to search for it.

Sources: data\corpus\text\<id>.txt for every DATED transcript in corpus_manifest.json
(dateless transcripts are skipped and counted - a first-mention claim needs a date).

Stored content is DISCRETE FACTS ONLY - dates, pages, counts, a GW figure, a company
name, the matched term. Never transcript prose (S&P transcripts carry a no-reproduction
notice; same rule as earnings_calls.json).

Match rules, stated once:
  - data_center: /data\s*cent(er|re)|datacenter/i anywhere.
  - gw_quantified: a GW figure within +/-300 chars of a data-center / large-load /
    hyperscale / co-location term - a bare GW number elsewhere is fleet talk, not the
    large-load theme.
  - hyperscaler_named: a named operator within +/-400 chars of the same context terms,
    so "you can Google it" never counts. Names list below; 'Meta' must be capitalized.

Derived file - regenerate after new transcripts rip. Served at /api/eia/theme_timeline.json.
"""
import json, os, re, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
TEXT = os.path.join(DATA, 'corpus', 'text')

RE_PAGE = re.compile(r'\[\[PAGE (\d+)\]\]')
RE_DC = re.compile(r'data\s*cent(?:er|re)s?|datacenter', re.I)
RE_CTX = re.compile(r'data\s*cent(?:er|re)s?|datacenter|large[\s-]load|hyperscal\w*|co-?location', re.I)
RE_GW = re.compile(r'(\d+(?:\.\d+)?)\s*(?:GW\b|gigawatts?)', re.I)
# Case-sensitive where ambiguity bites (Meta/metal, xAI); word-bounded.
HYPERSCALERS = [
    ('Microsoft', re.compile(r'\bMicrosoft\b')),
    ('Amazon/AWS', re.compile(r'\bAmazon\b|\bAWS\b')),
    ('Google', re.compile(r'\bGoogle\b|\bAlphabet\b')),
    ('Meta', re.compile(r'\bMeta\b')),
    ('Oracle', re.compile(r'\bOracle\b')),
    ('OpenAI', re.compile(r'\bOpenAI\b')),
    ('xAI', re.compile(r'\bxAI\b')),
    ('Anthropic', re.compile(r'\bAnthropic\b')),
    ('Stargate', re.compile(r'\bStargate\b')),
]

def page_at(txt, pos):
    """Page of the [[PAGE N]] marker most recently before pos (transcript footer pages)."""
    page = None
    for m in RE_PAGE.finditer(txt, 0, pos + 12):
        if m.start() > pos: break
        page = int(m.group(1))
    return page

def main():
    man = json.load(open(os.path.join(DATA, 'corpus_manifest.json'), encoding='utf-8'))
    docs = [d for d in man['documents'] if d.get('doc_type') == 'transcript']
    dated = [d for d in docs if d.get('date')]
    skipped_undated = len(docs) - len(dated)
    dated.sort(key=lambda d: d['date'])

    out = collections.OrderedDict()
    missing_text = 0
    for d in dated:
        tp = os.path.join(TEXT, d['id'] + '.txt')
        if not os.path.exists(tp):
            missing_text += 1; continue
        txt = open(tp, encoding='utf-8', errors='ignore').read()

        dc = list(RE_DC.finditer(txt))
        ctx_spans = [(m.start(), m.end()) for m in RE_CTX.finditer(txt)]
        def in_ctx(pos, win):
            return any(s - win <= pos <= e + win for s, e in ctx_spans)
        gw_hits = [m for m in RE_GW.finditer(txt) if in_ctx(m.start(), 300)]
        hs_hits = []
        for name, rx in HYPERSCALERS:
            for m in rx.finditer(txt):
                if in_ctx(m.start(), 400):
                    hs_hits.append((m.start(), name)); break   # first per operator
        hs_hits.sort()

        ref = {'date': d['date'], 'period': d.get('period'), 'event': d.get('event'),
               'doc_id': d['id'], 'title': d.get('title'), 'url': d.get('url')}
        for tkr in d.get('tickers') or []:
            t = out.setdefault(tkr, {'firsts': {}, 'mention_series': []})
            if dc:
                t['mention_series'].append({'date': d['date'], 'period': d.get('period'),
                                            'mentions': len(dc), 'doc_id': d['id'], 'url': d.get('url'),
                                            'page_first': page_at(txt, dc[0].start())})
                if 'data_center' not in t['firsts']:
                    t['firsts']['data_center'] = dict(ref, page=page_at(txt, dc[0].start()),
                                                      mentions_that_call=len(dc))
            if gw_hits and 'gw_quantified' not in t['firsts']:
                m0 = gw_hits[0]
                t['firsts']['gw_quantified'] = dict(ref, page=page_at(txt, m0.start()),
                                                    gw=float(m0.group(1)))
            if hs_hits and 'hyperscaler_named' not in t['firsts']:
                pos, name = hs_hits[0]
                t['firsts']['hyperscaler_named'] = dict(ref, page=page_at(txt, pos), name=name)

    # controls
    assert out, 'no tickers produced'
    n_dc = sum(1 for t in out.values() if 'data_center' in t['firsts'])
    n_gw = sum(1 for t in out.values() if 'gw_quantified' in t['firsts'])
    n_hs = sum(1 for t in out.values() if 'hyperscaler_named' in t['firsts'])
    for t, v in out.items():
        f = v['firsts']
        if 'gw_quantified' in f and 'data_center' not in f:
            # GW-near-large-load can legitimately precede the words "data center" (IPPs);
            # allowed, but the series must still be ordered.
            pass
        dates = [r['date'] for r in v['mention_series']]
        assert dates == sorted(dates), t

    doc = {
        '_note': ('Theme first-mention timeline off the DATED transcripts in the corpus '
                  '(%d transcripts scanned; %d undated skipped; %d missing text). Discrete facts only - '
                  'dates, pages, counts, a GW figure, an operator name - never transcript prose. '
                  'gw_quantified and hyperscaler_named require large-load context within 300/400 chars; '
                  'first per operator per call. Derived file: python scripts/build_theme_timeline.py.'
                  % (len(dated), skipped_undated, missing_text)),
        'themes': {'data_center': 'first "data center" mention',
                   'gw_quantified': 'first GW figure in large-load context',
                   'hyperscaler_named': 'first named operator in large-load context'},
        'tickers': out,
    }
    path = os.path.join(DATA, 'theme_timeline.json')
    json.dump(doc, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('wrote', path)
    print('tickers: %d | first data_center: %d | first GW: %d | first hyperscaler: %d'
          % (len(out), n_dc, n_gw, n_hs))
    for t in sorted(out):
        f = out[t]['firsts']
        bits = []
        if 'data_center' in f: bits.append('DC %s' % f['data_center']['date'])
        if 'gw_quantified' in f: bits.append('%gGW %s' % (f['gw_quantified']['gw'], f['gw_quantified']['date']))
        if 'hyperscaler_named' in f: bits.append('%s %s' % (f['hyperscaler_named']['name'], f['hyperscaler_named']['date']))
        print('  %-5s %s' % (t, ' | '.join(bits) if bits else '-'))

if __name__ == '__main__':
    main()
