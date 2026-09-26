"""add_pdf_page_anchors.py - give PDF evidence links in precedents.json a #page=N deep-link.

Rule: a verification field whose `url` is a PDF with no #page, and whose `src` note cites
a page ("p.13", "p.12-13", "pp. 4-5", "slide 12"), gets `#page=<first page>` appended.
The un-anchored URL is kept in `url_nopage` so the change is reversible and auditable.
Links whose note cites no page are left alone (a guessed page is worse than none).

    python scripts\\add_pdf_page_anchors.py            # dry run
    python scripts\\add_pdf_page_anchors.py --write    # writes, backup .bak-prepage-YYYYMMDD
"""
import json, re, sys, shutil, datetime, pathlib

DATA = pathlib.Path(r'E:\PowerAcademy\data') if sys.platform == 'win32' else pathlib.Path(sys.argv[-1] if sys.argv[-1].endswith('data') else '.')
PAGE_RE = re.compile(r'\b(?:pp?\.|page|slide)\s*(\d{1,3})\b', re.I)

def walk(o, path, hits):
    if isinstance(o, dict):
        url = o.get('url')
        if isinstance(url, str) and re.search(r'\.pdf($|[?#])', url, re.I) and '#page=' not in url:
            m = PAGE_RE.search(str(o.get('src') or ''))
            if m:
                hits.append((path, url, int(m.group(1)), o))
        for k, v in o.items():
            if k != 'url':
                walk(v, path + '.' + k, hits)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            walk(v, f'{path}[{i}]', hits)

def main():
    write = '--write' in sys.argv
    p = DATA / 'precedents.json'
    doc = json.loads(p.read_text(encoding='utf-8'))
    deals = doc['deals'] if isinstance(doc, dict) else doc
    hits = []
    for d in deals:
        walk(d.get('verification') or {}, d.get('id', '?') + '.verification', hits)
    for path, url, pg, o in hits:
        print(f'{path}: p.{pg}  {url[:90]}')
        if write:
            o['url_nopage'] = url
            o['url'] = url + f'#page={pg}'
    print(f'{len(hits)} link(s) {"anchored" if write else "would be anchored (dry run)"}')
    if write and hits:
        bak = p.with_name(p.name + '.bak-prepage-' + datetime.date.today().strftime('%Y%m%d'))
        shutil.copy2(p, bak)
        p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')  # house format: indent 2, no trailing newline
        print('backup:', bak.name)

if __name__ == '__main__':
    main()
