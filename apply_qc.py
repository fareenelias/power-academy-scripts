# -*- coding: utf-8 -*-
r"""Apply the QC patch lists to the main JSONs, verifying every edit before it lands.

Fareen QC'd the review workbook and captured the actual PDF page for every cell in
doubt. Those captures were read, turned into resolutions, and then into explicit
path/old/new edits. This applies them.

The safety property that matters: **every edit states the value it expects to find**,
and the applier refuses the whole file if any `old` does not match. A wrong path that
silently writes into the wrong cell is the failure mode worth engineering against —
it would be indistinguishable from a correct edit afterwards.

  python3 apply_qc.py <patch_dir> <data_dir> [--dry-run]
"""
import argparse, collections, json, os, sys

ABSENT = '__ABSENT__'


def walk(root, path, create=False):
    """Return (container, last_key) for a path, or raise KeyError."""
    cur = root
    for k in path[:-1]:
        if isinstance(cur, list):
            i = int(k)
            if i == len(cur) and create:      # append into a list mid-path
                cur.append({})
            cur = cur[i]
        else:
            if k not in cur:
                if not create:
                    raise KeyError('missing segment %r' % k)
                cur[k] = {}
            cur = cur[k]
    return cur, path[-1]


def get(root, path):
    cur, last = walk(root, path)
    if isinstance(cur, list):
        i = int(last)
        # index == len is an APPEND, which is a legitimate "absent" target
        return cur[i] if i < len(cur) else ABSENT
    return cur[last] if last in cur else ABSENT


def put(root, path, value):
    cur, last = walk(root, path, create=True)
    if isinstance(cur, list):
        i = int(last)
        if i == len(cur):
            cur.append(value)                  # append
        else:
            cur[i] = value
    else:
        cur[last] = value


def same(a, b):
    """Compare tolerantly on numbers (1.0 == 1) and exactly otherwise."""
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) \
       and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(a - b) < 1e-9
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('patch_dir')
    ap.add_argument('data_dir')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    grand = collections.Counter()
    problems = []

    for pf in sorted(os.listdir(a.patch_dir)):
        if not pf.endswith('.json'):
            continue
        target = os.path.join(a.data_dir, pf)
        if not os.path.exists(target):
            problems.append((pf, 'no such data file'))
            continue

        edits = json.load(open(os.path.join(a.patch_dir, pf), encoding='utf-8'))
        data = json.load(open(target, encoding='utf-8'),
                         object_pairs_hook=collections.OrderedDict)

        # ---- PASS 1: verify every `old`. Nothing is written until all pass.
        bad = []
        for i, e in enumerate(edits):
            try:
                cur = get(data, e['path'])
            except (KeyError, IndexError, ValueError) as ex:
                # An edit that declares old == ABSENT is CREATING something, so a
                # missing parent container is expected, not an error - `put` builds
                # the chain. Anything claiming to replace a real value must still
                # resolve, otherwise a typo'd path would silently create a new key
                # instead of correcting the intended one.
                if e.get('old', ABSENT) == ABSENT:
                    cur = ABSENT
                else:
                    bad.append((i, e.get('row'),
                                'PATH UNRESOLVABLE: %s' % ex, e['path']))
                    continue
            want = e.get('old', ABSENT)
            if want == ABSENT:
                if cur is not ABSENT and cur != ABSENT:
                    bad.append((i, e.get('row'), 'expected ABSENT, found %r' % (cur,), e['path']))
            elif not same(cur, want):
                bad.append((i, e.get('row'),
                            'expected %r, found %r' % (want, cur), e['path']))

        if bad:
            print(f'\n{pf}: {len(bad)} of {len(edits)} edits FAILED verification '
                  f'— file NOT written')
            for i, row, why, path in bad[:12]:
                print(f'   edit #{i} (review row {row}): {why}')
                print(f'      path: {" -> ".join(map(str, path))}')
            if len(bad) > 12:
                print(f'   ... and {len(bad)-12} more')
            problems.append((pf, f'{len(bad)} verification failures'))
            continue

        # ---- PASS 2: apply
        changed = filled = noted = 0
        for e in edits:
            try:
                before = get(data, e['path'])
            except (KeyError, IndexError, ValueError):
                before = ABSENT      # verified above as an intentional creation
            put(data, e['path'], e['new'])
            if before is ABSENT or before == ABSENT:
                filled += 1
            elif isinstance(e['new'], str) and isinstance(before, str):
                noted += 1
            else:
                changed += 1

        print(f'{pf:24} {len(edits):3} edits verified and applied  '
              f'({changed} values corrected, {filled} cells filled, {noted} notes rewritten)')
        grand['edits'] += len(edits)
        grand['changed'] += changed
        grand['filled'] += filled
        grand['noted'] += noted

        if not a.dry_run:
            tmp = target + '.tmp'
            json.dump(data, open(tmp, 'w', encoding='utf-8'),
                      ensure_ascii=False, indent=1)
            json.load(open(tmp, encoding='utf-8'))   # re-parse before swap
            os.replace(tmp, target)

    print(f'\nTOTAL {grand["edits"]} edits  |  {grand["changed"]} values corrected, '
          f'{grand["filled"]} cells filled, {grand["noted"]} notes rewritten')
    if a.dry_run:
        print('DRY RUN — nothing written')
    if problems:
        print('\nFILES NOT WRITTEN:')
        for f, why in problems:
            print('  ', f, '—', why)
        sys.exit(1)


main()
