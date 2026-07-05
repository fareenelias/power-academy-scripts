"""
patch_filings_search.py
Replaces FilingsPanel with a version that has full-text search via SEC EDGAR EFTS.
- Type filter pills unchanged
- New search bar: on Enter/click, queries efts.sec.gov with the term + entity name
- Results show form type, date, and text snippets with highlighted matches
- Clear button returns to normal FMP filings table
"""
import re

SRC = r"E:\PowerAcademy\app\poweracademy\src\components\CompanyIntel.js"

with open(SRC, 'r', encoding='utf-8') as f:
    raw = f.read()
code = raw.replace('\r\n', '\n')

# ── Find the FilingsPanel function boundaries ────────────────────────────────
start = code.find('\nfunction FilingsPanel({ ticker })')
end   = code.find('\nfunction ManualPanel(')
if start == -1 or end == -1:
    print(f"ERROR: FilingsPanel start={start}, ManualPanel start={end}")
    raise SystemExit(1)

old_panel = code[start:end]
print(f"Found FilingsPanel: chars {start}–{end} ({len(old_panel)} chars)")

NEW_PANEL = r'''
function FilingsPanel({ ticker }) {
  const [filings,       setFilings]       = useState(null);
  const [loading,       setLoading]       = useState(true);
  const [typeFilter,    setTypeFilter]    = useState('key');
  const [searchInput,   setSearchInput]   = useState('');
  const [searchQuery,   setSearchQuery]   = useState('');
  const [searchResults, setSearchResults] = useState(null);
  const [searchLoading, setSearchLoading] = useState(false);

  const KEY_FORMS = ['10-K','10-Q','8-K','DEF 14A','S-3','S-4','SC 13D','SC 13G'];
  const company    = COMPANIES.find(c => c.ticker === ticker);
  const entityName = company?.name || ticker;

  // Load recent filings from FMP
  useEffect(() => {
    if (!ticker) return;
    setLoading(true);
    setSearchResults(null);
    setSearchQuery('');
    setSearchInput('');
    const toDate   = new Date().toISOString().split('T')[0];
    const fromDate = new Date(Date.now() - 730*24*60*60*1000).toISOString().split('T')[0];
    fmpFetch(`/stable/sec-filings-search/symbol?symbol=${ticker}&from=${fromDate}&to=${toDate}&limit=100`)
      .then(f => { setFilings(Array.isArray(f) ? f : []); setLoading(false); });
  }, [ticker]);

  // Full-text search via SEC EDGAR EFTS (free, public, CORS-enabled)
  const runSearch = (q) => {
    if (!q.trim()) { setSearchResults(null); setSearchQuery(''); return; }
    const trimmed = q.trim();
    setSearchLoading(true);
    setSearchQuery(trimmed);
    const toDate   = new Date().toISOString().split('T')[0];
    const fromDate = new Date(Date.now() - 730*24*60*60*1000).toISOString().split('T')[0];
    const formsParam = (typeFilter !== 'all' && typeFilter !== 'key') ? `&forms=${encodeURIComponent(typeFilter)}` : '';
    const url = [
      'https://efts.sec.gov/LATEST/search-index',
      `?q=${encodeURIComponent('"' + trimmed + '"')}`,
      `&dateRange=custom&startdt=${fromDate}&enddt=${toDate}`,
      `&entity=${encodeURIComponent(entityName)}`,
      formsParam,
    ].join('');
    fetch(url)
      .then(r => r.ok ? r.json() : null)
      .then(d => { setSearchResults(d?.hits?.hits || []); setSearchLoading(false); })
      .catch(() => { setSearchResults([]); setSearchLoading(false); });
  };

  const clearSearch = () => { setSearchResults(null); setSearchQuery(''); setSearchInput(''); };

  // Build EDGAR filing viewer URL from hit
  const filingUrl = (hit) => {
    const src = hit._source || {};
    const accNo = (src.accession_no || hit._id || '').replace(/-/g, '');
    const cikMatch = (src.display_names || [''])[0].match(/CIK (\d+)/);
    if (cikMatch && accNo)
      return `https://www.sec.gov/Archives/edgar/data/${parseInt(cikMatch[1], 10)}/${accNo}/${accNo}-index.htm`;
    return `https://efts.sec.gov/LATEST/search-index?q=${encodeURIComponent('"' + searchQuery + '"')}&entity=${encodeURIComponent(entityName)}`;
  };

  // Render snippet: convert EDGAR <em> tags to visible highlights
  const renderSnippet = (html) => ({
    __html: '\u2026' + html
      .replace(/<em>/g,  '<mark style="background:#2a2000;color:#f4c542;padding:0 2px;border-radius:2px">')
      .replace(/<\/em>/g, '</mark>') + '\u2026'
  });

  if (loading) return <Loading />;

  const filtered = typeFilter === 'all'
    ? filings
    : typeFilter === 'key'
    ? (filings||[]).filter(f => KEY_FORMS.includes(f.formType||f.type))
    : (filings||[]).filter(f => (f.formType||f.type) === typeFilter);

  const inSearch = searchResults !== null;

  return (
    <div>
      {/* Type filter pills */}
      <div style={{ display:'flex', gap:6, marginBottom:10, flexWrap:'wrap' }}>
        {[
          { id:'key',     label:'Key Filings' },
          { id:'10-K',    label:'10-K' },
          { id:'10-Q',    label:'10-Q' },
          { id:'8-K',     label:'8-K' },
          { id:'DEF 14A', label:'Proxy' },
          { id:'S-3',     label:'S-3' },
          { id:'S-4',     label:'S-4' },
          { id:'all',     label:'All' },
        ].map(t => (
          <button key={t.id} onClick={() => setTypeFilter(t.id)}
            style={{ padding:'4px 10px', borderRadius:20, border:`1px solid ${typeFilter===t.id?COLORS.accent:COLORS.border}`, background:typeFilter===t.id?COLORS.accentLo:'transparent', color:typeFilter===t.id?COLORS.accent:COLORS.textMid, fontSize:11, fontWeight:typeFilter===t.id?700:400, cursor:'pointer' }}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Search bar */}
      <div style={{ display:'flex', gap:8, marginBottom:14, alignItems:'center' }}>
        <div style={{ flex:1, position:'relative' }}>
          <span style={{ position:'absolute', left:10, top:'50%', transform:'translateY(-50%)', color:COLORS.textLo, fontSize:12, pointerEvents:'none' }}>&#128269;</span>
          <input
            value={searchInput}
            onChange={e => setSearchInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && runSearch(searchInput)}
            placeholder={`Search full text of ${entityName} SEC filings\u2026`}
            style={{ width:'100%', background:COLORS.bg, border:`1px solid ${inSearch?COLORS.accent:COLORS.border}`, borderRadius:6, padding:'7px 10px 7px 32px', fontSize:12, color:COLORS.text, outline:'none', boxSizing:'border-box', fontFamily:'inherit' }}
          />
        </div>
        <button onClick={() => runSearch(searchInput)}
          style={{ padding:'7px 14px', borderRadius:6, background:COLORS.accent, color:'#fff', border:'none', fontSize:12, fontWeight:600, cursor:'pointer', whiteSpace:'nowrap' }}>
          Search
        </button>
        {inSearch && (
          <button onClick={clearSearch}
            style={{ padding:'7px 12px', borderRadius:6, background:'transparent', color:COLORS.textMid, border:`1px solid ${COLORS.border}`, fontSize:12, cursor:'pointer' }}>
            Clear
          </button>
        )}
      </div>

      {/* Search results */}
      {inSearch ? (
        searchLoading ? <Loading /> : (
          <div>
            <div style={{ fontSize:11, color:COLORS.textLo, marginBottom:10 }}>
              {searchResults.length > 0
                ? `${searchResults.length} filing${searchResults.length !== 1 ? 's' : ''} contain \u201c${searchQuery}\u201d`
                : `No filings found containing \u201c${searchQuery}\u201d`}
              <span style={{ marginLeft:8, color:COLORS.border }}>&#183;</span>
              <span style={{ marginLeft:8 }}>Full-text search via SEC EDGAR</span>
            </div>
            <div style={{ display:'flex', flexDirection:'column', gap:10 }}>
              {searchResults.map((hit, i) => {
                const src      = hit._source || {};
                const snippets = hit.highlight?.['_all'] || hit.highlight?.['full_document'] || [];
                const url      = filingUrl(hit);
                return (
                  <div key={i} style={{ background:COLORS.bg, border:`1px solid ${COLORS.border}`, borderRadius:8, padding:'12px 14px' }}>
                    <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom: snippets.length ? 8 : 0 }}>
                      <Pill label={src.form_type || '--'} color={COLORS.accent} />
                      <span style={{ fontSize:11, color:COLORS.textLo, whiteSpace:'nowrap' }}>{src.file_date || '--'}</span>
                      {src.period_of_report && (
                        <span style={{ fontSize:10, color:COLORS.textLo }}>period {src.period_of_report}</span>
                      )}
                      <span style={{ flex:1 }} />
                      <a href={url} target="_blank" rel="noopener noreferrer"
                        style={{ fontSize:11, fontWeight:600, color:COLORS.accent, textDecoration:'none', whiteSpace:'nowrap' }}>
                        View on EDGAR &#8599;
                      </a>
                    </div>
                    {snippets.length > 0 && (
                      <div style={{ borderTop:`1px solid ${COLORS.border}33`, paddingTop:8, display:'flex', flexDirection:'column', gap:6 }}>
                        {snippets.slice(0, 3).map((s, j) => (
                          <div key={j} style={{ fontSize:11, color:COLORS.textLo, lineHeight:1.65, fontFamily:'inherit' }}
                            dangerouslySetInnerHTML={renderSnippet(s)} />
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )
      ) : (
        /* Normal filings table */
        <div style={{ background:COLORS.bg, border:`1px solid ${COLORS.border}`, borderRadius:8, overflow:'hidden' }}>
          <table style={{ width:'100%', borderCollapse:'collapse', fontSize:12 }}>
            <thead>
              <tr style={{ borderBottom:`1px solid ${COLORS.border}` }}>
                {['Type','Date','Description','Link'].map(h => (
                  <th key={h} style={{ padding:'10px 12px', textAlign:'left', color:COLORS.textLo, fontWeight:600, fontSize:11, textTransform:'uppercase', letterSpacing:'0.06em' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(filtered||[]).slice(0, 20).map((f, i) => (
                <tr key={i} style={{ borderBottom:`1px solid ${COLORS.border}`, background: i%2===0 ? 'transparent' : COLORS.panel }}>
                  <td style={{ padding:'9px 12px' }}><Pill label={f.formType||f.type||'--'} color={COLORS.accent} /></td>
                  <td style={{ padding:'9px 12px', color:COLORS.textLo, whiteSpace:'nowrap' }}>{(f.filedAt||f.fillingDate||'--').split('T')[0].split(' ')[0]}</td>
                  <td style={{ padding:'9px 12px', color:COLORS.textMid, maxWidth:300, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{f.description||f.formType||f.type||'--'}</td>
                  <td style={{ padding:'9px 12px' }}>
                    {(f.finalLink||f.linkToFilingDetails||f.url) &&
                      <a href={f.finalLink||f.linkToFilingDetails||f.url} target="_blank" rel="noopener noreferrer"
                        style={{ color:COLORS.accent, textDecoration:'none', fontSize:11, fontWeight:600 }}>View</a>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {(!filtered || filtered.length === 0) && <Empty msg="No filings found" />}
        </div>
      )}
    </div>
  );
}
'''

code = code[:start] + NEW_PANEL + code[end:]
print(f"Replaced FilingsPanel ({len(old_panel)} chars -> {len(NEW_PANEL)} chars)")

with open(SRC, 'w', encoding='utf-8') as f:
    f.write(code)
print(f"Saved: {SRC}")
print("Try a search like: wildfire, data center, rate case, nuclear, MISO")