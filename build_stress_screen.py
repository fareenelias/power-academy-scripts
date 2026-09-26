r"""build_stress_screen.py - one screen for 'who has activist pressure / balance-sheet stress /
ROE risk / capex-credibility issues' (roadmap II.B), off JSONs other builders already wrote.

No new data: every signal is read from an existing file and carries the evidence string and
the file it came from. Thresholds live HERE (retune here, never in the UI).

  funding      funding_gap.json  flag: divestiture_candidate = 2, watch = 1
  leverage     funding_gap.json  net debt / EBITDA >= 6.0x = 1  (utility holdco rule of thumb, not an agency metric)
  credit       capiq_export.json current_ratings, S&P holdco LT: negative outlook / CreditWatch neg = 1;
                                 BBB- = 1; sub-investment grade = 2
  roe          roe_drivers.json  rate-base-weighted earned gap <= -100 bps = 1; <= -200 bps = 2
  capex        cashflow_vs_plan.json newest plan >= 1.5x the capex run-rate = 1; delivery < 90% in the
                                 last filed plan year = 1
  activist     ownership.json    a non-proxy-proposal campaign (board representation, strategic,
                                 vote-no) launched in the last 3 years = 2; ESG/governance proposals only = 0
  market       issuance.json     median new-issue yield >= +40 bp vs contemporaneous peers = 1

    python scripts\build_stress_screen.py          (Windows default path)
    python scripts/build_stress_screen.py <data_dir>
"""
import sys, os, json, datetime

DATA = sys.argv[1] if len(sys.argv) > 1 else r'E:\PowerAcademy\data'
TODAY = datetime.date.today()
RANK = ['AAA', 'AA+', 'AA', 'AA-', 'A+', 'A', 'A-', 'BBB+', 'BBB', 'BBB-', 'BB+', 'BB', 'BB-', 'B+', 'B', 'B-']


def load(f):
    p = os.path.join(DATA, f)
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else None


