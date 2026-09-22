#!/usr/bin/env python3
"""
build_guidance_history.py — Power Academy guidance history layer.

Builds data/guidance_history.json:  <TICKER> -> <period key> -> guidance fields
using the SAME field names as data/Guidance_ip.json, so the dashboard panel can
read one schema and the single-vintage file is simply the newest row.

Design rules (non-negotiable, see project tracker):
  * Every numeric cell carries the verbatim source sentence (`note` / `source_text`)
    plus source_id, source_page (from the [[PAGE N]] markers) and source_url.
  * capital_plan_total_b NEVER appears without capital_plan_years (the window).
  * Nothing is interpolated. A computed value is marked basis="derived" and says how.
  * Tickers with zero decks are ABSENT, not empty. Per-ticker `_coverage` is carried.
  * Merge-only + atomic write + before/after KEY DIFF printed on every run.

Usage:
  python3 scripts/build_guidance_history.py                 # all tickers, merge
  python3 scripts/build_guidance_history.py --tickers AEE,D # rebuild subset only
  python3 scripts/build_guidance_history.py --rebuild       # ignore existing file
"""
import argparse, json, os, re, sys, tempfile, collections
# Hardened dividend + equity extractors (2026-09-21): 29 controls, 10 tamper-proven
# guards, built from the QC sessions in which 10 of 61 workbook proposals were wrong.
from guidance_extractors import (dividend_from_text, equity_from_text, compose_equity_text,
                                 debt_from_text)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(BASE, 'guidance_index.json')
TEXT  = os.path.join(BASE, 'data', 'corpus', 'text')
OUT   = os.path.join(BASE, 'data', 'guidance_history.json')
FLAG  = os.path.join(BASE, 'guidance_flagged.json')

PERIOD_RULE = ("Period key = '<Qn> <YYYY>' of the reporting period, not the call date. "
               "Manifest 'FY YYYY' rows are the Q4 YYYY call held the following February and are "
               "normalised to 'Q4 YYYY'; verified no ticker lands its Q4 under two keys.")

# ---------------------------------------------------------------- text plumbing
PAGE_RE = re.compile(r'\[\[PAGE (\d+)\]\]')
_pc = {}
def pages(pid):
    if pid in _pc: return _pc[pid]
    with open(os.path.join(TEXT, pid + '.txt'), encoding='utf-8') as fh:
        parts = PAGE_RE.split(fh.read())
    v = [(int(parts[i]), parts[i+1]) for i in range(1, len(parts), 2)]
    _pc[pid] = v
    return v

def flat(s):
    return re.sub(r'\s+', ' ', s).strip()

def norm_period(p):
    q, y = p.split()
    return ('Q4 ' + y) if q == 'FY' else p

def pkey_sort(k):
    q, y = k.split()
    return (int(y), int(q[1]))

DASH = r'[\-‐‑‒–—―−]'
def win(a, b):
    a, b = int(a), int(b)
    if a < 100: a += 2000
    if b < 100: b += 2000
    return '%d-%d' % (a, b)

# ------------------------------------------------------------------ evidence
def find(pid, regexes, band=None, page_pred=None):
    """Run regexes (flattened page text) in priority order; return first hit list."""
    for rx, handler in regexes:
        hits = []
        for pno, body in pages(pid):
            fb = flat(body)
            if page_pred and not page_pred(fb):
                continue
            for m in re.finditer(rx, fb, re.I):
                out = handler(m)
                if out is None:
                    continue
                if band and not (band[0] <= out['value'] <= band[1]):
                    continue
                out['page'] = pno
                s = max(0, m.start() - 90); e = min(len(fb), m.end() + 90)
                out.setdefault('text', fb[s:e])
                hits.append(out)
        if hits:
            return hits
    return []

def cell(v, rec, deck, basis='printed', note=None, extra=None):
    d = {'value': v, 'basis': basis,
         'source_id': deck['id'], 'source_page': rec['page'], 'source_url': deck['url'],
         'source_text': rec['text'][:400]}
    if note: d['note'] = note
    if extra: d.update(extra)
    return d

# ============================================================ CAPITAL PLAN ====
# Per-ticker recipes. Each recipe is (regex, handler). Handlers return
# {'value':float,'window':str,'basis':str,'note':str|None}. First recipe that
# hits anywhere in the deck wins; among hits the one with the LATEST window start
# is taken (roll-forward slides print the prior plan alongside the new one).

def H(vg, w1, w2, basis='printed', note=None, mid=False, vg2=None):
    def h(m):
        g = m.groupdict()
        v = float(g[vg].replace(',', ''))
        b = basis; n = note
        if mid and g.get(vg2):
            hi = float(g[vg2].replace(',', ''))
            v = round((v + hi) / 2.0, 3)
            b = 'derived'
            n = ('midpoint of printed range $%s-$%sB' % (g[vg], g[vg2])) + (('; ' + note) if note else '')
        return {'value': v, 'window': win(g[w1], g[w2]) if w1 else g.get('wraw'),
                'basis': b, 'note': n}
    return h

def h_thru(vg, yg, basis='printed', note=None, vg2=None):
    def h(m):
        g = m.groupdict()
        v = float(g[vg]); b = basis; n = note
        if vg2 and g.get(vg2):
            v = round((v + float(g[vg2])) / 2.0, 3); b = 'derived'
            n = ('midpoint of printed range $%s-$%sB' % (g[vg], g[vg2])) + (('; ' + note) if note else '')
        return {'value': v, 'window': 'through %s' % g[yg], 'basis': b, 'note': n}
    return h

Y = r'(?:20)?(\d\d)'
W = (r'(?P<w1>20\d\d|’\d\d|\'\d\d)\s*(?:E|A)?\s*(?:%s|\s+through\s+|\s+to\s+)\s*'
     r'(?P<w2>20\d\d|’\d\d|\'\d\d)\s*(?:E|A)?') % DASH
def _w(m, k='w1', k2='w2'):
    try:
        g1, g2 = m.group(k), m.group(k2)
    except (IndexError, error_group):
        return None
    if not g1 or not g2:
        return None
    return win(re.sub(r'\D', '', g1), re.sub(r'\D', '', g2))
error_group = IndexError

def hw(vg, basis='printed', note=None, vg2=None):
    """handler for regexes using the shared W window group"""
    def h(m):
        g = m.groupdict(); v = float(g[vg]); b = basis; n = note
        if vg2 and g.get(vg2):
            v = round((v + float(g[vg2])) / 2.0, 3); b = 'derived'
            n = 'midpoint of printed range $%s-$%sB' % (g[vg], g[vg2]) + (('; ' + note) if note else '')
        return {'value': v, 'window': _w(m), 'basis': b, 'note': n}
    return h

AMT = r'~?\$\s?(?P<v>\d{1,3}(?:\.\d{1,2})?)'
AMT2 = (r'~?\$\s?(?P<v>\d{1,3}(?:\.\d{1,2})?)\s*(?:B|billion)?\s*(?:%s|to)\s*\$?\s?'
        r'(?P<v2>\d{1,3}(?:\.\d{1,2})?)') % DASH

NO_SLIDE_WINDOW = {'AWR'}   # rate-case slides carry several unrelated year ranges

CAP_BAND = {   # consolidated multi-year plan totals only; guards segment/project figures
 'AEE': (8, 60), 'CMS': (8, 45), 'ES': (10, 40), 'PCG': (30, 120), 'PPL': (8, 40),
 'EVRG': (5, 40), 'D': (25, 120), 'EIX': (10, 60), 'AWK': (5, 60), 'HTO': (0.8, 5),
 'WTRG': (3, 15), 'AQN': (2, 20), 'ETR': (8, 120), 'NEE': (30, 200), 'AWR': (0.05, 2),
 'CWT': (0.3, 3), 'XIFR': (0.5, 10), 'POR': (2, 15), 'HE': (0.5, 6),
}

