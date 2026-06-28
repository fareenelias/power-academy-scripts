"""
Fix: adds PowerAcademyQuiz panel to App.js
Searches for any existing panel pattern and inserts after the last one
"""
import re
from pathlib import Path

APP_JS = Path(r"E:\PowerAcademy\app\poweracademy\src\App.js")

def main():
    content = APP_JS.read_text(encoding="utf-8")

    if "activeTab === 'train'" in content or 'activeTab === "train"' in content:
        print("Panel already present.")
        return

    # Strategy: find the closing </div> or closing tag of the main content area
    # by looking for the last activeTab === check and inserting after its closing block
    patterns = [
        # Pattern 1: {activeTab === 'library' && <Library />}  (self-closing)
        r"(\{activeTab\s*===\s*['\"]library['\"]\s*&&\s*<\w+\s*/>})",
        # Pattern 2: {activeTab === 'library' && <Library>...</Library>}
        r"(\{activeTab\s*===\s*['\"]library['\"]\s*&&.*?})",
        # Pattern 3: look for last activeTab check of any kind
        r"(\{activeTab\s*===\s*['\"][^'\"]+['\"]\s*&&[^}]+})",
    ]

    inserted = False
    for pat in patterns:
        matches = list(re.finditer(pat, content, re.DOTALL))
        if matches:
            last_match = matches[-1]
            insert_pos = last_match.end()
            panel = "\n      {activeTab === 'train' && <PowerAcademyQuiz />}"
            content = content[:insert_pos] + panel + content[insert_pos:]
            print(f"Panel inserted after: {last_match.group()[:60]}...")
            inserted = True
            break

    if not inserted:
        # Last resort: show the user what to add and where
        # Find the main return/render area
        print("Auto-insert failed. Please add this line manually in App.js")
        print("Find where your other tab panels are (like the Library panel)")
        print("and add this line right after the last one:")
        print()
        print("      {activeTab === 'train' && <PowerAcademyQuiz />}")
        return

    APP_JS.write_text(content, encoding="utf-8")

    # Verify
    result = APP_JS.read_text(encoding="utf-8")
    ok = "activeTab === 'train'" in result or 'activeTab === "train"' in result
    print(f"Verification: Panel {'OK' if ok else 'STILL MISSING'}")

if __name__ == "__main__":
    main()