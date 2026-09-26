r"""build_transaction_screen.py - ranked 'likely to transact in 12-24 months' screen (tracker 361) -> data\transaction_screen.json

Two lanes, each a transparent point score (every point carries its evidence and source file):

A. SPONSOR-HELD US UTILITY ASSETS (sponsor_universe.json holdings, the deal book)
   hold age  >= 10y: 3 | 7-10y: 2 | 5-7y: 1        (infra funds typically hold 7-12y; the book basis is caveated)
   sponsor running live sell-side processes now (Infralogic): +1
   minority stake (<50%) held 5y+: +1               (co-control positions are the usual first sell-downs)
   already linked to a pending exit deal -> status 'in process', listed but not ranked
   pending/unclosed entries are skipped (not yet owned)

B. COVERAGE NAMES AS SELLERS OF ASSETS (strategic_moves + funding_gap + stress_screen)
   funding gap flag: divestiture_candidate +2, watch +1               (funding_gap.json)
   monetization / simplification call talk: rising or new +1 each     (strategic_moves.json call_talk)
   active seller: 2+ disposals since 2023 +1; a minority sell-down +1 (strategic_moves.json)
   stress tier: high +2, elevated +1                                  (stress_screen.json)
   a name that is party to a pending live deal (live_deals.json) is marked 'in process'

Heuristic ranking, not a probability. Tiers: >=5 high, 3-4 medium, else low.
    python scripts\build_transaction_screen.py [data_dir]
"""
import sys, os, json, datetime

DATA = sys.argv[1] if len(sys.argv) > 1 else r'E:\PowerAcademy\data'
J = lambda f: json.load(open(os.path.join(DATA, f), encoding='utf-8'))
tier = lambda s: 'high' if s >= 5 else 'medium' if s >= 3 else 'low'


def sponsor_lane():
    su = J('sponsor_universe.json')
    sps = su['sponsors'] if isinstance(su['sponsors'], list) else list(su['sponsors'].values())
    by_asset = {}
    for s in sps:
        il = s.get('inframation') if isinstance(s.get('inframation'), dict) and isinstance(s['inframation'].get('fund_count'), int) else None
        live = (il or {}).get('live_processes') or []
        for h in s.get('holdings') or []:
            if h.get('hold_years_asof') is None or not str(h.get('status', '')).startswith('closed'):
                continue
            key = h['target']
            row = by_asset.setdefault(key, {'asset': key, 'holders': [], 'score': 0, 'signals': [], 'status': 'held'})
            row['holders'].append({'sponsor': s['name'], 'pct': h.get('pct'), 'entry': h.get('entry'), 'hold_years': h['hold_years_asof'],
                                   'entry_basis': h.get('entry_basis'), 'deal_id': h.get('deal_id')})
            if h.get('possible_exit_deals'):
                row['status'] = 'in process'
                row['exit_deals'] = h['possible_exit_deals']
            if live:
                row.setdefault('_live', set()).add(s['name'])
    out = []
    for row in by_asset.values():
        y = max(x['hold_years'] for x in row['holders'])
        lead = max(row['holders'], key=lambda x: x['hold_years'])
        pts = 3 if y >= 10 else 2 if y >= 7 else 1 if y >= 5 else 0
        if pts:
            row['signals'].append({'points': pts, 'evidence': f"{lead['sponsor']} has held {y}y (entry {lead['entry']}, {lead['entry_basis']})", 'source': 'sponsor_universe.json'})
        for sp in sorted(row.pop('_live', [])):
            row['signals'].append({'points': 1, 'evidence': f'{sp} is running live sell-side processes now (Infralogic)', 'source': 'sponsor_universe.json'})
            break
        mino = [x for x in row['holders'] if x['pct'] is not None and x['pct'] < 50 and x['hold_years'] >= 5]
        if mino:
            m = mino[0]
            row['signals'].append({'points': 1, 'evidence': f"{m['sponsor']} minority {m['pct']}% held {m['hold_years']}y - typical sell-down window", 'source': 'sponsor_universe.json'})
        row['score'] = sum(s['points'] for s in row['signals'])
        row['max_hold_years'] = y
        row['tier'] = 'in process' if row['status'] == 'in process' else tier(row['score'])
        out.append(row)
    return sorted(out, key=lambda r: (r['status'] != 'in process', r['score'], r['max_hold_years']), reverse=True)


