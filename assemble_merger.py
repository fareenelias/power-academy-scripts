# -*- coding: utf-8 -*-
r"""assemble_merger.py - merge the per-deal SPEC_MERGER extracts into data\merger_valuation.json.

  python E:\PowerAcademy\scripts\assemble_merger.py [--in data\_merge\merger_extract] [--out data\merger_valuation.json]

Adds, per deal:
  offer            offer $/share from precedents.json raw.offer_px (the reference line on the football field)
  bars[]           one row per advisor x method with a $/share range: {bank, side, method, label, low, high,
                   reference_only, subject, terminal}. Dict-shaped results (e.g. {'2026E': [..], '2027E': [..]})
                   become one bar per key; exchange-ratio-only results (a ratio, not $) are left out of bars
                   and stay in the method records.
And a cross-deal board:
  board[]          per deal x advisor: methods used, DCF terminal treatments (canonical type + range),
                   precedent / trading multiples cited (metric + selected range), comp-set sizes.
Deep links: every advisor, method, process and projections block gets `src` = an anchored working copy of the
filing (data\_proxies\linked\<deal>.htm, served by Caddy at :8080/corpus/_proxies/linked/) with an <a id>
dropped in front of that passage - any browser jumps there and the passage is highlighted. `src_sec` keeps the
SEC original with a text fragment; `src_exact` says whether the anchor was placed (else the copy's top).
Canonical terminal types: exit_pe, exit_ev_ebitda, exit_ev_rate_base, exit_price_book, perpetual_growth, other.
"""
import os, sys, json, glob, re, datetime as dt

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TERM = [('perpetual', 'perpetual_growth'), ('growth', 'perpetual_growth'), ('rate_base', 'exit_ev_rate_base'),
        ('rate base', 'exit_ev_rate_base'), ('book', 'exit_price_book'), ('ebitda', 'exit_ev_ebitda'),
        ('pe', 'exit_pe'), ('p/e', 'exit_pe')]



# ── deep links into the proxy (Chrome/Edge text fragments: <url>#:~:text=<exact snippet>) ─────────────────
import urllib.parse
METHOD_RX = {
    'dcf_unlevered': r'discounted\s+cash\s+flow', 'dcf_levered': r'discounted\s+cash\s+flow|levered', 'ddm': r'dividend\s+discount',
    'sotp': r'sum[-\s]of[-\s]the[-\s]parts', 'precedent_transactions': r'precedent|selected\s+(?:\w+\s+)?transactions|transactions?\s+analysis',
    'trading_comps': r'selected\s+(?:public\s+)?compan|comparable\s+compan|trading\s+(?:multiples|comparables|analysis)|peer',
    'premiums_paid': r'premiums?\s+paid|premium', '52wk_range': r'52[-\s]week|historical\s+(?:stock|share)\s+(?:price|trading)',
    'analyst_targets': r'analyst', 'future_share_price': r'future\s+(?:stock|share)\s+price|present\s+value\s+of\s+future',
    'contribution': r'contribution', 'accretion_dilution': r'accretion|pro\s+forma', 'exchange_ratio': r'exchange\s+ratio',
    'lbo': r'leveraged\s+buyout|lbo|infrastructure|returns\s+analysis', 'nav': r'net\s+asset\s+value', 'other': r'$^'}


def _sections(sec_text):
    out = []
    # the cutter prints each block's own length; use it (blocks can overlap, e.g. a mis-cut PROJECTIONS block
    # inside an opinion, so 'next block start' is the wrong end)
    for m in re.finditer(r'^===== (.+?) \| offset (\d+) \| ([\d,]+) chars \|[^\n]*?heading: (.*?) =====$', sec_text, re.M):
        st = int(m.group(2))
        out.append({'name': m.group(1), 'start': st, 'end': st + int(m.group(3).replace(',', '')), 'heading': m.group(4)})
    out.sort(key=lambda x: x['start'])
    return out


def _snippet(text, pos):
    """Shortest run of words starting at the first prose line at/after pos that occurs exactly ONCE in the
    document - so the browser's text fragment lands on this spot, not the table of contents."""
    norm_all = re.sub(r'\s+', ' ', text)
    p = pos
    for _ in range(40):                                   # skip table rows / short headings
        e = text.find('\n', p)
        line = text[p:e if e >= 0 else len(text)].strip()
        if line and '|' not in line and len(line.split()) >= 4:
            words = line.split()
            for k in range(5, min(len(words), 24) + 1):
                snip = ' '.join(words[:k])
                if norm_all.count(snip) == 1:
                    return snip
        if e < 0: break
        p = e + 1
    return None