CAP_RECIPES = {
 'AEE': [
   (W + r'\s+capital plan(?: of)?\s+' + AMT + r'\s*(?:B\b|billion)', hw('v')),
   (AMT + r'(?:\s+\$\d{1,3}(?:\.\d)?\+?)?\s+(?:5-Year\s+)?Investment Plan\s+' + W, hw('v')),
   (r'(?P<w1>20\d\d)' + DASH + r'(?P<w2>20\d\d)(?:\s+[A-Za-z][\w&,\.\- ]{0,120})?\s+' + AMT +
      r'\s+(?:5-Year\s+)?Investment Plan', hw('v')),
   (AMT + r'\s*(?:B\b|billion)[^$]{0,60}?(?:investment|capital) plan[^$]{0,40}?' + W, hw('v')),
 ],
 'CMS': [
   (AMT + r'\s*B?\s*utility capital investment plan\s*\(' + W + r'\)', hw('v')),
   (r'(?:Investment Plan|Capital Plan)[^$]{0,240}?' + AMT + r'\s*B\s*' + W, hw('v')),
   (r'5-yr Capital Plan[^$]{0,60}?' + AMT + r'\s*B?\b', lambda m: {'value': float(m.group('v')), 'window': None,
        'basis': 'printed', 'note': 'deck prints the 5-yr capital plan total on the outlook slide without the window'}),
 ],
 'ES': [
   (AMT + r'\s*(?:BILLION|Billion|billion)\s*' + W, hw('v')),
   (r'capital (?:investment )?plan of\s+' + AMT + r'\s*billion\s*(?:through|for)?\s*(?P<yr>20\d\d)?',
      lambda m: {'value': float(m.group('v')),
                 'window': ('through %s' % m.group('yr')) if m.group('yr') else None,
                 'basis': 'printed', 'note': None}),
   (r'Capital expenditures of\s+' + AMT + r'\s*billion[^.]{0,80}?' + W, hw('v')),
   (AMT + r'B Core Business Capital Investment Forecast',
      lambda m: {'value': float(m.group('v')), 'window': None, 'basis': 'printed',
                 'note': 'core business capital investment forecast; window on adjacent slide'}),
 ],
 'PCG': [
   (AMT + r'B\s+' + W + r'(?!\s*(?:E|A|F))', hw('v')),
   (r'Five[- ]Year Plan\s+' + W + r'\s*~?' + AMT + r'\s*B', hw('v')),
   (AMT + r'B (?:Five-Year )?Capital Plan', lambda m: {'value': float(m.group('v')), 'window': None,
        'basis': 'printed', 'note': None}),
   (r'Five[- ]Year \$?(?P<v>\d{1,3}(?:\.\d)?)B Capital Plan', lambda m: {'value': float(m.group('v')),
        'window': None, 'basis': 'printed'}),
   (r'CapEx Next 5 Years\s*' + AMT + r'B', lambda m: {'value': float(m.group('v')), 'window': None,
        'basis': 'printed', 'note': 'slide states the five-year CapEx total without printing the window'}),
 ],
 'PPL': [
   (r'capital plan to\s+' + AMT + r'\s*billion for\s+' + W, hw('v')),
   (AMT + r'B capex plan', lambda m: {'value': float(m.group('v')), 'window': None, 'basis': 'printed'}),
   (AMT + r'B capital investment plan', lambda m: {'value': float(m.group('v')), 'window': None, 'basis': 'printed'}),
   (r'Robust\s+' + AMT + r'B Regulated Utility Capital Plan From\s+' + W, hw('v')),
   (AMT + r'\s*billion capital investment plan', lambda m: {'value': float(m.group('v')), 'window': None, 'basis': 'printed'}),
   (r'capital plan of\s+' + AMT + r'\s*billion for\s+' + W, hw('v')),
   (AMT + r'\s*billion capital plan', lambda m: {'value': float(m.group('v')), 'window': None, 'basis': 'printed'}),
 ],
 'EVRG': [
   (AMT + r'B (?:of )?infrastructure investment\s+' + W, hw('v')),
   (AMT + r'\s*billion 5-year capital investment plan', lambda m: {'value': float(m.group('v')),
        'window': None, 'basis': 'printed'}),
   (AMT + r'\s*billion 5-year capital', lambda m: {'value': float(m.group('v')), 'window': None, 'basis': 'printed'}),
   (r'5-yr:\s*' + AMT + r'B', lambda m: {'value': float(m.group('v')), 'window': None, 'basis': 'printed'}),
   (r'Capital Expenditures\s+' + AMT + r'B\s+' + W, hw('v')),
 ],
 'D': [
   (r'capital plan\s+' + W + r'\s*:\s*' + AMT + r'\s*billion', lambda m: {
        'value': float(m.group('v')), 'window': _w(m), 'basis': 'printed'}),
   (W + r'\s+capital investment plan\s+' + AMT + r'\s*B', hw('v')),
   (W + r'\s*capital (?:investment )?plan\s*\(\$B\)\s*~?\$?(?P<v>\d{2,3}(?:\.\d)?)', hw('v')),
   (AMT + r'B 5-year growth capital', lambda m: {'value': float(m.group('v')), 'window': None, 'basis': 'printed'}),
   (r'5-year capital (?:plan|budget) of\s+' + AMT + r'B', lambda m: {'value': float(m.group('v')), 'window': None, 'basis': 'printed'}),
 ],
 'EIX': [
   (r'(?:Five-year )?capex plan of\s+' + AMT2 + r'\s*billion', hw('v', vg2='v2')),
   (r'(?:GRC underpins )?~?' + AMT2 + r'\s*billion\s+' + W + r'\s*capex forecast', hw('v', vg2='v2')),
   (W + r'\s*Capital Expenditures Plan\D{0,40}?(?:Five|Four|Three)-year capex plan of\s*~?' + AMT2 +
      r'\s*billion', hw('v', vg2='v2')),
 ],
 'AWK': [
   (r'five-?\s?year capital (?:investment )?plan of (?:approximately )?' + AMT2 + r'\s*billion',
      lambda m: {'value': round((float(m.group('v')) + float(m.group('v2'))) / 2.0, 3), 'window': None,
                 'basis': 'derived',
                 'note': 'midpoint of the printed five-year plan range $%s-$%sB' % (m.group('v'), m.group('v2'))}),
 ],
 'HTO': [
   (AMT + r'\s*billion in infrastructure investment planned (?:for )?' + W, hw('v')),
   (AMT + r'B (?:5-year )?capex', lambda m: {'value': float(m.group('v')), 'window': None, 'basis': 'printed'}),
   (r'5-Year CAPEX\s+' + AMT + r'B', lambda m: {'value': float(m.group('v')), 'window': None, 'basis': 'printed'}),
   (AMT + r'\s*billion\d?\s*5-year CapEx Plan', lambda m: {'value': float(m.group('v')), 'window': None, 'basis': 'printed'}),
   (r'(?:Five-year|5-year) CapEx[^$]{0,60}?' + AMT + r'\s*[Bb]', lambda m: {'value': float(m.group('v')), 'window': None, 'basis': 'printed'}),
   (AMT + r'\s*billion in next 5 years', lambda m: {'value': float(m.group('v')), 'window': None, 'basis': 'printed'}),
   (AMT + r'\s*billion planned over next five years', lambda m: {'value': float(m.group('v')), 'window': None, 'basis': 'printed'}),
 ],
 'WTRG': [
   (W + r'\s*Infrastructure investments of\s*~?' + AMT + r'B', hw('v')),
   (r'Infrastructure investments of\s*~?' + AMT + r'B', lambda m: {'value': float(m.group('v')), 'window': None, 'basis': 'printed'}),
 ],
 'AQN': [
   (r'~?' + AMT + r'\s*[Bb]illion Capital Investment Plan\s*(?:from|–|-)?\s*(?P<w1>20\d\d)\s*(?:through|%s)\s*(?P<w2>20\d\d)' % DASH, hw('v')),
   (AMT + r'\s*Billion Capital Investment Plan\s*%s\s*(?P<w1>20\d\d)\s*through\s*(?P<w2>20\d\d)' % DASH, hw('v')),
   (AMT + r'\s*Billion Total Regulated Capital Investment Planned From\s*' + W, hw('v')),
 ],
 'ETR': [
   (r'(?P<w1>(?:20)?\d\d)E\s*' + DASH + r'\s*(?P<w2>(?:20)?\d\d)E\s*(?:\d-year |four-year |five-year )?capital plan'
      r'(?: by function)?\d?[\s\S]{0,420}?\$(?P<v>\d{2,3})B',
      lambda m: {'value': float(m.group('v')), 'window': win(m.group('w1'), m.group('w2')), 'basis': 'printed',
                 'note': 'headline total printed on the capital-plan-by-function slide'}),
   (r'(?<!Adding )' + AMT + r'\s*(?:B\b|billion)[^$]{0,40}?capital plan', lambda m: {'value': float(m.group('v')), 'window': None, 'basis': 'printed'}),
   (r'capital plan[^$]{0,40}?' + AMT + r'\s*(?:B\b|billion)', lambda m: {'value': float(m.group('v')), 'window': None, 'basis': 'printed'}),
 ],
 'NEE': [
   (r'plans to invest\s*~?\$\s?(?P<v>\d{2,3})\s*(?:%s|to)\s*\$\s?(?P<v2>\d{2,3})\s*(?:B\b|billion)\s*through\s*(?P<yr>20\d\d)' % DASH,
      h_thru('v', 'yr', note='Florida Power & Light (FPL) only, not consolidated NextEra', vg2='v2')),
   (r'plans to invest\s*~?' + AMT + r'\s*billion from\s*' + W,
      hw('v', note='Florida Power & Light (FPL) only, not consolidated NextEra')),
 ],
 'AWR': [
   (r'(?:new )?rates for the years (?P<w1>20\d\d), 20\d\d and (?P<w2>20\d\d)[\s\S]{0,200}?'
      r'capital budget requests of approximately \$?(?P<v>\d{3}(?:\.\d)?) million',
      lambda m: {'value': round(float(m.group('v')) / 1000.0, 4), 'window': win(m.group('w1'), m.group('w2')),
                 'basis': 'printed',
                 'note': 'GSWC capital budget REQUESTED in the GRC for that rate cycle (not yet authorised); excludes BVES'}),
   (r'rates for (?:the years )?(?P<w1>20\d\d)\s*' + DASH + r'\s*(?P<w2>20\d\d)[\s\S]{0,260}?'
      r'(?:invest|investment of|investment in capital infrastructure of)\s*\$?(?P<v>\d{3}(?:\.\d)?) million',
      lambda m: {'value': round(float(m.group('v')) / 1000.0, 4), 'window': win(m.group('w1'), m.group('w2')),
                 'basis': 'printed',
                 'note': 'GSWC CPUC-authorised capital infrastructure over the GRC rate cycle; excludes BVES'}),
   (r'invest(?:ment of|)?\s*\$?(?P<v>\d{3}(?:\.\d)?) million in capital infrastructure over (?:the |a )?three-year capital cycle',
      lambda m: {'value': round(float(m.group('v')) / 1000.0, 4), 'window': None, 'basis': 'printed',
                 'note': 'GSWC CPUC-authorised capital infrastructure over the GRC rate cycle; excludes BVES'}),
   (r'investment in capital infrastructure of \$?(?P<v>\d{3}(?:\.\d)?) million over a three-year capital cycle',
      lambda m: {'value': round(float(m.group('v')) / 1000.0, 4), 'window': None, 'basis': 'printed',
                 'note': 'GSWC CPUC-authorised capital infrastructure over the GRC rate cycle; excludes BVES'}),
   (r'requested capital budgets of (?:approximately )?\$?(?P<v>\d{3}(?:\.\d)?) million',
      lambda m: {'value': round(float(m.group('v')) / 1000.0, 4), 'window': None, 'basis': 'printed',
                 'note': 'GSWC capital budget REQUESTED in pending GRC (not yet authorised); excludes BVES'}),
   (r'capital budget requests of approximately \$?(?P<v>\d{3}(?:\.\d)?) million',
      lambda m: {'value': round(float(m.group('v')) / 1000.0, 4), 'window': None, 'basis': 'printed',
                 'note': 'GSWC capital budget REQUESTED in pending GRC (not yet authorised); excludes BVES'}),
 ],
 'CWT': [
   (r'\$?(?P<v>1\.\d\d)B TOTAL CAPITAL', lambda m: {'value': float(m.group('v')), 'window': None,
        'basis': 'printed', 'note': 'California GRC-authorised total capital investments over the rate cycle'}),
   (r'REQUESTING \$?(?P<v>\d\.\d\d)B CAPITAL SPENDING\s*' + W, hw('v',
        note='California GRC capital spending REQUESTED (not yet authorised)')),
 ],
 'XIFR': [
   (r'through (?P<yr>20\d\d)[\s\S]{0,120}?capex for [\s\S]{0,40}?program is now \$\s?(?P<v>\d\.\d)\s*B to '
      r'\$\s?(?P<v2>\d\.\d)\s*B',
      h_thru('v', 'yr', note='wind repowering programme capex only; XPLR states no consolidated multi-year utility capital plan', vg2='v2')),
 ],
 # POR / HE: no $B plan total is printed; annual capex bars in $M are (see ANNUAL_SUM)
 'POR': [
   (r'(?:over |approximately |~)?\$\s?(?P<v>\d{1,2}(?:\.\d)?)B of capital expenditures forecasted through '
      r'(?P<yr>20\d\d)', h_thru('v', 'yr')),
 ],
 'HE': [],
 # TLN / VST: merchant IPPs. Their "capital allocation plan" is a capital-RETURN
 # plan (buybacks/dividends/debt), NOT a capex plan -> capital_plan_total_b stays null.
 'TLN': [], 'VST': [],
}

