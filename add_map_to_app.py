"""Add EnergyMap to Power Academy App.js"""
import re
from pathlib import Path

APP_JS = Path(r"E:\PowerAcademy\app\poweracademy\src\App.js")

def main():
    content = APP_JS.read_text(encoding="utf-8")
    backup  = APP_JS.with_suffix(".js.map_bak")
    backup.write_text(content, encoding="utf-8")
    print(f"Backup: {backup}")

    # 1. Import
    if "EnergyMap" not in content:
        last_import = max(m.end() for m in re.finditer(r'^import .+;', content, re.MULTILINE))
        content = content[:last_import] + \
                  "\nimport EnergyMap from './components/EnergyMap';" + \
                  content[last_import:]
        print("Added import")

    # 2. Nav entry after train
    if "'map'" not in content and '"map"' not in content:
        for pattern in [
            r"(\{\s*id:\s*['\"]train['\"].*?\})",
        ]:
            m = re.search(pattern, content, re.DOTALL)
            if m:
                content = content[:m.end()] + \
                          ",\n    { id: 'map', label: 'Map', icon: '\U0001f5fa' }" + \
                          content[m.end():]
                print("Added nav entry")
                break

    # 3. Panel
    if "EnergyMap" not in content or "activeTab === 'map'" not in content:
        patterns = [
            r"(\{activeTab\s*===\s*['\"]train['\"]\s*&&[^}]+\})",
            r"(\{activeTab\s*===\s*['\"][^'\"]+['\"]\s*&&[^}]+\})",
        ]
        for pat in patterns:
            matches = list(re.finditer(pat, content, re.DOTALL))
            if matches:
                last = matches[-1]
                content = content[:last.end()] + \
                          "\n      {activeTab === 'map' && <EnergyMap />}" + \
                          content[last.end():]
                print("Added panel")
                break

    APP_JS.write_text(content, encoding="utf-8")

    result = APP_JS.read_text(encoding="utf-8")
    for label, check in [
        ("Import",     "EnergyMap" in result),
        ("Nav entry",  "'map'" in result or '"map"' in result),
        ("Panel",      "activeTab === 'map'" in result),
    ]:
        print(f"  {'OK' if check else 'MISSING'}: {label}")

if __name__ == "__main__":
    main()