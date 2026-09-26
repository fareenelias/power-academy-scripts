r"""build_strategic_moves.py - 'recent reorgs / moves signalling strategy' per name (roadmap I.I).

Joins three files that already exist into one dated strip per ticker since SINCE:
  capiq_export.json  ma_history   - acquisitions, divestitures, minority sell-downs (role, type, value)
  succession.json    changes/ceo  - C-suite and board arrivals/departures, new CEO (role start year)
  theme_screen.json  themes       - simplification / monetization / spin talk on the calls (count, trend, latest page)

and derives a posture label from the deal flow (net seller / net buyer / both / quiet) with the
counts that drove it. Nothing is inferred beyond what the three files state.

    python scripts\build_strategic_moves.py          (Windows default path)
    python scripts/build_strategic_moves.py <data_dir>
"""
import sys, os, json, datetime, collections

DATA = sys.argv[1] if len(sys.argv) > 1 else r'E:\PowerAcademy\data'
SINCE = 2023


def yr(mmYYYY):
    s = str(mmYYYY or '')
    return int(s[-4:]) if s[-4:].isdigit() else None


def main():
    capiq = json.load(open(os.path.join(DATA, 'capiq_export.json'), encoding='utf-8'))['companies']
    succ = json.load(open(os.path.join(DATA, 'succession.json'), encoding='utf-8')).get('names', {})
    themes_p = os.path.join(DATA, 'theme_screen.json')
    themes = json.load(open(themes_p, encoding='utf-8'))['tickers'] if os.path.exists(themes_p) else {}
    out = {}
    for t, co in sorted(capiq.items()):
        moves, buys, sells, stakes = [], 0, 0, 0
        seen = set()     # CapIQ prints one transaction twice when the company is both 'Seller' and 'Seller - Parent'
        for m in co.get('ma_history') or []:
            tid_ = m.get('transaction_id')
            if tid_ and tid_ in seen:
                continue
            seen.add(tid_)
            y = yr(m.get('announced'))
            if not y or y < SINCE:
                continue
            role = (m.get('role') or '')
            dt = m.get('deal_type') or ''
            if role.startswith('Seller'):
                kind = 'minority sell-down' if 'Minority' in dt else ('divestiture' if 'Whole' in dt else 'asset sale')
                sells += 1; stakes += 'Minority' in dt
            elif role.startswith(('Ultimate Buyer', 'Buyer')):
                kind = 'acquisition' if 'Whole' in dt else ('minority investment' if 'Minority' in dt else 'asset acquisition')
                buys += 1
            elif role.startswith('Target'):
                kind = 'company is the target'
            else:
                continue
            moves.append({'date': m.get('announced'), 'completed': m.get('completed'), 'kind': kind, 'target': m.get('target'),
                          'counterparty': m.get('buyer') if role.startswith('Seller') else m.get('seller'),
                          'value_m': m.get('value_m'), 'capacity_mw': m.get('capacity_mw'), 'sector': m.get('sector'),
                          'transaction_id': m.get('transaction_id')})
        # one sale placed with several investors (HE's American Savings Bank, 12/2024: 10 CapIQ rows) is ONE move
        grouped = collections.OrderedDict()
        for mv in moves:
            k = (mv['date'], (mv['target'] or '').rstrip('*').strip().lower(), mv['kind'])
            if k in grouped:
                g = grouped[k]
                g['counterparty'] = '; '.join(x for x in [g['counterparty'], mv['counterparty']] if x)
                g['value_m'] = round((g['value_m'] or 0) + (mv['value_m'] or 0), 1) if (g['value_m'] or mv['value_m']) else None
                g['legs'] = g.get('legs', 1) + 1
            else:
                grouped[k] = dict(mv)
        moves = list(grouped.values())
        buys = sum(1 for mv in moves if mv['kind'] in ('acquisition', 'minority investment', 'asset acquisition'))
        sells = sum(1 for mv in moves if mv['kind'] in ('minority sell-down', 'divestiture', 'asset sale'))
        stakes = sum(1 for mv in moves if mv['kind'] == 'minority sell-down')
        moves.sort(key=lambda x: (str(x['date'])[-4:], str(x['date'])[:2]), reverse=True)
        posture = ('net seller' if sells > buys and sells >= 2 else 'net buyer' if buys > sells and buys >= 2
                   else 'buyer and seller' if buys and sells else 'quiet' if not (buys or sells) else 'occasional')
        s = succ.get(t) or {}
        ch = s.get('changes') or {}
        people = []
        ceo = s.get('ceo') or {}
        if ceo.get('role_start_year') and ceo['role_start_year'] >= SINCE:
            people.append({'what': 'new CEO', 'who': ceo.get('name'), 'year': ceo['role_start_year']})
        for k, lab in (('exec_arrived', 'exec arrived'), ('exec_departed', 'exec departed'), ('board_joined', 'director joined'), ('board_departed', 'director left')):
            for p in ch.get(k) or []:
                people.append({'what': lab, 'who': p.get('name') if isinstance(p, dict) else p,
                               'title': p.get('title') if isinstance(p, dict) else None, 'since': ch.get('compared_to')})
        th = themes.get(t, {}).get('themes', {})
        talk = {}
        for tid in ('simplification', 'monetization'):
            x = th.get(tid) or {}
            if x.get('calls'):
                talk[tid] = {'calls': x['calls'], 'trend': x.get('trend'), 'last': x.get('last'), 'terms': x.get('terms')}
        signals = []
        if stakes:
            signals.append(f'{stakes} minority sell-down(s) since {SINCE} - capital recycling')
        if sells >= 2:
            signals.append(f'{sells} disposals since {SINCE}')
        if any(p['what'] == 'new CEO' for p in people):
            signals.append('CEO new since %d' % SINCE)
        for tid, x in talk.items():
            if x.get('trend') in ('rising', 'new'):
                signals.append(f"{tid} talk {x['trend']} on recent calls")
        out[t] = {'posture': posture, 'buys': buys, 'sells': sells, 'minority_selldowns': stakes,
                  'moves': moves, 'people': people, 'call_talk': talk, 'signals': signals}
    doc = {'_schema_version': '1.0', '_generated': datetime.date.today().isoformat(), 'since': SINCE,
           '_source': 'capiq_export.json ma_history + succession.json + theme_screen.json via scripts\\build_strategic_moves.py',
           '_caveat': ('CapIQ M&A rows include small asset deals and are month-precise; roles are as CapIQ prints them (Seller / Ultimate Buyer / '
                       'Buyer/Investor, "- Parent" rows counted with their base role). Posture: net seller/buyer needs >=2 deals on that side and '
                       'more than the other side. People changes cover the CapIQ pulls compared in succession.json only.'),
           'names': out}
    json.dump(doc, open(os.path.join(DATA, 'strategic_moves.json'), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    print(f'wrote strategic_moves.json: {len(out)} names')
    for t, v in out.items():
        print(f"  {t:5} {v['posture']:17} buys {v['buys']:>2} sells {v['sells']:>2} (minority {v['minority_selldowns']})  people {len(v['people'])}  | {'; '.join(v['signals'])}")


if __name__ == '__main__':
    main()
