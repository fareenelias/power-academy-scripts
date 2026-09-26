# -*- coding: utf-8 -*-
r"""build_cashflow_plan.py - cash flow vs plan: did the filed cash flows track the capital and financing
plans management printed?

  python E:\PowerAcademy\scripts\build_cashflow_plan.py [--out data\cashflow_vs_plan.json]

Inputs (both already built):
  data\guidance_history.json   every deck's capital plan (total, window) and financing plan (equity, debt),
                               plus _capital_plan_drift.vintages (one row per plan window)
  data\funding_gap.json        filed FY cash flows from CapIQ (CFO, dividends, capex, LT debt issued/repaid,
                               equity issued), FY2021-25

Per plan window (e.g. '2023-2027 $40B'), for each window year that has filed actuals:
  plan_capex_pace   = window total / years in window  (EVEN pacing assumed - decks rarely print the annual
                      phasing; a back-weighted plan reads as under-delivery in early years, so the
                      cumulative figure is the fairer read)
  capex_delivery    = filed capex / plan pace
  equity_vs_plan    = filed equity issued / (printed equity plan / years)   - when the deck printed one
  debt_vs_plan      = filed net LT debt (issued + repaid) / (printed debt plan / years)
  internal_vs_plan  = filed (CFO + dividends [negative]) / plan-implied internal cash, where
                      plan-implied internal = capex pace - equity pace - debt pace (only when BOTH equity and
                      debt were printed). This is the 'cash-flow realism' test: a plan that needs more internal
                      cash than the company has been generating leans on something the deck doesn't say.
Plan definitions vary (growth-only vs total capex, utility-only vs consolidated, C$ vs US$, pre/post a
divestiture), so a delivery % is read alongside the plan's own wording. Scope caveat carried from funding_gap: some plans are utility-only (e.g. NEE = FPL) while the filed figures
are consolidated - flagged per name from the capex_plan note.
"""
import os, sys, json, re, datetime as dt

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# A divestiture that changes what the capex plan covers. Windows printed BEFORE the change are kept for the
# record but marked superseded_scope and never judged (no flag, no stress-screen point); the forward run-rate
# uses filed years from the change year on. Add a row here when a name sells a business its plans included.
SCOPE_CHANGES = {
    'AQN': {'from_year': 2025, 'note': 'AQN sold its renewable energy business (ex-hydro) in January 2025. The 2021-2025 '
            '($9.4B) and 2022-2026 ($12.4B) plans included it, so filed capex after the sale cannot be measured against '
            'them; the regulated-only plan is 2026-2028 (~$3.2B, Q4 2025 deck) and has no filed year yet.'},
}


def r1(x): return None if x is None else round(x, 2)


def pct(a, b): return None if a is None or not b else round(100 * a / b, 1)


