"""
apply_basis.py — Power Academy / precedents.json

Writes a `basis` block onto every deal that carries a multiple, so the board can
tell the difference between "1.8x" and "1.8x struck on WHICH rate base".

CONVENTION (Fareen, 2026-07-22):
  column value  = most recent ACTUAL vintage        <- independently verifiable
  drop-down     = seller basis + buyer basis where they differ

Never rewrites a stored multiple. Where the convention implies a different
headline number than the DB already holds, it FLAGS the conflict for review
rather than silently restating it.

Undocumented bases are recorded EXPLICITLY with a reason and a next action --
never left blank, never guessed.

Reads : precedents.json, basis_audit.json
Writes: precedents.json (in place, indent=2 LF, matching existing format)
"""

import json, io, re, collections, shutil, datetime, os

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
AUD = os.path.join(os.path.dirname(SRC), 'basis_audit.json')

CONVENTION = 'most_recent_actual'
CONVENTION_NOTE = (
    'Column shows the multiple struck on the most recent ACTUAL vintage - the only '
    'basis independently verifiable from filings. Seller-basis and buyer-basis '
    'alternates are kept in alt[] and surfaced in the row deep-dive where they differ. '
    'A forward (E) vintage is mechanically a LOWER multiple than a trailing (A) one on '
    'the same deal because rate base grows, so this convention reads richer than a '
    'buyer-basis screen would.'
)

# deal-specific basis facts that no regex can recover
MANUAL_NOTES = {
    'brookfield_fet_2024': (
        'Second tranche was struck at the SAME valuation as the 2021 tranche - marking '
        'it up would have forced a write-down on the 19.9% Brookfield already held. The '
        'identical EV and rate base across both FET legs is therefore deliberate, not a '
        'data error. Consequence for screening: this is NOT a fresh 2024 market print '
        'and should be excluded from any 2024-vintage transmission comp set.'
    ),
    'brookfield_fet_2021': (
        'Sets the valuation mark that the 2024 follow-on tranche was struck against - '
        'the two legs are one valuation event, not two independent prints.'
    ),
}


def norm_side(name, target, acquirer):
    """Map a name mentioned in '(X basis)' to target / acquirer."""
    if not name:
        return None
    n = re.sub(r'[^a-z]', '', name.lower())
    if not n:
        return None
    for lbl, val in (('target', target), ('acquirer', acquirer)):
        v = re.sub(r'[^a-z]', '', (val or '').lower())
        if not v:
            continue
        if n[:6] and (n[:6] in v or v[:6] in n):
            return lbl
    return None


SIDE_PAT = re.compile(r'(\d+(?:\.\d+)?)\s*x[^.;|]{0,90}?\(([A-Za-z][A-Za-z&.\' ]{2,30}?)\s+basis\)', re.I)


def side_map(d):
    """value -> side, parsed from '(Duke basis)' style annotations."""
    out = {}
    txt = ' '.join(str(d.get(k) or '') for k in ('_recon', 'structure', '_note'))
    for m in SIDE_PAT.finditer(txt):
        s = norm_side(m.group(2), d.get('target'), d.get('acquirer'))
        if s:
            out[round(float(m.group(1)), 4)] = s
    return out


def reconcile_vintage(v, announced):
    """A vintage cannot be an ACTUAL if it post-dates the announcement.

    "9.2x Empire's 2017 EBITDA" in a Feb-2016 release is an ESTIMATE, however the
    press phrased it. Trusting the bare year mislabels forward multiples as
    trailing ones -- which is the exact comparability error this whole block
    exists to prevent.
    """
    if not v or not announced:
        return v
    m = re.match(r'^(\d{4})\s*(A|E)?$', str(v).strip())
    if not m:
        return v
    yr, suf = int(m.group(1)), (m.group(2) or '').upper()
    try:
        ann = int(str(announced)[:4])
    except (TypeError, ValueError):
        return v
    if yr > ann:
        return '%dE' % yr
    if not suf:
        return '%dA' % yr
    return '%d%s' % (yr, suf)


