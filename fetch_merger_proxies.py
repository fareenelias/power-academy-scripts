# -*- coding: utf-8 -*-
r"""fetch_merger_proxies.py - download the merger proxy / S-4 for each precedent deal and save a plain-text
copy, so Cowork can extract (1) the "Background of the Merger" process and (2) each financial advisor's
valuation work ("Opinion of <bank>": DCF / DDM / precedents / trading comps / other).

  $env:SEC_UA = "Your Name you@example.com"      # once per PowerShell session (VPN off)
  python E:\PowerAcademy\scripts\fetch_merger_proxies.py            # fetch what is missing
  python E:\PowerAcademy\scripts\fetch_merger_proxies.py --dry-run  # show what it would fetch
  python E:\PowerAcademy\scripts\fetch_merger_proxies.py --only fortis_itc_2016,emera_teco_2015

Which document, per deal (whole-company deals only; single-asset / portfolio sales rarely have a proxy):
  1. data\_proxies\_manual.json  {"deal_id": "https://www.sec.gov/...htm"}  - your override, always wins
  2. links.fairness_opinion in precedents.json (35 deals; set by resolve_agreements v2)
  3. any sec.gov URL in the deal's links/sources whose file name looks like a proxy or S-4
  4. SEARCH: EDGAR full-text search on the target's name (2001+), plus every CIK that appears in the deal's
     sec.gov URLs, is searched for a DEFM14A, 424B3 (final
     S-4 prospectus), S-4/A, S-4, PREM14A, DEFM14C or PREM14C filed 0-400 days after announcement.
     Preference: DEFM14A > 424B3 > DEFM14C > S-4/A (latest) > S-4 > PREM14A > PREM14C.
     The EDGAR submissions API is paged, so older deals load the older pages. Each candidate is downloaded in
     rank order and kept only if it reads as this deal's proxy (merger headings + target name on the cover):
     a 424B3 can be a debt prospectus supplement. Earlier picks that failed that test are redone on re-run.

Writes  data\_proxies\<deal_id>.<htm|txt>       the document as filed
        data\_proxies\<deal_id>.txt               plain text (tables kept as ' | ' rows) - what Cowork reads
        data\_proxies\_manifest.json              deal -> url, form, filed, how it was found, sizes
_proxies\ is git-ignored (re-fetchable public filings). Nothing licensed is involved.
"""
import json, os, re, sys, time, gzip, html, urllib.request, urllib.error, urllib.parse
import datetime as dt
from html.parser import HTMLParser

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREC = os.path.join(BASE, 'data', 'precedents.json')
OUT = os.path.join(BASE, 'data', '_proxies')
UA = os.environ.get('SEC_UA', '').strip()
SLEEP = 0.25
FORM_RANK = {'DEFM14A': 0, '424B3': 1, 'DEFM14C': 2, 'S-4/A': 3, 'S-4': 4, 'PREM14A': 5, 'PREM14C': 6}
PROXY_NAME = re.compile(r'(defm14a|prem14a|defm14c|prem14c|pre14a|preproxy|[_\-.]s-?4|s4a|drsa|424b3)', re.I)
CIK_IN_URL = re.compile(r'sec\.gov/Archives/edgar/data/0*(\d+)/', re.I)


def get(url, tries=5):
    host = url.split('/')[2]
    for i in range(tries):
        time.sleep(SLEEP if i == 0 else min(60, 5 * 2 ** (i - 1)))
        req = urllib.request.Request(url, headers={
            'User-Agent': UA, 'Accept-Encoding': 'gzip, deflate', 'Host': host,
            'Accept': 'application/json,text/html,text/plain,*/*;q=0.8'})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
                if r.headers.get('Content-Encoding') == 'gzip':
                    data = gzip.decompress(data)
                return data
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < tries - 1:
                print(f'    {e.code} from SEC, retrying ({i + 1}/{tries - 1})...')
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            if i < tries - 1:
                print(f'    network error ({e}), retrying...')
                continue
            raise


# ---------------------------------------------------------------- EDGAR submissions search
_SUBS = {}


