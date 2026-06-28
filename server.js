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

// ── Routes ─────────────────────────────────────────────────
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
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ exists: true, state: JSON.parse(state) }));
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

  // ── 5. Serve EIA plant/territory data ─────────────────
  if (pathname.startsWith('/api/eia/')) {
    const file = pathname.replace('/api/eia/', '');
    const filePath = path.join(DATA_DIR, file.replace(/\//g, path.sep));
    if (fs.existsSync(filePath)) {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(fs.readFileSync(filePath, 'utf8'));
    } else {
      res.writeHead(404); res.end(JSON.stringify({ error: 'Not found', path: filePath }));
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