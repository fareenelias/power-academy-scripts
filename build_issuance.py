r"""build_issuance.py - issuance history + new-issue pricing vs peers, off data\offerings.json.

offerings.json is the CapIQ Detailed Offerings sheet as printed (extract_offerings.py). This
builder adds, per priced USD debt row, a PEER PRICING read:

  tenor_yrs     = maturity - announce date
  bucket        = short (<=7y) | intermediate (7-15y) | long (>15y)
  peer_median   = median yield (YTM, else coupon) of every OTHER coverage-universe priced USD
                  debt row in the same bucket, same issuer tier (holdco vs opco/subsidiary),
                  announced within +/-120 days
  vs_peers_bps  = (yield - peer_median) * 100, only when >= 3 peers

Rate level cancels out because comps are contemporaneous; the residual mixes credit, tenor
within bucket, security (FMB vs unsecured) and deal size - it is a screen, not a spread.
Treasury curves are not used (no treasury series is on disk).

Also carries equity rows (follow-ons, ATM programmes, private placements, forwards) and
hybrids (junior subordinated / preferred) as their own lists.

    python scripts\build_issuance.py          (Windows default path)
    python scripts/build_issuance.py <data_dir>
"""
import sys, os, json, datetime, statistics

DATA = sys.argv[1] if len(sys.argv) > 1 else r'E:\PowerAcademy\data'
WINDOW_D = 120
DEBT = {'Senior Debt', 'Bond or Note', 'Term Loans', 'Senior Subordinated Debt'}
HYBRID = {'Junior Subordinated Debt', 'Preferred Security', 'Preferred Equity', 'Debt-Equity Composite Units', 'Units'}
EQUITY = {'Common Stock'}


def d(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def bucket(y):
    return None if y is None else ('short (<=7y)' if y <= 7 else ('intermediate (7-15y)' if y <= 15 else 'long (>15y)'))


def main():
    src = json.load(open(os.path.join(DATA, 'offerings.json'), encoding='utf-8'))
    debt_all = []
    per = {}
    for t, v in src['tickers'].items():
        rows = v.get('rows') or []
        dr, hy, eq = [], [], []
        for r in rows:
            if r.get('status') != 'Priced' or (r.get('currency') or 'USD') != 'USD' or r.get('duplicate_of'):
                continue
            ad, md = d(r.get('announce_date')), d(r.get('maturity_date'))
            base = {'id': r.get('transaction_id'), 'date': r.get('announce_date'), 'issuer': r.get('issuer'),
                    'holdco': not r.get('is_subsidiary'), 'type': r.get('offering_type') or r.get('funding_type'),
                    'size_m': round(r['size_k'] / 1000, 1) if r.get('size_k') else None}
            ft = r.get('funding_type')
            if ft in DEBT:
                ten = round((md - ad).days / 365.25, 1) if ad and md else None
                cpn = r.get('coupon')
                floating = isinstance(cpn, str)            # CapIQ prints 'Variable' for floaters
                y = r.get('ytm') if isinstance(r.get('ytm'), (int, float)) else (None if floating else cpn)
                row = dict(base, coupon=cpn, floating=floating, ytm=r.get('ytm'), yld=y, maturity=r.get('maturity_date'),
                           tenor_yrs=ten, bucket=bucket(ten), funding_type=ft)
                dr.append(row)
                if y is not None and ad and row['bucket']:
                    debt_all.append((t, ad, row))
            elif ft in HYBRID:
                hy.append(dict(base, coupon=r.get('coupon'), maturity=r.get('maturity_date'), funding_type=ft))
            elif ft in EQUITY:
                eq.append(dict(base, price=r.get('offering_price'), shares_m=round(r['shares_offered'] / 1e6, 2) if r.get('shares_offered') else None,
                               private=bool(r.get('private_placement'))))
        per[t] = {'debt': dr, 'hybrid': hy, 'equity': eq, 'annual': v.get('annual'), 'filters': v.get('filters'),
                  'workbook_date': v.get('workbook_date')}
    # peer pricing
    n_scored = 0
    for t, ad, row in debt_all:
        peers = [p['yld'] for tt, pd, p in debt_all if tt != t and p['bucket'] == row['bucket'] and p['holdco'] == row['holdco']
                 and abs((pd - ad).days) <= WINDOW_D]
        row['peer_n'] = len(peers)
        if len(peers) >= 3:
            med = statistics.median(peers)
            row['peer_median'] = round(med, 3)
            row['vs_peers_bps'] = round((row['yld'] - med) * 100)
            n_scored += 1
    for t, v in per.items():
        sc = [r['vs_peers_bps'] for r in v['debt'] if r.get('vs_peers_bps') is not None]
        v['summary'] = {'n_debt': len(v['debt']), 'n_scored': len(sc),
                        'median_vs_peers_bps': round(statistics.median(sc)) if sc else None,
                        'n_equity': len(v['equity']), 'n_atm': sum('At-the-Market' in (r['type'] or '') for r in v['equity']),
                        'n_hybrid': len(v['hybrid'])}
        for k in ('debt', 'hybrid', 'equity'):
            v[k].sort(key=lambda r: r['date'] or '', reverse=True)
    out = {'_schema_version': '1.0', '_generated': datetime.date.today().isoformat(),
           '_source': 'data\\offerings.json (CapIQ Detailed Offerings, as printed) via scripts\\build_issuance.py',
           '_method': __doc__.split('\n\n')[1].strip(),
           '_availability': src.get('_availability'),
           '_coverage_warning': src.get('_coverage_warning'),
           'tickers': per}
    json.dump(out, open(os.path.join(DATA, 'issuance.json'), 'w', encoding='utf-8'), indent=1)
    print(f'wrote issuance.json: {len(per)} tickers, {len(debt_all)} priced debt rows with a yield, {n_scored} scored vs peers')
    for t, v in sorted(per.items()):
        print(f"  {t:5} {v['summary']}")


if __name__ == '__main__':
    main()
