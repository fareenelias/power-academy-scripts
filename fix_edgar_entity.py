"""
fix_edgar_entity.py
Fixes the EDGAR entity parameter — was passing CIK number (753308) which
EDGAR entity filter doesn't understand. Should be company name substring.
Also adds a few name overrides for tricky tickers (PCG, XIFR, HTO).
"""
import re

SRC = r"E:\PowerAcademy\app\poweracademy\src\components\CompanyIntel.js"

with open(SRC, 'r', encoding='utf-8') as f:
    raw = f.read()
code = raw.replace('\r\n', '\n')

# ── 1. Add EDGAR entity name overrides map near the top of FilingsPanel ──────
OLD_ENTITY = """  const company     = COMPANIES.find(c => c.ticker === ticker);
  const entityName  = company?.name || ticker;"""

NEW_ENTITY = """  const company     = COMPANIES.find(c => c.ticker === ticker);
  // EDGAR entity names: override where our display name differs from SEC legal name
  const EDGAR_NAMES = {
    PCG:  'PG&E Corp',           // EDGAR has 'PG&E CORP', not 'PG&E'
    XIFR: 'NextEra Energy Partners',  // was NEP before rename to XPLR
    HTO:  'SJW Group',           // EDGAR may still have old SJW name
  };
  const entityName  = EDGAR_NAMES[ticker] || company?.name || ticker;"""

if OLD_ENTITY not in code:
    print("ERROR: could not find entity name block")
    raise SystemExit(1)
code = code.replace(OLD_ENTITY, NEW_ENTITY, 1)
print("Step 1: added EDGAR_NAMES override map")

# ── 2. Fix: use entityName (not cik) for the entity parameter ─────────────────
OLD_ENTITY_PARAM = """    // Use CIK if we have it (exact match), else entity name (substring match)
    const entityParam = cik ? cik : entityName;"""

NEW_ENTITY_PARAM = """    // EDGAR entity filter matches company name substrings (case-insensitive)
    // Do NOT use CIK here — entity= expects a name, not a number
    const entityParam = entityName;"""

if OLD_ENTITY_PARAM not in code:
    print("ERROR: could not find entityParam line")
    raise SystemExit(1)
code = code.replace(OLD_ENTITY_PARAM, NEW_ENTITY_PARAM, 1)
print("Step 2: fixed entityParam to use name, not CIK")

# ── 3. Add console.log so we can see the raw response ─────────────────────────
OLD_FETCH = """    fetch(`${PROXY}/api/edgar-search?${qs}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { setSearchResults(d?.hits?.hits || []); setSearchLoading(false); })
      .catch(e => { console.error('EDGAR search error:', e); setSearchResults([]); setSearchLoading(false); });"""

NEW_FETCH = """    console.log('EDGAR search:', `${PROXY}/api/edgar-search?${qs}`);
    fetch(`${PROXY}/api/edgar-search?${qs}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        console.log('EDGAR raw response:', JSON.stringify(d).slice(0, 500));
        setSearchResults(d?.hits?.hits || []);
        setSearchLoading(false);
      })
      .catch(e => { console.error('EDGAR search error:', e); setSearchResults([]); setSearchLoading(false); });"""

if OLD_FETCH not in code:
    print("ERROR: could not find fetch block")
    raise SystemExit(1)
code = code.replace(OLD_FETCH, NEW_FETCH, 1)
print("Step 3: added console.log for debugging")

with open(SRC, 'w', encoding='utf-8') as f:
    f.write(code)
print(f"\nSaved: {SRC}")
print("Open DevTools > Console, search for 'florida' in NEE, and paste what the EDGAR raw response log shows.")