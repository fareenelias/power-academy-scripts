#!/usr/bin/env python3
"""
guidance_extractors.py — hardened dividend + equity extractors for
build_guidance_history.py. Supersedes scripts/dividend_patch.py (retired).

Built 2026-09-21 from the two QC sessions (dividend workbook: 6 of 23 "low-risk"
FILL proposals were wrong; equity workbook: 4 of 18). Every defect class that
produced a wrong proposal is now a guard, and every guard has a control that
fails if the guard is removed.

SEVEN GUARDED DEFECT CLASSES (each with the real text that produced it):

  Dividend
  D1. EPS-growth-base collision — "~10% annual dividend per share growth
      through at least 2026 … 2024 2025E 2026E 2027E $3.43 6%-8% off 2024
      adjusted EPS range" (NEE x3): the money token is the growth chart's
      EPS BASE. Refused when the label->token span carries growth language
      AND a year-series, or the token is followed by "N%-M% off".
  D2. $-billions token — "target $300 million in dividends annually •
      Executed ~$4.25 billion in share repurchases" (VST): $4.25 is a
      buyback aggregate. A token followed by B/bn/billion is never a DPS.
  D3. Quarterly "(DPS) Paid" leak — "Adjusted EPS Dividend Per Share (DPS)
      Paid $0.53 $0.46" (CMS Q2/Q3 2022): quarterly amounts PAID beside
      quarterly EPS. 'Paid'/'YTD' near the label refuses the match.
  D4. from->to rate collision — "increased annual dividend 7.7% from $1.04
      per share to $1.12 per share" (CWT Q1 2024): the first token is the
      OLD rate. A token directly preceded by 'from' is skipped; the 'to'
      token is taken.

  Equity
  E1. Plan vs executed — "2024 ATM Equity Issuances $990" / "~$2B of equity
      needs already executed" (ES, PPL): historical actuals and executed
      portions are not plans. A bare single year prefixed to the label, or
      'already executed' in context, refuses the match.
  E2. Range-left — "2022 Equity issuance $100 - $400M" (PCG x2): a scalar
      field must not carry the left half of a printed range.
  E3. Other-metric collision — "at-the-market equity program • Credit
      agreements of $2.6 billion" (AEE Q4 2024): revolver capacity is not
      equity. Credit/liquidity/rate-base words in the span refuse the match.
  Plus: ATM figures are LABELLED — "for $X billion" is program CAPACITY,
  "increased … by $X billion" is a program INCREMENT; neither is a
  plan-window total, and the composed text says so (survives note
  truncation because the caveat is prefixed).

Verification: `python3 guidance_extractors.py --test` runs the control suite
(every QC-approved value reproduces; every rejected proposal refuses). Each
guard was disabled in turn during development and confirmed to break at least
one control — no guard is decorative.
"""
import re
import sys

# ============================================================ DIVIDEND =======
QUARTERLY   = re.compile(r'(?i)\bquarter(ly|s)?\b|\b\d{1,3}(st|nd|rd|th)\s+consecutive\b')
OTHERMETRIC = re.compile(r'(?i)\b(EPS|earnings per share|adjusted earnings|guidance|payout'
                         r'|yield|CAGR|ratio|rate base|revenue|O&M|capital)\b')
SPECIAL     = re.compile(r'(?i)\bspecial\b')
GROWTHY     = re.compile(r'(?i)\b(yield|growth|payout|CAGR|ratio)\b')
PAIDISH     = re.compile(r'(?i)\bpaid\b|\bYTD\b')                              # D3
YEARSERIES  = re.compile(r'20\d\d[E]?\s+20\d\d')                               # D1
PCT_OFF     = re.compile(r'^\s*\d+\s*%\s*[\-‐‑‒–—―−]\s*\d+\s*%\s*off\b', re.I) # D1
BILLIONS    = re.compile(r'^\s*(?:b\b|bn\b|billion)', re.I)                    # D2
FROMISH     = re.compile(r'(?i)\bfrom\s*$')                                    # D4

MONEY   = re.compile(r'\$\s?(\d\.\d{2})(?!\d)')
_DASH   = r'[\-‐‑‒–—―−]'
RANGE_R = re.compile(r'^\s*' + _DASH + r'\s*\$?\s?\d')
SERIES  = re.compile(r'^\s*\$\s?\d')

# NOTE: (?![A-Za-z]) not \b — footnote superscripts are \w characters in Python.
STRICT      = re.compile(r'(?i)(?:annuali[sz]ed (?:equivalent )?dividend(?: rate)?'
                         r'|annual dividend)(?: per share)?')
