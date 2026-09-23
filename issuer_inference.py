# -*- coding: utf-8 -*-
"""issuer_inference.py - infer the issuing entity of a CapIQ capital-structure row.

ONE copy of the logic: extract_all.py imports infer_issuing_entity() for the weekly
run, and `python issuer_inference.py` re-applies it to capiq_export.json in place
(no workbooks needed) so a rule change reaches the dashboard without a CapIQ pull.

Label grammar (the dashboard groups on the prefix, colours on the word):
    HoldCo · Entergy Corporation (unsecured)
    OpCo · Entergy Arkansas (secured)
    OpCo · Entergy Louisiana (VIE)
    HoldCo (hybrid)             <- no issuer name printed; class inferred from the row
    OpCo (secured)              <- no issuer name printed; class inferred from the row
    None                        <- nothing safe to say

Issuer names per ticker come from files that already exist for other reasons:
credit JSONs (entity keys, is_holdco), opco_cik_map.json (registrant opcos) and the
company name in capiq_export.json. No new list to maintain. A short ALIAS table covers
abbreviations CapIQ prints instead of names (CL&P, NSTAR, NEECH ...).

History: 2026-09-23. Before this, the inferrer keyed on the literal string
'First Mortgage', so every 'Entergy Arkansas - Mortgage Bonds' row (73 of ETR's 95)
came out None, and any unsecured senior row was called 'HoldCo (unsecured)' - which
labelled the opco nuclear-fuel VIE notes and the Arkansas DOE obligation as holdco debt.
"""
import io, json, os, re, sys, collections

DATA_DIR = r'E:\PowerAcademy\data' if os.name == 'nt' else \
    os.path.join(os.path.expanduser('~'), 'mnt', 'PowerAcademy', 'data')

# Names/abbreviations CapIQ prints that the credit files do not carry verbatim. Matched as
# whole-token phrases on the normalized description. holdco=True marks parent-level issuers.
ALIAS = {
    'CL&P':            ('Connecticut Light & Power', False),
    'NSTAR':           ('NSTAR Electric', False),
    'NSTAR Electric':  ('NSTAR Electric', False),
    'NSTAR Gas':       ('NSTAR Gas', False),
    'PSNH':            ('Public Service Co. of New Hampshire', False),
    'EGMA':            ('Eversource Gas of Massachusetts', False),
    'YGS':             ('Yankee Gas Services', False),
    'NEECH':           ('NextEra Energy Capital Holdings', True),
    'NEE Capital':     ('NextEra Energy Capital Holdings', True),
    'NEET':            ('NextEra Energy Transmission', False),
    'NEER':            ('NextEra Energy Resources', False),
    'FPL':             ('Florida Power & Light', False),
    'GSWC':            ('Golden State Water', False),
    'HEI':             ('Hawaiian Electric Industries', True),
    'DVP':             ('Virginia Electric & Power', False),
    'VEPCO':           ('Virginia Electric & Power', False),
    'Virginia Power':  ('Virginia Electric & Power', False),
    'DESC':            ('Dominion Energy South Carolina', False),
    'SCE':             ('Southern California Edison', False),
    'CTWS':            ('Connecticut Water Service', False),
    'SJWC':            ('San Jose Water', False),
    'AWCC':            ('American Water Capital Corp', True),
    'American Water Capital Corp': ('American Water Capital Corp', True),
    'EKC':             ('Evergy Kansas Central', False),
    'GMO':             ('Evergy Missouri West', False),
    'KCPL':            ('Evergy Metro', False),
    'System Energy':   ('System Energy Resources', False),
    'Grand Gulf':      ('System Energy Resources', False),
    'Vistra Zero':     ('Vistra Zero Operating Co', False),
    'Vistra Operations': ('Vistra Operations Co', False),
}
ALIAS_TOKS = sorted(((' ' + ' '.join(_n) + ' '), v) for k, v in ALIAS.items()
                    for _n in [re.sub(r'[^a-z0-9]+', ' ', k.lower().replace('&', ' and ')).split()])
