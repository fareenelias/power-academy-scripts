"""
patch_server_edgar.py
Adds /api/edgar-search proxy route to server.js.
Node proxies to efts.sec.gov — no CORS issues.
"""

SRC = r"E:\PowerAcademy\scripts\server.js"

with open(SRC, 'r', encoding='utf-8') as f:
    code = f.read()

EDGAR_ROUTE = r"""
  // ── EDGAR full-text search proxy ──────────────────────
  // Proxies to efts.sec.gov — avoids CORS block in browser.
  // SEC requires User-Agent with contact info per their crawl policy.
  if (pathname === '/api/edgar-search' && req.method === 'GET') {
    try {
      const parsedUrl = url.parse(req.url, true);
      const params    = new URLSearchParams(parsedUrl.query).toString();
      const options   = {
        hostname: 'efts.sec.gov',
        port:     443,
        path:     `/LATEST/search-index?${params}`,
        method:   'GET',
        headers:  {
          'User-Agent': 'PowerAcademy/1.0 power-academy@internal',
          'Accept':     'application/json',
        },
      };
      const proxyReq = https.request(options, proxyRes => {
        let data = '';
        proxyRes.on('data', chunk => data += chunk);
        proxyRes.on('end', () => {
          res.writeHead(proxyRes.statusCode, { 'Content-Type': 'application/json' });
          res.end(data);
          log(`EDGAR search: ${proxyRes.statusCode} (${params.slice(0,80)})`);
        });
      });
      proxyReq.on('error', err => {
        log(`EDGAR search error: ${err.message}`);
        res.writeHead(500); res.end(JSON.stringify({ error: err.message }));
      });
      proxyReq.end();
    } catch(e) {
      log(`EDGAR search error: ${e.message}`);
      res.writeHead(500); res.end(JSON.stringify({ error: e.message }));
    }
    return;
  }

"""

# Insert before the final 404 line
ANCHOR = "  res.writeHead(404); res.end('Not found');"
if ANCHOR not in code:
    print("ERROR: could not find final 404 anchor in server.js")
    raise SystemExit(1)

if '/api/edgar-search' in code:
    print("EDGAR route already present — nothing to do.")
    raise SystemExit(0)

code = code.replace(ANCHOR, EDGAR_ROUTE + ANCHOR, 1)

with open(SRC, 'w', encoding='utf-8') as f:
    f.write(code)
print(f"Added /api/edgar-search route to {SRC}")
print("Restart server.js: stop the running instance and run: node server.js")