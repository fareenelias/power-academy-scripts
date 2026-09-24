# -*- coding: utf-8 -*-
"""basis_from_cache.py - recover multiple BASES (vintage) from the locally cached deal documents.

For every deal x multiple that audit_basis.py marks stated_basis_missing, re-read the deal's
linked documents that are already in data\\_sec_cache (md5(url).txt, the scrub_links cache) and
pull every sentence that carries a multiple ('N.Nx' / 'N times'), the metric keyword and a
vintage token. Nothing is written into precedents.json: the candidates land in
data\\basis_candidates.json and a review workbook, and Fareen's rulings go through
apply_basis.py's evidence path (COWORK_HANDOFF rule: she does the QC).

Honest yield (2026-09-23): 114 metric-deals are stated_basis_missing, 98 have at least one
cached document, but only ~10 carry a quotable vintage - the decks are mostly GRAPHIC exhibits
with no text layer and most press releases are not cached. The rest needs a harvest pass
(scrub_links.py --phase harvest, desktop, VPN off - sec.gov is egress-blocked from the cloud
and the VM) and then this script again.

  python basis_from_cache.py [--dry]
"""
import io, os, re, sys, json, html, hashlib, collections, datetime

DATA_DIR = r'E:\PowerAcademy\data' if os.name == 'nt' else \
    os.path.join(os.path.expanduser('~'), 'mnt', 'PowerAcademy', 'data')
KW = {'rate_base_mult': r'rate\s*base', 'ev_ebitda': r'ebitda', 'pe': r'(?:earnings|\beps\b|p\s*[/|]\s*e|price[- ]to[- ]earnings|net income)'}
NOISE = {'ev_ebitda': r'debt[- ]to[- ]ebitda|debt\s*/\s*ebitda|ffo|leverage|coverage', 'pe': r'dividend|payout|yield', 'rate_base_mult': r'growth|cagr'}
VINT = re.compile(r'(20\d\d\s*(?:E|A|FY|P)?\b|trailing|forward|last twelve|\bltm\b|next twelve|\bntm\b|year[- ]end|projected|estimated)', re.I)
MULT = re.compile(r'.{0,170}?\b(\d{1,3}(?:\.\d+)?)\s*(?:x\b|times\b).{0,170}', re.I)


def cache_text(u):
    p = os.path.join(DATA_DIR, '_sec_cache', hashlib.md5(u.encode('utf-8')).hexdigest() + '.txt')
    if not os.path.exists(p): return None
    t = io.open(p, encoding='utf-8', errors='ignore').read()
    t = re.sub(r'<[^>]+>', ' ', t)
    return html.unescape(re.sub(r'\s+', ' ', t))


def vintage_of(s, announced):
    m = re.search(r'\b(20\d\d)\s*(E|A|FY|P)?\b', s)
    if m:
        y = int(m.group(1)); suf = (m.group(2) or '').upper()
        try: ann = int(str(announced)[:4])
        except Exception: ann = None
        if suf in ('E', 'P') or (ann and y > ann): return '%dE' % y
        if re.search(r'projected|estimated|forward', s, re.I) and (not ann or y >= ann): return '%dE' % y
        return '%dA' % y
    if re.search(r'trailing|last twelve|\bltm\b', s, re.I): return 'LTM'
    if re.search(r'forward|next twelve|\bntm\b', s, re.I): return 'NTM'
    return None