# ---- annual capex bar charts in $M -> DERIVED multi-year total ---------------
ANNUAL_SUM = {
  'POR': dict(anchor=r'Capital expenditures? forecast', lo=80, hi=2600),
  'HE':  dict(anchor=r'Capital Expenditures? Forecast', lo=80, hi=1200),
  'EIX': dict(anchor=r'Capital Expenditures, \$ in Billions', lo=0.5, hi=15, unit='B'),
}
BAREV = re.compile(r'\$\s?(\d{1,3}(?:,\d{3})?(?:\.\d{1,2})?)')

def annual_total(pid, cfg, min_year=0):
    """Sum a PRINTED per-year capex TOTALS row.

    Only fires when the slide actually prints a totals row: the last run of k
    values before the k year labels must sum to exactly the sum of every other
    money token in that block (i.e. it is the column-total row, not one category
    row). If that self-check fails the deck gets a null rather than a number
    assembled out of one category's bars — this check exists because the naive
    version produced plausible, wrong five-year totals for POR and HE.
    """
    out = []
    for pno, body in pages(pid):
        fb = flat(body)
        if not re.search(cfg['anchor'], fb, re.I):
            continue
        yrs = [(int(m.group(1)), m.start()) for m in re.finditer(r'\b(20[2-3]\d)\s*E?\b', fb)]
        runs = []; cur = []
        for y, pos in yrs:
            if cur and y == cur[-1][0] + 1: cur.append((y, pos))
            else:
                if len(cur) >= 4: runs.append(cur)
                cur = [(y, pos)]
        if len(cur) >= 4: runs.append(cur)
        toks = [(float(m.group(1).replace(',', '')), m.start()) for m in BAREV.finditer(fb)]
        for run in runs:
            if run[0][0] < min_year:
                continue
            k = len(run); sp = run[0][1]
            pre = [t for t in toks if t[1] < sp]
            if len(pre) < 2 * k:
                continue
            tot = [t[0] for t in pre[-k:]]
            rest = [t[0] for t in pre[:-k]]
            if not all(cfg['lo'] <= v <= cfg['hi'] for v in tot):
                continue
            if abs(sum(tot) - sum(rest)) > max(2.0, 0.005 * sum(tot)):
                continue                      # last run is NOT the printed totals row
            unit = cfg.get('unit', 'M')
            val = sum(tot) if unit == 'B' else sum(tot) / 1000.0
            out.append({'value': round(val, 3), 'window': win(run[0][0], run[-1][0]), 'basis': 'derived',
                        'note': 'sum of the PRINTED annual capex-forecast TOTALS row (%s $%s) = $%gB; the deck '
                                'prints no multi-year total. Totals row verified: it equals the sum of every '
                                'other bar on the slide.'
                                % (unit, ' + '.join('%g' % v for v in tot), round(val, 3)),
                        'page': pno, 'text': fb[max(0, pre[-k][1] - 120): run[-1][1] + 30]})
    return out