def main():
    fg = (load('funding_gap.json') or {}).get('names', {})
    capiq = (load('capiq_export.json') or {}).get('companies', {})
    roe = (load('roe_drivers.json') or {}).get('names', {})
    cfp = (load('cashflow_vs_plan.json') or {}).get('names', {})
    own = (load('ownership.json') or {}).get('tickers', {})
    iss = (load('issuance.json') or {}).get('tickers', {})
    tickers = sorted(set(fg) | set(capiq) | set(own))
    out = {'_schema_version': '1.0', '_generated': TODAY.isoformat(),
           '_method': __doc__.split('\n\n')[2].strip(),
           '_caveat': 'A screen, not a verdict: points add across independent lenses so a name that is stretched on several at once rises. Every point shows its evidence and source file; absent data scores 0 and is listed under gaps.',
           'names': {}}
    for t in tickers:
        sig, gaps = [], []
        def add(lens, pts, why, src):
            sig.append({'lens': lens, 'points': pts, 'evidence': why, 'source': src})
        g = fg.get(t)
        if g:
            fl = (g.get('gap') or {}).get('flag')
            if fl == 'divestiture_candidate':
                add('funding', 2, f"funding gap: divestiture candidate (need {g['gap'].get('external_need_per_yr_b')}B/yr, {g['gap'].get('step_up_x')}x the run-rate)", 'funding_gap.json')
            elif fl == 'watch':
                su = g['gap'].get('step_up_x')
                add('funding', 1, 'funding gap: watch' + (f' ({su}x the run-rate)' if su is not None else ' (no FY2023-25 run-rate to compare)'), 'funding_gap.json')
            lv = (g.get('leverage') or {}).get('net_debt_to_ebitda')
            if isinstance(lv, (int, float)) and lv >= 6.0:
                add('leverage', 1, f'net debt / EBITDA {lv:.1f}x', 'funding_gap.json')
            if fl is None:
                gaps.append('funding gap not computed')
        else:
            gaps.append('no funding_gap row')
        rats = [r for r in ((capiq.get(t) or {}).get('current_ratings') or [])
                if 'S&P' in (r.get('agency') or '').upper() and r.get('rating_type') in ('Local Currency LT', 'Foreign Currency LT')]
        if rats:
            r0 = rats[0]
            ol = (r0.get('outlook') or '').lower()
            if 'negative' in ol or 'watch neg' in ol:
                add('credit', 1, f"S&P {r0.get('entity')}: {r0.get('rating')} / {r0.get('outlook')} (reviewed {r0.get('last_review')})", 'capiq_export.json')
            rt = (r0.get('rating') or '').strip()
            if rt == 'BBB-':
                add('credit', 1, f"S&P {r0.get('entity')}: BBB- - at the investment-grade floor", 'capiq_export.json')
            elif rt in RANK and RANK.index(rt) > RANK.index('BBB-'):
                add('credit', 2, f"S&P {r0.get('entity')}: {rt} - sub-investment grade", 'capiq_export.json')
        else:
            gaps.append('no S&P LT rating in CapIQ current_ratings')
        rs = (roe.get(t) or {}).get('summary') or {}
        eg = rs.get('rb_weighted_earned_gap_bps')
        if isinstance(eg, (int, float)):
            if eg <= -200:
                add('roe', 2, f'earned {eg} bps vs authorized (rate-base weighted, {rs.get("cases")} cases)', 'roe_drivers.json')
            elif eg <= -100:
                add('roe', 1, f'earned {eg} bps vs authorized (rate-base weighted, {rs.get("cases")} cases)', 'roe_drivers.json')
        else:
            gaps.append('no earned-vs-authorized gap')
        c = cfp.get(t) or {}
        fw = c.get('forward') or {}
        su = fw.get('capex_step_up_x')
        if isinstance(su, (int, float)) and su >= 1.5:
            add('capex', 1, f"newest plan {fw.get('window')} is {su}x the FY{min(fw.get('run_rate_years') or [0])}-{max(fw.get('run_rate_years') or [0])} capex run-rate", 'cashflow_vs_plan.json')
        last = None
        for w in c.get('windows') or []:
            for y in w.get('years') or []:
                if y.get('capex_delivery_pct') is not None and (last is None or y['year'] > last['year']):
                    last = y
        if last and last['capex_delivery_pct'] < 90:
            add('capex', 1, f"FY{last['year']} capex delivered {last['capex_delivery_pct']}% of plan pace", 'cashflow_vs_plan.json')
        if not c:
            gaps.append('no cash-flow-vs-plan row')
        a = (own.get(t) or {}).get('activism') or {}
        hot = []
        for cp in a.get('campaigns') or []:
            try:
                d = datetime.date.fromisoformat(str(cp.get('launched'))[:10])
            except ValueError:
                continue
            tac = cp.get('tactics') or ''
            if (TODAY - d).days <= 3 * 365 and tac and tac != 'Shareholder proposals':
                hot.append(f"{cp.get('activists')} - {tac} ({cp.get('launched')}, {cp.get('status') or 'status n/a'})")
        if hot:
            add('activist', 2, '; '.join(hot[:3]), 'ownership.json')
        if not own.get(t):
            gaps.append('no CapIQ ownership sheet')
        m = ((iss.get(t) or {}).get('summary') or {}).get('median_vs_peers_bps')
        if isinstance(m, (int, float)) and m >= 40:
            add('market', 1, f'new-issue debt prices a median {m:+d} bp vs contemporaneous coverage peers', 'issuance.json')
        score = sum(s['points'] for s in sig)
        out['names'][t] = {'score': score, 'tier': 'high' if score >= 4 else ('elevated' if score >= 2 else 'low'),
                           'lenses': sorted({s['lens'] for s in sig}), 'signals': sig, 'gaps': gaps}
    ranked = sorted(out['names'].items(), key=lambda kv: -kv[1]['score'])
    out['_summary'] = {'high': [t for t, v in ranked if v['tier'] == 'high'], 'elevated': [t for t, v in ranked if v['tier'] == 'elevated']}
    json.dump(out, open(os.path.join(DATA, 'stress_screen.json'), 'w', encoding='utf-8'), indent=1)
    for t, v in ranked:
        print(f"  {t:5} {v['score']:>2} {v['tier']:8} {', '.join(v['lenses'])}")


if __name__ == '__main__':
    main()
