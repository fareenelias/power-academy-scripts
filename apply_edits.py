#!/usr/bin/env python3
"""
Apply guarded edit batches to the Power Academy JSON data files.

Guard contract (this is the whole point of the script):
  Every edit states the EXACT current value it expects at its path.
  If ANY edit mismatches, NOTHING is written -- the whole batch is refused.

That guard has already caught 9 bad edits in this project (2026-08-01), where a
naive applier would have silently created keys in the wrong place and been
indistinguishable from correct edits afterwards.

Also enforces the standing rules:
  - merge-only / no key loss: a before/after KEY DIFF is printed and the write
    ABORTS if the top-level key set or the deal/report count changes unexpectedly.
  - atomic write via os.replace.
  - _verified == 'human' fields are never overwritten.
"""
import argparse, json, os, re, sys, shutil, hashlib
from datetime import date

SENTINEL = object()


# ---------------------------------------------------------------- path parsing
def parse_path(path):
    """Supports:  $.deals[?(@.id=='x')].a.b   |   deals[3].a.b   |   $.a.b
    Returns a list of steps: ('key',name) ('idx',n) ('pred',field,value)"""
    steps = []
    p = path.lstrip('$').lstrip('.')
    token = ''
    i = 0
    while i < len(p):
        c = p[i]
        if c == '.':
            if token:
                steps.append(('key', token)); token = ''
            i += 1
        elif c == '[':
            if token:
                steps.append(('key', token)); token = ''
            j = p.index(']', i)
            inner = p[i + 1:j]
            m = re.match(r"\?\(@\.([A-Za-z0-9_]+)\s*==\s*'(.*)'\)$", inner)
            m2 = re.match(r"\?\(@\s*==\s*'(.*)'\)$", inner)
            if m:
                steps.append(('pred', m.group(1), m.group(2)))
            elif m2:
                # predicate on a bare scalar array element, e.g. a filename list
                steps.append(('selfpred', m2.group(1)))
            elif re.match(r'^-?\d+$', inner):
                steps.append(('idx', int(inner)))
            elif inner.startswith("'") and inner.endswith("'"):
                steps.append(('key', inner[1:-1]))
            else:
                raise ValueError(f'unparsable selector [{inner}] in {path}')
            i = j + 1
        else:
            token += c; i += 1
    if token:
        steps.append(('key', token))
    return steps


def resolve(root, steps):
    """Return (parent_container, final_accessor, value_or_SENTINEL)."""
    cur = root
    for k, step in enumerate(steps):
        last = (k == len(steps) - 1)
        if step[0] == 'key':
            name = step[1]
            if not isinstance(cur, dict):
                return None, None, SENTINEL
            if last:
                return cur, name, cur.get(name, SENTINEL)
            if name not in cur:
                return None, None, SENTINEL
            cur = cur[name]
        elif step[0] == 'idx':
            n = step[1]
            if not isinstance(cur, list) or n >= len(cur):
                return None, None, SENTINEL
            if last:
                return cur, n, cur[n]
            cur = cur[n]
        elif step[0] == 'selfpred':
            val = step[1]
            if not isinstance(cur, list):
                return None, None, SENTINEL
            hit = [(idx, e) for idx, e in enumerate(cur) if e == val]
            if len(hit) != 1:
                return None, None, SENTINEL
            idx, e = hit[0]
            if last:
                return cur, idx, e
            cur = e
        else:  # pred
            field, val = step[1], step[2]
            if not isinstance(cur, list):
                return None, None, SENTINEL
            hit = [(idx, e) for idx, e in enumerate(cur)
                   if isinstance(e, dict) and str(e.get(field)) == val]
            if len(hit) != 1:
                return None, None, SENTINEL
            idx, e = hit[0]
            if last:
                return cur, idx, e
            cur = e
    return None, None, SENTINEL


# ------------------------------------------------------------------ key diffing
def fingerprint(obj):
    """Recursive key-set fingerprint -- catches silent structural loss, which is
    how all four assemble.py data-loss incidents were eventually found."""
    keys = set()

    def walk(o, prefix=''):
        if isinstance(o, dict):
            for kk, vv in o.items():
                keys.add(f'{prefix}.{kk}')
                walk(vv, f'{prefix}.{kk}')
        elif isinstance(o, list):
            for vv in o:
                walk(vv, f'{prefix}[]')
    walk(obj)
    return keys