ALIAS_TOKS.sort(key=lambda kv: -len(kv[0]))
# Upper-case first words that are NOT issuers (conduit authorities, programme names).
NOT_ISSUER = {'PEDFA', 'EIRR', 'DWR', 'PPA', 'VIE', 'DOE', 'DDD', 'BBB', 'EEE', 'SSS',
              'CCC', 'TLB', 'WIFA', 'CLF', 'USD', 'CAD', 'NA', 'PIK', 'ABS', 'ESOP'}

SUFFIX = {'inc', 'corp', 'corporation', 'co', 'company', 'llc', 'lp', 'l', 'p',
          'the', 'ltd', 'limited', 'plc', 'holdings'}
SECURED_PAT = re.compile(r'mortgage bond|first mortgage|senior secured|securitization|'
                         r'recovery bond|(?<!un)secured note|sale-leaseback', re.I)
LEASE_PAT   = re.compile(r'\blease', re.I)
HYBRID_PAT  = re.compile(r'junior sub|trust preferred|subordinated deb', re.I)


def _norm(s):
    s = s.lower().replace('&', ' and ')
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    return [t for t in s.split() if t]


def short_name(raw):
    """'ENTERGY ARKANSAS, LLC' -> 'Entergy Arkansas'; keeps '&'."""
    toks = re.sub(r'[,\.]', ' ', raw).split()
    while toks and toks[-1].lower().strip('.') in SUFFIX:
        toks.pop()
    while toks and toks[0].lower() == 'the':
        toks.pop(0)
    out = ' '.join(toks)
    if out.isupper():
        out = ' '.join(w if w in ('&',) else w.capitalize() for w in out.split())
        out = re.sub(r'\bOf\b', 'of', out)
    return out


def load_issuer_names(ticker, company_name, data_dir=DATA_DIR):
    """[(display_name, is_holdco, token_list)] from credit JSONs + opco CIK map + company name."""
    names = {}
    def add(raw, holdco):
        if not raw: return
        disp = short_name(raw)
        toks = _norm(disp)
        toks = [t for t in toks if t not in SUFFIX] or toks
        if len(toks) < 1: return
        key = ' '.join(toks)
        if key not in names or (holdco and not names[key][1]):
            names[key] = (disp, holdco, toks)
    if company_name:
        add(company_name, True)
        ck0 = ' '.join(t for t in _norm(short_name(company_name)) if t not in SUFFIX)
        if ck0 in names:
            names[ck0] = (re.sub(r',?\s*(Inc\.?|Corp\.?|LP|L\.P\.)$', '', company_name).strip(), True, names[ck0][2])
    for ag in ('moodys', 'sp', 'fitch'):
        p = os.path.join(data_dir, f'{ag}_credit.json')
        if not os.path.exists(p): continue
        try:
            d = json.load(io.open(p, encoding='utf-8'))
        except Exception:
            continue
        for en, ev in (d.get(ticker, {}) or {}).get('entities', {}).items():
            add(en, bool(ev.get('is_holdco')))
    p = os.path.join(data_dir, 'opco_cik_map.json')
    if os.path.exists(p):
        try:
            m = json.load(io.open(p, encoding='utf-8')).get('opcos_by_ticker', {})
            for o in m.get(ticker, []) or []:
                add(o.get('edgar_name') or o.get('ferc_name'), False)
                add(o.get('ferc_name'), False)
        except Exception:
            pass
    # holdco flag by name equality with the company name
    if company_name:
        ck = ' '.join(t for t in _norm(short_name(company_name)) if t not in SUFFIX)
        for k, (disp, h, toks) in list(names.items()):
            if k == ck:
                names[k] = (disp, True, toks)
    return sorted(names.values(), key=lambda x: -len(x[2]))   # longest first