TABLE_LABEL = re.compile(r'(?i)(?:\d{4}\s+)?dividends?(?![A-Za-z])[^$]{0,25}?\(\$\s*per\s*share\)')
LOOSE_LABEL = re.compile(r'(?i)(?:common share |cash )?dividends?(?![A-Za-z])(?:\s*per share)?')
ANNUALISER  = re.compile(r'(?i)per share annually|annuali[sz]ed basis|\bannual(?:ly)?\b')
PAIRED      = re.compile(r'(?i)(?:adjusted\s+)?(?:EPS|earnings per share)[^$]{0,45}?'
                         r'(?:annuali[sz]ed\s+|annual\s+)?dividends?\s+per\s+share')

_BAND = (0.10, 9.99)


def _pick(fb, start, window=70):
    """First POINT money value in the window. Skips range-left halves and
    'from $X' old rates; refuses on bar-chart series, billions tokens, and
    quarterly / other-metric / special / paid / growth-base context."""
    tail = fb[start:start + window]
    for m in MONEY.finditer(tail):
        span = tail[:m.start()]
        if QUARTERLY.search(span) or OTHERMETRIC.search(span) or SPECIAL.search(span):
            return None, None
        if PAIDISH.search(span):                                            # D3
            return None, None
        after = tail[m.end():m.end() + 24]
        if GROWTHY.search(span) and (YEARSERIES.search(span) or PCT_OFF.match(after)):  # D1
            return None, None
        if PCT_OFF.match(after):                                            # D1
            return None, None
        if BILLIONS.match(after):                                           # D2
            continue
        if FROMISH.search(span[-9:] if len(span) >= 9 else span):           # D4
            continue
        if RANGE_R.match(after):
            continue
        if SERIES.match(after):
            return None, None
        v = float(m.group(1))
        if not (_BAND[0] <= v <= _BAND[1]):
            continue
        return v, fb[max(0, start - 70):start + m.end() + 40]
    return None, None


def _paired_columns(fb, window=60):
    """'EPS Guidance | Annual Dividend Per Share' -> '$A - $B  $C'. Two labels,
    two value groups, in order: take the last. Guarded by >=2 tokens, <=3 tokens,
    last < first (a utility's DPS is always below its EPS), and NO 'Paid'/'YTD'
    in the matched region (a quarterly results table, not annual guidance)."""
    for k in PAIRED.finditer(fb):
        tail = fb[k.end():k.end() + window]
        region = fb[max(0, k.start() - 20):k.end() + 16]
        if PAIDISH.search(region) or re.search(r'\bQ[1-4]\b', fb[k.start():k.end()]):   # D3
            continue
        toks = [float(m.group(1)) for m in MONEY.finditer(tail)][:3]
        if len(toks) < 2:
            continue
        first, last = toks[0], toks[-1]
        if not (_BAND[0] <= last <= _BAND[1]) or last >= first:
            continue
        return last, fb[max(0, k.start() - 40):k.end() + window], 4
    return None, None, None


def dividend_from_text(fb):
    """(value, verbatim_evidence, tier) or (None, None, None) for one flattened page."""
    for tier, rx, need_ann in ((1, STRICT, False), (2, TABLE_LABEL, False), (3, LOOSE_LABEL, True)):
        for k in rx.finditer(fb):
            pre = fb[max(0, k.start() - 45):k.start()]
            if QUARTERLY.search(pre) or SPECIAL.search(pre):
                continue
            if tier == 3 and GROWTHY.search(pre):
                continue
            if need_ann and not ANNUALISER.search(fb[max(0, k.start() - 90):k.end() + 70]):
                continue
            v, ev = _pick(fb, k.end())
            if v is not None:
                return v, ev, tier
    return _paired_columns(fb)


# ============================================================== EQUITY =======
_BV = r'\$\s?(\d{1,2}(?:\.\d{1,2})?)\s*(?:B\b|bn\b|billion)'   # $-billions value
EQ_LABEL = r'equity (?:issuances?|plan|needs|financing|program)'
EQ_VAL_FIRST  = re.compile(_BV + r'\s+(?:of\s+)?' + EQ_LABEL, re.I)
EQ_LABEL_FIRST = re.compile(EQ_LABEL + r'[^.$]{0,45}?' + _BV, re.I)
ATM_CAPACITY  = re.compile(r'(?i)at.the.market[^.$]{0,60}?(?:equity\s+)?program\s+for\s+' + _BV)
ATM_INCREASE  = re.compile(r'(?i)(?:increased|upsized)[^.$]{0,60}?at.the.market[^.$]{0,60}?by\s+' + _BV)

