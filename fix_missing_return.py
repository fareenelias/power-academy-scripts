"""
fix_missing_return.py
The stale-block removal accidentally deleted `return (` and `<div>` from
TradingMetricsPanel. This restores them before the Valuation comment.
"""
import sys, os

SRC = r"E:\PowerAcademy\app\poweracademy\src\components\CompanyIntel.js"

with open(SRC, 'r', encoding='utf-8') as f:
    raw = f.read()

code = raw.replace('\r\n', '\n')

# The broken state: JSX floating with no return() wrapper.
# Find the Valuation comment inside TradingMetricsPanel and confirm no return( above it.
# We look for the exact fragment that's now unanchored and prepend return(<div>.

TARGET = "      {/* Valuation */}\n      <div style={{ fontSize:10, fontWeight:700, color:COLORS.textLo, textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:4, marginTop:2 }}>Valuation</div>"

FIXED  = "  return (\n    <div>\n" + TARGET

if FIXED in code:
    print("Already fixed — return( wrapper is present. Nothing to do.")
    sys.exit(0)

if TARGET not in code:
    print("ERROR: Could not find the Valuation comment block. File may be in unexpected state.")
    print("Search for '/* Valuation */' manually around line 290.")
    sys.exit(1)

# Count occurrences to be safe
count = code.count(TARGET)
if count != 1:
    print(f"ERROR: Found {count} occurrences of the Valuation block — expected exactly 1.")
    sys.exit(1)

code = code.replace(TARGET, FIXED, 1)
print("Inserted  return (\\n    <div>  before the Valuation section.")

with open(SRC, 'w', encoding='utf-8') as f:
    f.write(code)

print(f"Saved: {SRC}")
print("Restart React dev server.")