def main():
    dry = '--dry' in sys.argv
    P = json.load(io.open(os.path.join(DATA_DIR, 'precedents.json'), encoding='utf-8'))
    deals = {d['id']: d for d in P['deals']}
    A = json.load(io.open(os.path.join(DATA_DIR, 'basis_audit.json'), encoding='utf-8'))['audit']
    cands = []
    stats = collections.Counter()
    for did, rec in A.items():
        d = deals.get(did)
        if not d: continue
        docs = {k: u for k, u in (d.get('links') or {}).items() if isinstance(u, str) and u.startswith('http') and not k.startswith('_')}
        texts = {k: cache_text(u) for k, u in docs.items()}
        texts = {k: v for k, v in texts.items() if v}
        for metric, info in rec.items():
            if metric not in KW or info.get('status') != 'stated_basis_missing': continue
            stats['missing'] += 1
            if texts: stats['has_cached_doc'] += 1
            m0 = d.get('multiples') or {}
            stored = m0.get('ev_rb') if metric == 'rate_base_mult' else m0.get(metric)
            seen = set(); got = False
            for k, t in texts.items():
                for m in MULT.finditer(t):
                    s = m.group(0).strip()
                    if not re.search(KW[metric], s, re.I) or re.search(NOISE[metric], s, re.I): continue
                    v = vintage_of(s, d.get('announced'))
                    val = float(m.group(1))
                    if val > 60 or val < 0.5: continue                      # not a deal multiple
                    if not v:
                        # no vintage in the sentence - still worth a row when the printed value
                        # DISAGREES with the stored multiple (Emera/TECO prints 1.6x, stored 1.7x)
                        if stored is None or abs(val - float(stored)) <= max(0.05, 0.03 * float(stored)): continue
                        v = 'unstated'
                    key = (round(val, 2), v)
                    if key in seen: continue
                    seen.add(key)
                    match = (stored is not None and abs(val - float(stored)) <= max(0.05, 0.03 * float(stored)))
                    cands.append(collections.OrderedDict([
                        ('deal_id', did), ('target', d.get('target')), ('acquirer', d.get('acquirer')), ('announced', d.get('announced')),
                        ('metric', metric), ('stored_value', stored), ('doc_value', val), ('value_matches_stored', match),
                        ('vintage', v), ('doc_key', k), ('doc_url', docs[k]), ('quote', s[:300]),
                        ('conf', 'doc_quote_matches_stored' if match else ('doc_value_differs_no_vintage' if v == 'unstated' else 'doc_quote_other_value'))]))
                    got = True
            if got: stats['with_candidate'] += 1
    out = collections.OrderedDict([('_generated', datetime.date.today().isoformat()), ('_stats', dict(stats)),
                                   ('_note', 'Candidates only - nothing applied. Rulings go through apply_basis.py evidence. Yield is bounded by what the cache holds (GRAPHIC decks carry no text).'),
                                   ('candidates', cands)])
    print(dict(stats), 'candidates', len(cands), 'matching stored', sum(1 for c in cands if c['value_matches_stored']))
    for c in cands: print(f"  {c['deal_id']:34} {c['metric']:14} stored={c['stored_value']} doc={c['doc_value']} {c['vintage']:6} {'MATCH' if c['value_matches_stored'] else '     '} [{c['doc_key']}] {c['quote'][:110]}")
    if dry: return
    p = os.path.join(DATA_DIR, 'basis_candidates.json')
    io.open(p, 'w', encoding='utf-8').write(json.dumps(out, indent=1, ensure_ascii=False)); json.load(io.open(p, encoding='utf-8'))
    print('wrote', p)
    # review workbook in the standing format
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = 'Review'
        hdr = ['#', 'Severity', 'Deal', 'Metric', 'Stored', 'Doc says', 'Vintage', 'Source doc', 'Quote', 'What I need from you', 'Action type', 'Open the doc', 'Done?']
        ws.append(hdr)
        for c in ws[1]: c.font = Font(bold=True); c.fill = PatternFill('solid', fgColor='DDDDDD')
        for i, c in enumerate(cands, 1):
            if c['value_matches_stored']:
                act = 'Confirm my cross-check — low priority'; need = 'Doc states the multiple with a vintage and it matches the stored value: OK to record basis %s?' % c['vintage']
            elif c['vintage'] == 'unstated':
                act = 'Eyeball and confirm'; need = 'Press release prints %s but we store %s and no vintage is stated in the sentence: which is right, and is the basis given elsewhere on the page?' % (c['doc_value'], c['stored_value'])
            else:
                act = 'Pick the governing exhibit'; need = 'Doc multiple %s (%s) differs from stored %s: which is the deal multiple, and on which vintage?' % (c['doc_value'], c['vintage'], c['stored_value'])
            ws.append([i, 'medium' if c['value_matches_stored'] else 'high', c['deal_id'], c['metric'], c['stored_value'], c['doc_value'], c['vintage'], c['doc_key'], c['quote'], need, act, c['doc_url'], ''])
            ws.cell(row=i + 1, column=12).hyperlink = c['doc_url']
        for col, w in zip('ABCDEFGHIJKLM', [4, 9, 34, 15, 8, 9, 8, 18, 70, 60, 34, 40, 7]): ws.column_dimensions[col].width = w
        for row in ws.iter_rows(min_row=2):
            for cell in row: cell.alignment = Alignment(wrap_text=True, vertical='top')
        s2 = wb.create_sheet('Coverage gaps')
        s2.append(['Item', 'Value']); [s2.append([k, v]) for k, v in stats.items()]
        s2.append(['not recoverable from cache', stats['missing'] - stats['with_candidate']])
        s2.append(['why', 'decks are GRAPHIC exhibits without a text layer; most press releases are not in _sec_cache; sec.gov egress-blocked from cloud + VM on 2026-09-23 - harvest on the desktop, VPN off, then re-run'])
        xp = os.path.join(DATA_DIR, 'PowerAcademy_basis_review_%s.xlsx' % datetime.date.today().isoformat())
        wb.save(xp); print('wrote', xp)
    except Exception as e:
        print('workbook not written:', e)


if __name__ == '__main__':
    main()
