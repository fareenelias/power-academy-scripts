"""
fix_usememo.py — adds useMemo to the React hooks destructure in CompanyIntel.js
"""
import sys, re

SRC = r"E:\PowerAcademy\app\poweracademy\src\components\CompanyIntel.js"

with open(SRC, 'r', encoding='utf-8') as f:
    raw = f.read()

code = raw.replace('\r\n', '\n')

if 'useMemo' in code:
    print("useMemo already present in file — nothing to do.")
    sys.exit(0)

# Find the line that destructures React hooks (useState is always there)
# Pattern: const { useState, ... } = React;  OR  import { useState, ... } from 'react';
# Try several patterns
patterns = [
    # const { ..., useCallback } = React;  or similar
    (r'const \{([^}]+)\} = React;',  lambda m: m.group(0).replace(m.group(1), m.group(1).rstrip() + ', useMemo')),
    # import { useState, ... } from 'react'
    (r"import \{([^}]+)\} from 'react'", lambda m: m.group(0).replace(m.group(1), m.group(1).rstrip() + ', useMemo')),
    (r'import \{([^}]+)\} from "react"', lambda m: m.group(0).replace(m.group(1), m.group(1).rstrip() + ', useMemo')),
]

fixed = False
for pattern, replacer in patterns:
    match = re.search(pattern, code)
    if match and 'useState' in match.group(1):
        old = match.group(0)
        new = replacer(match)
        code = code.replace(old, new, 1)
        print(f"Added useMemo to: {new[:80]}...")
        fixed = True
        break

if not fixed:
    # Last resort: find the line with useState and show it
    for i, line in enumerate(code.split('\n'), 1):
        if 'useState' in line and ('const {' in line or 'import {' in line):
            print(f"Found at line {i}: {line}")
            print("Could not auto-patch. Add 'useMemo' to this line manually.")
    sys.exit(1)

with open(SRC, 'w', encoding='utf-8') as f:
    f.write(code)

print(f"Saved: {SRC}")