def main():
    a = sys.argv[1:]
    data = a[a.index('--data') + 1] if '--data' in a else os.path.join(BASE, 'data')
    outp = a[a.index('--out') + 1] if '--out' in a else os.path.join(data, 'cashflow_vs_plan.json')
    gh = json.load(open(os.path.join(data, 'guidance_history.json'), encoding='utf-8'))
    fg = json.load(open(os.path.join(data, 'funding_gap.json'), encoding='utf-8'))['names']
    out = {}
    for t, rows in gh.items():
        if t.startswith('_') or not isinstance(rows, dict):
            continue
        filed = (fg.get(t) or {}).get('filed')
        vint = (rows.get('_capital_plan_drift') or {}).get('vintages') or []
        if not filed or not vint:
            out[t] = {'status': 'no ' + ('filed cash flows' if not filed else 'capital plan windows') + ' on file'}
            continue
        yrs = [int(p[:4]) for p in filed['periods']]
        F = {k: dict(zip(yrs, filed.get(k) or [])) for k in
             ('cfo_b', 'dividends_b', 'capex_b', 'lt_debt_issued_b', 'lt_debt_repaid_b', 'equity_issued_b')}
        decks = [(p, v) for p, v in rows.items() if not p.startswith('_') and isinstance(v, dict)]
        scope_note = ((fg.get(t) or {}).get('capex_plan') or {}).get('note')
        sc_chg = SCOPE_CHANGES.get(t)
        if sc_chg:
            scope_note = (scope_note + ' ' if scope_note else '') + sc_chg['note']
        windows = []
        for v in vint:
            m = re.match(r'(\d{4})\s*-\s*(\d{4})', v.get('window') or '')
            if not m or not v.get('per_year_b'):
                continue
            y0, y1 = int(m.group(1)), int(m.group(2))
            n = y1 - y0 + 1
            # latest deck that printed a financing plan for THIS window
            fin = None
            for p, d in decks:
                if (d.get('capital_plan_years') or '') == v['window']:
                    fp = d.get('financing_plan') or {}
                    if fp.get('equity_b') is not None or fp.get('debt_b') is not None:
                        fin = {'deck': p, 'equity_b': fp.get('equity_b'), 'debt_b': fp.get('debt_b'),
                               'source_page': fp.get('source_page'), 'source_url': d.get('source_url')}
            eq_pace = fin['equity_b'] / n if fin and fin['equity_b'] is not None else None
            dt_pace = fin['debt_b'] / n if fin and fin['debt_b'] is not None else None
            int_pace = (v['per_year_b'] - eq_pace - dt_pace) if eq_pace is not None and dt_pace is not None else None
            yrows = []
            for y in range(y0, y1 + 1):
                if y not in F['capex_b'] or F['capex_b'][y] is None:
                    continue
                capex = -F['capex_b'][y]
                internal = (F['cfo_b'].get(y) or 0) + (F['dividends_b'].get(y) or 0) if F['cfo_b'].get(y) is not None else None
                net_debt = None
                if F['lt_debt_issued_b'].get(y) is not None:
                    net_debt = (F['lt_debt_issued_b'][y] or 0) + (F['lt_debt_repaid_b'].get(y) or 0)
                eq = F['equity_issued_b'].get(y)
                yrows.append({'year': y, 'plan_capex_pace_b': r1(v['per_year_b']), 'capex_b': r1(capex),
                              'capex_delivery_pct': pct(capex, v['per_year_b']),
                              'cfo_b': r1(F['cfo_b'].get(y)), 'internal_after_div_b': r1(internal),
                              'plan_internal_pace_b': r1(int_pace), 'internal_vs_plan_pct': pct(internal, int_pace),
                              'equity_issued_b': r1(eq), 'plan_equity_pace_b': r1(eq_pace), 'equity_vs_plan_pct': pct(eq, eq_pace),
                              'net_lt_debt_b': r1(net_debt), 'plan_debt_pace_b': r1(dt_pace), 'debt_vs_plan_pct': pct(net_debt, dt_pace)})
            cum = None
            if yrows:
                sc = sum(r['capex_b'] for r in yrows); sp = v['per_year_b'] * len(yrows)
                cum = {'years': [r['year'] for r in yrows], 'capex_b': r1(sc), 'plan_pace_b': r1(sp),
                       'capex_delivery_pct': pct(sc, sp)}
                if eq_pace is not None and all(r['equity_issued_b'] is not None for r in yrows):
                    se = sum(r['equity_issued_b'] for r in yrows)
                    cum.update({'equity_issued_b': r1(se), 'plan_equity_b': r1(eq_pace * len(yrows)),
                                'equity_vs_plan_pct': pct(se, eq_pace * len(yrows))})
                if int_pace is not None and all(r['internal_after_div_b'] is not None for r in yrows):
                    si = sum(r['internal_after_div_b'] for r in yrows)
                    cum.update({'internal_after_div_b': r1(si), 'plan_internal_b': r1(int_pace * len(yrows)),
                                'internal_vs_plan_pct': pct(si, int_pace * len(yrows))})
            w = {'window': v['window'], 'total_b': v.get('total_b'), 'per_year_b': v['per_year_b'],
                 'basis': v.get('basis'), 'last_stated': v.get('last_stated'), 'financing_plan': fin,
                 'years': yrows, 'cumulative': cum}
            ls = re.search(r'(\d{4})', v.get('last_stated') or '')
            if sc_chg and ls and int(ls.group(1)) < sc_chg['from_year']:
                w['superseded_scope'] = sc_chg['note']
            windows.append(w)
        # forward look: the newest window vs the run-rate actually achieved (last 3 filed years)
        last3 = [y for y in sorted(F['capex_b']) if F['capex_b'][y] is not None
                 and (not sc_chg or y >= sc_chg['from_year'])][-3:]
        run_capex = sum(-F['capex_b'][y] for y in last3) / len(last3) if last3 else None
        run_int = None
        if last3 and all(F['cfo_b'].get(y) is not None for y in last3):
            run_int = sum((F['cfo_b'][y] or 0) + (F['dividends_b'].get(y) or 0) for y in last3) / len(last3)
        newest = windows[-1] if windows else None
        fwd = None
        if newest:
            fin = newest['financing_plan'] or {}
            n = int(newest['window'][-4:]) - int(newest['window'][:4]) + 1
            implied_int = (newest['per_year_b'] - fin['equity_b'] / n - fin['debt_b'] / n) \
                if fin.get('equity_b') is not None and fin.get('debt_b') is not None else None
            fwd = {'window': newest['window'], 'plan_capex_per_yr_b': newest['per_year_b'],
                   'run_rate_years': last3, 'run_rate_capex_b': r1(run_capex),
                   'capex_step_up_x': round(newest['per_year_b'] / run_capex, 2) if run_capex else None,
                   'plan_implied_internal_per_yr_b': r1(implied_int), 'run_rate_internal_b': r1(run_int),
                   'internal_step_up_x': round(implied_int / run_int, 2) if implied_int and run_int and run_int > 0 else None}
        flags = []
        # judge on the window with the MOST realized years (ties -> newest): early years of a plan are the
        # weakest evidence because most plans are back-weighted
        cums = [w['cumulative'] for w in windows if w['cumulative'] and len(w['cumulative']['years']) >= 2
                and not w.get('superseded_scope')]
        if cums:
            c = max(enumerate(cums), key=lambda ic: (len(ic[1]['years']), ic[0]))[1]
            if c['capex_delivery_pct'] is not None and c['capex_delivery_pct'] < 90:
                flags.append(f"capex ran {c['capex_delivery_pct']:.0f}% of plan pace over {c['years'][0]}-{c['years'][-1]}")
            if c['capex_delivery_pct'] is not None and c['capex_delivery_pct'] > 115:
                flags.append(f"capex ran ahead of plan: {c['capex_delivery_pct']:.0f}% of pace over {c['years'][0]}-{c['years'][-1]}")
            if c.get('equity_vs_plan_pct') is not None and c['equity_vs_plan_pct'] > 130:
                flags.append(f"equity issued {c['equity_vs_plan_pct']:.0f}% of the printed plan pace")
            if c.get('internal_vs_plan_pct') is not None and c['internal_vs_plan_pct'] < 85:
                flags.append(f"internal cash {c['internal_vs_plan_pct']:.0f}% of what the financing plan implied")
        if fwd and fwd['internal_step_up_x'] and fwd['internal_step_up_x'] > 1.25:
            flags.append(f"newest plan implies {fwd['internal_step_up_x']:.2f}x the internal cash of the last 3 years")
        if fwd and fwd['capex_step_up_x'] and fwd['capex_step_up_x'] > 1.4:
            flags.append(f"newest plan is {fwd['capex_step_up_x']:.2f}x the capex run-rate")
        out[t] = {'status': 'ok', 'scope_note': scope_note, 'filed_source': filed.get('source'),
                  'windows': windows, 'forward': fwd, 'flags': flags}
    doc = {'_schema_version': '1.0', '_generated': dt.date.today().isoformat(),
           '_method': __doc__.split('Per plan window')[1].split('"""')[0].strip(),
           '_caveat': 'Plan definitions vary (growth-only vs total capex, utility-only vs consolidated, currency, '
                       'plans set before a divestiture); read a delivery % alongside the deck wording linked per window.',
           '_units': '$B; filed = CapIQ cash-flow ladder (funding_gap.json); plan = printed decks (guidance_history.json)',
           'names': out}
    json.dump(doc, open(outp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    ok = [t for t, v in out.items() if v.get('status') == 'ok']
    print(f'wrote {outp}: {len(ok)} names with plan windows, {len(out) - len(ok)} without')
    for t in ok:
        v = out[t]; c = next((w['cumulative'] for w in reversed(v['windows']) if w['cumulative'] and len(w['cumulative']['years']) >= 2), None)
        print(f"  {t:5} {c and c['years']} capex {c and c['capex_delivery_pct']}%  eq {c and c.get('equity_vs_plan_pct')}%  "
              f"int {c and c.get('internal_vs_plan_pct')}%  | {'; '.join(v['flags'])}")


if __name__ == '__main__':
    main()
