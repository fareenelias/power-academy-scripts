r"""build_interconnection.py - interconnection-queue exposure per coverage name (roadmap I.C / I.F / II.B).

INPUT (one download, desktop - lbl.gov is not reachable from the cloud):
  Berkeley Lab 'Queued Up' project-level data (https://emp.lbl.gov/queues -> "data file").
  Save the .xlsx anywhere under data\eia_cache\ or data\Scans\NEW\ with 'queue' in the file name.

The workbook's project sheet is found by its header row (a row holding q_id + q_status or
equivalents); column names are matched from ALIASES so a renamed column in a new vintage does
not silently drop data - a missing required column stops the run and names it.

Attribution: the interconnecting utility / transmission owner column is matched to coverage
tickers with UTILITY_ALIASES (opco names, current and legacy). Projects whose utility is not a
coverage opco are kept in the ISO totals only.

OUTPUT data\interconnection.json:
  iso[region]     active MW by type, count, median queue age, withdrawn / operational counts
  tickers[T]      active projects & MW in the name's footprint by type and status (IA signed vs not),
                  top states, oldest request, largest projects (id, type, MW, state, q_date)

    python scripts\build_interconnection.py [data_dir] [path_to_xlsx]
"""
import sys, os, re, glob, json, datetime, statistics, collections
import openpyxl

DATA = sys.argv[1] if len(sys.argv) > 1 else r'E:\PowerAcademy\data'
ALIASES = {
    'q_id': ['q_id', 'queue_id', 'queue id', 'project id'],
    'q_status': ['q_status', 'status', 'queue_status'],
    'q_date': ['q_date', 'queue_date', 'queue date', 'request date'],
    'ia_status': ['ia_status_clean', 'ia_status', 'ia status'],
    'on_date': ['on_date', 'cod', 'actual cod'],
    'state': ['state'],
    'county': ['county'],
    'region': ['region', 'iso', 'rto', 'entity_region'],
    'entity': ['entity', 'balancing_authority', 'ba'],
    'utility': ['utility', 'transmission_owner', 'transmission owner', 'poi_utility', 'interconnecting utility'],
    'poi': ['poi_name', 'poi', 'point of interconnection'],
    'type': ['type_clean', 'type1', 'resource_type', 'fuel'],
    'mw': ['mw1', 'capacity_mw', 'mw', 'summer capacity (mw)'],
    'mw2': ['mw2'], 'type2': ['type2'],
}
REQUIRED = ['q_status', 'q_date', 'type', 'mw']
UTILITY_ALIASES = [
    ('D', r'dominion|virginia electric|\bvepco\b|south carolina electric|\bdesc\b|sce&g'),
    ('AEP', r'\baep\b|american electric power|appalachian power|indiana michigan|ohio power|public service co(?:mpany)? of oklahoma|\bpso\b|southwestern electric|swepco|kentucky power|wheeling power'),
    ('AEE', r'ameren|union electric'),
    ('ETR', r'entergy'),
    ('CMS', r'consumers energy|\bcms\b'),
    ('PPL', r'\bppl\b|louisville gas|\blg&e\b|kentucky utilities|narragansett|rhode island energy'),
    ('EVRG', r'evergy|westar|kansas city power|kcp&l|kansas gas'),
    ('ES', r'eversource|connecticut light|\bcl&p\b|nstar|public service co(?:mpany)? of new hampshire|\bpsnh\b'),
    ('NEE', r'florida power (?:&|and) light|\bfpl\b|gulf power|nextera energy transmission|\bneet\b|lone star transmission'),
    ('PCG', r'pacific gas|\bpg&e\b|\bpge\b(?!\s*portland)'),
    ('EIX', r'southern california edison|\bsce\b'),
    ('POR', r'portland general'),
    ('HE', r'hawaiian electric|\bheco\b|maui electric|hawaii electric light'),
    ('AQN', r'liberty utilities|empire district|algonquin'),
]
ACTIVE = re.compile(r'^active|^suspended', re.I)


def find_file(argv):
    if len(argv) > 2:
        return argv[2]
    c = [p for d in ('eia_cache', os.path.join('Scans', 'NEW')) for p in glob.glob(os.path.join(DATA, d, '*.xlsx')) if 'queue' in os.path.basename(p).lower()]
    return max(c, key=os.path.getmtime) if c else None


def header_map(row):
    low = [str(c).strip().lower() if c is not None else '' for c in row]
    m = {}
    for k, al in ALIASES.items():
        for a in al:
            if a in low:
                m[k] = low.index(a)
                break
    return m


