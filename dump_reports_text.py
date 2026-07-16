# dump_reports_text.py
# Bulk-extracts text from every <PREFIX>*.pdf in the flat reports folder into ONE markdown
# file you can upload to Claude — no image-limit problem, since it's text, not page images.
# Text layer first; OCR fallback (300 DPI) for scanned pages.
#
# Deps:  pip install pymupdf pytesseract pillow   (Tesseract binary already installed)
# Reuse for any ticker: change PREFIX.

import os, io, glob, sys
try:
    import pymupdf as fitz     # PyMuPDF >= 1.24
except ImportError:
    import fitz                # older PyMuPDF

PREFIX      = "EIX"
REPORTS_DIR = r"E:\PowerAcademy\documents\reports"          # flat folder, all tickers together
OUTPUT      = rf"E:\PowerAcademy\documents\reports\_{PREFIX}_text_dump.md"
OCR_DPI     = 300
MIN_CHARS   = 20            # a page with fewer real chars than this -> treat as scanned, OCR it


def ocr_page(page):
    try:
        import pytesseract
        from PIL import Image
        pix = page.get_pixmap(dpi=OCR_DPI)
        return pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes("png"))))
    except Exception as e:
        print(f"    ! OCR failed: {e}")
        return ""


def main():
    pattern = os.path.join(REPORTS_DIR, PREFIX + "*.pdf")
    files = sorted(glob.glob(pattern))
    if not files:
        sys.exit(f"No files match {pattern}")
    print(f"Found {len(files)} file(s) matching {PREFIX}*.pdf")

    out = [f"# {PREFIX} broker report text dump\n\n{len(files)} files\n"]
    for path in files:
        name = os.path.basename(path)
        doc = fitz.open(path)
        n = doc.page_count
        print(f"[{name}] {n} pages")
        out.append("\n" + "=" * 80)
        out.append(f"FILE: {name}   ({n} pages)")
        out.append("=" * 80 + "\n")
        for i, page in enumerate(doc, start=1):
            txt = page.get_text("text").strip()
            mode = "text"
            if len(txt) < MIN_CHARS:
                txt = ocr_page(page).strip()
                mode = "ocr"
            print(f"    p.{i}: {len(txt):>5} chars ({mode})")
            out.append(f"\n----- page {i} -----")
            out.append(txt if txt else "(no text extracted)")
        doc.close()

    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"\nWrote {OUTPUT}")
    print("Upload that one .md file to Claude for the structured extraction.")


if __name__ == "__main__":
    main()