# ---- ETR: consolidated "Total Utility ... Total" row of the capital-plan table
def etr_table(pid):
    out = []
    for pno, body in pages(pid):
        fb = flat(body)
        m = re.search(r'(?P<w1>20\d\d)\s*%s\s*(?P<w2>20\d\d)\s+Utility (?:three|four|five)-year capital plan|(?:Three|Four|Five)-year Utility capital plan' % DASH, fb, re.I)
        if not m: continue
        t = re.search(r'Total Utility.*?Total\s+((?:[\d,]+\s+){2,6})', fb)
        if not t: continue
        nums = [float(x.replace(',', '')) for x in t.group(1).split()]
        grand = nums[-1]
        if abs(sum(nums[:-1]) - grand) > max(5.0, 0.01 * grand):   # last col must be the row total
            continue
        w = _w(m) if m.groupdict().get('w1') else None
        if w is None:
            yl = re.findall(r'\b(20[2-3]\d)E\b', fb)
            if yl: w = win(min(yl), max(yl))
        out.append({'value': round(grand / 1000.0, 3), 'window': w, 'basis': 'printed',
                    'note': 'consolidated "Total Utility / Total" row of the multi-year capital-plan table ($M); '
                            'the deck states no $B headline total in this vintage',
                    'page': pno, 'text': flat(t.group(0))[:300]})
    return out

WIN_ON_SLIDE = re.compile(r"(?:20(\d\d)|[’'](\d\d))\s*(?:E|A)?\s*(?:%s)\s*(?:20(\d\d)|[’'](\d\d))\s*(?:E|A)?" % DASH)
def slide_window(fb, a, b, radius=320):
    """Exactly one distinct plan window on the slide near the match -> use it. Else None."""
    seg = fb[max(0, a - radius): b + radius]
    ws = set()
    for m in WIN_ON_SLIDE.finditer(seg):
        x = m.group(1) or m.group(2); y = m.group(3) or m.group(4)
        x = int(x) + 2000 if len(x) == 2 else int(x)
        y = int(y) + 2000 if len(y) == 2 else int(y)
        if 2019 <= x <= 2036 and 0 < y - x <= 12:
            ws.add('%d-%d' % (x, y))
    return list(ws)[0] if len(ws) == 1 else None


RANGE_RE = re.compile(r'\$\s?(\d{1,3}(?:\.\d)?)\s*' + DASH + r'\s*\$?\s?(\d{1,3}(?:\.\d)?)')
def awk_plan(pid):
    """AWK prints its capital plan as a stack of RANGES on one slide: regulated
    system investments + regulated acquisitions = the five-year total, and the
    same again for the ten-year total. Layouts differ by vintage, so:
      * the five-year total is the first range that equals the sum of the two
        ranges before it (or, in the 2021 layout, the sum of the first pair);
      * the window is the five-span window label with the LATEST start on the
        slide (later vintages print the prior plan alongside the new one)."""
    out = []
    for pno, body in pages(pid):
        fb = flat(body)
        if not re.search(r'Capital Plan \(\$ in billions\)|five-\s?year capital investment plan', fb, re.I):
            continue
        rs = [(float(m.group(1)), float(m.group(2)), m.start()) for m in RANGE_RE.finditer(fb)]
        w5 = []
        for m in re.finditer(r'(20[2-3]\d)\s*(?:%s)\s*(20[2-3]\d)' % DASH, fb):
            x, y = int(m.group(1)), int(m.group(2))
            if y - x == 4:
                w5.append(('%d-%d' % (x, y), m.start()))
        if not rs or not w5:
            continue
        tot = None
        for k in range(2, len(rs)):
            if abs(rs[k - 2][0] + rs[k - 1][0] - rs[k][0]) <= 0.55 and \
               abs(rs[k - 2][1] + rs[k - 1][1] - rs[k][1]) <= 0.55:
                tot = (rs[k], rs[k - 2], rs[k - 1]); break
        if tot is None and len(rs) >= 3:
            for k in range(2, len(rs)):
                if abs(rs[0][0] + rs[1][0] - rs[k][0]) <= 0.55 and abs(rs[0][1] + rs[1][1] - rs[k][1]) <= 0.55:
                    tot = (rs[k], rs[0], rs[1]); break
        if tot is None:
            continue
        t, sys_, acq = tot
        w = sorted(w5, key=lambda x: x[0])[-1][0]
        out.append({'value': round((t[0] + t[1]) / 2.0, 3), 'window': w, 'basis': 'derived',
                    'note': 'deck prints the five-year plan as a RANGE $%g-$%gB (regulated system investments '
                            '$%g-$%gB + regulated acquisitions $%g-$%gB); value stored is the midpoint of the '
                            'printed range' % (t[0], t[1], sys_[0], sys_[1], acq[0], acq[1]),
                    'page': pno, 'text': fb[max(0, min(sys_[2], t[2]) - 60): max(t[2], acq[2]) + 260]})
    return out


def capital_plan(tk, deck):
    """All recipes are run. The VALUE comes from the highest-priority recipe that
    hits (latest window / largest total among its hits). The WINDOW may be taken
    from any other hit that prints the SAME total together with its window."""
    pid = deck['id']
    by_rank = []
    for rank, (rx, h) in enumerate(CAP_RECIPES.get(tk, [])):
        if h is None:
            continue
        found = []
        for pno, body in pages(pid):
            fb = flat(body)
            for m in re.finditer(rx, fb, re.I):
                r = h(m)
                if r is None:
                    continue
                bnd = CAP_BAND.get(tk)
                if bnd and not (bnd[0] <= r['value'] <= bnd[1]):
                    continue
                r['page'] = pno
                r['rank'] = rank
                r['text'] = fb[max(0, m.start() - 100): m.end() + 110]
                if not r.get('window') and tk not in NO_SLIDE_WINDOW:
                    w = slide_window(fb, m.start(), m.end())
                    if w:
                        r['window'] = w
                        r['note'] = ((r.get('note') + '; ') if r.get('note') else '') + \
                            'window read from the same slide (%s)' % w
                found.append(r)
        if found:
            by_rank.append(found)
    every = [h for grp in by_rank for h in grp]
    if tk == 'AWK':
        every = every + awk_plan(pid)      # always available for window enrichment
    hits = by_rank[0] if by_rank else []
    if not hits and tk == 'AWK':
        hits = every = awk_plan(pid)
    if not hits and tk == 'ETR':
        hits = every = etr_table(pid)
    if not hits and tk in ANNUAL_SUM:
        fy = int(deck['period'].split()[-1])
        hits = every = annual_total(pid, ANNUAL_SUM[tk], min_year=fy)
    if not hits:
        return None, []

    def kk(r):
        w = r.get('window') or ''
        m = re.match(r'(\d{4})', w)
        start = int(m.group(1)) if m else -1
        thru = re.match(r'through (\d{4})', w)
        end = int(thru.group(1)) if thru else (int(w.split('-')[1]) if '-' in w else -1)
        return (start, end, r['value'])
    hits.sort(key=kk)
    best = dict(hits[-1])
    if not best.get('window'):
        same = [h for h in every if abs(h['value'] - best['value']) < 1e-9 and h.get('window')]
        if same:
            same.sort(key=kk)
            best['window'] = same[-1]['window']
            best['window_basis'] = ('same deck, slide p%d, which prints the same $%gB total with its window'
                                    % (same[-1]['page'], best['value']))
        else:
            v = best['value']
            vre = re.compile(r'\$\s?%s\s*(?:B\b|billion)' % re.escape(('%g' % v)), re.I)
            found = {}
            for pno, body in pages(pid):
                fb = flat(body)
                for m in vre.finditer(fb):
                    w = slide_window(fb, m.start(), m.end(), radius=200)
                    if w:
                        found.setdefault(w, pno)
            if len(found) == 1:
                w, pno = list(found.items())[0]
                best['window'] = w
                best['window_basis'] = ('elsewhere in the SAME deck (p%d) the identical $%gB total is printed '
                                        'next to exactly one plan window (%s)' % (pno, v, w))
    others = [h for h in every
              if (round(h['value'], 3), h.get('window')) != (round(best['value'], 3), best.get('window'))]
    seen = set(); od = []
    for o in others:
        k = (round(o['value'], 3), o.get('window'))
        if k in seen: continue
        seen.add(k); od.append(o)
    return best, od


