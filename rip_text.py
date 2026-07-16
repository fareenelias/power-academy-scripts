r"""
rip_text.py -- generic OCR-PDF text-layer ripper for the Power Academy pipeline.

Point it at a folder (or a file). For every OCR'd PDF it finds, it pulls the
existing text layer into a .txt with [[PAGE N]] markers and writes it to a
`text\` subfolder next to the PDFs. Content-agnostic: ER reports, credit
opinions, IPs, transcripts, decks -- anything with a text layer.

It READS the text layer (fast); it does NOT re-OCR unless you pass --ocr.
Pages with no text layer are flagged, never silently emitted empty. Each
`text\` folder gets a _rip_index.json manifest (pages / chars / flags) so the
output is self-describing when handed off for processing.

Usage
-----
  python rip_text.py <folder>                # rip every PDF in folder -> folder\text\
  python rip_text.py <folder> --recursive    # walk subfolders too (skips text\ dirs)
  python rip_text.py <folder> --force        # re-rip even if the .txt is up to date
  python rip_text.py <folder> --out <dir>    # send all .txt to ONE dir instead of per-folder text\
  python rip_text.py <file.pdf>              # single file
  python rip_text.py <folder> --ocr          # pytesseract fallback on empty pages (needs Tesseract)

Examples
--------
  python rip_text.py "E:\PowerAcademy\documents\reports\AEE"
  python rip_text.py "E:\PowerAcademy\documents\credit\AEE"
  python rip_text.py "E:\PowerAcademy\Documents\transcripts" --recursive

Requires: pip install pymupdf   (import name is fitz; VPN off to pip install)
Optional (only for --ocr): pip install pytesseract pillow  + Tesseract installed
"""
import sys
import os
import re
import json
import argparse
from datetime import datetime

import fitz  # PyMuPDF

MIN_VALID_BYTES = 100    # a .txt smaller than this is treated as empty and re-ripped
MIN_PAGE_CHARS = 20      # a page with fewer chars is treated as "no text layer"
OUT_DIRNAME = "text"

_multi_blank = re.compile(r"\n{3,}")


def _ocr_page(page):
    """Guarded pytesseract fallback. Returns text, or '' if OCR is unavailable."""
    try:
        import io
        from PIL import Image
        import pytesseract
    except Exception:
        return ""
    try:
        pix = page.get_pixmap(dpi=300)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return pytesseract.image_to_string(img).strip()
    except Exception:
        return ""


def iter_pdfs(paths, recursive):
    r"""Yield every .pdf under the given paths (skips any text\ output dirs)."""
    for p in paths:
        if os.path.isfile(p):
            if p.lower().endswith(".pdf"):
                yield p
            else:
                print(f"  skipped (not a PDF): {p}")
        elif os.path.isdir(p):
            if recursive:
                for dirpath, dirnames, filenames in os.walk(p):
                    dirnames[:] = [d for d in dirnames if d.lower() != OUT_DIRNAME]
                    for fn in sorted(filenames):
                        if fn.lower().endswith(".pdf"):
                            yield os.path.join(dirpath, fn)
            else:
                for fn in sorted(os.listdir(p)):
                    fp = os.path.join(p, fn)
                    if os.path.isfile(fp) and fn.lower().endswith(".pdf"):
                        yield fp
        else:
            print(f"  path not found: {p}")


def is_up_to_date(pdf_path, out_path):
    """True if a valid .txt already exists and is newer than the source PDF."""
    if not os.path.exists(out_path):
        return False
    if os.path.getsize(out_path) < MIN_VALID_BYTES:
        return False
    return os.path.getmtime(out_path) >= os.path.getmtime(pdf_path)


