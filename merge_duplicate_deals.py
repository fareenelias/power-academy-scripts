r"""
merge_duplicate_deals.py — precedents.json

h2o_southcentral_2025 and h2o_quadvest_2025 are the SAME transaction recorded
twice (Fareen, QC through 2023). Merge into h2o_southcentral_quadvest_2025.

MERGE RULE: take the union field by field, preferring a non-null value; where BOTH
rows hold a different non-null value, keep the surviving row's and record the other
under _merged_alt so nothing is silently discarded and the conflict stays visible.

Human-verified links win outright over anything else.

Generic enough to reuse: add pairs to MERGES.

  python merge_duplicate_deals.py --dry-run
  python merge_duplicate_deals.py
"""

import json, io, os, sys, shutil, datetime

# (keep_id, drop_id, new_id)
MERGES = [('h2o_southcentral_2025', 'h2o_quadvest_2025', 'h2o_southcentral_quadvest_2025')]


def _find():
    for i, a in enumerate(sys.argv):
        if a == '--file' and i + 1 < len(sys.argv):
            return os.path.abspath(sys.argv[i + 1])
    here = os.path.dirname(os.path.abspath(__file__))
    for c in [os.path.join(here, '..', 'data', 'precedents.json'),
              os.path.join(here, 'precedents.json'),
              r'E:\PowerAcademy\data\precedents.json']:
        if os.path.isfile(os.path.normpath(c)):
            return os.path.normpath(c)
    raise SystemExit('precedents.json not found; pass --file')


SRC = _find()
DRY = '--dry-run' in sys.argv


def merge_links(keep, drop):
    """Union the two link blocks, verified links winning."""
    out = dict(drop)
    kv = (keep.get('_verified') or {})
    dv = (drop.get('_verified') or {})
    for k, v in keep.items():
        if k in ('_verified', '_needs_find'):
            continue
        if v is None:
            continue
        if out.get(k) and out[k] != v:
            # conflict: verified wins, else keep's value survives and the other
            # is preserved rather than dropped
            if dv.get(k) == 'human' and kv.get(k) != 'human':
                out.setdefault('_merged_alt', {})[k] = v
                continue
            out.setdefault('_merged_alt', {})[k] = out[k]
        out[k] = v
    ver = dict(dv)
    ver.update(kv)
    if ver:
        out['_verified'] = ver
    nf = sorted(set((keep.get('_needs_find') or []) + (drop.get('_needs_find') or [])))
    if nf:
        out['_needs_find'] = nf
    return out


def merge_deal(keep, drop, new_id):
    out = dict(drop)
    alt = {}
    for k, v in keep.items():
        if k == 'links':
            continue
        if v in (None, '', [], {}):
            continue
        if k in out and out[k] not in (None, '', [], {}) and out[k] != v:
            alt[k] = out[k]
        out[k] = v
    out['links'] = merge_links(keep.get('links') or {}, drop.get('links') or {})
    out['id'] = new_id
    if alt:
        out['_merged_alt_fields'] = alt
    out['_merged_from'] = [keep['id'], drop['id']]
    out['_merge_note'] = ('%s and %s were the same transaction recorded twice; '
                          'merged %s. Conflicting values from the dropped row are kept '
                          'under _merged_alt / _merged_alt_fields rather than discarded.'
                          % (keep['id'], drop['id'], datetime.date.today().isoformat()))
    return out


def main():
    db = json.load(open(SRC, encoding='utf-8'))
    deals = db['deals']
    D = {d['id']: d for d in deals}

    for keep_id, drop_id, new_id in MERGES:
        k, dr = D.get(keep_id), D.get(drop_id)
        if not k or not dr:
            print('  !! missing: %s / %s' % (keep_id, drop_id))
            continue
        merged = merge_deal(k, dr, new_id)
        idx = deals.index(k)
        deals[idx] = merged
        deals.remove(dr)
        print('  merged %s + %s -> %s' % (keep_id, drop_id, new_id))
        for f in ('agreement', 'deck', 'press_release', 'press_release_acquirer',
                  'press_release_target'):
            v = (merged.get('links') or {}).get(f)
            if v:
                print('      %-24s %s' % (f, str(v)[-56:]))
        alt = (merged.get('links') or {}).get('_merged_alt') or {}
        if alt:
            print('      conflicts preserved: %s' % ', '.join(alt))
        alt_f = merged.get('_merged_alt_fields') or {}
        if alt_f:
            # SHOW the conflicting values, not just the field names -- these are
            # analytical inputs and the surviving choice needs to be judged.
            print('      field conflicts (kept <- vs -> dropped):')
            KEYFIELDS = ('target', 'acquirer', 'announced', 'closed', 'structure',
                         'consideration', 'pct_acquired', 'deal_scope')
            for f in KEYFIELDS:
                if f in alt_f:
                    print('        %-14s KEPT %-30s  dropped %s'
                          % (f, str(merged.get(f))[:30], str(alt_f[f])[:34]))
            rest = [f for f in alt_f if f not in KEYFIELDS]
            if rest:
                print('        (also: %s)' % ', '.join(rest))
            print('      -> review the KEPT column; dropped values are in '
                  '_merged_alt_fields')

    db.setdefault('_merge_meta', {})['duplicate_merge_2026_07_22'] = {
        'applied': datetime.date.today().isoformat(),
        'merges': [{'kept': a, 'dropped': b, 'new_id': c} for a, b, c in MERGES],
    }

    if not DRY:
        shutil.copyfile(SRC, SRC + '.bak_merge')
        with io.open(SRC, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
            f.write('\n')
    print('\ndeals: %d' % len(deals))
    print('DRY RUN — nothing written' if DRY else 'written (backup .bak_merge)')


if __name__ == '__main__':
    main()