EQ_WINDOW   = re.compile(r'(?:in(?:\s+the)?\s+)?(20\d\d)E?\s*[\-‐‑‒–—―−]\s*(20\d\d)E?')
EQ_OTHER    = re.compile(r'(?i)credit (?:agreement|facilit)|revolver|liquidity|debt financing'
                         r'|rate ?base|ratebase|repurchas')                          # E3
EQ_EXECUTED = re.compile(r'(?i)already executed')                                    # E1
EQ_HIST     = re.compile(r'(?i)\b20\d\d\s+(?:ATM\s+)?equity issuances?\s*\$?\s*$')   # E1
EQ_RANGE    = re.compile(r'^\s*(?:B\b|bn\b|billion)?\s*[\-‐‑‒–—―−]\s*\$?\s?\d', re.I)  # E2
EQ_ATMISH   = re.compile(r'(?i)at.the.market|\(ATM\)')

_EQ_BAND = (0.1, 30.0)


def _eq_ctx_ok(fb, vstart, vend, label_start):
    """Shared guards over the label->value span and near context."""
    span = fb[label_start:vstart]
    ctx = fb[max(0, label_start - 70):vend + 40]
    if EQ_OTHER.search(span):                                   # E3: wrong metric between label and value
        return False
    if EQ_EXECUTED.search(ctx):                                 # E1: executed portion, not the plan
        return False
    if EQ_HIST.search(fb[max(0, label_start - 12):vstart]):     # E1: '2024 ATM Equity Issuances' = actual
        return False
    if EQ_RANGE.match(fb[vend:vend + 14]):                      # E2: left half of a printed range
        return False
    return True


def equity_from_text(fb):
    """(value_b, kind, window, evidence) or (None,)*4 for one flattened page.
    kind: 'plan_total' | 'atm_program_capacity' | 'atm_program_increase'."""
    for kind, rx in (('plan_total', EQ_LABEL_FIRST), ('plan_total', EQ_VAL_FIRST),
                     ('atm_program_capacity', ATM_CAPACITY), ('atm_program_increase', ATM_INCREASE)):
        for m in rx.finditer(fb):
            v = float(m.group(1))
            if not (_EQ_BAND[0] <= v <= _EQ_BAND[1]):
                continue
            vstart = m.start(1)
            if not _eq_ctx_ok(fb, vstart, m.end(1), m.start()):
                continue
            # an ATM-context label is classified by the ATM patterns, never as a plan total
            if kind == 'plan_total' and EQ_ATMISH.search(fb[max(0, m.start() - 35):m.start()]):
                continue
            wm = EQ_WINDOW.search(fb[m.start():m.end() + 45])
            window = '%s-%s' % (wm.group(1), wm.group(2)) if wm else None
            ev = fb[max(0, m.start() - 70):m.end() + 70]
            return v, kind, window, ev
    return None, None, None, None


_KIND_CAVEAT = {
    'atm_program_capacity': '[ATM PROGRAM CAPACITY, not a windowed plan total] ',
    'atm_program_increase': '[ATM PROGRAM INCREASE, window unstated - not a plan-window total] ',
}


def compose_equity_text(kind, window, ev):
    """Caveat is PREFIXED so it survives the builder's note truncation."""
    pre = _KIND_CAVEAT.get(kind, '')
    if kind == 'plan_total' and window:
        pre = '[%s plan] ' % window
    return pre + ev


