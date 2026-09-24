# -*- coding: utf-8 -*-
"""build_funding_gap.py - data\\funding_gap.json for the Origination 'Funding Gap' board (tracker S4.3).

Question the board answers per name: does the stated capital plan outrun what the company
funds internally plus what it has SAID it will raise - and how does that compare with what it
has actually raised? A large unstated residual is the divestiture-candidate signal (AES/GIP is
the worked precedent).

Inputs (all on disk, nothing fetched):
  guidance_history.json  capital_plan_total_b + window (latest vintage per name)
                         financing_plan.equity_b / debt_b (printed plans; 9 / 1 names)
  capiq_export.json      cash_flow canonical ladder FY2021-25 (filed CFO, dividends, capex,
                         LT debt issued/repaid, equity issued) + net_debt / ebitda
  offerings.json         deal-level texture (holdco/opco split, equity events) + coverage %

Method (every figure labelled in the output):
  capex_plan_per_yr     = capital_plan_total_b / plan years
  internal_per_yr       = 3-yr avg (FY2023-25) of filed CFO after total dividends
  external_need_per_yr  = capex_plan_per_yr - internal_per_yr         (the number to fund)
  stated_per_yr         = (equity_b + debt_b) / their windows (plan window assumed when the
                          deck prints none - labelled)
  unstated_per_yr       = external_need_per_yr - stated_per_yr        (null when nothing stated)
  hist_external_per_yr  = 3-yr avg of filed (LT debt issued + LT debt repaid + equity issued)
  step_up_x             = external_need_per_yr / hist_external_per_yr
  flag                  = self_funding (need <= 0) | funded (stated covers >= 80% of the need, or
                          step_up_x < 1.3) | watch (step_up_x 1.3-2.0, or no external run-rate to
                          compare) | divestiture_candidate (step_up_x >= 2.0 AND stated covers < 50%
                          or nothing printed). A heuristic, stated as one on the board.
Coverage honesty: a name missing the numerator or the filed ladder gets a banner and NO flag.

  python build_funding_gap.py [--dry]
"""
import io, os, re, sys, json, collections, datetime

DATA_DIR = r'E:\PowerAcademy\data' if os.name == 'nt' else \
    os.path.join(os.path.expanduser('~'), 'mnt', 'PowerAcademy', 'data')
UNIVERSE = ['NEE','D','ETR','CMS','PPL','AEE','POR','EIX','PCG','HE','EVRG','ES','VST','TLN','XIFR',
            'AWR','CWT','YORW','GWRS','AWK','WTRG','HTO','MSEX','AQN','AEP']


def load(name):
    p = os.path.join(DATA_DIR, name)
    return json.load(io.open(p, encoding='utf-8')) if os.path.exists(p) else None


def qkey(q):
    m = re.match(r'Q(\d) (\d{4})', q or '')
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def window_years(w, vintage_year):
    """'2026-2030' -> 5 ; 'through 2032' -> 2032 - vintage + 1 ; None -> None"""
    if not w: return None
    m = re.match(r'(\d{4})\s*[-–]\s*(\d{4})', str(w))
    if m: return int(m.group(2)) - int(m.group(1)) + 1
    m = re.search(r'through\s+(\d{4})', str(w))
    if m and vintage_year: return int(m.group(1)) - vintage_year + 1
    return None


def latest_plan(qs):
    plan, fin = None, None
    for q, r in sorted(qs.items(), key=lambda kv: qkey(kv[0])):
        if not isinstance(r, dict): continue
        if r.get('capital_plan_total_b'):
            plan = dict(q=q, total_b=r['capital_plan_total_b'], window=r.get('capital_plan_years'),
                        basis=r.get('capital_plan_basis'), page=r.get('capital_plan_source_page'),
                        source=r.get('source'), source_url=r.get('source_url'), source_date=r.get('source_date'),
                        note=r.get('capital_plan_note'))
        fp = r.get('financing_plan') or {}
        if fp.get('equity_b') or fp.get('debt_b'):
            fin = dict(q=q, equity_b=fp.get('equity_b'), equity_window=fp.get('equity_window'),
                       debt_b=fp.get('debt_b'), debt_window=fp.get('debt_window'), basis=fp.get('basis'),
                       page=fp.get('source_page'), debt_page=fp.get('debt_source_page'),
                       source=r.get('source'), source_url=r.get('source_url'), note=fp.get('note'))
    return plan, fin