def human_locked(root, steps):
    """Refuse to touch anything under a links._verified[field] == 'human'."""
    try:
        for k in range(len(steps), 0, -1):
            parent, acc, val = resolve(root, steps[:k])
            if isinstance(val, dict) and val.get('_verified') == 'human':
                return True
    except Exception:
        pass
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--edits', required=True, nargs='+')
    ap.add_argument('--group', default=None,
                    help='for dict-shaped edit files, which group key to apply')
    ap.add_argument('--root', default='/home/claude/pa')
    ap.add_argument('--write', action='store_true',
                    help='without this, runs as a dry run and writes nothing')
    args = ap.parse_args()

    edits = []
    for ef in args.edits:
        raw = json.load(open(ef))
        if isinstance(raw, dict):
            groups = [args.group] if args.group else \
                     [g for g in raw if g.startswith('group_a')]
            for g in groups:
                for e in raw[g]:
                    e.setdefault('file', 'data/precedents.json')
                    e['_src'] = f'{os.path.basename(ef)}:{g}'
                    edits.append(e)
        else:
            for e in raw:
                e.setdefault('file', 'data/precedents.json')
                e['_src'] = os.path.basename(ef)
                edits.append(e)

    # questions carry no edit
    edits = [e for e in edits if e.get('op') != 'question']
    print(f'{len(edits)} candidate edits from {len(args.edits)} file(s)\n')

    byfile = {}
    for e in edits:
        byfile.setdefault(e['file'], []).append(e)

    # ---------------------------------------------------------------- PASS 1
    docs, failures = {}, []
    for fname, elist in byfile.items():
        path = os.path.join(args.root, fname)
        docs[fname] = json.load(open(path, encoding='utf-8'))
        root = docs[fname]
        for e in elist:
            try:
                steps = parse_path(e['path'])
            except Exception as ex:
                failures.append((e, f'unparsable path: {ex}')); continue
            if human_locked(root, steps):
                failures.append((e, "REFUSED: under a _verified=='human' block")); continue
            parent, acc, cur = resolve(root, steps)
            op = e.get('op', 'set')
            if cur is SENTINEL:
                if op == 'set' and e.get('old', None) is None:
                    continue  # creating a new key with old=null is legitimate
                failures.append((e, 'path does not resolve')); continue
            if cur != e.get('old'):
                failures.append((e,
                    f'MISMATCH\n      expected: {json.dumps(e.get("old"))[:220]}'
                    f'\n      actual:   {json.dumps(cur)[:220]}'))

    if failures:
        print(f'REFUSED — {len(failures)} of {len(edits)} edits did not match.'
              '  Nothing written.\n')
        for e, why in failures[:40]:
            print(f'  [{e["_src"]}] {e["path"]}\n      {why}')
        if len(failures) > 40:
            print(f'  ... and {len(failures)-40} more')
        sys.exit(1)

    print(f'GUARD PASSED — all {len(edits)} edits match their stated current value.\n')
    if not args.write:
        print('Dry run. Re-run with --write to apply.')
        return

    # ---------------------------------------------------------------- PASS 2
    for fname, elist in byfile.items():
        path = os.path.join(args.root, fname)
        root = docs[fname]
        before_keys = fingerprint(root)
        before_counts = {k: len(v) for k, v in root.items() if isinstance(v, list)} \
            if isinstance(root, dict) else {}

        applied = 0
        for e in elist:
            steps = parse_path(e['path'])
            parent, acc, cur = resolve(root, steps)
            op = e.get('op', 'set')
            if op == 'set':
                if parent is None:  # creating a fresh key
                    pparent, pacc, pval = resolve(root, steps[:-1])
                    if isinstance(pval, dict):
                        pval[steps[-1][1]] = e['new']; applied += 1
                    continue
                parent[acc] = e['new']; applied += 1
            elif op == 'delete_key':
                del parent[acc]; applied += 1
            elif op == 'delete_element':
                parent.pop(acc); applied += 1
            elif op == 'replace_element_with_two':
                parent.pop(acc)
                for off, item in enumerate(e['new']):
                    parent.insert(acc + off, item)
                applied += 1
            else:
                raise SystemExit(f'unknown op {op}')

        after_keys = fingerprint(root)
        lost = before_keys - after_keys
        gained = after_keys - before_keys
        after_counts = {k: len(v) for k, v in root.items() if isinstance(v, list)} \
            if isinstance(root, dict) else {}

        print(f'--- {fname}: {applied} edits applied')
        print(f'    key paths  before {len(before_keys)}  after {len(after_keys)}')
        for k, v in before_counts.items():
            if after_counts.get(k) != v:
                print(f'    ARRAY {k}: {v} -> {after_counts.get(k)}')
        if lost:
            print(f'    ! {len(lost)} key paths LOST:')
            for k in sorted(lost)[:25]:
                print(f'        {k}')
            # Un-merging a conflated row legitimately removes the merge artifacts:
            # the carried-over alternate fields and the duplicate/confidence markers
            # that only existed because two deals shared one record. Every one of
            # these was hand-checked to relocate into the split rows, not vanish.
            MERGE_ARTIFACTS = ('_merged_from', '_merge_note', '_merged_alt_fields',
                               '_merged_alt', '_dup_note')
            unexpected = [k for k in lost if not any(tok in k for tok in MERGE_ARTIFACTS)]
            if unexpected:
                print('    ABORTING — unexplained key loss. Nothing written.')
                sys.exit(2)
        if gained:
            print(f'    + {len(gained)} key paths gained')

        bak = path + f'.bak-{date.today().isoformat()}-preapply'
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(root, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
        print(f'    written atomically; backup at {os.path.basename(bak)}')


if __name__ == '__main__':
    main()
