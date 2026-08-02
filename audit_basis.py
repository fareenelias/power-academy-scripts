"""
audit_basis.py — Power Academy / precedents.json

READ-ONLY audit. Answers one question per deal, per multiple:
    do we KNOW what basis this figure was struck on?

Basis evidence already exists in the DB but as free text (_recon, structure,
advisors._note, sources values). This scans for it, classifies each multiple as
confirmed / inferred / unknown, and prints a punch list of what needs research.

Writes nothing. Emits basis_audit.json for the backfill step.
"""

import json, re, collections, io, os

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
OUT = os.path.join(os.path.dirname(SRC), 'basis_audit.json')

# ---------------------------------------------------------------- text corpus
def corpus(d):
    """Every free-text field on a deal, concatenated, for evidence scanning."""
    bits = []
    for k in ('structure', 'consideration', '_recon', '_note', '_flag',
              '_premium_check', '_note_close', 'rationale'):
        v = d.get(k)
        if isinstance(v, str):
            bits.append(v)
    for v in (d.get('_gaps') or []):
        if isinstance(v, str):
            bits.append(v)
    adv = d.get('advisors') or {}
    if isinstance(adv.get('_note'), str):
        bits.append(adv['_note'])
    for k, v in (d.get('sources') or {}).items():
        if isinstance(k, str):
            bits.append(k)
        if isinstance(v, str):
            bits.append(v)
    ver = ((d.get('verification') or {}).get('fields') or {})
    for f in ver.values():
        if isinstance(f, dict) and isinstance(f.get('src'), str):
            bits.append(f['src'])
    ms = d.get('multiples_stated') or {}
    for k, v in ms.items():
        bits.append('%s=%s' % (k, v))
    return ' ~|~ '.join(bits)


# ---------------------------------------------------------------- patterns
YR = r'(?:FY\s*)?(20\d\d|19\d\d)\s*(A|E)?'

# "1.8x 2024 year-end rate base", "2.5x 2020 rate base", "1.5x 2026E rate base"
RB_MULT = re.compile(
    r'(\d+(?:\.\d+)?)\s*x\s+'
    r'((?:(?:its|the|estimated|projected|forecast(?:ed)?|expected|year[- ]end|YE|pro\s*forma)\s+){0,3})'
    + YR +
    r'\s*(?:year[- ]end|YE)?\s*'
    r'((?:estimated|projected|forecast(?:ed)?|expected)\s+)?'
    r'rate\s*base', re.I)

# vintage-less but qualified: "1.49x projected rate base", "2.0x forward rate base"
RB_QUAL = re.compile(
    r'(\d+(?:\.\d+)?)\s*x\s+'
    r'((?:projected|estimated|forecast(?:ed)?|expected|forward|current|year[- ]end|YE|closing|deal[- ]year)\s+)'
    r'rate\s*base', re.I)

# bare: "2.5x rate base"
RB_BARE = re.compile(r'(\d+(?:\.\d+)?)\s*x\s+rate\s*base', re.I)

# "24x 2024 earnings", "38.0x 2020 earnings"
PE_MULT = re.compile(
    r'(\d+(?:\.\d+)?)\s*x\s+'
    r'(?:(?:its|the|estimated|projected|forecast(?:ed)?|expected)\s+){0,2}'
    + YR + r'\s*(?:year[- ]end)?\s*'
    r'(?:earnings|net\s+income|EPS|P/?E)', re.I)

# "9.2x 2017 EBITDA", "10.3x 2017E EBITDA"
EB_MULT = re.compile(
    r'(\d+(?:\.\d+)?)\s*x\s+'
    r'(?:(?:its|the|estimated|projected|forecast(?:ed)?|expected|NTM|LTM|forward)\s+){0,2}'
    + YR + r'\s*E?\s*'
    r'(?:adj(?:usted)?\.?\s*)?EBITDA', re.I)
EB_QUAL = re.compile(
    r'(\d+(?:\.\d+)?)\s*x\s+(LTM|NTM|TTM|forward|trailing)\s+(?:adj(?:usted)?\.?\s*)?EBITDA', re.I)

# premium reference language
PREM_UNAFF = re.compile(r'unaffected', re.I)
PREM_VWAP = re.compile(r'(\d+)[- ]day\s+(?:VWAP|volume[- ]weighted)', re.I)
PREM_CLOSE = re.compile(r'(?:last|prior|previous|day[- ]before|1[- ]day)\s+clos(?:e|ing)', re.I)
PREM_DATE = re.compile(
    r'unaffected\s+(?:price\s+)?(?:of\s+)?'
    r'(?:on\s+)?((?:\d{1,2}[- ])?[A-Z][a-z]{2,8}[- ]\d{1,2},?[- ]?\d{4}|\d{4}-\d{2}-\d{2})', re.I)