def filings(cik, lo, hi):
    """All filings of the proxy/S-4 forms for `cik` filed in [lo, hi] (ISO dates), loading older
    submission pages only as far back as needed."""
    if cik not in _SUBS:
        d = json.loads(get('https://data.sec.gov/submissions/CIK%010d.json' % cik))
        _SUBS[cik] = {'name': d.get('name'), 'blocks': [d.get('filings', {}).get('recent', {})],
                      'pages': list(d.get('filings', {}).get('files', [])), 'loaded': set()}
    S = _SUBS[cik]

    def rows():
        for b in S['blocks']:
            for form, a, p, f in zip(b.get('form', []), b.get('accessionNumber', []),
                                     b.get('primaryDocument', []), b.get('filingDate', [])):
                yield form, a, p, f

    def oldest():
        return min((f for _, _, _, f in rows()), default='9999')
    for pg in S['pages']:                      # pages are newest -> oldest
        if oldest() <= lo:
            break
        if pg['name'] in S['loaded']:
            continue
        S['blocks'].append(json.loads(get('https://data.sec.gov/submissions/' + pg['name'])))
        S['loaded'].add(pg['name'])
    return [{'cik': cik, 'filer': S['name'], 'form': form, 'accession': a, 'primary': p, 'filed': f}
            for form, a, p, f in rows() if form in FORM_RANK and lo <= f <= hi and p]


def _url(c):
    return 'https://www.sec.gov/Archives/edgar/data/%d/%s/%s' % (c['cik'], c['accession'].replace('-', ''), c['primary'])


GENERIC = {'the', 'inc', 'corp', 'corporation', 'co', 'company', 'group', 'holdings', 'incorporated', 'llc', 'lp', 'plc', 'ltd'}


def core_name(name):
    """'Piedmont Natural Gas Company, Inc.' -> 'piedmont natural gas' (lower, no suffixes/punctuation)."""
    w = [x for x in re.sub(r'[^a-z0-9 ]', ' ', re.sub(r'\s*\(.*?\)', '', name or '').lower()).split()]
    while w and w[-1] in GENERIC: w.pop()
    while w and w[0] == 'the': w.pop(0)
    return ' '.join(w)


def has_phrase(text, phrase):
    if not phrase: return False
    norm = re.sub(r'[^a-z0-9]+', ' ', text.lower())
    return re.search(r'\b' + re.escape(phrase) + r'\b', norm) is not None


EFTS_FORMS = ['DEFM14A', 'PREM14A', 'DEFM14C', 'PREM14C', 'S-4', 'S-4/A']   # no 424B3: mostly debt noise


def efts(deal, lo, hi):
    """EDGAR full-text search (2001+) on the TARGET's name - finds proxies filed under a CIK that none of the
    deal's links mention (e.g. Piedmont's own DEFM14A). Up to 300 hits are paged through; a hit is kept when
    the filer is the target or the acquirer (the proxy itself is validated after download)."""
    name = re.sub(r'\s*\(.*?\)', '', deal.get('target') or '').strip()
    if not name or lo < '2001-01-01':
        return []
    tgt, acq = core_name(name), core_name(deal.get('acquirer'))
    q = urllib.parse.quote(f'"{name}"')
    forms = urllib.parse.quote(','.join(EFTS_FORMS), safe=',')
    out, total = [], 0
    for page in range(3):
        url = (f'https://efts.sec.gov/LATEST/search-index?q={q}&forms={forms}'
               f'&dateRange=custom&startdt={lo}&enddt={hi}&from={100 * page}')
        try:
            d = json.loads(get(url))
        except Exception as e:
            print(f'    full-text search: {e}'); break
        hits = (d.get('hits') or {}).get('hits', [])
        total += len(hits)
        for h in hits:
            src = h.get('_source') or {}
            adsh, _, fn = (h.get('_id') or '').partition(':')
            form = src.get('form') or src.get('file_type') or ''
            names = ' '.join(src.get('display_names') or [])
            if form not in FORM_RANK or not fn:
                continue
            if not (has_phrase(names, tgt) or (acq and has_phrase(names, acq))):
                continue
            cik = int((src.get('ciks') or ['0'])[0])
            out.append({'cik': cik, 'filer': (src.get('display_names') or [''])[0], 'form': form,
                        'accession': adsh, 'primary': fn, 'filed': src.get('file_date') or ''})
        if len(hits) < 100:
            break
    print(f'    full-text search "{name}": {total} hits, {len(out)} filed by target/acquirer')
    return out


