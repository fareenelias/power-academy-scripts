"""
patch_filings_snippets_v2.py
- Fixes undefined.slice TypeError in debug log
- Adds snippetMap/snippetLoad state
- Uses regex to find clearSearch (resilient to prior edits)
- Adds snippet fetch useEffect
- Updates snippet rendering in results
"""
import re

SRC = r"E:\PowerAcademy\app\poweracademy\src\components\CompanyIntel.js"

with open(SRC, 'r', encoding='utf-8') as f:
    raw = f.read()
code = raw.replace('\r\n', '\n')

# ── 1. Fix the undefined.slice TypeError in debug log ─────────────────────────
OLD_LOG = "        console.log('EDGAR first hit highlight:', JSON.stringify(hits[0].highlight).slice(0, 800));"
NEW_LOG = "        console.log('EDGAR first hit highlight:', JSON.stringify(hits[0].highlight || {}).slice(0, 800));"
if OLD_LOG in code:
    code = code.replace(OLD_LOG, NEW_LOG, 1)
    print("Step 1: fixed undefined.slice TypeError")
else:
    print("Step 1: debug log not found (may already be fixed or absent)")

# ── 2. Add snippetMap/snippetLoad state after cik state ───────────────────────
OLD_CIK = "  const [cik,           setCik]           = useState(null);"
NEW_CIK  = ("  const [cik,           setCik]           = useState(null);\n"
             "  const [snippetMap,    setSnippetMap]    = useState({});\n"
             "  const [snippetLoad,   setSnippetLoad]   = useState({});")
if OLD_CIK not in code:
    print("ERROR: cik state line not found — was it already patched?")
    # Check if snippetMap is already there
    if 'snippetMap' in code:
        print("  snippetMap already present, skipping step 2")
    else:
        raise SystemExit(1)
else:
    code = code.replace(OLD_CIK, NEW_CIK, 1)
    print("Step 2: added snippetMap/snippetLoad state")

# ── 3. Clear snippetMap on ticker change ──────────────────────────────────────
OLD_CLEAR_TICKER = ("    setSearchResults(null);\n"
                    "    setSearchQuery('');\n"
                    "    setSearchInput('');\n"
                    "    setCik(null);")
NEW_CLEAR_TICKER  = ("    setSearchResults(null);\n"
                     "    setSearchQuery('');\n"
                     "    setSearchInput('');\n"
                     "    setCik(null);\n"
                     "    setSnippetMap({});\n"
                     "    setSnippetLoad({});")
if OLD_CLEAR_TICKER in code and 'setSnippetMap({});' not in code:
    code = code.replace(OLD_CLEAR_TICKER, NEW_CLEAR_TICKER, 1)
    print("Step 3: added snippet clear on ticker change")
else:
    print("Step 3: skipped (already patched or not found)")

# ── 4. Replace clearSearch using regex (resilient to prior edits) ─────────────
# Find clearSearch function and replace it
clear_pattern = re.compile(
    r'const clearSearch = \([^)]*\) => \{[^}]+\};',
    re.DOTALL
)
m = clear_pattern.search(code)
if m:
    NEW_CLEAR = (
        "const clearSearch = () => {\n"
        "    setSearchResults(null); setSearchQuery(''); setSearchInput('');\n"
        "    setSnippetMap({}); setSnippetLoad({});\n"
        "  };"
    )
    code = code[:m.start()] + NEW_CLEAR + code[m.end():]
    print("Step 4: replaced clearSearch with snippet cleanup")
else:
    print("Step 4 WARNING: clearSearch not found by regex — check manually")

# ── 5. Add snippet fetch useEffect after clearSearch ──────────────────────────
SNIPPET_EFFECT = r"""

  // Fetch text snippets (first 500KB of filing doc) for top 3 results
  useEffect(() => {
    if (!searchResults || searchResults.length === 0 || !searchQuery) return;
    setSnippetMap({});
    setSnippetLoad({});
    searchResults.slice(0, 3).forEach(hit => {
      const src       = hit._source || {};
      const accession = src.accession_no || hit._id || '';
      const names     = src.display_names || [];
      const cikMatch  = names[0]?.match(/CIK (\d+)/);
      if (!accession || !cikMatch) return;
      const hitCik = parseInt(cikMatch[1], 10);
      setSnippetLoad(prev => ({ ...prev, [hit._id]: true }));
      fetch(`${PROXY}/api/edgar-snippet?accession=${encodeURIComponent(accession)}&cik=${hitCik}&term=${encodeURIComponent(searchQuery)}`)
        .then(r => r.ok ? r.json() : { snippets: [] })
        .then(d => {
          setSnippetMap(prev  => ({ ...prev,  [hit._id]: d.snippets || [] }));
          setSnippetLoad(prev => ({ ...prev,  [hit._id]: false }));
        })
        .catch(() => setSnippetLoad(prev => ({ ...prev, [hit._id]: false })));
    });
  }, [searchResults]);
"""