def rip_pdf(pdf_path, out_dir, use_ocr=False):
    """Rip one PDF -> .txt in out_dir. Returns a manifest entry dict."""
    doc = fitz.open(pdf_path)
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    out_path = os.path.join(out_dir, base + ".txt")

    parts, empty_pages, ocr_pages = [], [], []
    total_chars = 0
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text").strip()
        if len(text) < MIN_PAGE_CHARS:
            recovered = _ocr_page(page) if use_ocr else ""
            if len(recovered) >= MIN_PAGE_CHARS:
                text = recovered
                ocr_pages.append(i)
            else:
                empty_pages.append(i)
                text = "[[NO TEXT LAYER - PAGE NEEDS OCR]]"
        text = _multi_blank.sub("\n\n", text)
        total_chars += len(text)
        parts.append(f"[[PAGE {i}]]\n{text}")

    pages = len(doc)
    doc.close()

    if empty_pages and len(empty_pages) == pages:
        flag = "no_text_layer"
    elif empty_pages:
        flag = "has_empty_pages"
    elif ocr_pages:
        flag = "ocr_recovered"
    else:
        flag = "ok"

    header = (f"[[FILE: {os.path.basename(pdf_path)} | {pages} pages | "
              f"flag={flag} | ripped {datetime.now().isoformat(timespec='seconds')}]]")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(header + "\n\n" + "\n\n".join(parts) + "\n")

    return {
        "source_pdf": os.path.basename(pdf_path),
        "source_path": os.path.abspath(pdf_path),
        "out_txt": os.path.basename(out_path),
        "pages": pages,
        "chars": total_chars,
        "avg_chars_per_page": round(total_chars / pages) if pages else 0,
        "empty_pages": empty_pages,
        "ocr_pages": ocr_pages,
        "flag": flag,
        "ripped_at": datetime.now().isoformat(timespec="seconds"),
    }


def write_index(out_dir, new_entries, force=False):
    """Merge new entries into (or create) _rip_index.json in out_dir."""
    index_path = os.path.join(out_dir, "_rip_index.json")
    existing = {}
    if os.path.exists(index_path) and not force:
        try:
            with open(index_path, encoding="utf-8") as f:
                for e in json.load(f).get("files", []):
                    existing[e["source_pdf"]] = e
        except Exception:
            pass
    for e in new_entries:
        existing[e["source_pdf"]] = e
    files = sorted(existing.values(), key=lambda e: e["source_pdf"])
    payload = {
        "_note": "Text-layer rip manifest for Power Academy handoff. One entry per source PDF.",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "out_dir": os.path.abspath(out_dir),
        "count": len(files),
        "flagged": [e["source_pdf"] for e in files if e["flag"] != "ok"],
        "files": files,
    }
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser(description="Rip the text layer out of OCR'd PDFs.")
    ap.add_argument("paths", nargs="+", help="folder(s) or PDF file(s)")
    ap.add_argument("-r", "--recursive", action="store_true",
                    help="walk subfolders too (skips text\\ output dirs)")
    ap.add_argument("-f", "--force", action="store_true",
                    help="re-rip even if the .txt is already up to date")
    ap.add_argument("--out", help="write all .txt to this ONE dir instead of a per-folder text\\")
    ap.add_argument("--ocr", action="store_true",
                    help="pytesseract fallback on empty pages (needs Tesseract installed)")
    args = ap.parse_args()

    by_outdir = {}
    ripped = skipped = 0
    flagged = []

    for pdf in iter_pdfs(args.paths, args.recursive):
        out_dir = args.out or os.path.join(os.path.dirname(pdf), OUT_DIRNAME)
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, os.path.splitext(os.path.basename(pdf))[0] + ".txt")

        if not args.force and is_up_to_date(pdf, out_path):
            skipped += 1
            continue

        try:
            entry = rip_pdf(pdf, out_dir, use_ocr=args.ocr)
        except Exception as e:
            print(f"  ERROR {os.path.basename(pdf)}: {e}")
            flagged.append((os.path.basename(pdf), f"error: {e}"))
            continue

        by_outdir.setdefault(out_dir, []).append(entry)
        ripped += 1
        note = f"  <- {entry['flag']} {entry['empty_pages'] or ''}" if entry["flag"] != "ok" else ""
        if entry["flag"] != "ok":
            flagged.append((entry["source_pdf"], entry["flag"]))
        print(f"  {entry['out_txt']}  ({entry['pages']}p, {entry['chars']:,} chars){note}")

    for out_dir, entries in by_outdir.items():
        write_index(out_dir, entries, force=args.force)

    print("\n=== rip complete ===")
    print(f"  ripped:  {ripped}")
    print(f"  skipped: {skipped} (already up to date; --force to redo)")
    if flagged:
        print(f"  flagged: {len(flagged)} (need attention)")
        for name, why in flagged:
            print(f"     - {name}: {why}")
    for out_dir in by_outdir:
        print(f"  index:   {os.path.join(out_dir, '_rip_index.json')}")


if __name__ == "__main__":
    main()