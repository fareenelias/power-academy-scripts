# backfill_full_text.py
# Populates full_text_pages{} on each report in broker_research.json so the Equity Research
# full-text search can hit report body text. Runs LOCALLY against the PDFs on disk (the broker
# text never leaves the desktop). Text layer first; OCR fallback for scanned pages.
#
#   python scripts\backfill_full_text.py --all            every ticker, only reports still empty
#   python scripts\backfill_full_text.py AEP CMS          named tickers
#   python scripts\backfill_full_text.py --all --force    re-extract even where pages already exist
#   python scripts\backfill_full_text.py --all --dry      list what would be extracted, write nothing
#
# Page scope (keeps the JSON from ballooning):
#   * a PDF used by ONE report  -> every page (up to MAX_PAGES)
#   * a PDF shared by several reports (multi-name sector notes, the ETR re-scan bundle)
#     -> only that report's pages: the span min..max(source_pages + methodology_page) when it is
#        13 pages or fewer, otherwise each cited page and the page after it
#
# Deps:  pip install pymupdf pytesseract pillow    (Tesseract binary already installed)
# After it finishes:  python scripts\split_broker_json.py   then restart Node.

import os, io, json, sys

try:
    import pymupdf as fitz     # PyMuPDF >= 1.24
except ImportError:
    import fitz

DATA_FILE   = r"E:\PowerAcademy\data\broker_research.json"
REPORTS_DIR = r"E:\PowerAcademy\Documents\reports"   # flat folder - every ticker's broker PDFs, matched by source_file
OCR_DPI     = 300
MIN_CHARS   = 20          # fewer real chars than this -> treat as scanned, OCR it
MAX_PAGES   = 60          # single-report PDFs longer than this keep the first 60 pages
SKIP_PAGES  = {}          # optional: {"GWRS-FreedomBroker_20260305.pdf": [5, 6, 7, 8, 9]}


def ocr_page(page):
    try:
        import pytesseract
        from PIL import Image
        pix = page.get_pixmap(dpi=OCR_DPI)
        return pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes("png"))))
    except Exception as e:
        print(f"    ! OCR failed: {e}")
        return ""


def extract(doc, pages, skip):
    out, n_ocr = {}, 0
    for i in pages:
        if i in skip or i < 1 or i > doc.page_count:
            continue
        page = doc[i - 1]
        txt = page.get_text("text").strip()
        if len(txt) < MIN_CHARS:
            txt = ocr_page(page).strip(); n_ocr += 1
        if txt:
            out[str(i)] = txt
    return out, n_ocr


def ints(v):
    return [int(x) for x in (v or []) if isinstance(x, (int, float)) or (isinstance(x, str) and x.isdigit())]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force, dry, every = "--force" in sys.argv, "--dry" in sys.argv, "--all" in sys.argv
    if not args and not every:
        sys.exit("usage: backfill_full_text.py --all | TICKER [TICKER ...] [--force] [--dry]")

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    tickers = [t for t in data if not t.startswith("_")] if every else [a.upper() for a in args]

    uses = {}
    for t in data:
        if t.startswith("_"): continue
        for r in data[t].get("reports", []):
            if r.get("source_file"): uses[r["source_file"]] = uses.get(r["source_file"], 0) + 1

    todo = []
    for t in tickers:
        node = data.get(t)
        if not node:
            print(f"[skip] no '{t}' block"); continue
        for r in node.get("reports", []):
            if r.get("source_file") and (force or not r.get("full_text_pages")):
                todo.append((t, r))
    print(f"{len(todo)} report(s) to extract across {len({t for t, _ in todo})} ticker(s)")

    done, missing, cache = 0, [], {}
    for n, (t, r) in enumerate(todo, 1):
        sf = r["source_file"]
        path = os.path.join(REPORTS_DIR, sf)
        if not os.path.exists(path):
            missing.append(sf); print(f"[missing] {t} {sf}"); continue
        if uses.get(sf, 1) > 1:
            sp = ints(r.get("source_pages")) + ints([r.get("methodology_page")])
            if sp and max(sp) - min(sp) <= 12:
                pages = list(range(min(sp), max(sp) + 1))
            else:                               # far-apart pages in a sector note: the cited pages and the one after each
                pages = sorted({q for x in sp for q in (x, x + 1)})
            scope = (f"p.{','.join(map(str, pages))} (shared PDF, {uses[sf]} reports)" if sp
                     else "no source_pages - skipped (shared PDF)")
        else:
            pages, scope = None, "all pages"
        print(f"[{n}/{len(todo)}] {t} {r.get('broker', '')} {r.get('report_date', '')}  {sf}  {scope}")
        if dry or pages == []:
            continue
        doc = cache.get(sf) or fitz.open(path)
        cache.clear(); cache[sf] = doc          # keep one PDF open (bundles are reused back to back)
        if pages is None:
            pages = list(range(1, min(doc.page_count, MAX_PAGES) + 1))
        txt, n_ocr = extract(doc, pages, set(SKIP_PAGES.get(sf, [])))
        r["full_text_pages"] = txt
        done += 1
        print(f"    {len(txt)} pages, {n_ocr} OCR'd")
        if done % 20 == 0:                      # checkpoint - a crash never loses the whole run
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

    if not dry and done:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\nDone. full_text_pages written on {done} report(s); {len(missing)} PDF(s) not found in {REPORTS_DIR}.")
    if missing: print("  missing:", ", ".join(sorted(set(missing))[:20]))
    print("Next: python scripts\\split_broker_json.py, then restart Node.")


if __name__ == "__main__":
    main()
