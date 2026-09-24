# -*- coding: utf-8 -*-
r"""build_opco_cik_map.py - refresh/extend data\opco_cik_map.json (SEC-by-subsidiary phase 2).

The map was seeded and VERIFIED 2026-09-21 (every cik checked against
data.sec.gov/submissions: name, formerNames, filing forms). This script re-verifies
and refreshes it, and retries the status=no_own_sec_registrant_found entities via
EDGAR company search.

Needs network - run on the desktop with the VPN off (python cannot reach external
URLs when the VPN is active). SEC header lessons from resolve_edgar_links.py apply:
Accept-Encoding is REQUIRED or www.sec.gov 403s; <10 req/sec.

  python build_opco_cik_map.py            # re-verify + refresh in place
  python build_opco_cik_map.py --check    # verify only, write nothing
"""
import json, os, re, sys, time, gzip, urllib.request, urllib.parse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP = os.path.join(BASE, 'data', 'opco_cik_map.json')
UA = os.environ.get('SEC_UA', 'PowerAcademy/1.0 power-academy@internal')
SLEEP = 0.25

def get(url, host):
    time.sleep(SLEEP)
    req = urllib.request.Request(url, headers={
        'User-Agent': UA, 'Accept-Encoding': 'gzip, deflate', 'Host': host,
        'Accept': 'application/json,text/html,*/*;q=0.8'})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
        if r.headers.get('Content-Encoding') == 'gzip':
            data = gzip.decompress(data)
        return data

def norm(s):
    s = re.sub(r'[.,/]', '', (s or '').lower())
    s = re.sub(r'\b(the|inc|llc|corp|corporation|company|co|of|and|&|ltd|limited)\b', ' ', s)
    return ' '.join(s.split())

def submissions(cik):
    d = json.loads(get('https://data.sec.gov/submissions/CIK%010d.json' % cik, 'data.sec.gov'))
    recent = d.get('filings', {}).get('recent', {})
    forms, dates = recent.get('form', []), recent.get('filingDate', [])
    def last(pred):
        for f, dt in zip(forms, dates):
            if pred(f): return dt
        return None
    return {'edgar_name': d.get('name'),
            'former': [f.get('name') for f in d.get('formerNames', [])],
            'last_10k': last(lambda f: f.startswith('10-K')),
            'last_10q': last(lambda f: f.startswith('10-Q'))}

def edgar_search(company):
    """EDGAR company-name lookup. 2026-09-24: www.sec.gov/cgi-bin/browse-edgar now returns 403 to
    scripts, so this uses the JSON index behind EDGAR's own company search box
    (efts.sec.gov/LATEST/search-index?keysTyped=...); each hit's _id is the CIK."""
    q = urllib.parse.urlencode({'keysTyped': company})
    d = json.loads(get('https://efts.sec.gov/LATEST/search-index?' + q, 'efts.sec.gov'))
    out = []
    for h in (d.get('hits') or {}).get('hits') or []:
        src = h.get('_source') or {}
        name = src.get('entity') or h.get('entity') or ''
        cik = h.get('_id') or src.get('cik')
        try:
            out.append((int(cik), name))
        except (TypeError, ValueError):
            pass
    return out  # [(cik, name)]

def main():
    check = '--check' in sys.argv
    doc = json.load(open(MAP, encoding='utf-8'))
    changed, problems = 0, []
    for tkr, entities in doc['opcos_by_ticker'].items():
        for ent in entities:
            cik = ent.get('cik')
            if cik:
                try:
                    sub = submissions(cik)
                except Exception as e:
                    problems.append((tkr, ent['ferc_name'], 'submissions error: %s' % e)); continue
                names = [sub['edgar_name']] + sub['former']
                no = norm(ent['ferc_name'])
                tie = any(n and (norm(n) in no or no in norm(n) or norm(n).split()[:2] == no.split()[:2])
                          for n in names)
                if not tie and ent.get('name_tie') != 'external_corporate_history':
                    problems.append((tkr, ent['ferc_name'],
                                     'NAME TIE FAILED vs %s - investigate, do not auto-fix' % sub['edgar_name']))
                    continue
                new_fop = bool((sub['last_10k'] and sub['last_10k'] >= '2024') or
                               (sub['last_10q'] and sub['last_10q'] >= '2024'))
                for k, v in (('edgar_name', sub['edgar_name']), ('last_10k', sub['last_10k']),
                             ('last_10q', sub['last_10q']), ('files_own_periodic', new_fop)):
                    if ent.get(k) != v:
                        print('  %s %s: %s %r -> %r' % (tkr, ent['ferc_name'][:35], k, ent.get(k), v))
                        if not check: ent[k] = v
                        changed += 1
            elif ent.get('status') == 'no_own_sec_registrant_found':
                try:
                    cands = edgar_search(ent['ferc_name'])
                except Exception as e:
                    problems.append((tkr, ent['ferc_name'], 'search error: %s' % e)); continue
                no = norm(ent['ferc_name'])
                hit = [(c, n) for c, n in cands if norm(n) in no or no in norm(n)]
                if hit:
                    print('  %s %s: SEARCH NOW FINDS %s - verify by hand and fill the cik' %
                          (tkr, ent['ferc_name'][:35], hit[0]))
                    problems.append((tkr, ent['ferc_name'], 'candidate found: %s' % (hit[0],)))
    if not check and changed:
        json.dump(doc, open(MAP, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('wrote %s (%d field changes)' % (MAP, changed))
    print('%s: %d changes, %d problems' % ('CHECK' if check else 'REFRESH', changed, len(problems)))
    for p in problems: print('  !', p)

if __name__ == '__main__':
    main()
