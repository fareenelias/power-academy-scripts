"""
patch_server_snippet.py
Adds /api/edgar-snippet route to server.js.
Fetches filing document from SEC, strips HTML, returns text snippets around the search term.
"""

SRC = r"E:\PowerAcademy\scripts\server.js"

with open(SRC, 'r', encoding='utf-8') as f:
    code = f.read()

if '/api/edgar-snippet' in code:
    print("Route already present.")
    raise SystemExit(0)

SNIPPET_ROUTE = r"""
  // ── EDGAR filing snippet extractor ────────────────────────────────────────
  // Fetches the primary document of an EDGAR filing, strips HTML,
  // and returns up to 3 text snippets (200 chars each side) around the search term.
  // Uses Range header to avoid downloading full 10-K (only first 500KB).
  if (pathname === '/api/edgar-snippet' && req.method === 'GET') {
    const q = url.parse(req.url, true).query;
    const { accession, cik, term } = q;
    if (!accession || !cik || !term) {
      res.writeHead(400); res.end(JSON.stringify({ error: 'Missing params', snippets: [] }));
      return;
    }

    // Helper: fetch a URL, return text (stops at maxBytes)
    function secFetch(path, maxBytes) {
      return new Promise((resolve) => {
        const opts = {
          hostname: 'www.sec.gov', port: 443, path, method: 'GET',
          headers: {
            'User-Agent': 'PowerAcademy/1.0 power-academy@internal',
            'Accept-Encoding': 'identity',
            ...(maxBytes ? { 'Range': `bytes=0-${maxBytes}` } : {}),
          }
        };
        let data = '';
        const r = https.request(opts, rsp => {
          rsp.on('data', chunk => {
            data += chunk;
            if (data.length > (maxBytes || 2e6)) r.destroy();
          });
          rsp.on('end',  () => resolve(data));
        });
        r.on('error', () => resolve(data));  // resolve with whatever we got
        r.end();
      });
    }

    try {
      const accNoDashes = accession.replace(/-/g, '');
      const indexPath   = `/Archives/edgar/data/${cik}/${accNoDashes}/${accNoDashes}-index.htm`;

      // Step 1: fetch the filing index page (small, ~10KB)
      const indexHtml = await secFetch(indexPath);

      // Step 2: find the primary document link (first .htm that isn't the index itself)
      const links = [...indexHtml.matchAll(/href="([^"]+\.htm[^"]*)"/gi)].map(m => m[1]);
      const primary = links.find(h =>
        !h.toLowerCase().includes('-index') &&
        !h.toLowerCase().includes('viewer') &&
        !h.toLowerCase().includes('xbrl')
      );

      if (!primary) {
        res.writeHead(200); res.end(JSON.stringify({ snippets: [] }));
        return;
      }

      const docPath = primary.startsWith('/')
        ? primary
        : `/Archives/edgar/data/${cik}/${accNoDashes}/${primary}`;

      // Step 3: fetch first 500KB of primary document
      const docHtml = await secFetch(docPath, 500000);

      // Step 4: strip HTML and extract snippets (200 chars of context each side)
      const text    = docHtml.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
      const termLow = term.toLowerCase();
      const snippets = [];
      let pos = 0;
      while (snippets.length < 3 && pos < text.length) {
        const idx = text.toLowerCase().indexOf(termLow, pos);
        if (idx === -1) break;
        const start   = Math.max(0, idx - 200);
        const end     = Math.min(text.length, idx + termLow.length + 200);
        const raw     = text.slice(start, end).trim();
        const mStart  = idx - start;
        // Wrap match in [[...]] so client can highlight it
        const snippet = raw.slice(0, mStart) +
          '[[' + raw.slice(mStart, mStart + termLow.length) + ']]' +
          raw.slice(mStart + termLow.length);
        snippets.push(snippet);
        pos = idx + termLow.length + 100;
      }

      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ snippets }));
      log(`EDGAR snippet: ${accession.slice(0,20)} "${term}" -> ${snippets.length} snippet(s)`);

    } catch(e) {
      log(`EDGAR snippet error: ${e.message}`);
      res.writeHead(200); res.end(JSON.stringify({ snippets: [], error: e.message }));
    }
    return;
  }

"""

ANCHOR = "  res.writeHead(404); res.end('Not found');"
code = code.replace(ANCHOR, SNIPPET_ROUTE + ANCHOR, 1)

with open(SRC, 'w', encoding='utf-8') as f:
    f.write(code)
print(f"Added /api/edgar-snippet to {SRC}")
print("Restart server.js")