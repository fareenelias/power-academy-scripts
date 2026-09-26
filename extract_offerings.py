# -*- coding: utf-8 -*-
"""extract_offerings.py - CapIQ 'Detailed Offerings' sheet -> data\\offerings.json

The public-offerings history the Funding Gap board (tracker S4.3) needs.

AVAILABILITY (superseded 2026-09-26): all 25 names ARE available. Fareen pulled standalone
Detailed Offerings reports for every name (2000-01-01 -> 2026-09-26, announcement-date basis)
into data\reports\Detailed Offerings\ - one '25Entities_Report_<date>*.xlsx' per ticker plus an
all-currency AQN re-pull 'SPGlobal_AlgonquinPowerAndUtilitiesCorp._DetailedOfferings_<dd-Mon-yyyy>.xlsx'.
The 2026-09-23 note that AQN/CMS/GWRS/XIFR/AEP were 'not available in CapIQ' was wrong - the tab
was missing from the company-workbook template only. Those standalone files carry no exchange
ticker in the filename, so the ticker is read from sheet row 3 ('NYSE:AEP (MI Key ...').
Newest workbook per ticker wins; the Detailed Offerings folder beats the June/July workbook tabs.

AQN MERGE: the all-currency file prints every row in C$ (CUR = reporting currency - a US$70M
note shows as C$90,423K), the USD-only file prints the same deals in US$. When one ticker has
several files of the same date they are unioned by Transaction ID; a row present in a USD file
keeps the exact US$ size (size_k_alt keeps the other print), rows only in the all-currency file
are converted at the annual-average FX below and flagged fx_converted.

  python extract_offerings.py                       # default globs: data\\reports + data\\reports\\_archive
  python extract_offerings.py "E:\\path\\*.xlsx" ...  # explicit globs
  python extract_offerings.py --dry                 # print, don't write

Roll-up rules (annual, US$ m, announce-date year):
  * only rows whose status starts with 'Priced' count; Pending / Terminated are kept as rows
    but excluded from totals (an ATM authorisation or a shelf is not an issuance)
  * a Pending Common Stock row with the same issuer + announce date + shares as a Priced row is
    CapIQ's announcement record of the same deal -> flagged duplicate_of, excluded
  * Shelf Registration sections never count
  * equity = Common Stock (+ Preferred / Units / Composite Units, flagged), debt = everything
    else that prices with a size; holdco vs subsidiary split = the '(Subsidiaries)' suffix
  * CAD rows convert to US$ at the annual-average CAD-per-USD rate of the announce year
    (FX_CAD_PER_USD; flag n_fx_converted); any other currency stays out of totals (n_non_usd)
"""
import io, os, re, sys, glob, json, collections, datetime

DATA_DIR = r'E:\PowerAcademy\data' if os.name == 'nt' else \
    os.path.join(os.path.expanduser('~'), 'mnt', 'PowerAcademy', 'data')
SHEET = 'Detailed Offerings'
EQUITY_SECTIONS = {'Common Stock', 'Preferred Security', 'Preferred Equity', 'Units',
                   'Debt-Equity Composite Units'}
EQUITY_FLAGGED = {'Preferred Security', 'Preferred Equity', 'Units', 'Debt-Equity Composite Units'}
NON_ISSUANCE = {'Shelf Registration'}
# CAD per 1 USD, annual averages. 2000-2016 FRED AEXCAUS (Fed H.10); 2017-2025 Bank of Canada FXAUSDCAD;
# 2026 = Fareen's AQN TEV pair C$15,562.8M / US$11,210.9M (2026-09-26 CapIQ) = 1.3882, a spot proxy.
FX_CAD_PER_USD = {2000: 1.4855, 2001: 1.5487, 2002: 1.5704, 2003: 1.4008, 2004: 1.3017, 2005: 1.2115,
    2006: 1.1340, 2007: 1.0734, 2008: 1.0660, 2009: 1.1412, 2010: 1.0298, 2011: 0.9887, 2012: 0.9995,
    2013: 1.0300, 2014: 1.1043, 2015: 1.2791, 2016: 1.3243, 2017: 1.2986, 2018: 1.2957, 2019: 1.3269,
    2020: 1.3415, 2021: 1.2535, 2022: 1.3013, 2023: 1.3497, 2024: 1.3698, 2025: 1.3978, 2026: 1.3882}
