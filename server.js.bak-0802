/**
 * Power Academy — Local API Server
 * Runs on port 3001, handles:
 *   1. Anthropic API proxy (fixes "Failed to fetch" in dashboard)
 *   2. State sync (curriculum, flashcards, CRM, all tabs → state.json)
 *   3. EIA data serving
 *
 * Start: node server.js
 * Auto-start: add to Windows Task Scheduler (see bottom of file)
 */

const http    = require('http');
const https   = require('https');
const fs      = require('fs');
const path    = require('path');
const url     = require('url');
const zlib    = require('zlib');

const PORT       = 3001;
const DATA_DIR   = 'E:\\PowerAcademy\\data';
const STATE_FILE = path.join(DATA_DIR, 'state.json');
const LOG_FILE   = path.join(DATA_DIR, 'server_log.txt');

// ── Your Anthropic API key ─────────────────────────────────
const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY || 'YOUR_ANTHROPIC_API_KEY_HERE';
// Set via environment variable for security:
// In Task Scheduler action: set ANTHROPIC_API_KEY=sk-ant-... && node server.js
// Or in PowerShell before starting: $env:ANTHROPIC_API_KEY="sk-ant-..."

// ── Logging ────────────────────────────────────────────────
function log(msg) {
  const line = `${new Date().toISOString()}  ${msg}`;
  console.log(line);
  try { fs.appendFileSync(LOG_FILE, line + '\n'); } catch(e) {}
}

// ── CORS headers ───────────────────────────────────────────
function cors(res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
}

// ── Read body ──────────────────────────────────────────────
function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', chunk => data += chunk);
    req.on('end', () => {
      try { resolve(JSON.parse(data)); }
      catch(e) { resolve(data); }
    });
    req.on('error', reject);
  });
}

// ── Send JSON with gzip ────────────────────────────────────
// Compresses large JSON payloads when the client accepts gzip. The local data
// files (capiq_export ~2.4MB, broker_research, ferc_opco, earnings_calls, rra_states)
// are the ones that drag over Tailscale; small responses skip compression.
// CORS headers set earlier via cors(res) persist through writeHead.
function sendJSON(req, res, status, body, extraHeaders = {}) {
  const bodyStr = typeof body === 'string' ? body : JSON.stringify(body);
  const headers = { 'Content-Type': 'application/json', ...extraHeaders };
  const accepts = req.headers['accept-encoding'] || '';
  if (/\bgzip\b/.test(accepts) && Buffer.byteLength(bodyStr) > 1024) {
    zlib.gzip(bodyStr, (err, gz) => {
      if (err) { res.writeHead(status, headers); res.end(bodyStr); return; }
      res.writeHead(status, { ...headers, 'Content-Encoding': 'gzip', 'Vary': 'Accept-Encoding' });
      res.end(gz);
    });
  } else {
    res.writeHead(status, headers);
    res.end(bodyStr);
  }
}

// ── Cached static-file serving (gzip once, keyed by mtime) ─────────────────
// The heavy data files (capiq_export ~2.4MB, broker_research, ferc_opco,
// earnings_calls, rra_states, precedents) were being re-read from disk AND
// re-gzipped on EVERY request — the latency you feel switching tabs over
// Tailscale. This caches the raw + gzipped buffers per file and only rebuilds
// when the file's mtime changes on disk, so regenerating a data file
// (extract_all.py, split_broker_json.py, etc.) auto-invalidates the cache.
const _fileCache = new Map(); // filePath -> { mtimeMs, raw:Buffer, gz:Buffer|null }
function serveFile(req, res, filePath, notFoundMsg) {
  let stat;
  try { stat = fs.statSync(filePath); }
  catch(e) {
    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: notFoundMsg || 'Not found', path: filePath }));
    return;
  }
  let entry = _fileCache.get(filePath);
  if (!entry || entry.mtimeMs !== stat.mtimeMs) {
    entry = { mtimeMs: stat.mtimeMs, raw: fs.readFileSync(filePath), gz: null };
    _fileCache.set(filePath, entry);
  }
  const accepts = req.headers['accept-encoding'] || '';
  if (/\bgzip\b/.test(accepts) && entry.raw.length > 1024) {
    if (!entry.gz) entry.gz = zlib.gzipSync(entry.raw); // compress once, then cached
    res.writeHead(200, { 'Content-Type': 'application/json', 'Content-Encoding': 'gzip', 'Vary': 'Accept-Encoding' });
    res.end(entry.gz);
  } else {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(entry.raw);
  }
}


