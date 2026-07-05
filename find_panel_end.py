"""Finds what function comes after FilingsPanel in the current file."""
import re
SRC = r"E:\PowerAcademy\app\poweracademy\src\components\CompanyIntel.js"
with open(SRC, 'r', encoding='utf-8') as f:
    code = f.read().replace('\r\n', '\n')

start = code.find('\nfunction FilingsPanel(')
print(f"FilingsPanel starts at char: {start}")

# Find all top-level function declarations after FilingsPanel
fns = [(m.start(), m.group()) for m in re.finditer(r'\nfunction \w+\(', code) if m.start() > start]
print("Functions after FilingsPanel:")
for pos, name in fns[:6]:
    print(f"  char {pos}: {name.strip()}")