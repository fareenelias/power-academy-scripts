# -*- coding: utf-8 -*-
"""build_guidance_track_record.py - data\\guidance_track_record.json (roadmap I.B).

Did management deliver what it guided? Per name, per guidance year: the FIRST printed EPS
range (the initial call), the LAST printed range before the year closed (the final call),
CapIQ's normalized actual, and the outcome - all off files on disk.

Inputs:
  guidance_history.json   eps_guidance per deck vintage {year, low, high, midpoint, source_page}
  capiq_export.json       eps_actuals_normalized {year: actual}  (CapIQ 'EPS Normalized' FY
                          actuals - adjusted basis, split-adjusted; begins FY2023) and the
                          Key Stats consensus for the in-flight year (labelled consensus)

Rules:
  * guidance year: the deck's printed year when captured; otherwise INFERRED - a Q4 deck
    (Feb of year+1) guides year+1, a Q1-Q3 deck guides its own year. Inferred years are
    labelled year_basis='inferred'.
  * a Q4 deck of year Y can't guide year Y (that year is closed) - such rows are dropped.
  * splits: every vintage printed BEFORE a split is divided by the ratio, whatever year it
    guides, because CapIQ's actuals are all split-adjusted (ETR 2-for-1 effective 2024-12-13).
    Labelled split_adjusted.
  * sanity gate: |actual / initial midpoint - 1| > 40% with no split -> 'basis_mismatch'
    (the deck and CapIQ are not on the same EPS definition); shown, excluded from the stats.
  * outcome vs the initial range: above / within / below; revision = final vs initial midpoint
    (raised / held / lowered, |delta| >= 1c).
  * in-flight year (no actual yet): consensus stands in, labelled; excluded from the stats.

  python build_guidance_track_record.py [--dry]
"""
import io, os, re, sys, json, collections, datetime

DATA_DIR = r'E:\PowerAcademy\data' if os.name == 'nt' else \
    os.path.join(os.path.expanduser('~'), 'mnt', 'PowerAcademy', 'data')
SPLITS = {'ETR': ('2024-12-13', 2.0), 'NEE': ('2020-10-26', 4.0)}   # effective date, ratio



# In-year revisions >=8% that were CHECKED on the deck page and are real raises/cuts, not
# outlook-column captures (2026-09-24 QC of the six '?' rows: CMS 2023/24, ETR 2024 and
# PCG 2024/25 were capture errors, fixed in guidance_history via the extractor year rule
# and guidance_qc_overrides.json; HTO 2023 is the one genuine revision).
VERIFIED_REVISIONS = {
    ('HTO', '2023'): 'SJW Q3 2023 deck p4 - "Guidance range increased for 2023: $2.65 to $2.70" (from $2.40-$2.50)',
}

def load(name):
    p = os.path.join(DATA_DIR, name)
    return json.load(io.open(p, encoding='utf-8')) if os.path.exists(p) else None


