"""
fix_edgar_snippets.py
- Logs the full highlight structure of the first hit so we can see exact field names
- Broadens snippet lookup to try all highlight fields, not just _all
- Shows up to 3 snippets per result with better styling
"""

SRC = r"E:\PowerAcademy\app\poweracademy\src\components\CompanyIntel.js"

with open(SRC, 'r', encoding='utf-8') as f:
    raw = f.read()
code = raw.replace('\r\n', '\n')

# ── 1. Improve the raw response log to show the full first hit highlight ──────
OLD_LOG = """        console.log('EDGAR raw response:', JSON.stringify(d).slice(0, 500));
        setSearchResults(d?.hits?.hits || []);"""

NEW_LOG = """        const hits = d?.hits?.hits || [];
        if (hits[0]) {
          console.log('EDGAR highlight keys:', Object.keys(hits[0].highlight || {}));
          console.log('EDGAR first hit highlight:', JSON.stringify(hits[0].highlight).slice(0, 800));
        }
        setSearchResults(hits);"""

if OLD_LOG not in code:
    print("ERROR: old log block not found")
    raise SystemExit(1)
code = code.replace(OLD_LOG, NEW_LOG, 1)
print("Step 1: improved debug logging")

# ── 2. Broaden snippet extraction — try all highlight fields ─────────────────
# Replace the snippets line inside the results map
OLD_SNIPPETS = """                const snippets = hit.highlight?.['_all'] || hit.highlight?.full_document || [];"""

NEW_SNIPPETS = """                // Try all highlight fields EDGAR might use — key varies by index config
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

if OLD_SNIPPETS not in code:
    print("ERROR: old snippets line not found")
    raise SystemExit(1)
code = code.replace(OLD_SNIPPETS, NEW_SNIPPETS, 1)
print("Step 2: broadened snippet field lookup")

# ── 3. Improve snippet rendering — more visible, always show something ────────
OLD_RENDER = """                    {snippets.length > 0 && (
                      <div style={{ borderTop:`1px solid ${COLORS.border}33`, paddingTop:8, display:'flex', flexDirection:'column', gap:6 }}>
                        {snippets.slice(0,3).map((s,j) => (
                          <div key={j} style={{ fontSize:11, color:COLORS.textLo, lineHeight:1.65 }}
                            dangerouslySetInnerHTML={renderSnippet(s)} />
                        ))}
                      </div>
                    )}"""

NEW_RENDER = """                    <div style={{ borderTop:`1px solid ${COLORS.border}22`, paddingTop:8, marginTop:4 }}>
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
                          {src.description || src.entity_name || 'No preview available — click to view filing'}
                        </div>
                      )}
                    </div>"""

if OLD_RENDER not in code:
    print("ERROR: old render block not found")
    raise SystemExit(1)
code = code.replace(OLD_RENDER, NEW_RENDER, 1)
print("Step 3: improved snippet rendering with fallback")

with open(SRC, 'w', encoding='utf-8') as f:
    f.write(code)
print(f"\nSaved: {SRC}")
print("Search 'florida' in NEE, then check DevTools console for 'EDGAR highlight keys:' to see what field names EDGAR uses.")