# ============================================================ CONTROLS =======
# Every control is a real slide text from the 2026-08-06 -> 2026-09-21 QC chain.
_DIV_MUST_MATCH = [
    ("Adjusted EPS Guidance Annual Dividend Per Share $3.06 - $3.12 $1.95 Toward the high end", 1.95),
    ("Adjusted EPS Guidance Annual Dividend Per Share (DPS) $3.06 - $3.12 $2.17 Toward the high end", 2.17),
    ("Common Share Dividend** $0.26 per share annually * Shares outstanding", 0.26),
    ("No change 2025 dividend2 ($ per share) $2.67 No change 2025-2029 capital investment", 2.67),
    ("2021 Dividend 13 Stable and Consistent Growth - $1.36 per share (annual) - Paid dividends for 50 years", 1.36),
    ("Increased annual dividend in 2020 by 9.8% to $1.34 per share", 1.34),
    ("Increased annual dividend 7.7% from $1.04 per share to $1.12 per share.", 1.12),           # D4
    ("Note: Annual 2024 cash dividends per share of $3.00 over weather-normalized 2024 EPS guidance", 3.00),
    ("Projected Earnings Per Share Projected Annualized Dividends Per Share 6% - 8% CAGR $1.48 6% - 8% CAGR $0.90 Top-Tier", 0.90),
]
_DIV_MUST_REFUSE = [
    "Continue to expect ~10% annual dividend per share growth through at least 20263 2024 2025E 2026E 2027E $3.43 6% - 8% off 2024 adjusted EPS range2",  # D1
    "target $300 million in dividends annually - Executed ~$4.25 billion in share repurchases from Nov.",   # D2
    "Q2 2022 Results Adjusted EPS Dividend Per Share (DPS) Paid $0.53 $0.46 Ahead of plan",                 # D3
    "2022 Results YTD Adjusted EPS Q3 Dividend Per Share (DPS) $2.29 $0.46 Ahead of plan",                  # D3 (YTD)
    "one-time special dividend of $0.04 per share",
    "declared a quarterly dividend of $0.34 per share",
    "Dividends ($ per share) Paid $0.53 in the period",                                                    # D3 via _pick
]
_EQ_MUST_MATCH = [
    ("$2.5B of equity issuances in 2026-2030, driven by capital investment needs", 2.5, 'plan_total', '2026-2030'),
    ("Common Equity Financing Plan $3.3B 2026E-2030E - Expect annual EPS growth", 3.3, 'plan_total', '2026-2030'),
    ("Equity Issuance $1,000 Sale Proceeds - $1.0B equity issuance in 2024-2028 plan, driven by increased capital plan", 1.0, 'plan_total', '2024-2028'),
    ("$2.0B of equity issuances in Current Plan, a $900M increase over Prior Plan", 2.0, 'plan_total', None),
    ("New Shares At-The-Market Program for $1.2 billion issued 7.1 million shares in 2025 with net proceeds", 1.2, 'atm_program_capacity', None),
    ("increased existing at-the-market (ATM) equity program by $1 billion to support expected equity needs in 2024 and beyond", 1.0, 'atm_program_increase', None),
]
_EQ_MUST_REFUSE = [
    "GIP Sale Gross Proceeds $875 2024 ATM Equity Issuances $990 Rate Increases $300 - $400",     # E1 historical
    "structures to the extent they provide an efficient cost of capital ~$2B of equity needs already executed",  # E1 executed
    "at-the-market equity program - Credit agreements of $2.6 billion in place through Dec. 2028",  # E3
    "Equity 2022 Equity issuance $100 - $400M",                                                    # E2 (also $M form)
    "Equity Earning Ratebase (1) ~$47.2B 2021 Equity issuance Equity Earning Ratebase ~$44.5B",    # PCG rate base
    "equity needs of $1.5B - $2.0 billion over the plan",                                          # E2 in $B form
    "2024 Equity Issuances $1.0B completed under the program",                                     # E1 hist, $B form
    "our equity needs - Credit agreements of $2.6 billion in place through Dec. 2028",             # E3 without ATM prefix
]


def _run_controls():
    bad = 0
    for txt, want in _DIV_MUST_MATCH:
        v, ev, tier = dividend_from_text(txt)
        ok = (v == want)
        bad += not ok
        print('%s DIV match  %-6s got %-6s | %s' % ('PASS' if ok else 'FAIL', want, v, txt[:60]))
    for txt in _DIV_MUST_REFUSE:
        v, ev, tier = dividend_from_text(txt)
        ok = (v is None)
        bad += not ok
        print('%s DIV refuse        got %-6s | %s' % ('PASS' if ok else 'FAIL', v, txt[:60]))
    for txt, want, kind, window in _EQ_MUST_MATCH:
        v, k, w, ev = equity_from_text(txt)
        ok = (v == want and k == kind and w == window)
        bad += not ok
        print('%s EQ  match  %-4s/%s/%s got %s/%s/%s | %s' % ('PASS' if ok else 'FAIL', want, kind, window, v, k, w, txt[:48]))
    for txt in _EQ_MUST_REFUSE:
        v, k, w, ev = equity_from_text(txt)
        ok = (v is None)
        bad += not ok
        print('%s EQ  refuse        got %-6s | %s' % ('PASS' if ok else 'FAIL', v, txt[:60]))
    print('---')
    if bad:
        sys.exit('%d CONTROL(S) FAILED' % bad)
    print('all %d controls pass' % (len(_DIV_MUST_MATCH) + len(_DIV_MUST_REFUSE) + len(_EQ_MUST_MATCH) + len(_EQ_MUST_REFUSE)))


if __name__ == '__main__':
    _run_controls()