# "50% to unaffected Dec-10-2015 price" / "premium to the Feb-8 close"
PREM_TWO = re.compile(
    r'(\d+(?:\.\d+)?)\s*%\s*(?:premium\s*)?to\s+(?:the\s+)?(unaffected|last\s+clos\w+|[A-Z][a-z]{2,8}[- ]\d{1,2})', re.I)


def norm_vintage(y, ae, qual=None):
    if y:
        suff = (ae or '').upper()
        if not suff and qual:
            q = qual.lower()
            if any(t in q for t in ('estimat', 'project', 'forecast', 'expected')):
                suff = 'E'
        return '%s%s' % (y, suff or 'A')
    if qual:
        q = qual.lower().strip()
        if any(t in q for t in ('project', 'estimat', 'forecast', 'expected', 'forward')):
            return 'FWD'
        if 'year-end' in q or 'ye' == q or 'year end' in q:
            return 'YE'
        if 'current' in q:
            return 'CUR'
    return None


def scan(d):
    """Return {metric: evidence} for one deal."""
    txt = corpus(d)
    ev = {}

    # ---- rate base multiple
    hits = []
    for m in RB_MULT.finditer(txt):
        qual = (m.group(2) or '') + (m.group(5) or '')
        hits.append({'value': float(m.group(1)),
                     'vintage': norm_vintage(m.group(3), m.group(4), qual),
                     'quote': m.group(0).strip(), 'conf': 'confirmed'})
    for m in RB_QUAL.finditer(txt):
        v = float(m.group(1))
        if not any(abs(h['value'] - v) < 1e-9 for h in hits):
            hits.append({'value': v, 'vintage': norm_vintage(None, None, m.group(2)),
                         'quote': m.group(0).strip(), 'conf': 'inferred'})
    if not hits:
        for m in RB_BARE.finditer(txt):
            hits.append({'value': float(m.group(1)), 'vintage': None,
                         'quote': m.group(0).strip(), 'conf': 'unknown'})
    # structured field already present
    ry = (d.get('raw') or {}).get('rate_base_year')
    if ry:
        for h in hits:
            if h['vintage'] is None:
                h['vintage'] = str(ry)
                h['conf'] = 'confirmed'
                h['quote'] += ' [raw.rate_base_year=%s]' % ry
        if not hits:
            hits.append({'value': None, 'vintage': str(ry),
                         'quote': 'raw.rate_base_year=%s' % ry, 'conf': 'confirmed'})
    if hits:
        ev['rate_base_mult'] = hits

    # ---- P/E
    hits = []
    for m in PE_MULT.finditer(txt):
        hits.append({'value': float(m.group(1)),
                     'vintage': norm_vintage(m.group(2), m.group(3)),
                     'quote': m.group(0).strip(), 'conf': 'confirmed'})
    if hits:
        ev['pe'] = hits

    # ---- EV/EBITDA
    hits = []
    for m in EB_MULT.finditer(txt):
        hits.append({'value': float(m.group(1)),
                     'vintage': norm_vintage(m.group(2), m.group(3)),
                     'quote': m.group(0).strip(), 'conf': 'confirmed'})
    for m in EB_QUAL.finditer(txt):
        v = float(m.group(1))
        if not any(abs(h['value'] - v) < 1e-9 for h in hits):
            hits.append({'value': v, 'vintage': m.group(2).upper(),
                         'quote': m.group(0).strip(), 'conf': 'confirmed'})
    if hits:
        ev['ev_ebitda'] = hits

    # ---- premium
    hits = []
    for m in PREM_TWO.finditer(txt):
        ref = m.group(2).lower()
        ref = ('unaffected' if 'unaff' in ref
               else 'last_close' if 'clos' in ref else 'dated:' + m.group(2))
        hits.append({'value': float(m.group(1)), 'reference': ref,
                     'quote': m.group(0).strip(), 'conf': 'confirmed'})
    mv = PREM_VWAP.search(txt)
    if mv:
        hits.append({'value': None, 'reference': '%sd_vwap' % mv.group(1),
                     'quote': mv.group(0).strip(), 'conf': 'confirmed'})
    if not hits:
        if PREM_UNAFF.search(txt):
            hits.append({'value': None, 'reference': 'unaffected',
                         'quote': 'mentions "unaffected"', 'conf': 'inferred'})
        elif PREM_CLOSE.search(txt):
            hits.append({'value': None, 'reference': 'last_close',
                         'quote': 'mentions last close', 'conf': 'inferred'})
    md = PREM_DATE.search(txt)
    if md:
        for h in hits:
            h.setdefault('reference_date_text', md.group(1))
    if hits:
        ev['premium_pct'] = hits
    return ev