# ============================================================ OTHER FIELDS ====
EPS_RANGE = re.compile(r'\$\s?(?P<lo>\d{1,2}\.\d{2})\s*(?:%s|to)\s*\$?\s?(?P<hi>\d{1,2}\.\d{2})' % DASH)
SEGMENT = re.compile(r'(?i)(virginia|south carolina|contracted energy|segment|subsidiar|opco|by business|'
                     r'kentucky|pennsylvania|rhode island|ameren missouri|ameren illinois)')
def eps_guidance(tk, deck):  # noqa: C901
    """All $X.XX-$Y.YY ranges in the deck, scored on their slide context. The
    highest-scoring one wins; ties go to the earliest slide (headline guidance
    is printed early). Segment-level EPS ranges are pushed down hard - that is
    exactly how a wrong-but-plausible EPS cell gets created."""
    fy = int(deck['period'].split()[-1])
    cands = []
    for pno, body in pages(deck['id']):
        fb = flat(body)
        for m in EPS_RANGE.finditer(fb):
            lo, hi = float(m.group('lo')), float(m.group('hi'))
            if not (0.2 <= lo < hi <= 30) or (hi - lo) > 0.35 * lo:
                continue
            pre = fb[max(0, m.start() - 150): m.start()]
            post = fb[m.end(): m.end() + 90]
            sc = 0
            if re.search(r'(?i)guidance|forecast range|outlook|targeting', pre[-100:] + post[:40]): sc += 3
            if re.search(r'(?i)EPS|earnings per share|per diluted share|per share', pre[-130:] + post[:60]): sc += 2
            if re.search(r'(?i)dividend|DPS|rate base|revenue|O&M|capital', pre[-60:]): sc -= 5
            if SEGMENT.search(pre[-110:]): sc -= 5
            if sc <= 2:
                continue
            yrs = [y for y in re.findall(r'\b(20[2-3]\d)\b', pre[-90:] + ' ' + post[:60])
                   if int(y) in (fy, fy + 1)]
            cands.append(((sc, -pno), {'year': yrs[-1] if yrs else None, 'low': lo, 'high': hi,
                                       'midpoint': round((lo + hi) / 2.0, 4), 'basis': 'printed', 'page': pno,
                                       'text': fb[max(0, m.start() - 130): m.end() + 90]}))
    if not cands:
        return None
    cands.sort(key=lambda c: c[0], reverse=True)
    top = cands[0]
    rivals = [c for c in cands[1:]
              if c[0] == top[0] and c[1]['page'] == top[1]['page']
              and (c[1]['low'], c[1]['high']) != (top[1]['low'], top[1]['high'])]
    if rivals:
        # two equally-supported ranges on the SAME slide (e.g. prior-year result
        # printed beside next-year guidance). Refuse to guess.
        return {'ambiguous': [(c[1]['low'], c[1]['high']) for c in [top] + rivals][:4],
                'page': top[1]['page'], 'text': top[1]['text']}
    return top[1]


# LOAD-GROWTH COLLISION GUARD (2026-09-21b). The drift layer caught three POR cells
# where this extractor stored a LOAD-growth range as the LT EPS algorithm: the old
# gap class [^.]{0,70} let a load-growth range bridge across intervening percent
# figures to a later "...EPS growth" anchor. Two changes, both proven by the
# embedded controls below (real slide texts, incl. all three POR defects):
#   1. the gap between the range and the EPS anchor may not contain another '%'
#      ([^.%] instead of [^.]) - a bridge across a different figure is refused;
#   2. the lookback before the range (truncated at the previous % figure) may not name a colliding metric (load
#      growth / dividend / payout / rate base) - "load growth of 2.5% to 3.0%
#      supporting EPS growth" is refused even with a clean gap.
# A refused match is SKIPPED, not fatal - scanning continues, so the slide's real
# algorithm range (which has a clean gap) still lands.
_LT_COLLIDE = re.compile(r'load\s+growth|dividend|payout|rate\s+base', re.I)

def lt_growth_scan(fb):
    """Per-text LT-EPS-growth scan; module-level so the controls can run on strings."""
    rx = (r'(?P<lo>\d{1,2}(?:\.\d)?)\s*%\s*(?:' + DASH + r'|to|-)\s*(?P<hi>\d{1,2}(?:\.\d)?)\s*%[^.%]{0,70}?'
          r'(?:EPS|earnings per share|adjusted EPS)[^.%]{0,30}?(?:CAGR|growth)')
    rx2 = (r'(?:EPS|earnings per share)[^.%]{0,40}?(?:CAGR|growth)[^.%]{0,40}?(?P<lo>\d{1,2}(?:\.\d)?)\s*%'
           r'\s*(?:' + DASH + r'|to|-)\s*(?P<hi>\d{1,2}(?:\.\d)?)\s*%')
    for r_ in (rx, rx2):
        for m in re.finditer(r_, fb, re.I):
            lo, hi = float(m.group('lo')), float(m.group('hi'))
            if not (0 < lo < hi <= 20): continue
            pre = fb[max(0, m.start('lo') - 45): m.start('lo')]
            # A '%' between the collide word and our range means the collide word
            # governs THAT earlier figure, not ours - truncate the lookback there
            # (found by control 2: 'load growth of 2.5% to 3.0% Re-affirming 4% to
            # 6% ... EPS growth' must keep its true 4-6 match).
            cut = pre.rfind('%')
            if cut >= 0: pre = pre[cut + 1:]
            if _LT_COLLIDE.search(pre): continue
            seg = fb[max(0, m.start() - 140): m.end() + 160]
            by = re.search(r'(?:off|from|using|base(?:d)? (?:off|on)|vs\.?)[^.]{0,60}?(20\d\d)', seg)
            thru = re.search(r'through (?:at least )?(20\d\d)', seg)
            return {'rate_low_pct': lo, 'rate_high_pct': hi,
                    'base_year': by.group(1) if by else None,
                    'through_year': thru.group(1) if thru else None,
                    'basis': 'printed',
                    'text': fb[max(0, m.start() - 120): m.end() + 120]}
    return None

def lt_growth(tk, deck):
    pid = deck['id']
    for pno, body in pages(pid):
        r = lt_growth_scan(flat(body))
        if r:
            r['page'] = pno
            return r
    return None

