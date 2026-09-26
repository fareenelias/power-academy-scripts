r"""build_eia861_trends.py - reliability (SAIDI/SAIFI) and retail load trends per coverage name.

Source: EIA Form 861 annual files already in data\eia_cache\ (eia861.zip = 2024,
f8612015.zip, f8612018.zip - any zip holding Reliability_YYYY.xlsx / Sales_Ult_Cust_YYYY.xlsx
is picked up, so dropping another year's zip in the folder extends the series).
Utility attribution: data\eia_utility_id_map.json (verified EIA ids per ticker - the same
map the Map tab and fleet use).

Output data\eia861_trends.json:
  tickers[T].reliability[year] = {saidi_all, saifi_all, saidi_ex_med, saifi_ex_med,
      med_minutes (= SAIDI all - SAIDI ex-MED: the major-event / storm share), customers,
      standard: 'IEEE' | 'Other'}   customer-weighted across the ticker's utilities
  tickers[T].by_utility[] = same per EIA utility (state-level rows combined, customer-weighted)
  tickers[T].load[year] = {delivered_mwh, customers, res_mwh, com_mwh, ind_mwh}
      delivered = Bundled + Delivery-only service rows (all load on the wires, incl. choice customers)
  tickers[T].retail_energy[year] = Energy-only rows (competitive retail supply - VST/TXU etc.)
  tickers[T].load_cagr = {period: pct}

    python scripts\build_eia861_trends.py              (Windows default paths)
    python scripts/build_eia861_trends.py <data_dir>
"""
import sys, os, re, io, json, zipfile, datetime, collections
import openpyxl

DATA = sys.argv[1] if len(sys.argv) > 1 else r'E:\PowerAcademy\data'
CACHE = os.path.join(DATA, 'eia_cache')


# Known perimeter breaks in the EIA series (the map holds CURRENT utility ids, so acquired
# utilities that still report are included in every year - pro forma. A utility that stopped
# reporting because it merged INTO a coverage opco is not.)
STRUCTURAL_NOTES = {
    'NEE': 'Gulf Power merged into FPL on 2021-01-01 and stopped filing separately: 2024 load/customers include the former Gulf territory (~0.47M customers, ~11 TWh), 2015/2018 do not - the FPL CAGR overstates organic growth by roughly 1pp/yr.',
    'PPL': 'Narragansett (RI) was acquired May 2022 but is included in every year here (pro forma current perimeter).',
    'D': 'SCE&G/DESC (acquired Jan 2019) included in every year (pro forma current perimeter).',
    'EVRG': 'Pre-2018 rows are the legacy KCP&L/GMO/Westar/KG&E utilities (renamed Evergy entities) - same perimeter, different names.',
}


def num(x):
    if x in (None, '', '.', ' '):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def sheets(zpath, stem, year):
    with zipfile.ZipFile(zpath) as z:
        names = [n for n in z.namelist() if re.search(rf'(^|/){stem}_{year}\.xlsx$', n)]
        if not names:
            return None
        return openpyxl.load_workbook(io.BytesIO(z.read(names[0])), read_only=True, data_only=True)


def find_years():
    out = {}
    for fn in os.listdir(CACHE):
        if not fn.lower().endswith('.zip'):
            continue
        try:
            with zipfile.ZipFile(os.path.join(CACHE, fn)) as z:
                for n in z.namelist():
                    m = re.search(r'Reliability_(\d{4})\.xlsx$', n)
                    if m:
                        out[int(m.group(1))] = os.path.join(CACHE, fn)
        except zipfile.BadZipFile:
            pass
    return dict(sorted(out.items()))


def data_rows(ws):
    for r in ws.iter_rows(values_only=True):
        if r and str(r[0]).strip().isdigit():
            yield r


