"""
Adds PowerAcademyQuiz to Power Academy App.js
Run from anywhere: python add_quiz_to_app.py
"""
import re
from pathlib import Path

APP_JS = Path(r"E:\PowerAcademy\app\poweracademy\src\App.js")

def patch(content):
    # 1. Add import after last import line
    if "PowerAcademyQuiz" in content:
        print("Import already present — skipping import step")
    else:
        last_import = max(m.end() for m in re.finditer(r'^import .+;$', content, re.MULTILINE))
        content = content[:last_import] + \
                  "\nimport PowerAcademyQuiz from './components/PowerAcademyQuiz';" + \
                  content[last_import:]
        print("Added import")

    # 2. Add nav entry — find the nav items array/section
    # Looks for pattern like: { id: 'library', label: '...', icon: '...' }
    # and appends after the last one
    if "'train'" in content or '"train"' in content:
        print("Nav entry already present — skipping")
    else:
        # Find last nav item entry and insert after it
        nav_pattern = re.compile(
            r"(\{\s*id:\s*['\"]library['\"].*?\})",
            re.DOTALL
        )
        match = nav_pattern.search(content)
        if match:
            insert_pos = match.end()
            nav_entry = ",\n    { id: 'train', label: 'Train', icon: '\U0001f393' }"
            content = content[:insert_pos] + nav_entry + content[insert_pos:]
            print("Added nav entry")
        else:
            print("WARNING: Could not find library nav entry to insert after — add manually:")
            print("  { id: 'train', label: 'Train', icon: '\U0001f393' }")

    # 3. Add panel — find where other panels render
    if "PowerAcademyQuiz" in content and "activeTab === 'train'" in content:
        print("Panel already present — skipping")
    else:
        # Find the library panel pattern and insert after it
        panel_pattern = re.compile(
            r"(activeTab === ['\"]library['\"].*?</[^>]+>)",
            re.DOTALL
        )
        match = panel_pattern.search(content)
        if match:
            insert_pos = match.end()
            panel = "\n      {activeTab === 'train' && <PowerAcademyQuiz />}"
            content = content[:insert_pos] + panel + content[insert_pos:]
            print("Added panel")
        else:
            print("WARNING: Could not find library panel — add manually:")
            print("  {activeTab === 'train' && <PowerAcademyQuiz />}")

    return content

def main():
    if not APP_JS.exists():
        print(f"ERROR: App.js not found at {APP_JS}")
        return

    original = APP_JS.read_text(encoding="utf-8")

    # Backup
    backup = APP_JS.with_suffix(".js.bak")
    backup.write_text(original, encoding="utf-8")
    print(f"Backup saved to {backup}")

    patched = patch(original)

    APP_JS.write_text(patched, encoding="utf-8")
    print(f"App.js updated successfully")

    # Verify
    result = APP_JS.read_text(encoding="utf-8")
    checks = [
        ("Import",     "PowerAcademyQuiz" in result and "import" in result),
        ("Nav entry",  "'train'" in result or '"train"' in result),
        ("Panel",      "activeTab === 'train'" in result),
    ]
    print("\nVerification:")
    for label, ok in checks:
        print(f"  {'OK' if ok else 'MISSING'}: {label}")

if __name__ == "__main__":
    main()