def _nm(x):
    return re.sub(r'\b(and)\b', ' ', re.sub(r'[^a-z0-9]+', ' ', (x or '').lower().replace('&', ' '))).split()


def company_ciks(name):
    """CIKs whose EDGAR company name starts with the target's core name (EDGAR company browse, atom feed).
    Works for pre-2001 targets the full-text search cannot see; the submissions API then lists their filings."""
    core = core_name(name)
    if not core:
        return []
    q = urllib.parse.quote_plus(core.replace(' and ', ' & '))
    url = f'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={q}&owner=include&count=40&output=atom'
    try:
        x = get(url).decode('utf-8', errors='replace')
    except Exception as e:
        print(f'    company lookup "{core}": {e}'); return []
    want = _nm(core)
    out = []
    # company-list feed: <entry> ... <cik>..</cik> ... <name>..</name>; single-company feed: <company-info><cik>
    for blk in re.findall(r'<(?:entry|company-info)>(.*?)</(?:entry|company-info)>', x, re.S):
        cik = re.search(r'<cik>\s*(\d+)\s*</cik>', blk)
        nm = re.search(r'<(?:name|conformed-name|title)>\s*([^<]+?)\s*</', blk)
        if not cik: continue
        got = _nm(html.unescape(nm.group(1)) if nm else '')
        if got[:len(want)] == want:
            out.append(int(cik.group(1)))
    out = list(dict.fromkeys(out))[:5]
    print(f'    company lookup "{core}": {len(out)} CIK(s) {out}')
    return out


def search(deal):
    """Ranked candidate filings (best first). main() downloads them in order and keeps the first that
    actually reads as this deal's merger proxy."""
    ann = deal.get('announced')
    if not ann:
        return []
    lo = ann
    hi = (dt.date.fromisoformat(ann) + dt.timedelta(days=400)).isoformat()
    ciks = sorted({int(c) for u in urls_of(deal) for c in CIK_IN_URL.findall(u)})
    ciks = list(dict.fromkeys(company_ciks(deal.get('target')) + ciks))     # target's own filings first
    cands = []
    for cik in ciks:
        try:
            cands += filings(cik, lo, hi)
        except Exception as e:
            print(f'    submissions {cik}: {e}')
    cands += efts(deal, lo, hi)
    seen, uniq = set(), []
    for c in cands:
        if c['accession'] in seen: continue
        seen.add(c['accession']); c['url'] = _url(c); c['how'] = 'search'; uniq.append(c)
    # best form; within a form the latest filing (S-4/A amendments carry the final numbers)
    uniq.sort(key=lambda c: (FORM_RANK[c['form']], -int((c['filed'] or '0').replace('-', ''))))
    return uniq[:8]


def looks_like_proxy(text, deal, strict=True):
    """Keep a candidate only if it reads as THIS deal's merger proxy: the target's full name (not just a
    first word - 'Peoples' matched People's United, 'NV' matched everything) on the cover pages, a
    'Background of the Merger' heading, and fairness-opinion language."""
    head = text[:80000]
    tgt = core_name(deal.get('target'))
    has_target = has_phrase(head, tgt) if tgt else True
    if has_target and len(tgt.split()) < 2:          # one-word names ('Peoples', 'Oncor') also need the acquirer
        acq = core_name(deal.get('acquirer'))
        n = len(re.findall(r'\b' + re.escape(tgt) + r'\b', re.sub(r'[^a-z0-9]+', ' ', text[:300000].lower())))
        acq_hit = bool(acq and any(has_phrase(text[:200000], w) for w in [acq] + [a for a in acq.split() if len(a) > 4][:1]))
        has_target = acq_hit if strict else (n >= 20 or acq_hit)   # search picks must name the acquirer too
    has_bg = re.search(r'^\s*(the\s+merger\s*[-\u2014:]\s*)?background(\s+(of|to)\s+the\s+(proposed\s+)?'
                       r'(merger|mergers|transaction|transactions|acquisition|combination|share\s+exchange|offer)s?)?\s*$',
                       text, re.I | re.M) is not None
    has_fair = re.search(r'from\s+a\s+financial\s+point\s+of\s+view', text, re.I) is not None
    return has_target and has_bg and has_fair


