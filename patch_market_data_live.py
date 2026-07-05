"""
patch_market_data_live.py
Replaces static useMarketData (reads market_data.json) with useLiveMarketData.
Live price/mktcap from FMP, net debt + EPS from capiqData already in component.
Eliminates fetch_market_data.py dependency.
"""
import re, os, sys

# Auto-detect CompanyIntel.js location
CANDIDATES = [
    r"E:\PowerAcademy\app\poweracademy\src\components\CompanyIntel.js",
    r"E:\PowerAcademy\src\components\CompanyIntel.js",
    r"E:\PowerAcademy\src\pages\CompanyIntel.js",
]
SRC = None
for c in CANDIDATES:
    if os.path.isfile(c):
        SRC = c
        print(f"Found CompanyIntel.js at: {SRC}")
        break

if SRC is None:
    print("ERROR: CompanyIntel.js not found at any expected path.")
    print("Checked:")
    for c in CANDIDATES:
        print(f"  {c}")
    print("\nSet SRC manually in this script and re-run.")
    sys.exit(1)

with open(SRC, 'r', encoding='utf-8') as f:
    raw = f.read()

# Normalize CRLF -> LF for clean string matching
code = raw.replace('\r\n', '\n')

# ── 1. Replace useMarketData hook ─────────────────────────────────────────────
OLD_HOOK = """function useMarketData(ticker) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!ticker) return;
    setLoading(true);
    setData(null);
    fetch(`http://100.86.108.51:3001/api/market-data/${ticker}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [ticker]);
  return { data, loading };
}"""

NEW_HOOK = """function useLiveMarketData(ticker, capiqData) {
  const [quote,   setQuote]   = useState(null);
  const [rbIp,    setRbIp]    = useState(null);
  const [loading, setLoading] = useState(false);
  const API_BASE_G = 'http://100.86.108.51:3001';

  // Live price + market cap from FMP
  useEffect(() => {
    if (!ticker) return;
    setLoading(true);
    setQuote(null);
    fmpFetch(`/stable/quote?symbol=${ticker}`)
      .then(d => setQuote(Array.isArray(d) ? d[0] : d))
      .finally(() => setLoading(false));
  }, [ticker]);

  // Rate base IP data (Node wildcard EIA route) -- fetch once
  useEffect(() => {
    if (rbIp) return;
    fetch(`${API_BASE_G}/api/eia/rate_base_ip.json`)
      .then(r => r.ok ? r.json() : null)
      .then(d => d && setRbIp(d))
      .catch(() => {});
  }, []);

  const md = useMemo(() => {
    const co = capiqData?.[ticker];
    if (!quote && !co) return null;

    const price          = quote?.price ?? null;
    const equity_value_b = quote?.marketCap ? quote.marketCap / 1e9 : null;

    // Net debt: 5-value historical array in thousands -> billions
    const netDebtArr  = co?.net_debt || [];
    const lastNetDebt = [...netDebtArr].reverse().find(v => typeof v === 'number' && v !== null);
    const net_debt_b  = lastNetDebt != null ? lastNetDebt / 1e6 : null;

    const firm_value_b = (equity_value_b != null && net_debt_b != null)
      ? equity_value_b + net_debt_b : null;

    // EPS: indices [4,5,6] = forward estimates; [0-3] = historical actuals
    const eps     = co?.eps_diluted || [];
    const periods = co?.periods     || [];
    const eps_fy  = typeof eps[4] === 'number' ? eps[4] : null;
    const eps_fy1 = typeof eps[5] === 'number' ? eps[5] : null;
    const eps_fy2 = typeof eps[6] === 'number' ? eps[6] : null;
    const pe_fy   = price && eps_fy  ? price / eps_fy  : null;
    const pe_fy1  = price && eps_fy1 ? price / eps_fy1 : null;
    const pe_fy2  = price && eps_fy2 ? price / eps_fy2 : null;

    // Dividend: capiq historical most recent, fallback to FMP lastDiv * 4
    const divsArr      = co?.dividends_ps || [];
    const lastDivCapiq = [...divsArr].reverse().find(v => typeof v === 'number' && v !== null);
    const div_per_share = lastDivCapiq ?? (quote?.lastDiv != null ? quote.lastDiv * 4 : null);
    const div_yield_pct = (div_per_share && price) ? (div_per_share / price) * 100 : null;
    const payout_pct    = (div_per_share && eps_fy) ? (div_per_share / eps_fy) * 100 : null;

    // Rate base: rate_base_ip.json (IP-disclosed) then capiq NUP (GAAP proxy)
    const rbEntry           = rbIp?.[ticker];
    const consolidated_rb_b = rbEntry?.consolidated_b
      ?? (co?.net_utility_plant_latest ? co.net_utility_plant_latest / 1e6 : null);
    const consol_source = rbEntry?.source ?? (co?.net_utility_plant_latest ? 'gaap' : null);
    const consol_label  = rbEntry?.label  ?? (co?.net_utility_plant_latest ? 'GAAP Net Utility Plant (proxy)' : null);
    const fv_rate_base_x = (firm_value_b && consolidated_rb_b)
      ? firm_value_b / consolidated_rb_b : null;

    return {
      price, equity_value_b, net_debt_b, firm_value_b,
      eps_fy, eps_fy1, eps_fy2,
      fy_label:  periods[4] ?? 'FY',
      fy1_label: periods[5] ?? 'FY+1',
      fy2_label: periods[6] ?? 'FY+2',
      pe_fy, pe_fy1, pe_fy2,
      div_per_share, div_yield_pct, payout_pct,
      consolidated_rb_b, consol_source, consol_label, fv_rate_base_x,
      generated: null,
    };
  }, [quote, capiqData, ticker, rbIp]);

  return { data: md, loading };
}"""

