"""
add_nav_entries.py
==================
Safely adds imports and nav entries for all 8 new stub components to App.js.

Uses Python string manipulation only — never PowerShell.
Reads the file, patches it, verifies, then writes back.

Run AFTER stub_components.py:
  python add_nav_entries.py
"""

import re
from pathlib import Path

APP_JS = Path(r"E:\PowerAcademy\app\poweracademy\src\App.js")

if not APP_JS.exists():
    raise SystemExit(f"App.js not found at {APP_JS}")

with open(APP_JS, "r", encoding="utf-8") as f:
    src = f.read()

print(f"Loaded App.js ({len(src):,} chars)")

# ── 1. Imports ────────────────────────────────────────────────────────────────
NEW_IMPORTS = [
    ("CRM",           "./components/CRM"),
    ("Sponsors",      "./components/Sponsors"),
    ("MandAScreen",   "./components/MandAScreen"),
    ("CompsLibrary",  "./components/CompsLibrary"),
    ("PitchTracker",  "./components/PitchTracker"),
    ("ReadingLog",    "./components/ReadingLog"),
    ("CalendarView",  "./components/CalendarView"),
    ("WeeklyDebrief", "./components/WeeklyDebrief"),
]

# Find a good anchor import line — insert after CompanyIntel import
# (or after any existing component import)
anchor_patterns = [
    r"import CompanyIntel from './components/CompanyIntel';",
    r"import MapTab from './components/MapTab';",
    r"import Library from './components/Library';",
    r"import Curriculum from './components/Curriculum';",
]

anchor_line = None
for pat in anchor_patterns:
    if re.search(re.escape(pat.replace("'", "'")), src) or pat in src:
        anchor_line = pat
        break

if not anchor_line:
    print("WARNING: Could not find anchor import. Appending imports before first 'function App'.")
    anchor_line = None

imports_to_add = []
for name, path in NEW_IMPORTS:
    import_stmt = f"import {name} from '{path}';"
    if import_stmt not in src:
        imports_to_add.append(import_stmt)
    else:
        print(f"  [skip] {import_stmt} already present")

if imports_to_add:
    block = "\n".join(imports_to_add)
    if anchor_line and anchor_line in src:
        src = src.replace(anchor_line, anchor_line + "\n" + block)
        print(f"  Added {len(imports_to_add)} imports after: {anchor_line[:50]}")
    else:
        # Fallback: insert before 'function App'
        src = src.replace("function App(", block + "\n\nfunction App(", 1)
        print(f"  Added {len(imports_to_add)} imports before function App()")

# ── 2. NAV entries ────────────────────────────────────────────────────────────
# Power Academy nav array typically looks like:
#   const NAV = [ { id: 'map', label: 'Energy Map', icon: '...' }, ... ]
# We'll append new entries before the closing bracket of NAV.

NEW_NAV = [
    ("crm",          "CRM",           "\U0001f91d"),   # handshake
    ("sponsors",     "Sponsors",      "\U0001f3e6"),   # bank
    ("manda",        "M&A Screen",    "\U0001f4c8"),   # chart
    ("comps",        "Comps",         "\U0001f4ca"),   # bar chart
    ("pitches",      "Pitches",       "\U0001f3af"),   # target
    ("reading",      "Reading Log",   "\U0001f4d5"),   # book
    ("calendar",     "Calendar",      "\U0001f4c5"),   # calendar
    ("debrief",      "Weekly Debrief","\U0001f4dd"),   # memo
]

# Detect NAV array pattern
nav_pattern = re.compile(
    r'(const\s+NAV\s*=\s*\[)(.*?)(\];)',
    re.DOTALL
)
nav_match = nav_pattern.search(src)

if nav_match:
    nav_body = nav_match.group(2)
    additions = []
    for nav_id, label, icon in NEW_NAV:
        # Check if already present
        if f"id: '{nav_id}'" in nav_body or f'id: "{nav_id}"' in nav_body:
            print(f"  [skip nav] {nav_id} already in NAV")
            continue
        entry = (
            f"\n  {{ id: '{nav_id}', label: '{label}', "
            f"icon: '{icon}' }},"
        )
        additions.append(entry)

    if additions:
        new_nav_body = nav_body.rstrip().rstrip(",") + "," + "".join(additions) + "\n"
        src = src[:nav_match.start(2)] + new_nav_body + src[nav_match.end(2):]
        print(f"  Added {len(additions)} NAV entries")
    else:
        print("  All NAV entries already present")
