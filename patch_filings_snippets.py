"""
patch_filings_snippets.py
Updates FilingsPanel to:
- Fetch text snippets from /api/edgar-snippet for the first 3 search results
- Show snippets with highlighted match term in gold
- Show loading state per result while snippets fetch
"""

SRC = r"E:\PowerAcademy\app\poweracademy\src\components\CompanyIntel.js"

with open(SRC, 'r', encoding='utf-8') as f:
    raw = f.read()
code = raw.replace('\r\n', '\n')

# ── 1. Add snippetMap state ────────────────────────────────────────────────────
OLD_STATE = "  const [cik,           setCik]           = useState(null);"
NEW_STATE  = """  const [cik,           setCik]           = useState(null);
  const [snippetMap,    setSnippetMap]    = useState({});   // hit._id -> string[]
  const [snippetLoad,   setSnippetLoad]   = useState({});   // hit._id -> bool"""

if OLD_STATE not in code:
    print("ERROR: cik state line not found"); raise SystemExit(1)
code = code.replace(OLD_STATE, NEW_STATE, 1)
print("Step 1: added snippetMap/snippetLoad state")

# ── 2. Clear snippetMap on ticker change ──────────────────────────────────────
OLD_CLEAR = """    setSearchResults(null);
    setSearchQuery('');
    setSearchInput('');
    setCik(null);"""
NEW_CLEAR  = """    setSearchResults(null);
    setSearchQuery('');
    setSearchInput('');
    setCik(null);
    setSnippetMap({});
    setSnippetLoad({});"""

if OLD_CLEAR not in code:
    print("ERROR: clear block not found"); raise SystemExit(1)
code = code.replace(OLD_CLEAR, NEW_CLEAR, 1)
print("Step 2: clear snippets on ticker change")

# ── 3. Fetch snippets useEffect — runs when searchResults changes ─────────────
OLD_CLEAR_SEARCH = """  const clearSearch = () => { setSearchResults(null); setSearchQuery(''); setSearchInput(''); };"""
NEW_CLEAR_SEARCH  = """  const clearSearch = () => {
    setSearchResults(null); setSearchQuery(''); setSearchInput('');
    setSnippetMap({}); setSnippetLoad({});
  };

  // Fetch text snippets for first 3 results whenever searchResults changes
  useEffect(() => {
    if (!searchResults || searchResults.length === 0 || !searchQuery) return;
    setSnippetMap({});
    setSnippetLoad({});
    searchResults.slice(0, 3).forEach(hit => {
      const src      = hit._source || {};
      const accession = src.accession_no || hit._id || '';
      const names    = src.display_names || [];
      const cikMatch = names[0]?.match(/CIK (\\d+)/);
      if (!accession || !cikMatch) return;
      const hitCik = parseInt(cikMatch[1], 10);
      setSnippetLoad(prev => ({ ...prev, [hit._id]: true }));
      fetch(`${PROXY}/api/edgar-snippet?accession=${encodeURIComponent(accession)}&cik=${hitCik}&term=${encodeURIComponent(searchQuery)}`)
        .then(r => r.ok ? r.json() : { snippets: [] })
        .then(d => {
          setSnippetMap(prev => ({ ...prev, [hit._id]: d.snippets || [] }));
          setSnippetLoad(prev => ({ ...prev, [hit._id]: false }));
        })
        .catch(() => setSnippetLoad(prev => ({ ...prev, [hit._id]: false })));
    });
  }, [searchResults]);"""

if OLD_CLEAR_SEARCH not in code:
    print("ERROR: clearSearch not found"); raise SystemExit(1)
code = code.replace(OLD_CLEAR_SEARCH, NEW_CLEAR_SEARCH, 1)
print("Step 3: added snippet fetch useEffect")

# ── 4. Replace snippet rendering in the results map ───────────────────────────
OLD_RESULT_SNIPPETS = """                    <div style={{ borderTop:`1px solid ${COLORS.border}22`, paddingTop:8, marginTop:4 }}>
                      {snippets.length > 0 ? (
                        <div style={{ display:'flex', flexDirection:'column', gap:6 }}>
                          {snippets.slice(0,3).map((s,j) => (
                            <div key={j}
                              style={{ fontSize:11, color:COLORS.textMid, lineHeight:1.7, background:COLORS.panel, borderRadius:4, padding:'5px 8px', borderLeft:`2px solid ${COLORS.accent}40` }}
                              dangerouslySetInnerHTML={renderSnippet(s)} />
                          ))}
                        </div>
                      ) : (
                        <div style={{ fontSize:11, color:COLORS.textLo, fontStyle:'italic' }}>
                          {src.description || src.entity_name || 'No preview available \u2014 click to view filing'}
                        </div>
                      )}
                    </div>"""

NEW_RESULT_SNIPPETS = """                    {/* Snippet preview — fetched from filing document */}
                    <div style={{ borderTop:`1px solid ${COLORS.border}22`, paddingTop:8, marginTop:4 }}>
                      {snippetLoad[hit._id] ? (
                        <div style={{ fontSize:11, color:COLORS.textLo, fontStyle:'italic' }}>Loading preview\u2026</div>
                      ) : (snippetMap[hit._id] || []).length > 0 ? (
                        <div style={{ display:'flex', flexDirection:'column', gap:6 }}>
                          {(snippetMap[hit._id] || []).map((s, j) => (
                            <div key={j}
                              style={{ fontSize:11, color:COLORS.textMid, lineHeight:1.7, background:COLORS.panel, borderRadius:4, padding:'5px 8px', borderLeft:`2px solid ${COLORS.accent}40` }}
                              dangerouslySetInnerHTML={{
                                __html: '\u2026' + s
                                  .replace(/\[\[([^\]]+)\]\]/g, '<mark style="background:#2a2000;color:#f4c542;padding:0 2px;border-radius:2px">$1</mark>')
                                  .trim() + '\u2026'
                              }}
                            />
                          ))}
                        </div>
                      ) : i < 3 ? (
                        <div style={{ fontSize:11, color:COLORS.textLo, fontStyle:'italic' }}>No preview in first 500KB of filing</div>
                      ) : (
                        <div style={{ fontSize:11, color:COLORS.textLo, fontStyle:'italic' }}>Click to view filing</div>
                      )}
                    </div>"""

if OLD_RESULT_SNIPPETS not in code:
    print("ERROR: result snippets block not found"); raise SystemExit(1)
code = code.replace(OLD_RESULT_SNIPPETS, NEW_RESULT_SNIPPETS, 1)
print("Step 4: updated snippet rendering with loading state")

# ── 5. Remove now-unused renderSnippet and snippets variable ─────────────────
# The old `snippets` const inside the map and `renderSnippet` helper are no longer needed
OLD_SNIPPETS_VAR = """                // Try all highlight fields EDGAR might use \u2014 key varies by index config
                const hl = hit.highlight || {};
                const snippets = (
                  hl['_all'] ||
                  hl['full_document'] ||
                  hl['file_description'] ||
                  hl['description'] ||
                  hl['text'] ||
                  Object.values(hl).find(v => Array.isArray(v) && v.length > 0) ||
                  []
                );"""

if OLD_SNIPPETS_VAR in code:
    code = code.replace(OLD_SNIPPETS_VAR, '                // Snippets fetched separately via /api/edgar-snippet', 1)
    print("Step 5: removed old snippets var")
else:
    print("Step 5: old snippets var not found (may already be cleaned up)")

with open(SRC, 'w', encoding='utf-8') as f:
    f.write(code)
print(f"\nSaved: {SRC}")
print("Run patch_server_snippet.py first, restart Node server, then React.")