def urls_of(deal):
    out = []

    def walk(x):
        if isinstance(x, str):
            out.extend(re.findall(r'https?://[^\s;,)\'"]+', x))
        elif isinstance(x, dict):
            for v in x.values(): walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
    walk(deal.get('links', {})); walk(deal.get('sources', {}))
    return [u for u in out if 'sec.gov' in u]


# ---------------------------------------------------------------- HTML -> text
class _Text(HTMLParser):
    BLOCK = {'p', 'div', 'br', 'tr', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'center', 'hr'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, a):
        if tag in ('script', 'style'): self.skip += 1
        elif tag in self.BLOCK: self.out.append('\n')
        elif tag in ('td', 'th'): self.out.append(' | ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'): self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK: self.out.append('\n')

    def handle_data(self, d):
        if not self.skip: self.out.append(d)


def to_text(raw, is_html):
    s = raw.decode('utf-8', errors='replace') if isinstance(raw, bytes) else raw
    if is_html:
        p = _Text(); p.feed(s); s = ''.join(p.out)
    else:
        s = re.sub(r'<[^>]+>', ' ', s)              # old .txt submissions carry SGML wrappers
        s = html.unescape(s)
    s = s.replace('\xa0', ' ')
    lines = []
    for ln in s.split('\n'):
        ln = re.sub(r'[ \t]+', ' ', ln).strip()
        ln = re.sub(r'^(\| ?)+', '', ln).strip()      # leading empty cells
        ln = re.sub(r'( ?\| ?)+$', '', ln).strip()
        ln = re.sub(r'(\s*\|\s*){2,}', ' | ', ln)     # runs of empty cells
        lines.append(ln)
    s = '\n'.join(lines)
    return re.sub(r'\n{3,}', '\n\n', s).strip() + '\n'


