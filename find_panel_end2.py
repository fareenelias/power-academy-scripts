"""
Finds the end of FilingsPanel by brace counting,
and shows what text follows it.
"""
SRC = r"E:\PowerAcademy\app\poweracademy\src\components\CompanyIntel.js"
with open(SRC, 'r', encoding='utf-8') as f:
    code = f.read().replace('\r\n', '\n')

start = code.find('\nfunction FilingsPanel(')
if start == -1:
    print("FilingsPanel not found"); raise SystemExit(1)

# Count braces from the opening { to find closing }
depth = 0
i = start
found_first = False
end = -1
while i < len(code):
    c = code[i]
    if c == '{':
        depth += 1
        found_first = True
    elif c == '}':
        depth -= 1
        if found_first and depth == 0:
            end = i + 1
            break
    i += 1

print(f"FilingsPanel: chars {start}–{end}")
print(f"\nFirst 200 chars after FilingsPanel end:")
print(repr(code[end:end+200]))