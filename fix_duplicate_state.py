import re
SRC = r"E:\PowerAcademy\app\poweracademy\src\components\CompanyIntel.js"
with open(SRC, 'r', encoding='utf-8') as f:
    code = f.read().replace('\r\n', '\n')

# Remove the duplicate lines (the ones with trailing comments)
DUPE = ("\n  const [snippetMap,    setSnippetMap]    = useState({});   // hit._id -> string[]\n"
        "  const [snippetLoad,   setSnippetLoad]   = useState({});   // hit._id -> bool")
if DUPE in code:
    code = code.replace(DUPE, '', 1)
    print("Removed duplicate state declarations")
else:
    print("Duplicate not found — check lines 1449-1452 manually")

with open(SRC, 'w', encoding='utf-8') as f:
    f.write(code)