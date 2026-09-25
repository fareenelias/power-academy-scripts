# -*- coding: utf-8 -*-
r"""fetch_sec_xbrl.py - download the latest 10-K XBRL instance for every SEC-registrant opco
in data\opco_cik_map.json (plus each coverage parent), for SEC-by-subsidiary phase 2.

FETCH ONLY. Parsing (facts by dei:LegalEntityAxis member -> per-registrant revenue, NI,
equity, rate base proxies; ASC 280 segments; segment ROE with a stated capital allocation)
is done in a Cowork session from the files this writes. Why a split: sec.gov is blocked by
org network policy from the cloud container AND the Cowork VM (verified 2026-09-23/24/25);
only this desktop reaches it, and only with the VPN OFF.

Why the instance document and not companyfacts: in a combined 10-K a co-registrant's facts
are dimensioned by LegalEntityAxis and companyfacts serves only undimensioned facts, so
every opco comes back as its parent (probed 2026-09-23, FPL CIK 37634 -> NEXTERA ENERGY).

  python fetch_sec_xbrl.py              # fetch anything missing (incremental)
  python fetch_sec_xbrl.py --force      # re-fetch everything
  python fetch_sec_xbrl.py --dry-run    # list what would be fetched

Writes  data\_sec_xbrl\<acc>_<primary>_htm.xml   (one per accession; combined filings shared)
        data\_sec_xbrl\_manifest.json            (ticker -> registrants -> accession / file)
SEC etiquette: <10 req/sec, a real User-Agent (set SEC_UA="Name email"), Accept-Encoding.
"""
import json, os, sys, time, gzip, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP = os.path.join(BASE, 'data', 'opco_cik_map.json')
OUT = os.path.join(BASE, 'data', '_sec_xbrl')
UA = os.environ.get('SEC_UA', 'PowerAcademy/1.0 power-academy@internal')
SLEEP = 0.25
COVERAGE = ['AEE', 'AEP', 'AQN', 'AWK', 'AWR', 'CMS', 'CWT', 'D', 'EIX', 'ES', 'ETR', 'EVRG',
            'GWRS', 'HE', 'HTO', 'MSEX', 'NEE', 'PCG', 'POR', 'PPL', 'TLN', 'VST', 'WTRG',
            'XIFR', 'YORW']


def get(url):
    time.sleep(SLEEP)
    host = url.split('/')[2]
    req = urllib.request.Request(url, headers={
        'User-Agent': UA, 'Accept-Encoding': 'gzip, deflate', 'Host': host,
        'Accept': 'application/json,application/xml,text/html,*/*;q=0.8'})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
        if r.headers.get('Content-Encoding') == 'gzip':
            data = gzip.decompress(data)
        return data


def latest_10k(cik):
    d = json.loads(get('https://data.sec.gov/submissions/CIK%010d.json' % cik))
    rec = d.get('filings', {}).get('recent', {})
    for form, acc, doc, dt in zip(rec.get('form', []), rec.get('accessionNumber', []),
                                  rec.get('primaryDocument', []), rec.get('filingDate', [])):
        if form == '10-K':
            return {'accession': acc, 'primary': doc, 'filed': dt, 'edgar_name': d.get('name')}
    return None


def instance_name(cik, acc):
    idx = json.loads(get('https://www.sec.gov/Archives/edgar/data/%d/%s/index.json'
                         % (cik, acc.replace('-', ''))))
    names = [i['name'] for i in idx.get('directory', {}).get('item', [])]
    for n in names:                       # inline-XBRL filings publish an extracted instance
        if n.endswith('_htm.xml'):
            return n
    for n in names:                       # older plain-XBRL filings
        if n.endswith('.xml') and not n.startswith(('Financial_Report', 'FilingSummary')) \
           and not n.endswith(('_cal.xml', '_def.xml', '_lab.xml', '_pre.xml')):
            return n
    return None


def main():
    force, dry = '--force' in sys.argv, '--dry-run' in sys.argv
    os.makedirs(OUT, exist_ok=True)
    cmap = json.load(open(MAP, encoding='utf-8'))['opcos_by_ticker']
    tick = json.loads(get('https://www.sec.gov/files/company_tickers.json'))
    parent_cik = {v['ticker']: int(v['cik_str']) for v in tick.values()}

    jobs = []                                  # (ticker, role, name, cik)
    for t in COVERAGE:
        if t in parent_cik:
            jobs.append((t, 'parent', t, parent_cik[t]))
        else:
            print(f'  {t}: parent CIK not in company_tickers.json (foreign filer / 40-F?)')
        for o in cmap.get(t, []):
            if o.get('cik') and o.get('status') == 'verified' and o.get('files_own_periodic'):
                jobs.append((t, 'opco', o.get('ferc_name') or o.get('edgar_name'), int(o['cik'])))

    manifest, seen, fetched, failed = {}, {}, 0, []
    for t, role, name, cik in jobs:
        try:
            k = latest_10k(cik)
        except Exception as e:
            failed.append((t, name, str(e))); continue
        rec = {'role': role, 'name': name, 'cik': cik}
        if not k:
            rec['note'] = 'no 10-K in recent filings'
            manifest.setdefault(t, []).append(rec); continue
        rec.update(k)
        acc = k['accession']
        if acc not in seen:
            try:
                inst = instance_name(cik, acc)
            except Exception as e:
                failed.append((t, name, 'index: ' + str(e))); continue
            seen[acc] = inst
            if inst:
                path = os.path.join(OUT, f'{acc}_{inst}')
                if dry:
                    print(f'  would fetch {t:5} {name[:40]:40} {acc} {inst}')
                elif force or not os.path.exists(path):
                    data = get('https://www.sec.gov/Archives/edgar/data/%d/%s/%s'
                               % (cik, acc.replace('-', ''), inst))
                    open(path, 'wb').write(data)
                    fetched += 1
                    print(f'  fetched {t:5} {name[:40]:40} {acc} {len(data)/1e6:.1f} MB')
        rec['instance'] = seen[acc]
        rec['combined_with_parent'] = None     # resolved at parse time (dei:EntityCentralIndexKey members)
        manifest.setdefault(t, []).append(rec)

    if not dry:
        json.dump({'_note': 'written by fetch_sec_xbrl.py; one instance per accession; parse in Cowork',
                   '_generated': time.strftime('%Y-%m-%d %H:%M'), 'tickers': manifest},
                  open(os.path.join(OUT, '_manifest.json'), 'w', encoding='utf-8'), indent=1)
    print(f'\n{len(jobs)} registrants, {len(seen)} unique 10-K accessions, {fetched} fetched, '
          f'{len(failed)} failed')
    for f in failed:
        print('  FAILED', *f)
    if failed and any('403' in f[2] for f in failed):
        print('  403s: set SEC_UA="Your Name your@email" and retry (SEC requires a real UA).')


if __name__ == '__main__':
    main()
