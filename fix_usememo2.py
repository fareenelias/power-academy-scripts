"""
fix_usememo2.py
useMemo is used in the hook body but never destructured at the top.
Finds the React hooks destructure line and adds useMemo to it.
"""
import sys, re

SRC = r"E:\PowerAcademy\app\poweracademy\src\components\CompanyIntel.js"

with open(SRC, 'r', encoding='utf-8') as f:
    raw = f.read()
code = raw.replace('\r\n', '\n')

# Find the specific destructure line that has useState in it
# (could be const { ... } = React  or  import { ... } from 'react')
lines = code.split('\n')
target_idx = None
for i, line in enumerate(lines):
    if 'useState' in line and ('useMemo' not in line) and (
        ('const {' in line and '} = React' in line) or
        ("from 'react'" in line) or ('from "react"' in line)
    ):
        target_idx = i
        print(f"Found destructure at line {i+1}: {line.strip()}")
        break

if target_idx is None:
    # Broader search — any line with useState and a destructure
    for i, line in enumerate(lines):
        if 'useState' in line and 'useMemo' not in line and 'const {' in line:
            target_idx = i
            print(f"Found (broad) at line {i+1}: {line.strip()}")
            break

if target_idx is None:
    print("ERROR: Could not find the useState destructure line.")
    print("Lines containing 'useState':")
    for i, line in enumerate(lines):
        if 'useState' in line:
            print(f"  line {i+1}: {line.strip()}")
    sys.exit(1)

# Insert useMemo — find the last hook name before the closing }
old_line = lines[target_idx]
# Add useMemo before the closing } or before ' = React' or before " from '"
new_line = re.sub(
    r'(useCallback|useRef|useEffect|useState)(\s*[}\)])',
    r'\1, useMemo\2',
    old_line,
    count=1
)

if new_line == old_line:
    # Fallback: just insert before the closing brace
    new_line = old_line.replace(' }', ', useMemo }', 1)

lines[target_idx] = new_line
print(f"Updated line: {new_line.strip()}")

code = '\n'.join(lines)
with open(SRC, 'w', encoding='utf-8') as f:
    f.write(code)
print(f"Saved: {SRC}")