def _frag(url, text, pos):
    if not url or text is None or pos is None: return url
    snip = _snippet(text, pos)
    return f"{url}#:~:text={urllib.parse.quote(snip, safe='')}" if snip else url


def _bank_region(secs, bank, n):
    key = [w for w in re.sub(r'[^a-z ]', ' ', (bank or '').lower()).split()
           if w not in ('the', 'co', 'inc', 'llc', 'securities', 'and', 'company', 'capital', 'markets', 'partners', 'group')]
    cands = [x for x in secs if x['name'].startswith('OPINION') and key and
             any(k in x['heading'].lower().replace('jpmorgan', 'j p morgan').replace('j.p.', 'j p') for k in key[:2])]
    if not cands: return 0, n
    best = max(cands, key=lambda x: (x['end'] or n) - x['start'])
    return best['start'], best['end'] or n


LOCAL_BASE = 'http://100.86.108.51:8080/corpus/_proxies/linked/'   # Caddy :8080 serves data\ under /corpus/
SEP = r'(?:&[#A-Za-z0-9]+;|<[^>]*>|[^A-Za-z0-9<&])+?'


def _html_pos(html, snip, rel):
    """Offset in the filing's HTML where `snip` (text from the converted .txt) starts: its words matched in
    order with any tags / entities / punctuation between them; the match nearest the snippet's relative
    position wins if the words repeat."""
    toks = re.findall(r'[A-Za-z0-9]+', snip)[:9]
    if len(toks) < 2: return None
    rx = re.compile(r'(?<![A-Za-z0-9])' + SEP.join(re.escape(t) for t in toks) + r'(?![A-Za-z0-9])')
    hits = [m.start() for m in rx.finditer(html)]
    if not hits: return None
    # the match must start outside a tag
    hits = [h for h in hits if html.rfind('<', 0, h) <= html.rfind('>', 0, h)]
    if not hits: return None
    return min(hits, key=lambda h: abs(h / max(1, len(html)) - rel))


LINKED_HEAD = """<style>.pa-anchor{scroll-margin-top:90px}.pa-hit{background:#fff3a8 !important;outline:2px solid #e0b000}
.pa-anchor:target::before{content:'\\25B6  ';color:#c00;font:bold 14px Arial,sans-serif;background:#ffe066;padding:0 3px}
#pa-banner{position:sticky;top:0;z-index:9;background:#1f3864;color:#fff;font:12px Arial,sans-serif;padding:6px 10px}
#pa-banner a{color:#ffe066}</style>
<script>function paHi(){var h=decodeURIComponent(location.hash.slice(1));if(!h)return;var a=document.getElementById(h);if(!a)return;
document.querySelectorAll('.pa-hit').forEach(function(e){e.classList.remove('pa-hit')});
var n=a.parentElement;while(n&&n!==document.body&&!/^(P|DIV|TD|LI|PRE|TABLE|FONT|CENTER|H\\d)$/.test(n.tagName))n=n.parentElement;
if(n&&n!==document.body&&n.tagName!=='PRE'){n.classList.add('pa-hit')}a.scrollIntoView({block:'start'});}
window.addEventListener('load',paHi);window.addEventListener('hashchange',paHi);</script>"""


def build_linked(did, prox_dir, url, text, targets):
    r"""Write data\_proxies\linked\<did>.htm: the filing as downloaded, with an <a id> dropped in front of each
    target passage. Any browser jumps to it; the passage is highlighted. Returns {target_id: anchor or None}."""
    src_htm = os.path.join(prox_dir, did + '.htm'); src_raw = os.path.join(prox_dir, did + '.raw.txt')
    if os.path.exists(src_htm):
        doc = open(src_htm, encoding='utf-8', errors='replace').read()
    elif os.path.exists(src_raw):
        import html as _h
        doc = '<html><head></head><body><pre style="white-space:pre-wrap;font:12px monospace">' + _h.escape(open(src_raw, encoding='utf-8', errors='replace').read()) + '</pre></body></html>'
    else:
        return {}
    ins, got = [], {}
    for tid, pos in targets:
        snip = _snippet(text, pos) if pos is not None else None
        hp = _html_pos(doc, snip, pos / max(1, len(text))) if snip else None
        if hp is None:
            got[tid] = None; continue
        aid = f'pa-{len(ins) + 1}'
        ins.append((hp, aid)); got[tid] = aid
    for hp, aid in sorted(ins, reverse=True):
        doc = doc[:hp] + f'<a id="{aid}" class="pa-anchor"></a>' + doc[hp:]
    base = url.rsplit('/', 1)[0] + '/'
    banner = (f'<div id="pa-banner">Power Academy working copy of the SEC filing (anchored for QC). '
              f'Original: <a href="{url}" target="_blank">{url}</a></div>')
    head = f'<base href="{base}">' + LINKED_HEAD
    m = re.search(r'<head[^>]*>', doc, re.I)
    doc = doc[:m.end()] + head + doc[m.end():] if m else head + doc
    m = re.search(r'<body[^>]*>', doc, re.I)
    doc = doc[:m.end()] + banner + doc[m.end():] if m else banner + doc
    os.makedirs(os.path.join(prox_dir, 'linked'), exist_ok=True)
    open(os.path.join(prox_dir, 'linked', did + '.htm'), 'w', encoding='utf-8').write(doc)
    return got