if OLD_HOOK not in code:
    print("ERROR: useMarketData hook not found verbatim.")
    idx = code.find('function useMarketData')
    print(f"  'function useMarketData' at char {idx}" if idx >= 0 else "  NOT FOUND at all")
    sys.exit(1)

code = code.replace(OLD_HOOK, NEW_HOOK, 1)
print("Step 1: replaced useMarketData with useLiveMarketData")

# ── 2. Update hook call in TradingMetricsPanel ────────────────────────────────
OLD_CALL = "  const { data: md, loading } = useMarketData(ticker);"
NEW_CALL = "  const { data: md, loading } = useLiveMarketData(ticker, capiqData);"
if OLD_CALL not in code:
    print("ERROR: useMarketData(ticker) call not found")
    sys.exit(1)
code = code.replace(OLD_CALL, NEW_CALL, 1)
print("Step 2: updated hook call in TradingMetricsPanel")

# ── 3. Remove stale-data warning (generated/ageHours/stale + JSX block) ──────
stale_pattern = re.compile(
    r'\n  const generated = md\.generated.*?'
    r'\{generated && !stale && \(.*?\)\}\n',
    re.DOTALL
)
m = stale_pattern.search(code)
if m:
    code = stale_pattern.sub('\n', code, count=1)
    print("Step 3: removed stale data warning")
else:
    print("Step 3: stale block not matched by regex -- attempting line-by-line removal")
    lines = code.split('\n')
    out, skip = [], False
    for line in lines:
        if 'const generated = md.generated' in line:
            skip = True
        if skip:
            # Stop skipping after the closing line of the generated block
            if line.strip() == ')}' and skip:
                skip = False
                continue
        if not skip:
            out.append(line)
    code = '\n'.join(out)
    print("  Line-by-line removal applied")

# ── 4. Add useMemo import if missing ─────────────────────────────────────────
if 'useMemo' not in code:
    for old, new in [
        ("{ useState, useEffect, useRef, useCallback }",
         "{ useState, useEffect, useRef, useCallback, useMemo }"),
        ("{ useState, useEffect, useRef }",
         "{ useState, useEffect, useRef, useMemo }"),
        ("{ useState, useEffect }",
         "{ useState, useEffect, useMemo }"),
    ]:
        if old in code:
            code = code.replace(old, new, 1)
            print("Step 4: added useMemo to React destructure")
            break
    else:
        print("Step 4 WARNING: could not auto-add useMemo -- add it manually")
else:
    print("Step 4: useMemo already present, skipped")

with open(SRC, 'w', encoding='utf-8') as f:
    f.write(code)

print(f"\nAll done. Saved: {SRC}")
print("Restart React dev server. fetch_market_data.py no longer needed for Overview.")