FX_SOURCE = ('CAD->USD at annual-average CAD per USD: FRED AEXCAUS 2000-2016, Bank of Canada FXAUSDCAD 2017-2025, '
             '2026 = 1.3882 implied by the AQN TEV pair in CapIQ (C$15,562.8M / US$11,210.9M).')
OFFER_DIR = 'Detailed Offerings'

try:
    import openpyxl
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'openpyxl', '--break-system-packages', '-q'])
    import openpyxl


def ticker_from_filename(f):
    b = re.sub(r'_Report_.*$', '', os.path.splitext(os.path.basename(f))[0])
    m = re.search(r'(NYSE|NASDAQGS|NASDAQGM|NASDAQCM|TSX)([A-Z]+)$', b)
    return m.group(2) if m else None


def ticker_from_sheet(ws):
    for i, r in enumerate(ws.iter_rows(min_row=1, max_row=6, values_only=True)):
        for v in r:
            m = re.match(r'\s*[A-Z]+:([A-Z.]+) \(MI Key', str(v or ''))
            if m: return m.group(1)
    return None


MON = {m: i + 1 for i, m in enumerate(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'])}


def workbook_date(f):
    b = os.path.basename(f)
    m = re.search(r'_Report_(\d{2})-(\d{2})-(\d{4})', b)
    if m: return f'{m.group(3)}-{m.group(1)}-{m.group(2)}'
    m = re.search(r'_(\d{2})-([A-Z][a-z]{2})-(\d{4})', b)
    if m and m.group(2) in MON: return f'{m.group(3)}-{MON[m.group(2)]:02d}-{m.group(1)}'
    return None


def rank(f):
    """(date, standalone-offerings-folder, ...) - newest wins, the standalone folder beats a workbook tab."""
    return (workbook_date(f) or '', os.path.basename(os.path.dirname(f)) == OFFER_DIR)


def merge_rows(parts):
    """Union same-date files of one ticker by Transaction ID; a USD print beats a converted/reporting-currency one."""
    by, order = {}, []
    for rows in parts:
        for r in rows:
            k = r.get('transaction_id') or id(r)
            if k not in by:
                by[k] = r; order.append(k); continue
            a = by[k]
            if r.get('currency') == 'USD' and a.get('currency') != 'USD':
                r['size_k_alt'] = [a.get('currency'), a.get('size_k')]; by[k] = r
            elif a.get('currency') != r.get('currency') and 'size_k_alt' not in a:
                a['size_k_alt'] = [r.get('currency'), r.get('size_k')]
    return [by[k] for k in order]


def usd_m(r):
    """(US$ m, converted?) or (None, None) for a currency with no table."""
    if r['currency'] in ('USD', None): return r['size_k'] / 1000.0, False
    if r['currency'] == 'CAD':
        fx = FX_CAD_PER_USD.get(int(r['announce_date'][:4]))
        if fx: return r['size_k'] / 1000.0 / fx, True
    return None, None


def num(v):
    if v is None: return None
    if isinstance(v, (int, float)): return float(v)
    s = str(v).strip().replace(',', '')
    if s.upper() in ('NA', 'N/A', '', '-', 'NM'): return None
    try: return float(s)
    except ValueError: return None


def dt(v):
    if v is None: return None
    if isinstance(v, datetime.datetime): return v.strftime('%Y-%m-%d')
    s = str(v).strip()
    return s[:10] if re.match(r'\d{4}-\d{2}-\d{2}', s) else (None if s.upper() in ('NA', 'NONE', '') else s)


def parse_sheet(ws):
    rows = list(ws.iter_rows(values_only=True))
    filters = collections.OrderedDict()
    for r in rows[3:14]:
        if r and r[0] and isinstance(r[0], str) and r[0].strip().endswith(':') and r[1] is not None:
            filters[r[0].strip().rstrip(':')] = str(r[1]).strip()
    out, section, header = [], None, None
    for r in rows[14:]:
        c0 = r[0]
        if c0 is None: continue
        s = str(c0).strip()
        if s == 'Transaction ID':
            header = [str(x).strip() if x is not None else None for x in r]; continue
        if not s.startswith('SPTRO'):
            if all(x is None for x in r[1:]) and not s.startswith('*'):
                section, header = s, None
            continue
        if header is None: continue
        rec = collections.OrderedDict()
        rec['transaction_id'] = s
        rec['section'] = section
        rec['funding_type'] = re.sub(r'\s*\(Subsidiaries\)\s*$', '', section or '')
        rec['is_subsidiary'] = bool(section and section.endswith('(Subsidiaries)'))
        cols = {h: r[i] for i, h in enumerate(header) if h}
        rec['issuer'] = str(cols.get('Issuer Name') or '').strip() or None
        rec['announce_date'] = dt(cols.get('Announce Date'))
        rec['offering_type'] = (str(cols['Offering Type']).strip() if cols.get('Offering Type') else None)
        st = str(cols.get('Transaction Status') or '').strip()
        m = re.match(r'^(Pending|Priced|Terminated/Withdrawn|Terminated|Withdrawn|Completed|Postponed)\s*(.*)$', st)
        rec['status'] = m.group(1) if m else (st or None)
        rec['status_date'] = (m.group(2).strip() or None) if m else None
        pp = cols.get('Private Placement?')
        rec['private_placement'] = (str(pp).strip().lower() == 'yes') if pp is not None else None
        cp = cols.get('Coupon (%)')
        rec['coupon'] = num(cp) if num(cp) is not None else (str(cp).strip() if cp is not None and str(cp).strip().upper() != 'NA' else None)
        rec['maturity_date'] = dt(cols.get('Maturity Date'))
        rec['ytm'] = num(cols.get('YTM'))
        cur = cols.get('CUR')
        rec['currency'] = {'$': 'USD', 'C$': 'CAD', '€': 'EUR', '£': 'GBP', '¥': 'JPY', 'A$': 'AUD'}.get(str(cur).strip(), str(cur).strip()) if cur is not None else None
        rec['offering_price'] = num(cols.get('Offering Price'))
        rec['shares_offered'] = num(cols.get('Total Shares Offered'))
        rec['size_k'] = num(cols.get('Offering Size (000)'))
        out.append(rec)
    return filters, out


def flag_duplicates(rows):
    """CapIQ lists a Pending 'Common Stock - Other' beside the Priced follow-on of the same deal."""
    priced = [r for r in rows if r['status'] == 'Priced' and r['funding_type'] == 'Common Stock']
    for r in rows:
        if r['status'] != 'Pending' or r['funding_type'] != 'Common Stock': continue
        for p in priced:
            if p['issuer'] == r['issuer'] and p['announce_date'] == r['announce_date'] and \
               r['shares_offered'] and p['shares_offered'] == r['shares_offered']:
                r['duplicate_of'] = p['transaction_id']; break


def annual(rows):
    A = collections.defaultdict(lambda: collections.OrderedDict([
        ('equity_usd_m', 0.0), ('equity_flagged_usd_m', 0.0), ('debt_usd_m', 0.0),
        ('debt_holdco_usd_m', 0.0), ('debt_sub_usd_m', 0.0), ('n_equity', 0), ('n_debt', 0), ('n_non_usd', 0), ('n_fx_converted', 0)]))
    for r in rows:
        if r['status'] != 'Priced' or r.get('duplicate_of'): continue
        if r['funding_type'] in NON_ISSUANCE: continue
        if not r['announce_date'] or not r['size_k']: continue
        y = r['announce_date'][:4]
        m, conv = usd_m(r)
        if m is None:
            A[y]['n_non_usd'] += 1; continue
        if conv:
            A[y]['n_fx_converted'] += 1; r['fx_converted'] = True; r['size_usd_m'] = round(m, 1)
        if r['funding_type'] in EQUITY_SECTIONS:
            A[y]['equity_usd_m'] += m; A[y]['n_equity'] += 1
            if r['funding_type'] in EQUITY_FLAGGED: A[y]['equity_flagged_usd_m'] += m
        else:
            A[y]['debt_usd_m'] += m; A[y]['n_debt'] += 1
            A[y]['debt_sub_usd_m' if r['is_subsidiary'] else 'debt_holdco_usd_m'] += m
    for y in A:
        for k in list(A[y]):
            if isinstance(A[y][k], float): A[y][k] = round(A[y][k], 1)
    return collections.OrderedDict(sorted(A.items()))


def cf_crosscheck(ticker, ann, capiq):
    """Filed cash-flow 'Long-term Debt Issued' / 'Issuance of Common Stock' beside the offerings
    roll-up, per year. The offerings sheet is CapIQ's DEAL-DATABASE coverage and runs 0-99% of the
    filed figure (NEE 2021-24: 0%; ES: ~90%), so the filed line is the denominator and the
    offerings rows are deal texture. Never present the roll-up as 'debt issued'."""
    co = (capiq or {}).get(ticker) or {}
    cf = co.get('cash_flow') or {}
    rows = cf.get('rows') or {}
    lt, eq = rows.get('Long-term Debt Issued'), rows.get('Issuance of Common Stock')
    for i, p in enumerate(cf.get('periods') or []):
        y = str(p)[:4]
        a = ann.setdefault(y, collections.OrderedDict([('equity_usd_m', 0.0), ('equity_flagged_usd_m', 0.0),
            ('debt_usd_m', 0.0), ('debt_holdco_usd_m', 0.0), ('debt_sub_usd_m', 0.0), ('n_equity', 0), ('n_debt', 0), ('n_non_usd', 0), ('n_fx_converted', 0)]))
        v = lt[i] if lt and i < len(lt) and lt[i] is not None else None
        e = eq[i] if eq and i < len(eq) and eq[i] is not None else None
        a['cf_lt_debt_issued_usd_m'] = round(v / 1000.0, 1) if v is not None else None
        a['cf_equity_issued_usd_m'] = round(e / 1000.0, 1) if e is not None else None
        a['offerings_debt_coverage_pct'] = round(100.0 * a['debt_usd_m'] / (v / 1000.0), 0) if v else None
    return ann


def main():
    dry = '--dry' in sys.argv
    capiq = None
    try:
        capiq = json.load(io.open(os.path.join(DATA_DIR, 'capiq_export.json'), encoding='utf-8')).get('companies')
    except Exception as e:
        print('  [warn] capiq_export.json not read - no cash-flow cross-check:', e)
    globs = [a for a in sys.argv[1:] if not a.startswith('--')] or \
            [os.path.join(DATA_DIR, 'reports', '*.xlsx'), os.path.join(DATA_DIR, 'reports', '_archive', '*.xlsx'),
             os.path.join(DATA_DIR, 'reports', OFFER_DIR, '*.xlsx')]
    files = sorted({f for g in globs for f in glob.glob(g) if not os.path.basename(f).startswith('~$')})
    cand = collections.defaultdict(list)
    for f in files:
        t = ticker_from_filename(f)
        if not t and os.path.basename(os.path.dirname(f)) != OFFER_DIR: continue
        try:
            wb = openpyxl.load_workbook(f, read_only=True)
        except Exception as e:
            print(f'  [skip] {os.path.basename(f)}: {e}'); continue
        if SHEET not in wb.sheetnames:
            wb.close(); continue
        t = t or ticker_from_sheet(wb[SHEET])
        wb.close()
        if t: cand[t].append(f)
    best = {}
    for t, fs in cand.items():
        top = max(rank(f) for f in fs)
        best[t] = (top[0], sorted(f for f in fs if rank(f) == top))
    out = collections.OrderedDict()
    out['_schema_version'] = '1.0'
    out['_source'] = f"CapIQ workbook sheet '{SHEET}' (10-year window, announcement-date basis, subsidiaries from time of acquisition)"
    out['_coverage_warning'] = ('The offerings sheet is CapIQ deal-database coverage, NOT the filed financing: annual[y].offerings_debt_coverage_pct '
                                'is the roll-up over the filed cash-flow Long-term Debt Issued (capiq_export.json cash_flow) and runs 0-99% by name/year. '
                                'Use cf_lt_debt_issued_usd_m as the debt denominator; use rows[] for holdco/opco split, tenor, coupon and equity-event texture.')
    out['_availability'] = ('All 25 names, 2000-01-01 -> 2026-09-26, from the standalone CapIQ Detailed Offerings reports in '
                            'data\\reports\\Detailed Offerings (pulled 2026-09-26). Supersedes the 2026-09-23 note that AQN, CMS, GWRS, '
                            'XIFR and AEP had none - the tab was only missing from the company-workbook template.')
    out['_fx'] = FX_SOURCE
    out['_note'] = ('Rows are as printed; annual{} is derived (see extract_offerings.py docstring): Priced only, US$ m (CAD converted, see _fx), '
                    'shelf registrations excluded, CapIQ announcement duplicates flagged duplicate_of. size_k is thousands of '
                    'issue currency. Funding-type filters differ by ticker pull - see filters{} per ticker before comparing names.')
    out['_generated'] = datetime.date.today().isoformat()
    out['tickers'] = collections.OrderedDict()
    for t in sorted(best):
        d, fs = best[t]
        parts, filters = [], {}
        for f in fs:
            wb = openpyxl.load_workbook(f, read_only=True)
            fl, rr = parse_sheet(wb[SHEET]); wb.close()
            parts.append(rr)
            for k, v in fl.items():
                if k in filters and filters[k] != v: filters[k] = f'{filters[k]} | {v}'
                else: filters[k] = v
        rows = merge_rows(parts)
        f = ' + '.join(os.path.basename(x) for x in fs)
        flag_duplicates(rows)
        ann = cf_crosscheck(t, annual(rows), capiq)
        ann = collections.OrderedDict(sorted(ann.items()))
        rec = collections.OrderedDict([('source_workbook', os.path.basename(f)), ('workbook_date', d),
                                       ('filters', filters), ('n_rows', len(rows)), ('annual', ann), ('rows', rows)])
        out['tickers'][t] = rec
        eq = sum(v['equity_usd_m'] for v in ann.values()); db = sum(v['debt_usd_m'] for v in ann.values())
        dup = sum(1 for r in rows if r.get('duplicate_of')); nonusd = sum(v['n_non_usd'] for v in ann.values()); fxc = sum(v.get('n_fx_converted', 0) for v in ann.values())
        cov = [a.get('offerings_debt_coverage_pct') for a in ann.values() if a.get('offerings_debt_coverage_pct') is not None]
        covs = f'{min(cov):3.0f}-{max(cov):3.0f}%' if cov else '  n/a  '
        print(f'{t:5} {d}  rows={len(rows):3}  priced equity ${eq:8,.0f}M  debt ${db:9,.0f}M  dups={dup} fx={fxc} non-usd={nonusd}  cov vs CF {covs}  '
              f"types={filters.get('Funding Type','?')[:50]}")
    print(f'\n{len(best)} tickers with the sheet')
    if dry: return
    p = os.path.join(DATA_DIR, 'offerings.json')
    io.open(p, 'w', encoding='utf-8').write(json.dumps(out, indent=1, ensure_ascii=False))
    json.load(io.open(p, encoding='utf-8'))
    print('wrote', p)


if __name__ == '__main__':
    main()