def add_links(d, text, secs, did=None, prox_dir=None):
    url = (d.get('document') or {}).get('url')
    if not url: return
    d['document']['link'] = url
    if text is None: return
    n = len(text)
    targets, setters = [], []            # (id, pos) and (id, object, key)

    def want(obj, key, pos):
        tid = f't{len(targets)}'
        targets.append((tid, pos)); setters.append((tid, obj, key, pos))

    for a in d.get('advisors') or []:
        lo, hi = _bank_region(secs, a.get('bank'), n)
        bank_t = len(targets); want(a, 'src', lo if (hi != n or lo) else None)
        region = text[lo:hi]
        for m in a.get('methods') or []:
            pos = None
            lab = (m.get('label_as_printed') or '').strip()
            if lab:
                i = region.lower().find(lab.lower()[:60])
                if i >= 0: pos = lo + i
            if pos is None:
                mm = re.search(METHOD_RX.get(m.get('method'), r'$^'), region, re.I)
                if mm: pos = lo + mm.start()
            if pos is None and lab:
                i = text.lower().find(lab.lower()[:60], lo)
                if i >= 0: pos = i
            want(m, 'src', pos if pos is not None else lo)
        if targets[bank_t][1] is None:              # no opinion block found: point the bank at its first analysis
            mp = [t[1] for t in targets[bank_t + 1:] if t[1] is not None]
            if mp:
                targets[bank_t] = (targets[bank_t][0], min(mp)); setters[bank_t] = setters[bank_t][:3] + (min(mp),)
    for name, key in (('BACKGROUND', 'process'), ('PROJECTIONS', 'projections')):
        x = next((s for s in secs if s['name'] == name), None)
        if x and isinstance(d.get(key), dict):
            e = text.find('\n', x['start'])
            want(d[key], 'src', e + 1 if e >= 0 else x['start'])
    got = build_linked(did, prox_dir, url, text, targets) if did and prox_dir else {}
    local_doc = LOCAL_BASE + did + '.htm' if got is not None and did and os.path.exists(os.path.join(prox_dir or '', 'linked', (did or '') + '.htm')) else None
    d['document']['local'] = local_doc
    for tid, obj, key, pos in setters:
        obj[key + '_sec'] = _frag(url, text, pos) if pos is not None else url   # SEC original (Chrome/Edge text fragment)
        aid = got.get(tid)
        obj[key] = (local_doc + '#' + aid) if (local_doc and aid) else (local_doc or obj[key + '_sec'])
        obj[key + '_exact'] = bool(local_doc and aid)


def canon_term(t):
    if not isinstance(t, dict):
        return None
    raw = str(t.get('type') or '').lower()
    types = sorted({c for k, c in TERM if k in raw}) or (['other'] if raw else [])
    return {'types': types, 'range': t.get('range'), 'applied_to': t.get('applied_to'),
            'implied_other': t.get('implied_other')}


def is_range(v):
    return isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v)


def bars_of(v, label):
    """-> [(label, low, high)] from a list range or a (nested) dict of ranges."""
    if is_range(v):
        return [(label, float(min(v)), float(max(v)))]
    out = []
    if isinstance(v, dict):
        for k, x in v.items():
            out += bars_of(x, f'{label} · {k}' if label else str(k))
    return out


def mult_list(m):
    out = []
    for x in m.get('multiples') or []:
        if isinstance(x, dict) and x.get('metric'):
            out.append({'metric': x['metric'], 'range': x.get('stat_range') or x.get('selected_range'),
                        'median': x.get('comp_median'), 'applied_to': x.get('applied_to')})
    return out


