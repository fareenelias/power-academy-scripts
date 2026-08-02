r"""
clean_fairness.py — precedents.json

Strips the fairness_opinion links written by resolve_agreements.py v1, which was
broken in four ways: it accepted DEF 14A (the ANNUAL proxy, not the merger proxy),
had no upper date bound (FirstEnergy/GPU got a proxy filed 199 months after
announcement), read only the `recent` submissions window so older deals could
never match their real proxy, and matched "opinion of counsel" style boilerplate
as if it were a banker's fairness opinion.

53 of 68 links written were wrong. Rather than try to sort good from bad in place,
this removes ALL of them -- a link that might be right is worse than no link,
because it looks sourced.

AGREEMENTS ARE NOT TOUCHED. Those 22 came off the Type=EX-2.x column and are good.

Idempotent. Reports exactly what it removed.
"""

import json, io, os, shutil


def _find_precedents():
    import sys
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
KILL = ('fairness_opinion', '_fo_src')


def main():
    db = json.load(open(SRC, encoding='utf-8'))
    deals = db['deals']

    removed = []
    for d in deals:
        L = d.get('links') or {}
        hit = {k: L[k] for k in KILL if L.get(k)}
        if not hit:
            continue
        for k in KILL:
            if k in L:
                L[k] = None if k == 'fairness_opinion' else None
                if k == '_fo_src':
                    L.pop(k, None)
        removed.append((d['id'], hit.get('_fo_src', '')[:60]))

    agr = sum(1 for d in deals if (d.get('links') or {}).get('agreement'))

    if not removed:
        print('no fairness_opinion links present — nothing to clean')
    else:
        shutil.copyfile(SRC, SRC + '.bak_clean')
        with io.open(SRC, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
            f.write('\n')

    print('removed %d fairness_opinion links' % len(removed))
    print('agreements retained: %d  (untouched — sourced from Type=EX-2.x)' % agr)
    if removed:
        print('\nfirst 10 removed:')
        for i, (did, src) in enumerate(removed[:10]):
            print('  %-38s %s' % (did, src))
        print('\nbackup: %s.bak_clean' % os.path.basename(SRC))


if __name__ == '__main__':
    main()