else:
    print("WARNING: Could not find 'const NAV = [...]' — add nav entries manually.")

# ── 3. Panel switch cases ──────────────────────────────────────────────────────
# Look for a switch/if-else panel renderer like:
#   case 'map': return <MapTab ... />;
# or activePanel === 'map' patterns

PANEL_CASES = [
    ("crm",       "CRM",          "<CRM />"),
    ("sponsors",  "Sponsors",     "<Sponsors />"),
    ("manda",     "MandAScreen",  "<MandAScreen />"),
    ("comps",     "CompsLibrary", "<CompsLibrary />"),
    ("pitches",   "PitchTracker", "<PitchTracker />"),
    ("reading",   "ReadingLog",   "<ReadingLog />"),
    ("calendar",  "CalendarView", "<CalendarView />"),
    ("debrief",   "WeeklyDebrief","<WeeklyDebrief />"),
]

# Pattern 1: switch statement
switch_case_anchor = re.search(r"case '(map|curriculum|library|companyintel)':", src, re.IGNORECASE)
# Pattern 2: ternary / conditional
cond_anchor = re.search(r"activePanel\s*===\s*'(map|curriculum|library)'", src)

added_panels = 0
if switch_case_anchor:
    # Find the last case before default: or closing brace
    # Insert new cases before 'default:'
    default_match = re.search(r"\s+default:", src)
    if default_match:
        insert_pos = default_match.start()
        cases_block = ""
        for panel_id, _, jsx in PANEL_CASES:
            if f"case '{panel_id}':" not in src:
                cases_block += f"\n      case '{panel_id}': return {jsx};"
                added_panels += 1
        src = src[:insert_pos] + cases_block + src[insert_pos:]
        print(f"  Added {added_panels} panel switch cases before 'default:'")
    else:
        print("  WARNING: switch found but no 'default:' anchor — add panel cases manually")

elif cond_anchor:
    # Conditional chain — add elif/ternary before final else
    # Find the renderPanel function or equivalent
    render_fn = re.search(r"(const render(?:Panel|Content)\s*=.*?\{)(.*?)(^\s*\})", src, re.DOTALL | re.MULTILINE)
    if render_fn:
        fn_body = render_fn.group(2)
        cond_additions = ""
        for panel_id, _, jsx in PANEL_CASES:
            if f"'{panel_id}'" not in fn_body:
                cond_additions += f"\n  if (activePanel === '{panel_id}') return {jsx};"
                added_panels += 1
        if cond_additions:
            new_body = fn_body.rstrip() + cond_additions + "\n"
            src = src[:render_fn.start(2)] + new_body + src[render_fn.end(2):]
            print(f"  Added {added_panels} conditional panel checks")
    else:
        print("  WARNING: Could not find renderPanel function — add panel cases manually")

else:
    print("  WARNING: Could not detect panel rendering pattern.")
    print("  Manually add these panel cases to your renderPanel/switch:\n")
    for panel_id, _, jsx in PANEL_CASES:
        print(f"    case '{panel_id}': return {jsx};")

# ── 4. Write back ──────────────────────────────────────────────────────────────
with open(APP_JS, "w", encoding="utf-8") as f:
    f.write(src)

print(f"\nApp.js written ({len(src):,} chars)")

# ── 5. Verify ─────────────────────────────────────────────────────────────────
with open(APP_JS, "r", encoding="utf-8") as f:
    verify = f.read()

checks = {
    "import CRM":           "import CRM" in verify,
    "import WeeklyDebrief": "import WeeklyDebrief" in verify,
    "import Sponsors":      "import Sponsors" in verify,
    "nav crm":              "'crm'" in verify,
    "nav debrief":          "'debrief'" in verify,
}

print("\nVerification:")
for label, ok in checks.items():
    print(f"  {'[OK]  ' if ok else '[FAIL]'} {label}")

all_ok = all(checks.values())
if all_ok:
    print("\n\u2713 All checks passed — restart npm start to see new tabs")
else:
    print("\n\u26a0  Some checks failed. Review App.js manually for missing entries.")