def main():
    idmap = json.load(open(os.path.join(DATA, 'eia_utility_id_map.json'), encoding='utf-8'))
    uid2t = {}
    for t, v in idmap.items():
        if t.startswith('_') or not isinstance(v, dict):
            continue
        for u in v.get('utility_ids') or []:
            uid2t.setdefault(str(u), t)
    years = find_years()
    print('years:', list(years))
    rel = collections.defaultdict(lambda: collections.defaultdict(list))     # t -> year -> rows
    ures = collections.defaultdict(lambda: collections.defaultdict(list))    # (t, uid, name) -> year -> rows
    load = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.Counter()))
    retail = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.Counter()))
    for y, zp in years.items():
        wb = sheets(zp, 'Reliability', y)
        ws = wb[[s for s in wb.sheetnames if s.startswith('Reliability_States')][0]]
        for r in data_rows(ws):
            uid = str(int(float(r[1])))
            t = uid2t.get(uid)
            if not t:
                continue
            ieee = [num(v) for v in r[5:11]] + [num(r[14])]
            oth = [num(v) for v in r[17:23]] + [num(r[23])]
            use, std = (ieee, 'IEEE') if ieee[0] is not None and ieee[6] else ((oth, 'Other') if oth[0] is not None and oth[6] else (None, None))
            if not use:
                continue
            row = {'saidi_all': use[0], 'saifi_all': use[1], 'saidi_ex_med': use[3], 'saifi_ex_med': use[4],
                   'customers': use[6], 'standard': std, 'state': r[3]}
            rel[t][y].append(row)
            ures[(t, uid, str(r[2]).strip())][y].append(row)
        wb = sheets(zp, 'Sales_Ult_Cust', y)
        ws = wb[[s for s in wb.sheetnames if s.startswith('States')][0]]
        for r in data_rows(ws):
            uid = str(int(float(r[1])))
            t = uid2t.get(uid)
            if not t:
                continue
            svc = str(r[4] or '').strip().lower()
            tgt = retail if svc.startswith('energy') else load
            c = tgt[t][y]
            c['res_mwh'] += num(r[10]) or 0; c['com_mwh'] += num(r[13]) or 0; c['ind_mwh'] += num(r[16]) or 0
            c['delivered_mwh'] += num(r[22]) or 0
            if tgt is load and svc.startswith(('bundled', 'delivery')):
                c['customers'] += num(r[23]) or 0          # delivery-only customers are still on the wires
            elif tgt is retail:
                c['customers'] += num(r[23]) or 0

    def wavg(rows):
        w = sum(r['customers'] for r in rows)
        o = {'customers': int(w), 'standard': 'IEEE' if all(r['standard'] == 'IEEE' for r in rows) else 'mixed/Other'}
        for k in ('saidi_all', 'saifi_all', 'saidi_ex_med', 'saifi_ex_med'):
            vs = [(r[k], r['customers']) for r in rows if r[k] is not None]
            ww = sum(c for _, c in vs)
            o[k] = round(sum(v * c for v, c in vs) / ww, 3 if k.startswith('saifi') else 1) if ww else None
        o['med_minutes'] = round(o['saidi_all'] - o['saidi_ex_med'], 1) if o['saidi_all'] is not None and o['saidi_ex_med'] is not None else None
        return o

    out = {'_schema_version': '1.0', '_generated': datetime.date.today().isoformat(),
           '_source': 'EIA Form 861 (Reliability_YYYY, Sales_Ult_Cust_YYYY) from data\\eia_cache; ids from eia_utility_id_map.json',
           'years': list(years),
           '_caveats': [
               'SAIDI/SAIFI are customer-weighted across the ticker\'s reporting utilities and states; IEEE 1366 where reported, the utility\'s own standard otherwise (flagged standard=mixed/Other).',
               'med_minutes = SAIDI with major event days minus SAIDI without: the storm/major-event share of outage minutes - a proxy for storm exposure and restoration, not a recovery-cost measure.',
               'delivered_mwh = all load on the utility\'s wires (bundled + delivery-only choice customers); competitive retail energy sales (Energy-only rows) are kept apart in retail_energy.',
               'EIA 861 years on disk are sparse (2015, 2018, 2024) - CAGRs are point-to-point, not fitted. Add intermediate years by dropping the EIA zips into data\\eia_cache and re-running.'],
           'tickers': {}}
    for t in sorted(set(rel) | set(load) | set(retail)):
        d = {'note': STRUCTURAL_NOTES.get(t),
             'reliability': {y: wavg(rows) for y, rows in sorted(rel[t].items())},
             'by_utility': [], 'load': {}, 'retail_energy': {}, 'load_cagr': {}}
        for (tt, uid, nm), yrs in sorted(ures.items()):
            if tt == t:
                d['by_utility'].append({'eia_id': uid, 'name': nm, 'years': {y: wavg(rows) for y, rows in sorted(yrs.items())}})
        for y, c in sorted(load[t].items()):
            d['load'][y] = {k: round(v) for k, v in c.items()}
        for y, c in sorted(retail[t].items()):
            d['retail_energy'][y] = {k: round(v) for k, v in c.items()}
        ys = sorted(d['load'])
        for a in ys[:-1]:
            b = ys[-1]
            va, vb = d['load'][a]['delivered_mwh'], d['load'][b]['delivered_mwh']
            if va and vb:
                d['load_cagr'][f'{a}-{b}'] = round(((vb / va) ** (1 / (b - a)) - 1) * 100, 2)
        out['tickers'][t] = d
        lr = d['reliability'].get(max(d['reliability'])) if d['reliability'] else None
        print(f"  {t:5} rel years {list(d['reliability'])}  latest SAIDI {lr and lr['saidi_all']} (exMED {lr and lr['saidi_ex_med']})  load {list(d['load'])}  CAGR {d['load_cagr']}")
    json.dump(out, open(os.path.join(DATA, 'eia861_trends.json'), 'w', encoding='utf-8'), indent=1)
    print('wrote eia861_trends.json:', len(out['tickers']), 'tickers')


if __name__ == '__main__':
    main()