def main():
    db = json.load(open(SRC, encoding='utf-8'))
    deals = db['deals']

    def has(d, *keys):
        m = d.get('multiples') or {}
        s = d.get('multiples_stated') or {}
        for k in keys:
            if m.get(k) is not None or s.get(k) is not None:
                return True
        return False

    METRICS = [
        ('rate_base_mult', ('rate_base_mult', 'ev_rb', 'ev_rate_base')),
        ('ev_ebitda',      ('ev_ebitda',)),
        ('pe',             ('pe',)),
        ('premium_pct',    None),   # lives in raw
    ]

    tally = collections.Counter()
    audit = {}
    punch = collections.defaultdict(list)

    for d in deals:
        ev = scan(d)
        rec = {}
        for metric, keys in METRICS:
            if metric == 'premium_pct':
                present = (d.get('raw') or {}).get('premium_pct') is not None
            else:
                present = has(d, *keys)
            if not present:
                continue
            hits = ev.get(metric, [])
            confs = [h['conf'] for h in hits]
            if 'confirmed' in confs:
                status = 'confirmed'
            elif 'inferred' in confs:
                status = 'inferred'
            else:
                status = 'unknown'
            # a hit with no vintage is not actually a known basis
            if metric != 'premium_pct' and status == 'confirmed':
                if not any(h.get('vintage') for h in hits):
                    status = 'unknown'

            # split UNKNOWN by whether it is RESEARCHABLE.
            # a multiple the parties themselves disclosed has a basis printed in
            # a document we already link -> fixable by re-reading, no new hunt.
            # a multiple WE computed from a model input has no disclosed basis at
            # all -> the honest answer is to record the input's vintage or admit
            # it is undocumented.
            if status == 'unknown':
                stated = (d.get('multiples_stated') or {})
                vf = ((d.get('verification') or {}).get('fields') or {})
                keyset = keys or ('premium_pct',)
                party_stated = any(stated.get(k) is not None for k in keyset)
                vstat = None
                for k in keyset:
                    f = vf.get('multiples.%s' % k) or vf.get(k)
                    if f and f.get('status'):
                        vstat = f['status']
                        break
                if party_stated or vstat == 'confirmed':
                    status = 'stated_basis_missing'
                else:
                    status = 'computed_undocumented'
                rec_extra = {'verification_status': vstat,
                             'party_stated': party_stated}
            else:
                rec_extra = {}
            rec[metric] = dict({'status': status, 'evidence': hits}, **rec_extra)
            tally[(metric, status)] += 1
            if status not in ('confirmed',):
                punch['%s::%s' % (metric, status)].append(d['id'])
            # multi-basis conflict
            vals = {h.get('vintage') for h in hits if h.get('vintage')}
            if len(vals) > 1:
                tally[(metric, 'MULTI-BASIS')] += 1
                rec[metric]['multi_basis'] = sorted(vals)
        if rec:
            audit[d['id']] = rec

    # ------------------------------------------------------------- report
    print('=' * 78)
    print('BASIS AUDIT — %d deals scanned' % len(deals))
    print('=' * 78)
    for metric, _ in METRICS:
        tot = sum(v for (m, s), v in tally.items() if m == metric and s != 'MULTI-BASIS')
        if not tot:
            continue
        c  = tally[(metric, 'confirmed')]
        i  = tally[(metric, 'inferred')]
        sm = tally[(metric, 'stated_basis_missing')]
        cu = tally[(metric, 'computed_undocumented')]
        mb = tally[(metric, 'MULTI-BASIS')]
        print('\n%-16s populated on %3d deals' % (metric, tot))
        print('   basis KNOWN            %3d  (%3.0f%%)' % (c, 100.0*c/tot))
        print('   qualifier only         %3d  (fwd/YE, no year)' % i)
        print('   party-stated, no vint. %3d  <- RESEARCHABLE (doc already linked)' % sm)
        print('   computed, undocumented %3d  <- our calc; record input vintage' % cu)
        if mb:
            print('   MULTI-BASIS            %3d  <- two vintages for the same deal' % mb)

    json.dump({'_note': 'read-only audit output; input to the basis backfill',
               'audit': audit,
               'punch_list': {k: sorted(v) for k, v in punch.items()}},
              io.open(OUT, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    print('\nwrote %s' % OUT)


if __name__ == '__main__':
    main()