def avg(vals):
    v = [x for x in vals if isinstance(x, (int, float))]
    return round(sum(v) / len(v), 1) if v else None


def build():
    g = load('guidance_history.json') or {}
    cq = (load('capiq_export.json') or {}).get('companies') or {}
    off = (load('offerings.json') or {}).get('tickers') or {}
    out = collections.OrderedDict()
    out['_schema_version'] = '1.0'
    out['_generated'] = datetime.date.today().isoformat()
    out['_method'] = __doc__.split('Method (every figure labelled in the output):')[1].split('Coverage honesty')[0].strip()
    out['_units'] = '$B per year unless suffixed; filed figures are CapIQ cash-flow ladder values ($000) / 1e6'
    out['_flag_rule'] = ("self_funding: need <= 0 | funded: printed equity+debt plan covers >= 80% of the need, or the need is < 1.3x "
                         "the FY2023-25 net external run-rate | watch: 1.3-2.0x (or no run-rate to compare) | divestiture_candidate: "
                         ">= 2.0x AND the printed plan covers < 50% (or nothing printed). Heuristic - the AES/GIP precedent is the "
                         "reference case, not a calibration; retune the thresholds here, never in the UI.")
    rows = collections.OrderedDict()
    for t in UNIVERSE:
        r = collections.OrderedDict(); r['ticker'] = t
        gaps = []
        plan, fin = latest_plan(g.get(t) or {}) if isinstance(g.get(t), dict) else (None, None)
        co = cq.get(t) or {}
        cf = co.get('cash_flow') or {}
        can = cf.get('canonical') or {}
        rws = cf.get('rows') or {}
        periods = cf.get('periods') or []
        # numerator
        if plan:
            vy = int(plan['source_date'][:4]) if plan.get('source_date') else None
            n = window_years(plan['window'], vy)
            r['capex_plan'] = dict(total_b=plan['total_b'], window=plan['window'], years=n,
                                   per_yr_b=round(plan['total_b'] / n, 2) if n else None, basis=plan['basis'],
                                   vintage=plan['q'], source=plan['source'], source_url=plan['source_url'],
                                   source_page=plan['page'], note=plan['note'])
            if not n: gaps.append('capital plan window not parseable (' + str(plan['window']) + ')')
        else:
            r['capex_plan'] = None; gaps.append('no multi-year capital plan total in guidance_history')
        # filed ladder
        def series(key, label=None):
            v = (can.get(key) or {}).get('values') if key in can else rws.get(label)
            return [x / 1e6 if isinstance(x, (int, float)) else None for x in (v or [])]
        cfo, div, capex = series('cfo'), series('dividends_total'), series('capex')
        lt_iss, lt_rep, eq_iss = series('', 'Long-term Debt Issued'), series('', 'Long-term Debt Repaid'), series('equity_issued')
        if periods and cfo:
            idx = [i for i, p in enumerate(periods) if str(p)[:4] in ('2023', '2024', '2025')]
            pick = lambda s: [s[i] for i in idx if i < len(s)]
            internal = [ (c + (d or 0)) if isinstance(c, (int, float)) else None for c, d in zip(cfo, div + [None] * len(cfo)) ]
            ext_hist = [ ((a or 0) + (b or 0) + (e or 0)) if isinstance(a, (int, float)) else None
                         for a, b, e in zip(lt_iss, lt_rep + [None] * len(lt_iss), eq_iss + [None] * len(lt_iss)) ]
            r['filed'] = collections.OrderedDict([
                ('periods', [str(p) for p in periods]),
                ('cfo_b', [round(x, 2) if x is not None else None for x in cfo]),
                ('dividends_b', [round(x, 2) if x is not None else None for x in div]),
                ('capex_b', [round(x, 2) if x is not None else None for x in capex]),
                ('lt_debt_issued_b', [round(x, 2) if x is not None else None for x in lt_iss]),
                ('lt_debt_repaid_b', [round(x, 2) if x is not None else None for x in lt_rep]),
                ('equity_issued_b', [round(x, 2) if x is not None else None for x in eq_iss]),
                ('internal_after_div_b', [round(x, 2) if x is not None else None for x in internal]),
                ('external_raised_b', [round(x, 2) if x is not None else None for x in ext_hist]),
                ('avg_window', [str(periods[i]) for i in idx]),
                ('internal_per_yr_b', round(avg(pick(internal)), 2) if avg(pick(internal)) is not None else None),
                ('capex_actual_per_yr_b', round(-avg(pick(capex)), 2) if avg(pick(capex)) is not None else None),
                ('external_per_yr_b', round(avg(pick(ext_hist)), 2) if avg(pick(ext_hist)) is not None else None),
                ('source', cf.get('_source_file')),
            ])
        else:
            r['filed'] = None; gaps.append('no filed cash-flow ladder in capiq_export (run extract_segments_cashflow.py)')
        # stated financing
        if fin and plan:
            n = r['capex_plan']['years']
            ew = window_years(fin.get('equity_window'), None) or n
            dw = window_years(fin.get('debt_window'), None) or n
            r['stated'] = collections.OrderedDict([
                ('equity_b', fin.get('equity_b')), ('equity_window', fin.get('equity_window') or (plan['window'] + ' (plan window assumed)' if plan.get('window') else None)),
                ('equity_per_yr_b', round(fin['equity_b'] / ew, 2) if fin.get('equity_b') and ew else None),
                ('debt_b', fin.get('debt_b')), ('debt_window', fin.get('debt_window') or (plan['window'] + ' (plan window assumed)' if fin.get('debt_b') and plan.get('window') else None)),
                ('debt_per_yr_b', round(fin['debt_b'] / dw, 2) if fin.get('debt_b') and dw else None),
                ('vintage', fin['q']), ('basis', fin.get('basis')), ('source', fin.get('source')), ('source_url', fin.get('source_url')),
                ('source_page', fin.get('page')), ('debt_source_page', fin.get('debt_page')), ('note', fin.get('note'))])
        else:
            r['stated'] = None
            if plan: gaps.append('no printed equity/debt financing plan in the decks')
        # leverage snapshot
        nd, eb, per = co.get('net_debt') or [], co.get('ebitda') or [], co.get('periods') or []
        try:
            fy_idx = [i for i, p in enumerate(per) if str(p).startswith('2025')][0]
            r['leverage'] = dict(net_debt_b=round(nd[-1] / 1e6, 2), ebitda_fy2025_b=round(eb[fy_idx] / 1e6, 2),
                                 net_debt_to_ebitda=round(nd[-1] / eb[fy_idx], 2), note='CapIQ net_debt latest / EBITDA FY2025')
        except Exception:
            r['leverage'] = None
        # offerings texture
        o = off.get(t)
        if o:
            ann = o.get('annual') or {}
            recent = {y: a for y, a in ann.items() if y >= '2024'}
            hold = sum(a.get('debt_holdco_usd_m', 0) for a in recent.values()); sub = sum(a.get('debt_sub_usd_m', 0) for a in recent.values())
            eq_events = [x for x in o.get('rows', []) if x.get('funding_type') == 'Common Stock' and x.get('status') == 'Priced' and not x.get('duplicate_of') and (x.get('announce_date') or '') >= '2024']
            cov = [a.get('offerings_debt_coverage_pct') for a in ann.values() if a.get('offerings_debt_coverage_pct') is not None]
            r['offerings'] = collections.OrderedDict([
                ('since', '2024'), ('holdco_debt_b', round(hold / 1000, 2)), ('opco_debt_b', round(sub / 1000, 2)),
                ('opco_share_pct', round(100 * sub / (hold + sub)) if (hold + sub) else None),
                ('equity_events', [dict(date=x['announce_date'], issuer=x['issuer'], type=x.get('offering_type'), size_b=round((x.get('size_k') or 0) / 1e6, 2), price=x.get('offering_price')) for x in eq_events]),
                ('coverage_vs_filed_pct', dict(min=min(cov), max=max(cov)) if cov else None),
                ('workbook_date', o.get('workbook_date')),
                ('note', 'CapIQ deal-database coverage, not the filed financing - texture only; coverage_vs_filed_pct says how much of the filed LT debt it sees')])
        else:
            r['offerings'] = None
            r['offerings_note'] = 'no Detailed Offerings tab for this name in CapIQ (not available, per 2026-09-23 export)'
        # the gap
        gp = collections.OrderedDict()
        cp = (r['capex_plan'] or {}).get('per_yr_b'); ip = (r['filed'] or {}).get('internal_per_yr_b'); hx = (r['filed'] or {}).get('external_per_yr_b')
        if cp is not None and ip is not None:
            need = round(cp - ip, 2); gp['external_need_per_yr_b'] = need
            st = r['stated'] or {}
            s_eq, s_db = st.get('equity_per_yr_b'), st.get('debt_per_yr_b')
            stated = (s_eq or 0) + (s_db or 0) if (s_eq is not None or s_db is not None) else None
            gp['stated_per_yr_b'] = round(stated, 2) if stated is not None else None
            gp['unstated_per_yr_b'] = round(need - stated, 2) if stated is not None else None
            gp['equity_stated_pct_of_need'] = round(100 * s_eq / need) if s_eq is not None and need > 0 else None
            gp['step_up_x'] = round(need / hx, 2) if hx and hx > 0 else None
            gp['capex_step_up_x'] = round(cp / r['filed']['capex_actual_per_yr_b'], 2) if r['filed'].get('capex_actual_per_yr_b') else None
            su = gp['step_up_x']
            cov = (stated / need) if (stated is not None and need > 0) else None
            gp['stated_cov_pct'] = round(100 * cov) if cov is not None else None
            if need <= 0: gp['flag'] = 'self_funding'
            elif cov is not None and cov >= 0.8: gp['flag'] = 'funded'
            elif hx is not None and hx <= 0: gp['flag'] = 'watch'; gp['flag_note'] = 'no external run-rate to compare (net deleveraging FY2023-25)'
            elif su is not None and su >= 2.0 and (cov is None or cov < 0.5): gp['flag'] = 'divestiture_candidate'
            elif su is not None and su >= 1.3: gp['flag'] = 'watch'
            else: gp['flag'] = 'funded'
        else:
            gp['flag'] = None
        r['gap'] = gp
        r['coverage_gaps'] = gaps
        rows[t] = r
    out['names'] = rows
    flags = collections.Counter(v['gap'].get('flag') for v in rows.values())
    out['_summary'] = dict(names=len(rows), flags=dict(flags), no_numerator=[t for t, v in rows.items() if not v['capex_plan']],
                           no_filed=[t for t, v in rows.items() if not v['filed']])
    return out


if __name__ == '__main__':
    doc = build()
    for t, v in doc['names'].items():
        g = v['gap']; cp = (v['capex_plan'] or {}).get('per_yr_b'); f = v['filed'] or {}
        print(f"{t:5} capex/yr {str(cp):6} internal/yr {str(f.get('internal_per_yr_b')):6} hist ext/yr {str(f.get('external_per_yr_b')):6} "
              f"need {str(g.get('external_need_per_yr_b')):6} stated {str(g.get('stated_per_yr_b')):6} step {str(g.get('step_up_x')):5} -> {g.get('flag')}  {('; '.join(v['coverage_gaps']))[:60]}")
    print(doc['_summary'])
    if '--dry' not in sys.argv:
        p = os.path.join(DATA_DIR, 'funding_gap.json')
        io.open(p, 'w', encoding='utf-8').write(json.dumps(doc, indent=1, ensure_ascii=False)); json.load(io.open(p, encoding='utf-8'))
        print('wrote', p)