def _klass(desc, seniority, secured):
    if LEASE_PAT.search(desc): return None          # a lease is not an issuance
    if HYBRID_PAT.search(desc): return 'hybrid'
    if re.search(r'\bVIE\b', desc): return 'VIE'
    if secured == 'Yes' or SECURED_PAT.search(desc): return 'secured'
    if secured == 'No': return 'unsecured'
    return None


def infer_issuing_entity(desc, seniority, secured, issuer_names):
    desc = desc or ''
    seniority = seniority or ''
    secured = secured or ''
    k = _klass(desc, seniority, secured)
    dt = _norm(desc)
    dstr = ' ' + ' '.join(dt) + ' '
    # 1. a printed issuer name - credit-file entities and the ALIAS phrases pooled,
    #    longest phrase wins; on a tie the ALIAS spelling wins (it is hand-cased)
    cands = [(phrase, disp, holdco, 0) for phrase, (disp, holdco) in ALIAS_TOKS]
    cands += [(' ' + ' '.join(toks) + ' ', disp, holdco, 1) for disp, holdco, toks in issuer_names]
    cands.sort(key=lambda c: (-len(c[0].split()), c[3]))
    for phrase, disp, holdco, _ in cands:
        if phrase in dstr:
            role = 'HoldCo' if holdco else 'OpCo'
            return f'{role} · {disp}' + (f' ({k})' if k else '')
    first = desc.split()[0].rstrip(':,-') if desc.split() else ''
    if re.match(r'^[A-Z][A-Z&]{1,5}$', first) and first not in NOT_ISSUER and len(desc.split()) > 1:
        return f'OpCo · {first}' + (f' ({k})' if k else '')
    # 3. class only
    if k == 'hybrid':    return 'HoldCo (hybrid)'
    if k == 'VIE':       return 'OpCo (VIE)'
    if k == 'secured':   return 'OpCo (secured)'
    if k == 'unsecured' and 'Senior' in seniority: return 'HoldCo (unsecured)'
    return None


def reapply(capiq_path=None, dry=False):
    capiq_path = capiq_path or os.path.join(DATA_DIR, 'capiq_export.json')
    raw = io.open(capiq_path, encoding='utf-8').read()
    d = json.loads(raw, object_pairs_hook=collections.OrderedDict)
    changed = 0
    for tk, c in d['companies'].items():
        rows = c.get('capital_structure_details') or []
        names = load_issuer_names(tk, c.get('name'))
        before = collections.Counter(r.get('issuing_entity') for r in rows)
        for r in rows:
            new = infer_issuing_entity(r.get('description'), r.get('seniority'), r.get('secured'), names)
            if new != r.get('issuing_entity'):
                r['issuing_entity'] = new; changed += 1
        after = collections.Counter(r.get('issuing_entity') for r in rows)
        unc_b = before.get(None, 0); unc_a = after.get(None, 0)
        named = sum(v for k2, v in after.items() if k2 and '·' in k2)
        print(f'{tk:5} n={len(rows):3}  None {unc_b:3}->{unc_a:3}  named {named:3}  issuers={len(names)}')
    if dry:
        print(f'\nDRY RUN - {changed} cells would change'); return
    if changed:
        bak = capiq_path + '.bak-issuer-' + __import__('datetime').date.today().isoformat()
        n = 1
        while os.path.exists(bak):                      # never overwrite an earlier backup
            n += 1; bak = capiq_path + '.bak-issuer-' + __import__('datetime').date.today().isoformat() + f'-{n}'
        io.open(bak, 'w', encoding='utf-8').write(raw)
        indent = 2 if raw.startswith('{\n  "') else 1
        io.open(capiq_path, 'w', encoding='utf-8').write(json.dumps(d, indent=indent, ensure_ascii=False))
        json.load(io.open(capiq_path, encoding='utf-8'))
        print(f'\n{changed} cells changed; backup {bak}')
    else:
        print('\nno changes')


if __name__ == '__main__':
    reapply(dry='--dry' in sys.argv)