# Embedded controls - REAL slide texts. The three POR defects must resolve to the
# printed algorithm (or nothing), never to the load-growth range; the true
# positives must keep extracting. Runs at import; a failure refuses the build.
_LT_CONTROLS = [
    # (text, expected (lo,hi) or None-means-must-not-equal-forbidden)
    ("dance to $2.70 to $2.85 per diluted share from $2.55 to $2.70 per diluted share \u2022 2021 load growth to 2.5% to 3.0% from 1% to 1.5% Reaffirming \u2022 4% to 6% long-term EPS growth, 2019 base year \u2022 5% to 7% long-term dividend growth", (4.0, 6.0)),
    ("challenging power markets High-tech and digital growth + Sustained residential demand Re-affirming 2021 load growth of 2.5% to 3.0% Re-affirming 4% to 6% long-term EPS growth Re-affirming full year 2021 EPS guidance of $2.70 to $2.85 per diluted share", (4.0, 6.0)),
    ("rming \u2022 2026 adjusted earnings guidance of $3.33 to $3.53 per diluted share \u2022 2026 weather normalized load growth of 1.5% - 2.5% and long-term load growth of 3% through 2030 \u2022 Long-term EPS growth of 5% to 7% from 2024 adjusted EPS guidance midpoint", (5.0, 7.0)),
    ("load growth of 2.5% to 3.0% supporting EPS growth over the plan", None),
    ("Strong 5% to 7% adjusted EPS growth Expect dividend growth rate in line with EPS growth", (5.0, 7.0)),
    ("Expect 6% to 8% EPS CAGR from 2021-2025 Using 2021 EPS guidance midpoint", (6.0, 8.0)),
    ("Reaffirming adjusted EPS growth target of 4% to 6% through 2026 off the original 2023 adjusted EPS guidance midpoint of $3.65", (4.0, 6.0)),
]

def _run_lt_controls():
    for txt, want in _LT_CONTROLS:
        got = lt_growth_scan(txt)
        pair = (got['rate_low_pct'], got['rate_high_pct']) if got else None
        if want is None:
            assert pair is None, 'LT CONTROL FAILED (should refuse): %r -> %r' % (txt[:60], pair)
        else:
            assert pair == want, 'LT CONTROL FAILED: %r -> %r, want %r' % (txt[:60], pair, want)

_run_lt_controls()

def rate_base(tk, deck):
    pid = deck['id']
    pats = [
      r'~?(?P<r>\d{1,2}(?:\.\d)?)\s*%\s*(?:compound annual )?rate base (?:CAGR|growth)[^.]{0,40}?' + W,
      r'rate base (?:CAGR|growth)[^.]{0,30}?' + W + r'[^.]{0,25}?~?(?P<r>\d{1,2}(?:\.\d)?)\s*%',
      W + r'[^.]{0,40}?rate base[^.]{0,30}?CAGR[^.]{0,20}?~?(?P<r>\d{1,2}(?:\.\d)?)\s*%',
      r'~?(?P<r>\d{1,2}(?:\.\d)?)\s*%\s*rate base CAGR\s*' + W,
    ]
    for rx in pats:
        for pno, body in pages(pid):
            fb = flat(body)
            for m in re.finditer(rx, fb, re.I):
                r = float(m.group('r'))
                if not (2 <= r <= 20): continue
                w = _w(m)
                a, b = w.split('-')
                return {'rate_pct': r, 'from_year': int(a), 'to_year': int(b), 'basis': 'printed',
                        'page': pno, 'text': fb[max(0, m.start() - 110): m.end() + 110]}
    return None

def dividend(tk, deck):
    """Delegates to scripts/guidance_extractors.py (2026-09-21). The old inline
    regex took the FIRST money token after 'annual dividend' and stored the EPS
    on two-metric slides — 17 of its 58 values were wrong (QC 08-06 -> 09-21)."""
    for pno, body in pages(deck['id']):
        v, ev, tier = dividend_from_text(flat(body))
        if v is not None:
            return {'current_annual': v, 'basis': 'printed', 'page': pno,
                    'text': ev[:400]}
    return None

def equity_plan(tk, deck):
    """Delegates to scripts/guidance_extractors.py (2026-09-21). Labels ATM
    program capacity / increments (caveat PREFIXED so it survives note
    truncation), records the plan window, and refuses executed actuals,
    printed ranges and credit-facility figures."""
    for pno, body in pages(deck['id']):
        v, kind, window, ev = equity_from_text(flat(body))
        if v is not None:
            return {'equity_b': v, 'basis': 'printed', 'page': pno,
                    'text': compose_equity_text(kind, window, ev)}
    return None

def debt_plan(tk, deck):
    """Debt-financing plan figures (the §4.3 denominator's other half), added
    2026-09-21 — debt_b was previously None BY CONSTRUCTION. Guards: maturities
    schedules, bridge deltas, executed/refinanced/repaid, ranges. $M table
    values are converted with the conversion stated in the text."""
    for pno, body in pages(deck['id']):
        v, window, ev = debt_from_text(flat(body))
        if v is not None:
            return {'debt_b': v, 'basis': 'printed', 'page': pno, 'text': ev}
    return None

# =================================================================== BUILD ====
def build_row(tk, deck):
    row = {'source': deck['title'], 'source_date': deck['date'], 'source_id': deck['id'],
           'source_url': deck['url'], 'pages': deck['pages']}
    flags = []

    cp, others = capital_plan(tk, deck)
    if cp:
        row['capital_plan_total_b'] = cp['value']
        row['capital_plan_years'] = cp.get('window')
        row['capital_plan_basis'] = cp.get('basis', 'printed')
        row['capital_plan_source_page'] = cp['page']
        row['capital_plan_source_text'] = flat(cp['text'])[:400]
        row['capital_plan_note'] = cp.get('note')
        if others:
            row['capital_plan_other_figures'] = [
                {'value_b': o['value'], 'years': o.get('window'), 'page': o['page']} for o in others[:4]]
        if not cp.get('window'):
            flags.append(dict(field='capital_plan_years', candidate=flat(cp['text'])[:300],
                              page=cp['page'],
                              issue='plan total $%gB is printed but the deck slide does not print the plan window '
                                    'next to it; window must be confirmed before this level is compared across vintages'
                                    % cp['value']))
    else:
        row['capital_plan_total_b'] = None
        row['capital_plan_years'] = None
        row['capital_plan_basis'] = None
        row['capital_plan_note'] = 'no multi-year capital plan total stated in this deck'

    e = eps_guidance(tk, deck)
    if e and e.get('ambiguous'):
        flags.append(dict(field='eps_guidance', candidate=flat(e['text'])[:300], page=e['page'],
                          issue='the slide prints %s equally-supported EPS ranges side by side (%s); the column '
                                'layout does not say which is the guidance year, so no value was written'
                                % (len(e['ambiguous']),
                                   '; '.join('$%.2f-$%.2f' % r for r in e['ambiguous']))))
        e = None
    row['eps_guidance'] = ({'year': e['year'], 'low': e['low'], 'high': e['high'],
                            'midpoint': e['midpoint'], 'basis': 'printed',
                            'source_page': e['page'], 'note': flat(e['text'])[:300]}
                           if e else {'year': None, 'low': None, 'high': None,
                                      'midpoint': None, 'basis': None, 'note': 'not stated in this deck'})
    # (a missing guidance-year label is NOT flagged: the value is recorded, the
    #  period key identifies the call, and flagging it buried the real questions)

    g = lt_growth(tk, deck)
    row['lt_eps_growth'] = ({'rate_low_pct': g['rate_low_pct'], 'rate_high_pct': g['rate_high_pct'],
                             'base_year': g['base_year'], 'through_year': g['through_year'],
                             'basis': 'printed', 'source_page': g['page'], 'note': flat(g['text'])[:300]}
                            if g else {'rate_low_pct': None, 'rate_high_pct': None, 'base_year': None,
                                       'through_year': None, 'basis': None, 'note': 'not stated in this deck'})
    rb = rate_base(tk, deck)
    row['rate_base_cagr'] = ({'rate_pct': rb['rate_pct'], 'from_year': rb['from_year'],
                              'to_year': rb['to_year'], 'basis': 'printed',
                              'source_page': rb['page'], 'note': flat(rb['text'])[:300]}
                             if rb else {'rate_pct': None, 'from_year': None, 'to_year': None,
                                         'basis': None, 'note': 'not stated in this deck'})
    dv = dividend(tk, deck)
    row['dividend_guidance'] = ({'current_annual': dv['current_annual'], 'growth_rate_pct': None,
                                 'basis': 'printed', 'source_page': dv['page'], 'note': flat(dv['text'])[:250]}
                                if dv else {'current_annual': None, 'growth_rate_pct': None,
                                            'basis': None, 'note': 'not stated in this deck'})
    eq = equity_plan(tk, deck)
    db = debt_plan(tk, deck)
    fp = ({'equity_b': eq['equity_b'], 'debt_b': None, 'basis': 'printed',
           'source_page': eq['page'], 'note': flat(eq['text'])[:250]}
          if eq else {'equity_b': None, 'debt_b': None, 'basis': None,
                      'note': 'not stated in this deck'})
    if db:
        fp['debt_b'] = db['debt_b']
        fp['debt_basis'] = 'printed'
        fp['debt_source_page'] = db['page']
        fp['debt_note'] = flat(db['text'])[:250]
    row['financing_plan'] = fp
    return row, flags