# ---------------------------------------------------------------- main
def main():
    dry = '--dry-run' in sys.argv
    only = None
    if '--only' in sys.argv:
        only = set(sys.argv[sys.argv.index('--only') + 1].split(','))
    if '@' not in UA and not dry:
        sys.exit('SEC requires a User-Agent with a real name and email. In PowerShell run:\n'
                 '  $env:SEC_UA = "Your Name you@example.com"\nthen re-run (VPN off).')
    os.makedirs(OUT, exist_ok=True)
    deals = json.load(open(PREC, encoding='utf-8'))['deals']
    manual_p = os.path.join(OUT, '_manual.json')
    manual = json.load(open(manual_p, encoding='utf-8')) if os.path.exists(manual_p) else {}
    man_p = os.path.join(OUT, '_manifest.json')
    manifest = json.load(open(man_p, encoding='utf-8')).get('deals', {}) if os.path.exists(man_p) else {}
    fetched, missing, failed = 0, [], []
    try:
        for d in deals:
            did = d['id']
            if only and did not in only:
                continue
            if d.get('deal_scope') != 'whole_company' and did not in manual:
                continue
            txt_p = os.path.join(OUT, did + '.txt')
            prev = manifest.get(did) or {}
            ext_p = os.path.join(BASE, 'data', '_merge', 'merger_extract', did + '.json')
            extracted = os.path.exists(ext_p) and not json.load(open(ext_p, encoding='utf-8')).get('wrong_document')
            bad_prev = prev.get('how') == 'search' and (any('wrong filing' in f or 'Background' in f for f in prev.get('flags') or [])
                                                      or (os.path.exists(txt_p) and not looks_like_proxy(open(txt_p, encoding='utf-8', errors='replace').read(), d)))
            if prev.get('status') == 'ok' and os.path.exists(txt_p) and (extracted or not bad_prev) and did not in manual and not only:
                continue                                   # already done
            pick = None
            if did in manual and manual[did] is None:
                manifest[did] = {'status': 'no proxy (manual: private / asset / foreign target)', 'announced': d.get('announced'),
                                 'target': d.get('target'), 'acquirer': d.get('acquirer')}
                continue
            if did in manual:
                pick = {'url': manual[did], 'how': 'manual'}
            elif (d.get('links') or {}).get('fairness_opinion'):
                pick = {'url': d['links']['fairness_opinion'], 'how': 'links.fairness_opinion'}
            else:
                named = [u for u in urls_of(d) if PROXY_NAME.search(u.rsplit('/', 1)[-1])]
                if named:
                    pick = {'url': named[0], 'how': 'named url in links/sources'}
                else:
                    try:
                        cands = search(d)
                    except Exception as e:
                        failed.append((did, 'search: ' + str(e))); continue
                    tried = []
                    for c in cands:                  # first candidate that reads as THIS deal's merger proxy
                        if dry:
                            pick = c; break
                        try:
                            raw_c = get(c['url'])
                        except Exception as e:
                            tried.append(f"{c['form']} {c['accession']} download failed"); continue
                        txt_c = to_text(raw_c, not c['url'].lower().endswith('.txt'))
                        if looks_like_proxy(txt_c, d):
                            pick = c; pick['_raw'] = raw_c; break
                        tried.append(f"{c['form']} {c['filed']} {c['accession']} ({c['filer']}) - not this deal's proxy")
                    if pick:
                        pick['alternatives'] = tried + [f"{x['form']} {x['filed']} {x['accession']}" for x in cands if x is not pick][:6]
                    elif tried:
                        print(f'  {did}: rejected ' + '; '.join(tried))
            if not pick:
                missing.append(did)
                manifest[did] = {'status': 'not found', 'announced': d.get('announced'),
                                 'target': d.get('target'), 'acquirer': d.get('acquirer')}
                continue
            url = pick['url']
            if dry:
                print(f"  would fetch {did:38} {pick.get('form', ''):8} {pick['how']:26} {url[-70:]}")
                continue
            try:
                raw = pick.pop('_raw', None) or get(url)
            except Exception as e:
                failed.append((did, 'download: ' + str(e))); continue
            ext = 'txt' if url.lower().endswith('.txt') else 'htm'
            open(os.path.join(OUT, f'{did}.{ext}' if ext == 'htm' else f'{did}.raw.txt'), 'wb').write(raw)
            text = to_text(raw, ext == 'htm')
            open(txt_p, 'w', encoding='utf-8').write(text)
            flags = []
            if not re.search(r'background of the (merger|transaction|offer|acquisition|mergers|proposed)', text, re.I):
                flags.append('no "Background of the Merger" heading found')
            if not re.search(r'opinions? of [^\n]{0,80}(financial advisor|securities|capital|partners|& co|llc)', text, re.I):
                flags.append('no "Opinion of <advisor>" heading found')
            tw = re.sub(r'[^a-z]', ' ', (d.get('target') or '').lower()).split()
            tw = [w for w in tw if w not in ('the', 'inc', 'corp', 'co', 'company', 'energy', 'group', 'holdings')]
            if tw and tw[0] not in text[:40000].lower():
                flags.append(f'target name "{tw[0]}" not on the cover pages - may be the wrong filing')
            manifest[did] = {'status': 'ok', 'url': url, 'how': pick['how'], 'form': pick.get('form'),
                             'filed': pick.get('filed'), 'filer': pick.get('filer'),
                             'alternatives': pick.get('alternatives'), 'bytes': len(raw),
                             'text_chars': len(text), 'flags': flags,
                             'announced': d.get('announced'), 'target': d.get('target'), 'acquirer': d.get('acquirer')}
            fetched += 1
            print(f"  fetched {did:38} {len(raw)/1e6:5.1f} MB  {pick['how']}{'  <-- ' + '; '.join(flags) if flags else ''}")
    finally:
        if not dry:
            json.dump({'_note': 'written by fetch_merger_proxies.py', '_generated': time.strftime('%Y-%m-%d %H:%M'),
                       'deals': manifest}, open(man_p, 'w', encoding='utf-8'), indent=1)
    print(f'\n{fetched} fetched, {len(missing)} with no proxy found, {len(failed)} failed')
    if missing:
        print('  No proxy found (private target, asset deal, or pre-EDGAR). To supply one, add it to')
        print(r'  data\_proxies\_manual.json as {"deal_id": "https://www.sec.gov/...htm"}:')
        for m in missing:
            print('   ', m)
    for f in failed:
        print('  FAILED', *f)
    if failed:
        print('  Re-run: done deals are skipped, only failures retry.')


if __name__ == '__main__':
    main()
