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
import json, os, sys, time, gzip, urllib.request, urllib.error

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP = os.path.join(BASE, 'data', 'opco_cik_map.json')
OUT = os.path.join(BASE, 'data', '_sec_xbrl')
# SEC blocks requests whose User-Agent has no real contact (403 on the first call, 2026-09-25).
# Set it once per PowerShell session:  $env:SEC_UA = "Your Name you@example.com"
UA = os.environ.get('SEC_UA', '').strip()
SLEEP = 0.25
COVERAGE = ['AEE', 'AEP', 'AQN', 'AWK', 'AWR', 'CMS', 'CWT', 'D', 'EIX', 'ES', 'ETR', 'EVRG',
            'GWRS', 'HE', 'HTO', 'MSEX', 'NEE', 'PCG', 'POR', 'PPL', 'TLN', 'VST', 'WTRG',
            'XIFR', 'YORW']


def get(url, tries=5):
    # 503/429 = SEC throttling (hit after ~25 large downloads on 2026-09-25): back off and retry
    host = url.split('/')[2]
    for i in range(tries):
        time.sleep(SLEEP if i == 0 else min(60, 5 * 2 ** (i - 1)))
        req = urllib.request.Request(url, headers={
            'User-Agent': UA, 'Accept-Encoding': 'gzip, deflate', 'Host': host,
            'Accept': 'application/json,application/xml,text/html,*/*;q=0.8'})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
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


def latest_10k(cik):
    """All 10-K filings from the registrant's most recent filing season (within 150 days of
    the newest). An opco can co-register on a securitization vehicle's small 10-K filed
    AFTER its own - e.g. VEPCO on Virginia Power Fuel Securitization LLC (2026-03-26) and
    SCE on its recovery-funding LLC (2026-03-24) - so 'newest 10-K' is the wrong pick;
    main() takes the candidate with the largest XBRL instance instead."""
    import datetime as dt
    d = json.loads(get('https://data.sec.gov/submissions/CIK%010d.json' % cik))
    rec = d.get('filings', {}).get('recent', {})
    ks = [{'accession': a, 'primary': p, 'filed': f, 'edgar_name': d.get('name')}
          for form, a, p, f in zip(rec.get('form', []), rec.get('accessionNumber', []),
                                   rec.get('primaryDocument', []), rec.get('filingDate', []))
          if form == '10-K']
    if not ks:
        return []
    newest = dt.date.fromisoformat(ks[0]['filed'])
    return [k for k in ks if (newest - dt.date.fromisoformat(k['filed'])).days <= 150][:4]


def instance_name(cik, acc):
    idx = json.loads(get('https://www.sec.gov/Archives/edgar/data/%d/%s/index.json'
                         % (cik, acc.replace('-', ''))))
    items = idx.get('directory', {}).get('item', [])
    return _pick(items)


def _pick(items):
    def size(i):
        try: return int(i.get('size') or 0)
        except ValueError: return 0
    # inline-XBRL filings publish an extracted instance (*_htm.xml); take the LARGEST
    # candidate - VEPCO's 2026 accession returned a ~0 MB file when the first match was taken
    cands = [i for i in items if i['name'].endswith('_htm.xml')]
    if not cands:                         # older plain-XBRL filings
        cands = [i for i in items if i['name'].endswith('.xml')
                 and not i['name'].startswith(('Financial_Report', 'FilingSummary', 'MetaLinks'))
                 and not i['name'].endswith(('_cal.xml', '_def.xml', '_lab.xml', '_pre.xml'))]
    if not cands:
        return None
    best = max(cands, key=size)
    return best['name'], size(best)


def main():
    force, dry = '--force' in sys.argv, '--dry-run' in sys.argv
    if '@' not in UA:
        sys.exit('SEC requires a User-Agent with a real name and email. In PowerShell run:\n'
                 '  $env:SEC_UA = "Your Name you@example.com"\n'
                 'then re-run this script (VPN off).')
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

    manifest, seen, failed = {}, {}, []
    fetched = 0
    try:
        for t, role, name, cik in jobs:
            try:
                cands = latest_10k(cik)
            except Exception as e:
                failed.append((t, name, str(e))); continue
            rec = {'role': role, 'name': name, 'cik': cik}
            if not cands:
                rec['note'] = 'no 10-K in recent filings'
                manifest.setdefault(t, []).append(rec); continue
            k, best = None, (None, -1)
            for c in cands:                       # pick the filing with the LARGEST instance
                if c['accession'] in seen:
                    got = seen[c['accession']]
                else:
                    try:
                        got = instance_name(cik, c['accession'])
                    except Exception as e:
                        failed.append((t, name, 'index: ' + str(e))); got = None
                    seen[c['accession']] = got
                if got and got[1] > best[1]:
                    k, best = c, got
            if not k:
                rec['note'] = 'no XBRL instance found'
                manifest.setdefault(t, []).append(rec); continue
            rec.update(k)
            acc = k['accession']
            if len(cands) > 1:
                rec['other_10k_same_season'] = [c['accession'] for c in cands if c['accession'] != acc]
            inst = seen[acc][0]
            path = os.path.join(OUT, f'{acc}_{inst}')
            if dry:
                print(f'  would fetch {t:5} {name[:40]:40} {acc} {inst}')
            elif force or not os.path.exists(path) or os.path.getsize(path) < 100_000:
                try:
                    data = get('https://www.sec.gov/Archives/edgar/data/%d/%s/%s'
                               % (cik, acc.replace('-', ''), inst))
                except Exception as e:
                    failed.append((t, name, 'download: ' + str(e))); continue
                open(path, 'wb').write(data)
                fetched += 1
                small = '  <-- SMALL, check this filing' if len(data) < 100_000 else ''
                print(f'  fetched {t:5} {name[:40]:40} {acc} {len(data)/1e6:.1f} MB{small}')
            rec['instance'] = inst
            rec['combined_with_parent'] = None   # resolved at parse time (dei:EntityCentralIndexKey members)
            manifest.setdefault(t, []).append(rec)
    finally:                                     # manifest is written even if the run dies midway
        if not dry:
            json.dump({'_note': 'written by fetch_sec_xbrl.py; one instance per accession; parse in Cowork',
                       '_generated': time.strftime('%Y-%m-%d %H:%M'), 'tickers': manifest},
                      open(os.path.join(OUT, '_manifest.json'), 'w', encoding='utf-8'), indent=1)
    n_acc = len({r.get('accession') for rs in manifest.values() for r in rs if r.get('accession')})
    print(f'\n{len(jobs)} registrants, {n_acc} unique 10-K accessions used, {fetched} fetched, '
          f'{len(failed)} failed')
    for f in failed:
        print('  FAILED', *f)
    if failed:
        print('  Re-run the script: it skips files already on disk and retries only what failed.')


if __name__ == '__main__':
    main()