def carry_windows(tk, tobj, flagged):
    """A quarterly deck often prints the plan TOTAL on a summary slide with no
    window; the same total is printed WITH its window on another vintage of the
    same ticker. Carry it, and say so explicitly (never silently)."""
    per = sorted([k for k in tobj if not k.startswith('_')], key=pkey_sort)
    src = [(p, tobj[p]) for p in per
           if tobj[p].get('capital_plan_total_b') is not None and tobj[p].get('capital_plan_years')]
    for p in per:
        r = tobj[p]
        if r.get('capital_plan_total_b') is None or r.get('capital_plan_years'):
            continue
        v = round(r['capital_plan_total_b'], 3)
        cands = [(q, x) for q, x in src if round(x['capital_plan_total_b'], 3) == v]
        if not cands:
            continue
        cands.sort(key=lambda qx: abs(pkey_sort(qx[0])[0] * 4 + pkey_sort(qx[0])[1]
                                      - (pkey_sort(p)[0] * 4 + pkey_sort(p)[1])))
        q, x = cands[0]
        r['capital_plan_years'] = x['capital_plan_years']
        r['capital_plan_years_basis'] = ('derived: this deck prints the $%gB total without a window; window carried '
                                         'from %s %s (deck %s p%s), which prints the SAME $%gB total together with '
                                         'its window %s' % (v, tk, q, x['source_id'],
                                                            x.get('capital_plan_source_page'), v,
                                                            x['capital_plan_years']))
        # this cell no longer needs human review
        for f in list(flagged):
            if f.get('ticker') == tk and f.get('period') == p and f.get('field') == 'capital_plan_years':
                flagged.remove(f)


def plan_drift(tobj):
    """Rolling capital-plan vintages, newest statement per window. Levels across
    DIFFERENT window lengths are not comparable, so per_year is carried too and
    the like-for-like ratio is computed only over equal-length windows."""
    per = sorted([k for k in tobj if not k.startswith('_')], key=pkey_sort)
    vint = collections.OrderedDict()
    for p in per:
        r = tobj[p]
        t, w = r.get('capital_plan_total_b'), r.get('capital_plan_years')
        if t is None or not w:
            continue
        m = re.match(r'(\d{4})-(\d{4})$', w)
        yrs = (int(m.group(2)) - int(m.group(1)) + 1) if m else None
        vint[w] = {'window': w, 'years_in_window': yrs, 'total_b': t,
                   'per_year_b': round(t / yrs, 3) if yrs else None,
                   'last_stated': p, 'basis': r.get('capital_plan_basis'),
                   'source_page': r.get('capital_plan_source_page')}
    v = list(vint.values())
    out = {'vintages': v}
    if len(v) >= 2:
        out['first_to_last_total_x'] = round(v[-1]['total_b'] / v[0]['total_b'], 3)
        pv = [x for x in v if x['per_year_b']]
        if len(pv) >= 2:
            out['first_to_last_per_year_x'] = round(pv[-1]['per_year_b'] / pv[0]['per_year_b'], 3)
        five = [x for x in v if x['years_in_window'] == 5]
        if len(five) >= 2:
            out['five_year_plan_x'] = round(five[-1]['total_b'] / five[0]['total_b'], 3)
            out['five_year_plan_series'] = ['%s:$%gB' % (x['window'], x['total_b']) for x in five]
        out['comparability_warning'] = ('Totals over different window lengths are NOT comparable as levels; '
                                        'use per_year_b or five_year_plan_series.')
    return out


def algo_drift(tobj):
    """Guidance item 5 (2026-09-21): long-term algorithm drift. The stated LT EPS
    growth range and rate-base CAGR, collapsed to change points - a move in the
    LT algorithm (6-8% -> 8-10%) is a re-rating catalyst with a date attached,
    and until now each move was a single number buried in one deck. Only PRINTED
    statements enter; a vintage where the deck states nothing is SKIPPED
    (silence is not a change), so a run's last_stated is the last deck that
    actually printed the value."""
    per = sorted([k for k in tobj if not k.startswith('_')], key=pkey_sort)

    def collapse(rows, same, direction):
        runs = []
        for row in rows:
            if runs and same(runs[-1], row):
                runs[-1]['last_stated'] = row['period']
                runs[-1]['n_statements'] += 1
            else:
                r = dict(row)
                r['first_stated'] = r.pop('period')
                r['last_stated'] = r['first_stated']
                r['n_statements'] = 1
                runs.append(r)
        moves = []
        for a, b in zip(runs, runs[1:]):
            moves.append({'at': b['first_stated'], 'from': {k: a.get(k) for k in ('low', 'high', 'rate_pct', 'window') if k in a},
                          'to': {k: b.get(k) for k in ('low', 'high', 'rate_pct', 'window') if k in b},
                          'direction': direction(a, b),
                          'source_page': b.get('source_page'), 'source_url': b.get('source_url')})
        return {'runs': runs, 'moves': moves}

    eps_rows = []
    for p in per:
        g = tobj[p].get('lt_eps_growth') or {}
        if g.get('rate_low_pct') is None and g.get('rate_high_pct') is None:
            continue
        eps_rows.append({'period': p, 'low': g.get('rate_low_pct'), 'high': g.get('rate_high_pct'),
                         'basis': g.get('basis'), 'source_page': g.get('source_page'),
                         'source_url': tobj[p].get('source_url')})

    def eps_same(a, b):
        return a['low'] == b['low'] and a['high'] == b['high']

    def eps_dir(a, b):
        al, ah = a['low'], a['high']
        bl, bh = b['low'], b['high']
        if None in (al, ah, bl, bh):
            return 'changed'
        if bl >= al and bh >= ah and (bl > al or bh > ah): return 'raised'
        if bl <= al and bh <= ah and (bl < al or bh < ah): return 'lowered'
        if bl > al and bh < ah: return 'narrowed'
        if bl < al and bh > ah: return 'widened'
        return 'changed'

    rb_rows = []
    for p in per:
        g = tobj[p].get('rate_base_cagr') or {}
        if g.get('rate_pct') is None:
            continue
        w = None
        if g.get('from_year') and g.get('to_year'):
            w = '%s-%s' % (g['from_year'], g['to_year'])
        rb_rows.append({'period': p, 'rate_pct': g.get('rate_pct'), 'window': w,
                        'basis': g.get('basis'), 'source_page': g.get('source_page'),
                        'source_url': tobj[p].get('source_url')})

    def rb_same(a, b):
        return a['rate_pct'] == b['rate_pct']   # window roll-forward alone is not a move

    def rb_dir(a, b):
        if a['rate_pct'] is None or b['rate_pct'] is None: return 'changed'
        return 'raised' if b['rate_pct'] > a['rate_pct'] else 'lowered'

    return {'lt_eps_growth': collapse(eps_rows, eps_same, eps_dir),
            'rate_base_cagr': collapse(rb_rows, rb_same, rb_dir),
            'note': ('Runs collapse consecutive identical printed statements; moves are dated at the first '
                     'deck printing the new value. rate_base_cagr windows roll forward routinely, so a '
                     'window change with the same rate is NOT a move (the run row carries the first-stated '
                     'window). EPS ranges and rate-base CAGRs are house-stated algorithms, not guidance '
                     'levels - bases can differ vintage to vintage; the deep link is the arbiter.')}