if 'api/edgar-snippet' not in code:
    # Insert after clearSearch
    insert_after = re.compile(r'const clearSearch = \([^)]*\) => \{[^}]+\};', re.DOTALL)
    m2 = insert_after.search(code)
    if m2:
        code = code[:m2.end()] + SNIPPET_EFFECT + code[m2.end():]
        print("Step 5: inserted snippet fetch useEffect")
    else:
        print("Step 5 WARNING: could not insert useEffect — clearSearch anchor not found")
else:
    print("Step 5: snippet useEffect already present, skipped")

# ── 6. Replace snippet rendering inside the results map ──────────────────────
# Find and replace the preview/snippet display block
# Old block: the one from the previous patch (renderSnippet-based)
old_render_pattern = re.compile(
    r'\{/\* Snippet preview.*?</div>\s*\}',
    re.DOTALL
)
m3 = old_render_pattern.search(code)

NEW_RENDER = (
    "{/* Snippet preview — fetched from filing document via Node */}\n"
    "                    <div style={{ borderTop:`1px solid ${COLORS.border}22`, paddingTop:8, marginTop:4 }}>\n"
    "                      {snippetLoad[hit._id] ? (\n"
    "                        <div style={{ fontSize:11, color:COLORS.textLo, fontStyle:'italic' }}>Loading preview\u2026</div>\n"
    "                      ) : (snippetMap[hit._id] || []).length > 0 ? (\n"
    "                        <div style={{ display:'flex', flexDirection:'column', gap:6 }}>\n"
    "                          {(snippetMap[hit._id] || []).map((s, j) => (\n"
    "                            <div key={j}\n"
    "                              style={{ fontSize:11, color:COLORS.textMid, lineHeight:1.7, background:COLORS.panel, borderRadius:4, padding:'5px 8px', borderLeft:`2px solid ${COLORS.accent}40` }}\n"
    "                              dangerouslySetInnerHTML={{\n"
    r"                                __html: '\u2026' + s.replace(/\[\[([^\]]+)\]\]/g, '<mark style=&quot;background:#2a2000;color:#f4c542;padding:0 2px;border-radius:2px&quot;>$1</mark>').trim() + '\u2026'" + "\n"
    "                              }}\n"
    "                            />\n"
    "                          ))}\n"
    "                        </div>\n"
    "                      ) : i < 3 ? (\n"
    "                        <div style={{ fontSize:11, color:COLORS.textLo, fontStyle:'italic' }}>No match found in first 500KB of filing</div>\n"
    "                      ) : (\n"
    "                        <div style={{ fontSize:11, color:COLORS.textLo, fontStyle:'italic' }}>Click to view filing on EDGAR</div>\n"
    "                      )}\n"
    "                    </div>"
)

if m3:
    code = code[:m3.start()] + NEW_RENDER + code[m3.end():]
    print("Step 6: replaced snippet rendering block")
else:
    # Try finding the old renderSnippet-based block
    old_render2 = re.compile(
        r'\{snippets\.length > 0.*?No preview available.*?\}\s*\)\}',
        re.DOTALL
    )
    m4 = old_render2.search(code)
    if m4:
        code = code[:m4.start()] + NEW_RENDER + code[m4.end():]
        print("Step 6: replaced (alt pattern) snippet rendering block")
    else:
        print("Step 6 WARNING: could not find snippet rendering block — check manually")

# Fix the dangerouslySetInnerHTML &quot; escape back to real quotes
# (needed because f-strings make quoting tricky)
code = code.replace(
    r'style=&quot;background:#2a2000;color:#f4c542;padding:0 2px;border-radius:2px&quot;',
    r"style=\"background:#2a2000;color:#f4c542;padding:0 2px;border-radius:2px\""
)

with open(SRC, 'w', encoding='utf-8') as f:
    f.write(code)
print(f"\nSaved: {SRC}")