const server = http.createServer(async (req, res) => {
  cors(res);

  // Preflight
  if (req.method === 'OPTIONS') {
    res.writeHead(204); res.end(); return;
  }

  const { pathname } = url.parse(req.url);

  // ── 1. Anthropic API proxy ─────────────────────────────
  if (pathname === '/api/claude' && req.method === 'POST') {
    try {
      const body = await readBody(req);
      const payload = JSON.stringify(body);

      const options = {
        hostname: 'api.anthropic.com',
        port: 443,
        path: '/v1/messages',
        method: 'POST',
        headers: {
          'Content-Type':      'application/json',
          'Content-Length':    Buffer.byteLength(payload),
          'x-api-key':         ANTHROPIC_API_KEY,
          'anthropic-version': '2023-06-01',
        }
      };

      const proxyReq = https.request(options, proxyRes => {
        let responseData = '';
        proxyRes.on('data', chunk => responseData += chunk);
        proxyRes.on('end', () => {
          res.writeHead(proxyRes.statusCode, { 'Content-Type': 'application/json' });
          res.end(responseData);
          log(`Claude API proxy: ${proxyRes.statusCode}`);
        });
      });

      proxyReq.on('error', err => {
        log(`Claude API proxy error: ${err.message}`);
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: { message: err.message } }));
      });

      proxyReq.write(payload);
      proxyReq.end();

    } catch(e) {
      log(`Proxy error: ${e.message}`);
      res.writeHead(500); res.end(JSON.stringify({ error: e.message }));
    }
    return;
  }

  // ── 2. State sync — GET (load) ─────────────────────────
  if (pathname === '/api/state' && req.method === 'GET') {
    try {
      if (!fs.existsSync(STATE_FILE)) {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ exists: false, state: null }));
        return;
      }
      const state = fs.readFileSync(STATE_FILE, 'utf8');
      sendJSON(req, res, 200, { exists: true, state: JSON.parse(state) });
      log('State loaded');
    } catch(e) {
      log(`State load error: ${e.message}`);
      res.writeHead(500); res.end(JSON.stringify({ error: e.message }));
    }
    return;
  }

  // ── 3. State sync — POST (save) ────────────────────────
  if (pathname === '/api/state' && req.method === 'POST') {
    try {
      const body = await readBody(req);
      const toSave = typeof body === 'string' ? body : JSON.stringify(body, null, 2);
      fs.writeFileSync(STATE_FILE, toSave, 'utf8');
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true, saved: new Date().toISOString() }));
      log('State saved');
    } catch(e) {
      log(`State save error: ${e.message}`);
      res.writeHead(500); res.end(JSON.stringify({ error: e.message }));
    }
    return;
  }

  // ── 4. Health check ────────────────────────────────────
  if (pathname === '/api/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      ok: true,
      time: new Date().toISOString(),
      stateFile: fs.existsSync(STATE_FILE),
      apiKeySet: ANTHROPIC_API_KEY !== 'YOUR_ANTHROPIC_API_KEY_HERE',
    }));
    return;
  }

  // ── 4b. IOU data routes ──────────────────────────────────────────────────
  if (pathname === '/api/eia/iou_grouped.json') {
    serveFile(req, res, path.join(DATA_DIR, 'iou_grouped.json'), 'Run build_iou_grouped.py first');
    return;
  }

  // ── 4c. IOU territories full map ──────────────────────────────────────────
  if (pathname === '/api/eia/iou_territories.geojson') {
    serveFile(req, res, path.join(DATA_DIR, 'iou_territories.geojson'), 'Run build_iou_map.py first');
    return;
  }

  // ── 5. Serve EIA plant/territory data ─────────────────
  if (pathname.startsWith('/api/eia/')) {
    const file = pathname.replace('/api/eia/', '');
    const filePath = path.join(DATA_DIR, file.replace(/\//g, path.sep));
    serveFile(req, res, filePath, 'Not found');
    return;
  }

  // ── Market data (generated by fetch_market_data.py) ──
  if (pathname === '/api/market-data') {
    serveFile(req, res, path.join(DATA_DIR, 'market_data.json'), 'market_data.json not found. Run fetch_market_data.py first.');
    return;
  }

  if (pathname.startsWith('/api/market-data/')) {
    const ticker = pathname.replace('/api/market-data/', '').toUpperCase();
    const filePath = path.join(DATA_DIR, 'market_data.json');
    if (!fs.existsSync(filePath)) {
      res.writeHead(404);
      res.end(JSON.stringify({ error: 'market_data.json not found.' }));
      return;
    }
    try {
      const data = JSON.parse(fs.readFileSync(filePath, 'utf8'));
      const co = data.companies?.[ticker];
      if (!co) {
        res.writeHead(404);
        res.end(JSON.stringify({ error: `No market data for ${ticker}` }));
        return;
      }
      sendJSON(req, res, 200, { ...co, generated: data.generated });
    } catch(e) {
      res.writeHead(500);
      res.end(JSON.stringify({ error: e.message }));
    }
    return;
  }

  // ── CapIQ data ─────────────────────────────────────────
  if (pathname === '/api/capiq') {
    serveFile(req, res, path.join(DATA_DIR, 'capiq_export.json'), 'capiq_export.json not found.');
    return;
  }


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
            if (data.length > (maxBytes || 5e6)) r.destroy();
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
      const docHtml = await secFetch(docPath, 2000000);

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

  res.writeHead(404); res.end('Not found');
});

server.listen(PORT, '0.0.0.0', () => {
  log(`Power Academy server running on port ${PORT}`);
  log(`Health: http://localhost:${PORT}/api/health`);
  log(`State:  http://localhost:${PORT}/api/state`);
  log(`Claude: http://localhost:${PORT}/api/claude`);
});

/*
  ── SETUP INSTRUCTIONS ─────────────────────────────────────

  1. Save this file to E:\PowerAcademy\scripts\server.js

  2. Set your Anthropic API key — get it from console.anthropic.com:
     Either set an environment variable (recommended):
       $env:ANTHROPIC_API_KEY="sk-ant-api03-..."
       node server.js

     Or paste it directly into ANTHROPIC_API_KEY above (less secure)

  3. Test it's working:
     http://100.86.108.51:3001/api/health

  4. Add to Windows Task Scheduler to auto-start:
     Action: Start a program
     Program: node
     Arguments: E:\PowerAcademy\scripts\server.js
     Start in: E:\PowerAcademy\scripts\
     Trigger: At startup
     Add environment variable in task: ANTHROPIC_API_KEY=sk-ant-...

  5. Open port 3001 in Windows Firewall if needed:
     netsh advfirewall firewall add rule name="PowerAcademy API" ^
       dir=in action=allow protocol=TCP localport=3001
*/