def vint_key(v):
    """Sort key: prefer ACTUAL over ESTIMATE, then most recent year."""
    if not v:
        return (-1, -1)
    m = re.match(r'^(\d{4})\s*(A|E)?', str(v))
    if not m:
        return (0, 0)
    yr = int(m.group(1))
    is_actual = 1 if (m.group(2) or 'A').upper() == 'A' else 0
    return (is_actual, yr)


def pick_primary(hits):
    """Convention (b): most recent actual; fall back to nearest estimate."""
    cand = [h for h in hits if h.get('vintage') and h.get('value') is not None]
    if not cand:
        return None, []
    cand = sorted(cand, key=lambda h: vint_key(h['vintage']), reverse=True)
    # dedupe identical value+vintage
    seen, uniq = set(), []
    for h in cand:
        k = (round(h['value'], 4), h['vintage'])
        if k not in seen:
            seen.add(k)
            uniq.append(h)
    return uniq[0], uniq[1:]


def main():
    db = json.load(open(SRC, encoding='utf-8'))
    aud = json.load(open(AUD, encoding='utf-8'))['audit']
    deals = db['deals']

    tally = collections.Counter()
    conflicts, notes_applied = [], []

    for d in deals:
        rec = aud.get(d['id'])
        if not rec and d['id'] not in MANUAL_NOTES:
            continue
        sides = side_map(d)
        basis = {}

        for metric, info in (rec or {}).items():
            hits = info.get('evidence') or []
            entry = {'convention': CONVENTION}

            if metric == 'premium_pct':
                # primary = unaffected where disclosed; else the stated reference
                pri = None
                for h in hits:
                    if h.get('reference') == 'unaffected' and h.get('value') is not None:
                        pri = h
                        break
                if pri is None:
                    for h in hits:
                        if h.get('value') is not None:
                            pri = h
                            break
                if pri is None and hits:
                    pri = hits[0]
                if pri:
                    entry.update({
                        'value': pri.get('value'),
                        'reference': pri.get('reference'),
                        'reference_date': pri.get('reference_date_text'),
                        'quote': pri.get('quote'),
                        'status': 'documented' if info['status'] == 'confirmed' else info['status'],
                    })
                    alt = []
                    for h in hits:
                        if h is pri:
                            continue
                        if h.get('reference') and h.get('reference') != pri.get('reference'):
                            alt.append({'value': h.get('value'),
                                        'reference': h.get('reference'),
                                        'quote': h.get('quote')})
                    if alt:
                        entry['alt'] = alt
                    entry['convention'] = 'unaffected_preferred'
                else:
                    entry.update({'status': 'undocumented',
                                  'reason': 'reference type not stated in any linked source'})
                basis[metric] = entry
                tally[('premium_pct', entry['status'])] += 1
                continue

            # ---- vintage-based multiples
            for h in hits:
                h['vintage'] = reconcile_vintage(h.get('vintage'), d.get('announced'))
            pri, alts = pick_primary(hits)

            # a computed EV/RB is fully documented if the rate-base INPUT carries a
            # vintage, even when no press phrase states the multiple in words.
            if pri is None and metric == 'rate_base_mult':
                ry = (d.get('raw') or {}).get('rate_base_year')
                m0 = d.get('multiples') or {}
                stored0 = m0.get('rate_base_mult', m0.get('ev_rb'))
                if ry and stored0 is not None:
                    pri = {'value': float(stored0),
                           'vintage': reconcile_vintage(str(ry), d.get('announced')),
                           'quote': 'computed on raw.rate_base_year=%s' % ry}
                    alts = []

            if pri is None:
                reason = ('party disclosed the multiple but the vintage was not captured; '
                          're-read the linked announcement'
                          if info['status'] == 'stated_basis_missing'
                          else 'multiple computed by us from an input whose vintage is not recorded')
                doc = ((d.get('links') or {}).get('press_release')
                       or (d.get('links') or {}).get('filing')
                       or (d.get('links') or {}).get('filing_index'))
                entry.update({'status': 'undocumented', 'reason': reason})
                if doc:
                    entry['recheck_doc'] = doc
                basis[metric] = entry
                tally[(metric, 'undocumented')] += 1
                continue

            import re as _re
            _yr = bool(_re.match(r'^\d{4}', str(pri['vintage'] or '')))
            entry.update({
                'value': pri['value'],
                'vintage': pri['vintage'],
                'quote': pri['quote'],
                # a bare qualifier ("projected", "year-end") narrows the basis but
                # does NOT pin a vintage -- it is not the same as a documented year.
                'status': 'documented' if _yr else 'qualifier_only',
            })
            s = sides.get(round(pri['value'], 4))
            if s:
                entry['side'] = s
            if alts:
                entry['alt'] = [{'value': a['value'], 'vintage': a['vintage'],
                                 'quote': a['quote'],
                                 **({'side': sides[round(a['value'], 4)]}
                                    if round(a['value'], 4) in sides else {})}
                                for a in alts]
            # conflict vs stored headline
            m = d.get('multiples') or {}
            stored = m.get(metric)
            if metric == 'rate_base_mult' and stored is None:
                stored = m.get('ev_rb')
            if stored is not None and abs(float(stored) - float(pri['value'])) > 0.051:
                entry['_conflict'] = ('DB stores %s; convention picks %s (%s) - NOT auto-changed'
                                      % (stored, pri['value'], pri['vintage']))
                conflicts.append((d['id'], metric, stored, pri['value'], pri['vintage']))
            basis[metric] = entry
            tally[(metric, entry['status'])] += 1

        if d['id'] in MANUAL_NOTES:
            basis['_note'] = MANUAL_NOTES[d['id']]
            notes_applied.append(d['id'])

        if basis:
            basis['_convention_note'] = CONVENTION_NOTE
            d['basis'] = basis

    db['_schema_version'] = '1.4'
    db.setdefault('_merge_meta', {})
    db['_merge_meta']['basis_audit_2026_07_22'] = {
        'convention': CONVENTION,
        'note': CONVENTION_NOTE,
        'metrics_covered': ['rate_base_mult', 'ev_ebitda', 'pe', 'premium_pct'],
        'applied': datetime.date.today().isoformat(),
        'rule': ('basis.<metric>.status is documented | undocumented. undocumented rows '
                 'carry a reason and, where available, recheck_doc. Nothing is guessed and '
                 'no stored multiple was rewritten - convention conflicts are flagged in '
                 'basis.<metric>._conflict for manual review.'),
    }

    shutil.copyfile(SRC, SRC + '.bak')
    with io.open(SRC, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
        f.write('\n')

    # ------------------------------------------------------------- report
    print('=' * 74)
    print('BASIS BLOCKS WRITTEN  (convention: %s)' % CONVENTION)
    print('=' * 74)
    for met in ('rate_base_mult', 'ev_ebitda', 'pe', 'premium_pct'):
        doc = tally[(met, 'documented')]
        und = tally[(met, 'undocumented')]
        inf = tally[(met, 'inferred')] + tally[(met, 'qualifier_only')]
        if doc or und or inf:
            print('  %-15s documented %3d   undocumented %3d%s'
                  % (met, doc, und, ('   inferred %d' % inf) if inf else ''))
    print('\n  deals with a basis block : %d' % sum(1 for x in deals if x.get('basis')))
    print('  manual basis notes       : %s' % ', '.join(notes_applied))
    print('\n  CONVENTION CONFLICTS (stored vs convention pick) : %d' % len(conflicts))
    for c in conflicts:
        print('    %-32s %-15s stored %-6s -> %s (%s)' % c)
    print('\n  backup: %s.bak' % SRC)


if __name__ == '__main__':
    main()