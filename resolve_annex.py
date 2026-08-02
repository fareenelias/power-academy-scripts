r"""
resolve_annex.py — precedents.json  (local; needs sec.gov reachable)

Second-pass agreement finder for deals where the merger agreement was NOT filed
as an 8-K exhibit. For a stock/cash merger the agreement is annexed to the merger
proxy (S-4 / DEFM14A) as ANNEX A (sometimes B). Where a deal already has a
fairness_opinion pointing at that same S-4, the agreement is in the SAME document
-- so this resolves it by parsing the S-4's table of contents for the Annex A
anchor. No new EDGAR crawl for those deals.

Runs ONLY on deals that:
  - are whole_company (an asset/minority deal has no merger proxy), and
  - have no agreement yet, and are not _verified.

Two modes per deal:
  1. FROM PROXY: if links.fairness_opinion is an S-4/proxy, read its ToC for the
     'Annex A - Agreement and Plan of Merger' anchor and link to it directly.
  2. HUNT PROXY: else find the merger proxy (reusing resolve_agreements' finder)
     and do the same.

Writes links.agreement with an '(Annex A of S-4)' note so the source is explicit.
Never overwrites an existing or verified link. Fetch failures are counted, not
recorded as absence.

  python resolve_annex.py --dry-run
  python resolve_annex.py
  python resolve_annex.py --only exelon_pseg_2004
"""

import json, io, os, re, sys, shutil, argparse, importlib.util

# ---- reuse the machinery already written & debugged in resolve_agreements.py
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    'ra', os.path.join(HERE, 'resolve_agreements.py'))
ra = importlib.util.module_from_spec(spec)
# resolve_agreements runs argparse in __main__ only, so import is side-effect-free
old_argv = sys.argv
sys.argv = ['resolve_annex']
spec.loader.exec_module(ra)
sys.argv = old_argv

SRC = ra.SRC   # inherits the same self-locating data-file path

# --file must be honoured by THIS script: the ra import masks sys.argv so the
# shared locator never sees it, which silently wrote to the default file.
def _src_override(default):
    import sys, os
    for i, a in enumerate(sys.argv):
        if a == '--file' and i + 1 < len(sys.argv):
            p = os.path.abspath(sys.argv[i + 1])
            if not os.path.isfile(p):
                raise SystemExit('--file not found: %s' % p)
            return p
    return default


SRC = _src_override(SRC)


# ---- Annex detection -------------------------------------------------------
# ToC / body links whose text is "Annex A" (or B) near "Agreement and Plan of
# Merger". EDGAR S-4s render the ToC as anchored links into the same document.
ANNEX_LINK = re.compile(
    r'<a[^>]+href=["\']#([^"\']+)["\'][^>]*>\s*'
    r'(?:Annex\s+([A-C])\b|Agreement\s+and\s+Plan\s+of\s+Merger)', re.I)
ANNEX_NEAR = re.compile(
    r'Annex\s+([A-C])\b[^<]{0,80}?(Agreement\s+and\s+Plan\s+of\s+Merger|'
    r'Merger\s+Agreement|Purchase\s+Agreement)', re.I)
# a separate S-4 EXHIBIT can also carry the agreement (EX-2.1 filed WITH the S-4)
EX2 = re.compile(r'^EX-2(\.\d+)?$', re.I)


def annex_anchor(html):
    """Return an in-document anchor for the merger-agreement annex, or None.

    Only an annex that is EITHER 'Annex A' OR explicitly names the agreement is
    eligible. A 'Annex B - Opinion of Financial Advisor' link must NEVER be
    returned as the agreement, so it is not cached as a fallback.
    """
    if not html:
        return None
    for m in ANNEX_LINK.finditer(html):
        letter = (m.group(2) or '').upper()
        names_agreement = 'Agreement and Plan of Merger' in m.group(0)
        if letter == 'A' or names_agreement:
            return m.group(1)
    return None


def proxy_is_s4(url):
    return bool(url) and ('s-4' in url.lower() or '/s4' in url.lower()
                          or re.search(r'd\w+ds4|forms-4', url.lower()))


def resolve_from_proxy(proxy_url):
    """Given an S-4/proxy url, return (agreement_url, how) or (None, reason)."""
    html = ra.get(proxy_url, timeout=60)
    if html is None:
        return None, 'fetch failed'
    a = annex_anchor(html)
    if a:
        return proxy_url + '#' + a, 'Annex A anchor'
    if ANNEX_NEAR.search(ra.TAG.sub(' ', html[:4_000_000])):
        return proxy_url, 'Annex A present, no anchor (links to proxy top)'
    return None, 'no Annex A found in this proxy'


def find_proxy_url(d):
    """Best merger-proxy url for a deal: its FO if that's a proxy, else hunt."""
    L = d.get('links') or {}
    fo = L.get('fairness_opinion')
    if fo and ('sec.gov' in fo):
        return fo.split('#')[0], 'from fairness_opinion'
    # hunt one (reuse the validated finder)
    for cik in ra.all_ciks(d):
        cands = ra.find_proxy(cik, d.get('announced'), d)
        if cands:
            return cands[0][0], 'hunted proxy (%s %s)' % (cands[0][2], cands[0][1])
    return None, 'no proxy found'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--only')
    ap.add_argument('--file')
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()

    db = json.load(open(SRC, encoding='utf-8'))
    deals = db['deals']
    if a.only:
        deals = [d for d in deals if d['id'] == a.only]

    got = skipped = failed = fetchfail = notwhole = 0
    n = 0
    for d in deals:
        L = d.setdefault('links', {})
        ver = L.get('_verified') or {}
        if L.get('agreement') or ver.get('agreement') == 'human':
            skipped += 1
            continue
        if d.get('deal_scope') != 'whole_company':
            notwhole += 1
            continue

        n += 1
        if a.limit and n > a.limit:
            break

        proxy_url, how = find_proxy_url(d)
        if not proxy_url:
            failed += 1
            print('  ---  %-32s %s' % (d['id'], how))
            continue

        agr_url, why = resolve_from_proxy(proxy_url)
        if agr_url is None and why == 'fetch failed':
            fetchfail += 1
            print('  ...  %-32s fetch failed — retry, NOT recorded absent' % d['id'])
            continue
        if agr_url:
            got += 1
            print('  ANX  %-32s %s [%s]' % (d['id'], why, how))
            if not a.dry_run:
                L['agreement'] = agr_url
                L['_agreement_src'] = 'S-4 Annex A (%s) — %s' % (how, why)
        else:
            failed += 1
            print('  ---  %-32s %s' % (d['id'], why))

    if not a.dry_run:
        shutil.copyfile(SRC, SRC + '.bak_annex')
        with io.open(SRC, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
            f.write('\n')

    print('\nAnnex A agreements found %d · already had/verified %d · not whole-company %d'
          % (got, skipped, notwhole))
    print('  no proxy / no annex %d · fetch failed %d' % (failed, fetchfail))
    print('DRY RUN — nothing written' if a.dry_run else 'written (backup .bak_annex)')


if __name__ == '__main__':
    main()