def consolidate_flags(flagged, repeat_at=4):
    """A review list that over-asks gets ignored wholesale. Capital-plan rows are
    always kept one-per-cell. A systematic slide-layout problem that repeats
    across many decks of one ticker is collapsed to a single row that names every
    affected period."""
    keep, groups = [], collections.OrderedDict()
    for f in flagged:
        if f['field'].startswith('capital_plan'):
            keep.append(f)
        else:
            groups.setdefault((f['ticker'], f['field']), []).append(f)
    for (tk, field), rows in groups.items():
        if len(rows) < repeat_at:
            keep.extend(rows)
            continue
        r = dict(rows[0])
        r['period'] = rows[0]['period'] + ' .. ' + rows[-1]['period']
        r['affected_periods'] = [x['period'] for x in rows]
        r['issue'] = ('SAME slide layout in all %d of these decks: %s  (one row, not %d — answer it once and the '
                      'rule applies to every listed period)' % (len(rows), rows[0]['issue'], len(rows)))
        keep.append(r)
    return keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tickers', default=None, help='comma-separated subset to rebuild')
    ap.add_argument('--rebuild', action='store_true', help='ignore existing file (no merge)')
    args = ap.parse_args()

    idx = json.load(open(INDEX))
    all_t = sorted({r['ticker'] for r in idx})
    want = [t.strip().upper() for t in args.tickers.split(',')] if args.tickers else all_t
    unknown = [t for t in want if t not in all_t]
    if unknown:
        print('WARNING: no decks in the manifest for %s -> absent by design, not empty' % ','.join(unknown))
    want = [t for t in want if t in all_t]

    before = {}
    if os.path.exists(OUT) and not args.rebuild:
        before = json.load(open(OUT))
    out = {k: v for k, v in before.items()}          # merge-only
    before_keys = {'%s|%s' % (t, p) for t, v in before.items() if not t.startswith('_')
                   for p in v if not p.startswith('_')}

    flagged = []
    if os.path.exists(FLAG) and not args.rebuild:
        flagged = [f for f in json.load(open(FLAG)) if f['ticker'] not in want]

    for tk in want:
        decks = sorted([r for r in idx if r['ticker'] == tk], key=lambda r: r['date'])
        tobj = {}
        for d in decks:
            pk = norm_period(d['period'])
            if pk in tobj:
                raise SystemExit('period collision %s %s' % (tk, pk))
            row, fl = build_row(tk, d)
            tobj[pk] = row
            for f in fl:
                f.update(ticker=tk, period=pk, source_id=d['id'], source_url=d['url'])
                flagged.append(f)
        carry_windows(tk, tobj, flagged)
        drift = plan_drift(tobj)
        filled = sum(1 for r in tobj.values() if r.get('capital_plan_total_b') is not None)
        tobj['_coverage'] = {'decks': len(decks),
                             'periods': sorted(tobj.keys(), key=pkey_sort),
                             'first': min(tobj, key=pkey_sort), 'last': max(tobj, key=pkey_sort),
                             'capital_plan_filled': filled,
                             'sparse': len(decks) < 14}
        tobj['_capital_plan_drift'] = drift
        tobj['_lt_algo_drift'] = algo_drift(tobj)
        out[tk] = tobj

    out['_note'] = {
        'file': 'guidance_history.json',
        'schema': 'Same field names as data/Guidance_ip.json; Guidance_ip is the newest vintage row.',
        'period_rule': PERIOD_RULE,
        'evidence_rule': 'Every numeric cell carries source_id, source_page ([[PAGE N]] marker) and source_url, '
                         'plus the verbatim slide text it was read off.',
        'basis': 'printed = the figure appears on the slide. derived = computed from printed figures; '
                 'the note says exactly how. null = not in the deck (never interpolated).',
        'window_rule': 'capital_plan_total_b is never carried without capital_plan_years. Where the deck prints a '
                       'total but no window, capital_plan_years is null and the cell is listed in guidance_flagged.json.',
        'coverage_rule': 'Tickers with zero decks in guidance_index.json (GWRS, MSEX, YORW) are ABSENT from this file. '
                         'Per-ticker _coverage carries the deck count so sparse names render as sparse.',
        'tickers_absent_by_design': ['GWRS', 'MSEX', 'YORW'],
        'builder': 'scripts/build_guidance_history.py',
        'qc_overrides': 'data/guidance_qc_overrides.json is overlaid AFTER extraction on every '
                        'build, so hand-ruled cells (2026-09-21 dividend + equity QC) survive '
                        'rebuilds. Edit rulings THERE, never only in this file.',
    }

    # ---- QC overrides: hand-ruled cells survive every rebuild (2026-09-21) ----
    ov_path = os.path.join(BASE, 'data', 'guidance_qc_overrides.json')
    if os.path.exists(ov_path):
        ov = json.load(open(ov_path))
        applied = missing = 0
        for otk, pers in ov.items():
            if otk.startswith('_'):
                continue
            for oper, fields in pers.items():
                orow = out.get(otk, {}).get(oper)
                if orow is None:
                    missing += 1
                    print('  OVERRIDE TARGET MISSING: %s %s' % (otk, oper))
                    continue
                for fld, val in fields.items():
                    # dict-valued overrides MERGE per key, so a pinned ruling on
                    # (say) equity_b does not erase a freshly-extracted debt_b
                    if isinstance(val, dict) and isinstance(orow.get(fld), dict):
                        orow[fld] = {**orow[fld], **val}
                    else:
                        orow[fld] = val
                    applied += 1
        print('QC overrides applied: %d field(s)%s'
              % (applied, ('  ** %d TARGET ROWS MISSING **' % missing) if missing else ''))
    else:
        print('NOTE: data/guidance_qc_overrides.json not found — no QC overlay applied')

    flagged = consolidate_flags(flagged)

    after_keys = {'%s|%s' % (t, p) for t, v in out.items() if not t.startswith('_')
                  for p in v if not p.startswith('_')}
    lost = sorted(before_keys - after_keys)
    gained = sorted(after_keys - before_keys)
    print('KEY DIFF  before=%d  after=%d  gained=%d  lost=%d' % (len(before_keys), len(after_keys), len(gained), len(lost)))
    if lost:
        print('  LOST (data loss!): %s' % ', '.join(lost[:40]))
    if gained:
        print('  GAINED: %s%s' % (', '.join(gained[:12]), ' ...' if len(gained) > 12 else ''))
    if lost:
        sys.exit('ABORT: refusing to write a file that drops existing keys.')

    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(OUT), suffix='.tmp')
    with os.fdopen(fd, 'w') as fh:
        json.dump(out, fh, indent=1)
    os.replace(tmp, OUT)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(FLAG), suffix='.tmp')
    with os.fdopen(fd, 'w') as fh:
        json.dump(flagged, fh, indent=1)
    os.replace(tmp, FLAG)
    print('wrote %s (%d tickers) and %s (%d rows)' %
          (OUT, len([k for k in out if not k.startswith('_')]), FLAG, len(flagged)))

if __name__ == '__main__':
    main()