def load_rows(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for ws in wb.worksheets:
        it = ws.iter_rows(values_only=True)
        for i, row in zip(range(30), it):
            hm = header_map(row)
            if 'q_status' in hm and ('q_id' in hm or 'mw' in hm):
                miss = [k for k in REQUIRED if k not in hm]
                if miss:
                    sys.exit(f'{os.path.basename(path)} / {ws.title}: header found but missing {miss} - add the new column name to ALIASES')
                return ws.title, hm, [r for r in it if r and any(v is not None for v in r)]
    sys.exit(f'no project sheet with a q_status header in {path}')


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def to_date(v):
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    s = str(v or '').strip()
    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%Y'):
        try:
            return datetime.datetime.strptime(s[:10], fmt).date()
        except ValueError:
            pass
    return None


def main():
    path = find_file(sys.argv)
    if not path or not os.path.exists(path):
        sys.exit('No queue workbook found. Download LBNL "Queued Up" data (https://emp.lbl.gov/queues) and save it with "queue" in the name under data\\eia_cache\\')
    sheet, hm, rows = load_rows(path)
    today = datetime.date.today()
    rx = [(t, re.compile(p, re.I)) for t, p in UTILITY_ALIASES]
    g = lambda r, k: r[hm[k]] if k in hm and hm[k] < len(r) else None
    iso = collections.defaultdict(lambda: {'active_mw': collections.Counter(), 'active_n': 0, 'ages': [], 'withdrawn_n': 0, 'operational_n': 0})
    tk = collections.defaultdict(lambda: {'active_mw': collections.Counter(), 'active_n': 0, 'ia_signed_mw': 0.0, 'states': collections.Counter(),
                                          'oldest': None, 'projects': [], 'utilities': collections.Counter()})
    n_all = n_active = n_attr = 0
    for r in rows:
        st = str(g(r, 'q_status') or '')
        mw = num(g(r, 'mw')) or 0.0
        typ = str(g(r, 'type') or 'Unknown').strip() or 'Unknown'
        reg = str(g(r, 'region') or g(r, 'entity') or 'Unknown').strip()
        qd = to_date(g(r, 'q_date'))
        n_all += 1
        I = iso[reg]
        if re.match(r'^withdrawn', st, re.I):
            I['withdrawn_n'] += 1; continue
        if re.match(r'^operational|^online|^completed', st, re.I):
            I['operational_n'] += 1; continue
        if not ACTIVE.match(st):
            continue
        n_active += 1
        I['active_mw'][typ] += mw; I['active_n'] += 1
        if qd:
            I['ages'].append((today - qd).days / 365.25)
        util = str(g(r, 'utility') or '')
        tick = next((t for t, p in rx if p.search(util)), None)
        if not tick:
            continue
        n_attr += 1
        T = tk[tick]
        T['active_mw'][typ] += mw; T['active_n'] += 1; T['utilities'][util.strip()] += 1
        T['states'][str(g(r, 'state') or '?')] += mw
        ia = str(g(r, 'ia_status') or '')
        if re.search(r'executed|signed|ia\s*complete', ia, re.I):
            T['ia_signed_mw'] += mw
        if qd and (T['oldest'] is None or qd.isoformat() < T['oldest']):
            T['oldest'] = qd.isoformat()
        T['projects'].append({'q_id': g(r, 'q_id'), 'type': typ, 'mw': mw, 'state': g(r, 'state'), 'q_date': qd.isoformat() if qd else None,
                              'poi': g(r, 'poi'), 'ia_status': ia or None, 'region': reg})
    out_iso = {k: {'active_n': v['active_n'], 'active_gw': round(sum(v['active_mw'].values()) / 1000, 1),
                   'active_gw_by_type': {t: round(m / 1000, 1) for t, m in v['active_mw'].most_common()},
                   'median_age_yrs': round(statistics.median(v['ages']), 1) if v['ages'] else None,
                   'withdrawn_n': v['withdrawn_n'], 'operational_n': v['operational_n']} for k, v in sorted(iso.items())}
    out_tk = {}
    for t, v in sorted(tk.items()):
        tot = sum(v['active_mw'].values())
        out_tk[t] = {'active_n': v['active_n'], 'active_gw': round(tot / 1000, 2),
                     'active_gw_by_type': {k: round(m / 1000, 2) for k, m in v['active_mw'].most_common()},
                     'ia_signed_gw': round(v['ia_signed_mw'] / 1000, 2), 'ia_signed_share': round(v['ia_signed_mw'] / tot, 2) if tot else None,
                     'top_states_gw': {k: round(m / 1000, 2) for k, m in v['states'].most_common(5)}, 'oldest_request': v['oldest'],
                     'utilities_matched': dict(v['utilities'].most_common(8)),
                     'largest': sorted(v['projects'], key=lambda p: -(p['mw'] or 0))[:15]}
    doc = {'_schema_version': '1.0', '_generated': today.isoformat(), '_source_file': os.path.basename(path), '_sheet': sheet,
           '_columns': {k: v for k, v in hm.items()},
           '_caveat': ('Berkeley Lab Queued Up project data (a vintage, not live queues). "Active" = active or suspended requests. Attribution '
                       'is by the interconnecting utility / transmission owner named in the data, matched to coverage opcos by name - a '
                       'request in a name\'s footprint is exposure (network upgrades, load-serving capacity), not ownership.'),
           'counts': {'rows': n_all, 'active': n_active, 'active_attributed_to_coverage': n_attr},
           'iso': out_iso, 'tickers': out_tk}
    json.dump(doc, open(os.path.join(DATA, 'interconnection.json'), 'w', encoding='utf-8'), indent=1, default=str)
    print(f'wrote interconnection.json from {os.path.basename(path)} [{sheet}]: {n_all} rows, {n_active} active, {n_attr} attributed to coverage')
    for t, v in out_tk.items():
        print(f"  {t:5} {v['active_n']:>5} projects {v['active_gw']:>8} GW  IA signed {v['ia_signed_share']}  {list(v['active_gw_by_type'].items())[:3]}")


if __name__ == '__main__':
    main()