def qparts(q):
    m = re.match(r'Q(\d) (\d{4})', q or '')
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def build():
    g = load('guidance_history.json') or {}
    cq = (load('capiq_export.json') or {}).get('companies') or {}
    ca_all = ((load('eps_actuals_company.json') or {}).get('tickers')) or {}   # company-reported FY adjusted EPS (Q4 call)
    out = collections.OrderedDict()
    out['_schema_version'] = '1.0'
    out['_generated'] = datetime.date.today().isoformat()
    out['_method'] = __doc__.split('Rules:')[1].split('  python')[0].strip()
    out['_actuals_note'] = ("CapIQ 'EPS Normalized' FY actuals begin FY2023 in every workbook. Earlier years are scored only where "
                            "data/eps_actuals_company.json holds the company's own Q4-call adjusted EPS (actual_basis=company_reported, with the "
                            "transcript page); otherwise no_actual. Where both exist the company figure is a cross-check (>2c -> qc). "
                            "The in-flight year shows consensus, not an actual.")
    out['_coverage_note'] = ("A name with no EPS guidance cells in guidance_history is either a non-EPS guider (VST/TLN guide EBITDA and FCF; "
                             "AWR/CWT/YORW/MSEX/GWRS print no EPS range) or an extractor gap - NEE prints adjusted-EPS 'expectations' ranges in "
                             "every deck and EIX prints core EPS guidance yearly, and neither is captured before 2026: that is the extractor, "
                             "not the companies. Recorded here so the empty card reads as a gap, never as 'never guided'.")
    out['tickers'] = collections.OrderedDict()
    for t, qs in g.items():
        if t.startswith('_') or not isinstance(qs, dict): continue
        co = cq.get(t) or {}
        actuals = ((co.get('eps_actuals_normalized') or {}).get('values')) or {}
        actuals = {str(k): v for k, v in actuals.items() if isinstance(v, (int, float))}
        co_act = {str(k): v for k, v in (ca_all.get(t) or {}).items() if isinstance(v, dict) and isinstance(v.get('value'), (int, float))}
        per, eps = co.get('periods') or [], co.get('eps_diluted') or []
        consensus = {}
        for i, p in enumerate(per):
            m = re.match(r'(\d{4})FY E', str(p))
            if m and i < len(eps) and isinstance(eps[i], (int, float)): consensus[m.group(1)] = eps[i]
        split = SPLITS.get(t)
        by_year = collections.defaultdict(list)
        for q, r in qs.items():
            if not isinstance(r, dict): continue
            e = r.get('eps_guidance') or {}
            if not isinstance(e.get('midpoint'), (int, float)): continue
            qn, qy = qparts(q)
            if qn is None: continue
            if e.get('year') and str(e['year']).isdigit():
                y, basis = str(e['year']), 'printed'
            else:
                y, basis = (str(qy + 1) if qn == 4 else str(qy)), 'inferred'
            if qn == 4 and y == str(qy): continue           # a closed year is not guidance
            lo, hi, mid = e.get('low'), e.get('high'), e['midpoint']
            adj = False
            if split and r.get('source_date') and r['source_date'] < split[0]:   # CapIQ actuals are ALL split-adjusted
                lo = round(lo / split[1], 3) if isinstance(lo, (int, float)) else lo
                hi = round(hi / split[1], 3) if isinstance(hi, (int, float)) else hi
                mid = round(mid / split[1], 3); adj = True
            by_year[y].append(collections.OrderedDict([
                ('vintage', q), ('source_date', r.get('source_date')), ('low', lo), ('high', hi), ('midpoint', mid),
                ('year_basis', basis), ('split_adjusted', adj), ('source_url', r.get('source_url')),
                ('source_page', e.get('source_page')), ('source', r.get('source'))]))
        years = collections.OrderedDict()
        scored = []
        for y in sorted(by_year):
            vs = sorted(by_year[y], key=lambda v: (v['source_date'] or '', v['vintage']))
            # drop a vintage that is identical to its predecessor (same range re-printed) - keep for count only
            init, fin = vs[0], vs[-1]
            row = collections.OrderedDict([('year', y), ('n_vintages', len(vs)), ('initial', init), ('final', fin)])
            rev = fin['midpoint'] - init['midpoint']
            row['revision'] = 'raised' if rev >= 0.01 else 'lowered' if rev <= -0.01 else 'held'
            row['revision_pct'] = round(100 * rev / init['midpoint'], 1) if init['midpoint'] else None
            act = actuals.get(y); ca = co_act.get(y)
            if act is None and ca is not None:          # no CapIQ actual: the company's own Q4-call figure, labelled
                act = ca['value']; basis_a = 'company_reported'
            else:
                basis_a = 'capiq_normalized'
            if ca is not None:
                row['actual_source'] = collections.OrderedDict((k, ca.get(k)) for k in ('value', 'source_folder', 'source_file', 'source_page', 'said'))
                if basis_a == 'capiq_normalized' and act is not None and abs(act - ca['value']) > 0.02 + 1e-9:
                    row['qc'] = 'CapIQ normalized $%.2f vs company-reported $%.2f (Q4 call p%s) - different adjusted basis; check before relying on the outcome' % (act, ca['value'], ca.get('source_page'))
            if act is not None:
                row['actual'] = act; row['actual_basis'] = basis_a
                d = act / init['midpoint'] - 1 if init['midpoint'] else None
                row['delta_vs_initial_mid_pct'] = round(100 * d, 1) if d is not None else None
                row['delta_vs_final_mid_pct'] = round(100 * (act / fin['midpoint'] - 1), 1) if fin['midpoint'] else None
                if d is not None and abs(d) > 0.40:
                    row['outcome'] = 'basis_mismatch'; row['note'] = ('deck range and CapIQ FY normalized actual differ by >40% - a different EPS definition, or a quarterly / '
                                                              'outlook-year range captured as the annual guidance (D guides by quarter; VST/TLN guide EBITDA); excluded from the stats - the deep link is the arbiter')
                else:
                    lo, hi = init.get('low'), init.get('high')
                    if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
                        row['outcome'] = 'above' if act > hi + 1e-9 else 'below' if act < lo - 1e-9 else 'within'
                    else:
                        row['outcome'] = 'above' if act > init['midpoint'] else 'below' if act < init['midpoint'] else 'within'
                    flo, fhi = fin.get('low'), fin.get('high')
                    if isinstance(flo, (int, float)) and isinstance(fhi, (int, float)):
                        row['outcome_vs_final'] = 'above' if act > fhi + 1e-9 else 'below' if act < flo - 1e-9 else 'within'
                    scored.append(row)
            elif consensus.get(y) is not None:
                row['actual'] = None; row['consensus'] = consensus[y]; row['actual_basis'] = 'in_flight_consensus'
                row['outcome'] = 'in_flight'
                row['consensus_vs_final_mid_pct'] = round(100 * (consensus[y] / fin['midpoint'] - 1), 1) if fin['midpoint'] else None
            else:
                row['actual'] = None; row['outcome'] = 'no_actual'; row['note'] = 'no CapIQ normalized actual for this year (actuals begin FY2023) and no company-reported figure on file'
            if (t, y) in VERIFIED_REVISIONS and abs(row.get('revision_pct') or 0) >= 8:
                row['revision_verified'] = VERIFIED_REVISIONS[(t, y)]
                row['note'] = 'in-year revision of %s%% verified genuine: %s' % (row['revision_pct'], VERIFIED_REVISIONS[(t, y)])
            elif abs(row.get('revision_pct') or 0) >= 8 and row.get('outcome') not in ('basis_mismatch',):
                row['qc'] = ('in-year revision of %s%% - verify on the initial vintage\'s page that the range is this year\'s guidance and not an '
                             'outlook-year column (the ETR Q4-2023 deck prints 24E guidance beside 25E/26E outlooks)' % row['revision_pct'])
            years[y] = row
        n = len(scored)
        n_co = sum(1 for r in scored if r.get('actual_basis') == 'company_reported')
        summ = collections.OrderedDict([
            ('years_scored', n),
            ('years_scored_on_company_actual', n_co),
            ('years_listed', len(years)),
            ('within_initial_range', sum(1 for r in scored if r['outcome'] == 'within')),
            ('above_initial_range', sum(1 for r in scored if r['outcome'] == 'above')),
            ('below_initial_range', sum(1 for r in scored if r['outcome'] == 'below')),
            ('beat_initial_midpoint', sum(1 for r in scored if (r.get('delta_vs_initial_mid_pct') or 0) > 0)),
            ('avg_delta_vs_initial_mid_pct', round(sum(r['delta_vs_initial_mid_pct'] for r in scored) / n, 1) if n else None),
            ('raised_in_year', sum(1 for r in scored if r['revision'] == 'raised')),
            ('lowered_in_year', sum(1 for r in scored if r['revision'] == 'lowered')),
            ('basis_mismatch_years', [r['year'] for r in years.values() if r.get('outcome') == 'basis_mismatch']),
            ('review_years', [r['year'] for r in years.values() if r.get('qc')]),
        ])
        out['tickers'][t] = collections.OrderedDict([('summary', summ), ('years', years)])
    return out


if __name__ == '__main__':
    doc = build()
    for t, v in doc['tickers'].items():
        s = v['summary']
        ys = ' '.join(f"{y}:{r.get('outcome','?')[:5]}{('/'+r['revision'][:4]) if r.get('revision') else ''}" for y, r in v['years'].items())
        print(f"{t:5} scored={s['years_scored']} within={s['within_initial_range']} above={s['above_initial_range']} below={s['below_initial_range']} avgΔ={s['avg_delta_vs_initial_mid_pct']}  {ys}")
    if '--dry' not in sys.argv:
        p = os.path.join(DATA_DIR, 'guidance_track_record.json')
        io.open(p, 'w', encoding='utf-8').write(json.dumps(doc, indent=1, ensure_ascii=False)); json.load(io.open(p, encoding='utf-8'))
        print('wrote', p)
