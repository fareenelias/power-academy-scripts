"""
fix_snippet_size.py
1. Bumps edgar-snippet fetch from 500KB to 2MB in server.js
2. Removes "not found" message in CompanyIntel.js — shows nothing instead
"""

# ── server.js: increase fetch size ───────────────────────────────────────────
SRV = r"E:\PowerAcademy\scripts\server.js"
with open(SRV, 'r', encoding='utf-8') as f:
    srv = f.read()

OLD_SIZE = "if (data.length > (maxBytes || 2e6)) r.destroy();"
NEW_SIZE = "if (data.length > (maxBytes || 5e6)) r.destroy();"
# Also bump the call site
OLD_CALL = "const docHtml = await secFetch(docPath, 500000);"
NEW_CALL = "const docHtml = await secFetch(docPath, 2000000);"

if OLD_CALL in srv:
    srv = srv.replace(OLD_CALL, NEW_CALL, 1)
    print("Server: bumped doc fetch to 2MB")
else:
    print("Server: fetch call not found — check manually")

if OLD_SIZE in srv:
    srv = srv.replace(OLD_SIZE, NEW_SIZE, 1)

with open(SRV, 'w', encoding='utf-8') as f:
    f.write(srv)

# ── CompanyIntel.js: remove "not found" message ───────────────────────────────
CI = r"E:\PowerAcademy\app\poweracademy\src\components\CompanyIntel.js"
with open(CI, 'r', encoding='utf-8') as f:
    code = f.read().replace('\r\n', '\n')

# Replace the "not found" branch with null so the div just collapses
OLD_MSG = (
    "                      ) : i < 3 ? (\n"
    "                        <div style={{ fontSize:11, color:COLORS.textLo, fontStyle:'italic' }}>Term not found in first 500KB of filing</div>\n"
    "                      ) : (\n"
    "                        <div style={{ fontSize:11, color:COLORS.textLo, fontStyle:'italic' }}>Click View to open on EDGAR</div>\n"
    "                      )}"
)
NEW_MSG = (
    "                      ) : null}"
)

if OLD_MSG in code:
    code = code.replace(OLD_MSG, NEW_MSG, 1)
    print("Component: removed 'not found' message")
else:
    print("Component: message not found — check manually")

with open(CI, 'w', encoding='utf-8') as f:
    f.write(code)
print("Done. Restart Node server for the 2MB change to take effect.")