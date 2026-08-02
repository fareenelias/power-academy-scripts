# -*- coding: utf-8 -*-
r"""Build the rolling consensus price-target series from broker_research.json.

Fareen, 2026-07-31: "many of these reports, like UBS or JPM provide their price targets
over time. this would be good to have as an average across all the covered brokers for
that name, plotted as a line chart. so if i see a dip in price targets, i know some news
happened that caused analysts to lose confidence."

So the series has to be a TRUE ROLLING CONSENSUS, not a scatter of individual targets:
on any given date, take each broker's most recent target as of that date and average
across brokers. A dip then means brokers actually cut, not that a low-target house
happened to publish that week.

Two sources feed it, and they matter differently:
  1. reports[].price_target        - one point per report on file (~161 across the book)
  2. reports[].pt_history.points[] - the rating/price-target history brokers are REQUIRED
     to disclose, mined 2026-07-31. ~847 dated points, and the reason the series has any
     shape at all before the reports on file begin.

  python3 build_pt_consensus.py <broker_research.json> <out pt_consensus.json>

Regenerate after any broker_research.json change. Writing the JSON deploys it -
server.js serves data\ directly.
"""
import json, sys, collections, datetime

SRC, OUT = sys.argv[1], sys.argv[2]

# A rolling consensus goes stale: a house that has not published in two years is not
# part of today's view of the name. Drop a broker's contribution this many days after
# its last dated target.
STALE_DAYS = 550
# Below this many contributing houses the "consensus" is one or two opinions, which is
# noise on a chart. Points are still emitted, with n, so the UI can grey them.
MIN_BROKERS = 2


def d(s):
    return datetime.date.fromisoformat(s)


def main():
    src = json.load(open(SRC, encoding='utf-8'))
    out = collections.OrderedDict()
    out['_schema_version'] = '1'
    out['_schema_note'] = (
        'Rolling consensus price target per ticker. On each date, each broker contributes '
        'its most recent target as of that date; a broker drops out '
        f'{STALE_DAYS} days after its last dated target. mean/median/low/high are across '
        'CONTRIBUTING BROKERS, not across reports, so a house publishing twice in a week '
        'does not get double weight. n = contributing houses. Sources: reports[].price_target '
        'plus the mined reports[].pt_history disclosure tables. USD only - AQN J.P. Morgan '
        'was converted from C$ at the Bank of Canada rate for its report date before entering '
        'this series; see fx_conversion on that report.')
    out['_generated_from'] = SRC
    companies = collections.OrderedDict()

    for tkr, v in src.items():
        if tkr.startswith('_') or not isinstance(v, dict) or 'reports' not in v:
            continue
        # broker -> {date: target}
        by_broker = collections.defaultdict(dict)
        n_rep = n_hist = 0
        for r in v['reports']:
            b = r.get('broker')
            if not b:
                continue
            # a CAD-quoted target must never enter a USD consensus
            if (r.get('currency') or 'USD').upper() != 'USD':
                continue
            if r.get('report_date') and r.get('price_target') is not None:
                by_broker[b][r['report_date']] = float(r['price_target'])
                n_rep += 1
            for p in (r.get('pt_history') or {}).get('points', []):
                dt, pt = p.get('date'), p.get('price_target')
                if not dt or pt is None:
                    continue
                # the report's own target wins over a history row for the same day
                by_broker[b].setdefault(dt, float(pt))
                n_hist += 1

        if not by_broker:
            continue

        # every date on which any broker moved
        dates = sorted({dt for m in by_broker.values() for dt in m})
        series = []
        for dt in dates:
            cur = []
            for b, m in by_broker.items():
                prior = [x for x in m if x <= dt]
                if not prior:
                    continue
                last = max(prior)
                if (d(dt) - d(last)).days > STALE_DAYS:
                    continue
                cur.append(m[last])
            if not cur:
                continue
            cur.sort()
            k = len(cur)
            med = cur[k // 2] if k % 2 else (cur[k // 2 - 1] + cur[k // 2]) / 2
            series.append(collections.OrderedDict([
                ('date', dt),
                ('mean', round(sum(cur) / k, 2)),
                ('median', round(med, 2)),
                ('low', round(cur[0], 2)),
                ('high', round(cur[-1], 2)),
                ('n', k),
                ('thin', k < MIN_BROKERS),
            ]))

        companies[tkr] = collections.OrderedDict([
            ('ticker', tkr),
            ('brokers', sorted(by_broker)),
            ('n_brokers', len(by_broker)),
            ('points_from_reports', n_rep),
            ('points_from_disclosure_tables', n_hist),
            ('first_date', series[0]['date'] if series else None),
            ('last_date', series[-1]['date'] if series else None),
            ('series', series),
        ])

    out['companies'] = companies
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print(f'wrote {OUT}')
    print(f'{"ticker":6} {"pts":>4} {"brokers":>7} {"from":>11} {"to":>11}   '
          f'{"first mean":>10} {"last mean":>9}  max n')
    for t, c in companies.items():
        s = c['series']
        if not s:
            print(f'{t:6} {0:>4}')
            continue
        print(f'{t:6} {len(s):>4} {c["n_brokers"]:>7} {c["first_date"]:>11} '
              f'{c["last_date"]:>11}   {s[0]["mean"]:>10} {s[-1]["mean"]:>9}  '
              f'{max(x["n"] for x in s)}')


main()
