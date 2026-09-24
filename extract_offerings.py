# -*- coding: utf-8 -*-
"""extract_offerings.py - CapIQ 'Detailed Offerings' sheet -> data\\offerings.json

The public-offerings history the Funding Gap board (tracker S4.3) needs. The sheet exists in
the June/July-2026 workbooks for 20 names and in NO later pull: Fareen (2026-09-23) exported
everything CapIQ offers on Detailed Offerings, so a name without the tab (AQN, CMS, GWRS, XIFR,
AEP) is simply NOT AVAILABLE in CapIQ - not a pull gap, never ask for it again. This reads
whatever workbooks carry the sheet (data\reports + _archive); newest per ticker wins, so the
June/July vintage stays authoritative until CapIQ ships the tab again.

  python extract_offerings.py                       # default globs: data\\reports + data\\reports\\_archive
  python extract_offerings.py "E:\\path\\*.xlsx" ...  # explicit globs
  python extract_offerings.py --dry                 # print, don't write

Roll-up rules (annual, USD only, announce-date year):
  * only rows whose status starts with 'Priced' count; Pending / Terminated are kept as rows
    but excluded from totals (an ATM authorisation or a shelf is not an issuance)
  * a Pending Common Stock row with the same issuer + announce date + shares as a Priced row is
    CapIQ's announcement record of the same deal -> flagged duplicate_of, excluded
  * Shelf Registration sections never count
  * equity = Common Stock (+ Preferred / Units / Composite Units, flagged), debt = everything
    else that prices with a size; holdco vs subsidiary split = the '(Subsidiaries)' suffix
  * non-USD rows are kept with their currency and excluded from USD totals (flag n_non_usd)
"""
import io, os, re, sys, glob, json, collections, datetime

DATA_DIR = r'E:\PowerAcademy\data' if os.name == 'nt' else \
    os.path.join(os.path.expanduser('~'), 'mnt', 'PowerAcademy', 'data')
SHEET = 'Detailed Offerings'
EQUITY_SECTIONS = {'Common Stock', 'Preferred Security', 'Preferred Equity', 'Units',
                   'Debt-Equity Composite Units'}
EQUITY_FLAGGED = {'Preferred Security', 'Preferred Equity', 'Units', 'Debt-Equity Composite Units'}
NON_ISSUANCE = {'Shelf Registration'}

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


def workbook_date(f):
    m = re.search(r'_Report_(\d{2})-(\d{2})-(\d{4})', os.path.basename(f))
    return f'{m.group(3)}-{m.group(1)}-{m.group(2)}' if m else None


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
        ('debt_holdco_usd_m', 0.0), ('debt_sub_usd_m', 0.0), ('n_equity', 0), ('n_debt', 0), ('n_non_usd', 0)]))
    for r in rows:
        if r['status'] != 'Priced' or r.get('duplicate_of'): continue
        if r['funding_type'] in NON_ISSUANCE: continue
        if not r['announce_date'] or not r['size_k']: continue
        y = r['announce_date'][:4]
        if r['currency'] not in ('USD', None):
            A[y]['n_non_usd'] += 1; continue
        m = r['size_k'] / 1000.0
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
            ('debt_usd_m', 0.0), ('debt_holdco_usd_m', 0.0), ('debt_sub_usd_m', 0.0), ('n_equity', 0), ('n_debt', 0), ('n_non_usd', 0)]))
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
            [os.path.join(DATA_DIR, 'reports', '*.xlsx'), os.path.join(DATA_DIR, 'reports', '_archive', '*.xlsx')]
    files = sorted({f for g in globs for f in glob.glob(g) if not os.path.basename(f).startswith('~$')})
    best = {}
    for f in files:
        t = ticker_from_filename(f)
        if not t: continue
        try:
            wb = openpyxl.load_workbook(f, read_only=True)
        except Exception as e:
            print(f'  [skip] {os.path.basename(f)}: {e}'); continue
        if SHEET not in wb.sheetnames:
            wb.close(); continue
        d = workbook_date(f) or ''
        if t not in best or d > best[t][0]:
            best[t] = (d, f)
        wb.close()
    out = collections.OrderedDict()
    out['_schema_version'] = '1.0'
    out['_source'] = f"CapIQ workbook sheet '{SHEET}' (10-year window, announcement-date basis, subsidiaries from time of acquisition)"
    out['_coverage_warning'] = ('The offerings sheet is CapIQ deal-database coverage, NOT the filed financing: annual[y].offerings_debt_coverage_pct '
                                'is the roll-up over the filed cash-flow Long-term Debt Issued (capiq_export.json cash_flow) and runs 0-99% by name/year. '
                                'Use cf_lt_debt_issued_usd_m as the debt denominator; use rows[] for holdco/opco split, tenor, coupon and equity-event texture.')
    out['_availability'] = ('20 of 25 names. AQN, CMS, GWRS, XIFR and AEP have no Detailed Offerings tab in CapIQ at all '
                            '(Fareen exported everything available, 2026-09-23) - absence is a CapIQ limit, not a missing pull.')
    out['_note'] = ('Rows are as printed; annual{} is derived (see extract_offerings.py docstring): Priced only, USD only, '
                    'shelf registrations excluded, CapIQ announcement duplicates flagged duplicate_of. size_k is thousands of '
                    'issue currency. Funding-type filters differ by ticker pull - see filters{} per ticker before comparing names.')
    out['_generated'] = datetime.date.today().isoformat()
    out['tickers'] = collections.OrderedDict()
    for t in sorted(best):
        d, f = best[t]
        wb = openpyxl.load_workbook(f, read_only=True)
        filters, rows = parse_sheet(wb[SHEET]); wb.close()
        flag_duplicates(rows)
        ann = cf_crosscheck(t, annual(rows), capiq)
        ann = collections.OrderedDict(sorted(ann.items()))
        rec = collections.OrderedDict([('source_workbook', os.path.basename(f)), ('workbook_date', d),
                                       ('filters', filters), ('n_rows', len(rows)), ('annual', ann), ('rows', rows)])
        out['tickers'][t] = rec
        eq = sum(v['equity_usd_m'] for v in ann.values()); db = sum(v['debt_usd_m'] for v in ann.values())
        dup = sum(1 for r in rows if r.get('duplicate_of')); nonusd = sum(v['n_non_usd'] for v in ann.values())
        cov = [a.get('offerings_debt_coverage_pct') for a in ann.values() if a.get('offerings_debt_coverage_pct') is not None]
        covs = f'{min(cov):3.0f}-{max(cov):3.0f}%' if cov else '  n/a  '
        print(f'{t:5} {d}  rows={len(rows):3}  priced equity ${eq:8,.0f}M  debt ${db:9,.0f}M  dups={dup} non-usd={nonusd}  cov vs CF {covs}  '
              f"types={filters.get('Funding Type','?')[:50]}")
    missing = sorted(set(ticker_from_filename(f) for f in files if ticker_from_filename(f)) - set(best))
    print(f'\n{len(best)} tickers with the sheet; none for: {", ".join(missing) or "-"}')
    if dry: return
    p = os.path.join(DATA_DIR, 'offerings.json')
    io.open(p, 'w', encoding='utf-8').write(json.dumps(out, indent=1, ensure_ascii=False))
    json.load(io.open(p, encoding='utf-8'))
    print('wrote', p)


if __name__ == '__main__':
    main()
