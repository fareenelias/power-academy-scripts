# backfill_full_text.py
# Populates full_text_pages{} on each report in broker_research.json for one ticker,
# so the Analyst View full-text search can hit report body text (matches ETR's structure).
# Runs LOCALLY against the PDFs on disk. Text layer first; OCR fallback for scanned pages.
#
# Deps:  pip install pymupdf pytesseract pillow    (Tesseract binary already installed on your machine)
# Reuse for another ticker: change TICKER, drop that ticker's PDFs in its reports folder, rerun.

import os, io, json, sys
try:
    import pymupdf as fitz     # PyMuPDF >= 1.24 (preferred import name)
except ImportError:
    import fitz                # older PyMuPDF exposes the module as 'fitz'

TICKER      = "GWRS"
DATA_FILE   = r"E:\PowerAcademy\data\broker_research.json"
REPORTS_DIR = r"E:\PowerAcademy\documents\reports"   # flat folder — all tickers' PDFs live here; matched by source_file
OCR_DPI     = 300        # plenty for searchable text; exact-number extraction is a separate 600 DPI pass
MIN_CHARS   = 20         # a page with fewer real chars than this is treated as scanned -> OCR it
SKIP_PAGES  = {}         # optional: drop boilerplate, e.g. {"GWRS-FreedomBroker_20260305.pdf": [5,6,7,8,9]}


def ocr_page(page):
    try:
        import pytesseract
        from PIL import Image
        pix = page.get_pixmap(dpi=OCR_DPI)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return pytesseract.image_to_string(img)
    except Exception as e:
        print(f"    ! OCR failed: {e}")
        return ""


def extract(pdf_path, skip):
    doc = fitz.open(pdf_path)
    pages = {}
    for i, page in enumerate(doc, start=1):
        if i in skip:
            print(f"    p.{i}: skipped")
            continue
        txt = page.get_text("text").strip()
        mode = "text"
        if len(txt) < MIN_CHARS:              # image-only / scanned page -> OCR
            txt = ocr_page(page).strip()
            mode = "ocr"
        if txt:
            pages[str(i)] = txt
        print(f"    p.{i}: {len(txt):>5} chars ({mode})")
    doc.close()
    return pages


def main():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    node = data.get(TICKER)
    if not node:
        sys.exit(f"No '{TICKER}' block in {DATA_FILE}")

    updated = 0
    for r in node.get("reports", []):
        sf = r.get("source_file")
        if not sf:
            continue
        path = os.path.join(REPORTS_DIR, sf)
        if not os.path.exists(path):
            print(f"[skip] file not found: {path}")
            continue
        print(f"[extract] {sf}")
        r["full_text_pages"] = extract(path, set(SKIP_PAGES.get(sf, [])))
        updated += 1

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\nDone. Wrote full_text_pages on {updated} report(s) for {TICKER}.")
    print("Restart Node so the app serves the new JSON, then search in Analyst View.")


if __name__ == "__main__":
    main()