def main():
    a = sys.argv[1:]
    src = a[a.index('--in') + 1] if '--in' in a else os.path.join(BASE, 'data', '_merge', 'merger_extract')
    outp = a[a.index('--out') + 1] if '--out' in a else os.path.join(BASE, 'data', 'merger_valuation.json')
    prec = a[a.index('--precedents') + 1] if '--precedents' in a else os.path.join(BASE, 'data', 'precedents.json')
    prox_dir = a[a.index('--proxies') + 1] if '--proxies' in a else os.path.join(BASE, 'data', '_proxies')
    P = {d['id']: d for d in json.load(open(prec, encoding='utf-8'))['deals']}
    deals, board, wrong = {}, [], []
    for f in sorted(glob.glob(os.path.join(src, '*.json'))):
        d = json.load(open(f, encoding='utf-8'))
        did = d.get('deal_id') or os.path.basename(f)[:-5]
        if d.get('wrong_document'):
            wrong.append({'deal_id': did, 'qc': d.get('qc')}); continue
        p = P.get(did, {})
        raw = p.get('raw') or {}
        tp, sp = os.path.join(prox_dir, did + '.txt'), os.path.join(prox_dir, did + '.sections.txt')
        text = open(tp, encoding='utf-8', errors='replace').read() if os.path.exists(tp) else None
        secs = _sections(open(sp, encoding='utf-8', errors='replace').read()) if os.path.exists(sp) else []
        add_links(d, text, secs, did, prox_dir)
        bars = []
        for adv in d.get('advisors') or []:
            for m in adv.get('methods') or []:
                if m.get('method') in ('exchange_ratio', 'accretion_dilution', 'contribution') and not is_range(m.get('implied_value_per_share')):
                    continue
                iv = m.get('implied_value_per_share')
                if iv is None:
                    iv = m.get('range_low_high')
                for lab, lo, hi in bars_of(iv, m.get('subject') or ''):
                    if hi > 5 * (raw.get('offer_px') or hi) or lo <= 0:
                        continue            # ratios / enterprise values that slipped into $/share
                    bars.append({'src': m.get('src'), 'bank': adv.get('bank'), 'side': adv.get('side'), 'method': m.get('method'),
                                 'label': (m.get('label_as_printed') or m.get('method')) + (f' — {lab}' if lab else ''),
                                 'low': lo, 'high': hi, 'reference_only': bool(m.get('reference_only')),
                                 'subject': m.get('subject'), 'terminal': canon_term(m.get('terminal'))})
            row = {'deal_id': did, 'announced': p.get('announced'), 'asset_class': p.get('asset_class'),
                   'target': p.get('target'), 'acquirer': p.get('acquirer'), 'bank': adv.get('bank'), 'side': adv.get('side'),
                   'methods': sorted({m.get('method') for m in adv.get('methods') or [] if m.get('method')}),
                   'terminals': [], 'precedent_multiples': [], 'trading_multiples': [], 'comp_sets': {}}
            for m in adv.get('methods') or []:
                if m.get('subject'): continue                  # acquirer stand-alone work stays out of the board
                t = canon_term(m.get('terminal'))
                if t and m.get('method') in ('dcf_unlevered', 'dcf_levered', 'ddm', 'sotp'):
                    row['terminals'].append({'method': m['method'], **t, 'discount_rate_pct': m.get('discount_rate_pct')})
                if m.get('method') == 'precedent_transactions':
                    row['precedent_multiples'] += mult_list(m)
                    cs = m.get('comp_set'); row['comp_sets']['precedents'] = m.get('comp_set_size') or (len(cs) if isinstance(cs, list) else None)
                if m.get('method') == 'trading_comps':
                    row['trading_multiples'] += mult_list(m)
                    cs = m.get('comp_set'); row['comp_sets']['trading'] = len(cs) if isinstance(cs, list) else None
            board.append(row)
        d['offer'] = {'price_per_share': raw.get('offer_px'), 'premium_pct': raw.get('premium_pct'),
                      'source': 'precedents.json raw (deal facts on file)'}
        d['deal'] = {k: p.get(k) for k in ('target', 'acquirer', 'announced', 'closed', 'status', 'asset_class', 'structure')}
        d['bars'] = bars
        deals[did] = d
    doc = {'_schema_version': '1.0', '_generated': dt.date.today().isoformat(),
           '_source': 'Merger proxies / S-4s (SEC EDGAR) fetched by fetch_merger_proxies.py; sections cut by cut_proxy_sections.py; '
                      'extracted per data\\_merge\\SPEC_MERGER.md. Figures as printed; bars are $/share ranges only.',
           '_caveat': 'Many documents are PRELIMINARY proxies / initial S-4s (see each deal\'s document.form and qc). '
                      'Offer line = deal facts on file; the proxy\'s own implied offer value can differ (noted in qc).',
           'deals': deals, 'board': board, 'wrong_documents': wrong}
    json.dump(doc, open(outp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'wrote {outp}: {len(deals)} deals, {len(board)} advisor rows, {sum(len(v["bars"]) for v in deals.values())} bars, {len(wrong)} wrong documents')


if __name__ == '__main__':
    main()