def seller_lane():
    sm = J('strategic_moves.json')['names']
    fg = J('funding_gap.json')['names']
    ss = J('stress_screen.json')['names']
    live = J('live_deals.json')['deals']
    out = []
    for t in sorted(sm):
        v, sig = sm[t], []
        flag = ((fg.get(t) or {}).get('gap') or {}).get('flag')
        if flag == 'divestiture_candidate':
            g = fg[t]['gap']
            sig.append({'points': 2, 'evidence': f"funding gap: divestiture candidate ({g.get('step_up_x')}x the run-rate, {g.get('stated_cov_pct')}% covered by the printed plan)", 'source': 'funding_gap.json'})
        elif flag == 'watch':
            sig.append({'points': 1, 'evidence': f"funding gap: watch ({fg[t]['gap'].get('step_up_x')}x the run-rate)" if fg[t]['gap'].get('step_up_x') else 'funding gap: watch (no run-rate to compare)', 'source': 'funding_gap.json'})
        for theme in ('monetization', 'simplification'):
            c = (v.get('call_talk') or {}).get(theme)
            if c and c.get('trend') in ('rising', 'new'):
                sig.append({'points': 1, 'evidence': f"{theme} talk {c['trend']} on recent calls ({c['calls']} calls, last {c['last']['period']})",
                            'source': 'strategic_moves.json', 'url': c['last'].get('url'), 'page': c['last'].get('page')})
        if (v.get('sells') or 0) >= 2:
            sig.append({'points': 1, 'evidence': f"active seller: {v['sells']} disposals since {J('strategic_moves.json').get('since', '2023')}", 'source': 'strategic_moves.json'})
        if v.get('minority_selldowns'):
            sig.append({'points': 1, 'evidence': f"{v['minority_selldowns']} minority sell-down(s) - capital recycling in use", 'source': 'strategic_moves.json'})
        st = (ss.get(t) or {}).get('tier')
        if st in ('high', 'elevated'):
            sig.append({'points': 2 if st == 'high' else 1, 'evidence': f"stress screen {st} ({', '.join(ss[t]['lenses'])})", 'source': 'stress_screen.json'})
        deals = [d for d in live if t in (d.get('tickers') or [])]
        score = sum(s['points'] for s in sig)
        recent = [m for m in (v.get('moves') or []) if m.get('kind') in ('asset sale', 'divestiture', 'minority sell-down')][:3]
        out.append({'ticker': t, 'posture': v.get('posture'), 'score': score, 'tier': tier(score), 'signals': sig,
                    'in_process': [{'id': d['id'], 'headline': d.get('headline'), 'status': d.get('status')} for d in deals],
                    'recent_sales': [{'date': m.get('date'), 'target': m.get('target'), 'counterparty': m.get('counterparty'), 'value_m': m.get('value_m')} for m in recent]})
    return sorted(out, key=lambda r: r['score'], reverse=True)


def main():
    doc = {'_schema_version': '1.0', '_generated': datetime.date.today().isoformat(),
           '_method': __doc__.split('Heuristic')[0].split('Two lanes,')[1].strip(),
           '_caveat': ('Heuristic ranking, not a probability. Sponsor hold ages come from the deal book (entry dates, some approximated); '
                       'an asset missing an exit in the book is not proof it is still held. Coverage-name scores reuse the funding-gap, '
                       'stress and call-talk signals, so they overlap with the Stress board by design.'),
           'sponsor_assets': sponsor_lane(), 'coverage_sellers': seller_lane()}
    p = os.path.join(DATA, 'transaction_screen.json')
    json.dump(doc, open(p, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    print('sponsor-held assets:')
    for r in doc['sponsor_assets'][:12]:
        print(f"  {r['tier']:10} {r['score']}  {r['max_hold_years']:5}y  {r['asset']}  <- {', '.join(h['sponsor'] for h in r['holders'])}")
    print('coverage sellers:')
    for r in doc['coverage_sellers']:
        print(f"  {r['tier']:7} {r['score']}  {r['ticker']:5} {'IN PROCESS ' if r['in_process'] else ''}{'; '.join(s['evidence'][:50] for s in r['signals'])}")
    print('wrote', p)


if __name__ == '__main__':
    main()
