#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
rip.py -- ONE ripper for the Power Academy pipeline (replaces rip_text.py + rip_earnings.py).

Point it at a folder (or a PDF). For every PDF it opens page 1 and sniffs the cover:

  * CapIQ TRANSCRIPT  (cover says "... Call Transcript(s)" under S&P Global Market
    Intelligence)  -> transcript path: Participants / Presentation / Q&A sectioning,
    front matter, TICKER_PERIOD.txt naming, _earnings_index.json  (old rip_earnings behavior).

  * Anything else  (broker report, credit opinion, IP, deck, filing)  -> report path:
    text-layer rip with [[PAGE N]] markers  PLUS  table extraction (pdfplumber + camelot,
    belt-and-suspenders) emitted inline as [[TABLE p.N #k]] markdown grids, keeps the
    original filename.txt, _rip_index.json  (old rip_text behavior + tables).

Either way: [[PAGE N]] markers are preserved (page-cite deep-links keep working), nothing is
emitted silently empty, and it's incremental (only (re)rips missing/stale/stub .txt; --force redoes).

USAGE (PowerShell)
------------------
  python rip.py "E:\PowerAcademy\documents\reports\AEE"                 # one report folder
  python rip.py "E:\PowerAcademy\Documents\credit\AEE"                  # credit opinions
  python rip.py "E:\PowerAcademy\Documents\transcripts" --recursive     # whole transcript tree
  python rip.py <folder> --force            # re-rip everything
  python rip.py <folder> --out <dir>        # all .txt to ONE dir instead of per-folder text\
  python rip.py <folder> --no-tables        # skip table extraction (text only)
  python rip.py <folder> --no-camelot       # pdfplumber tables only (skip camelot)
  python rip.py <folder> --ocr              # OCR empty pages on the report path (needs Tesseract)

Requires: pip install pymupdf
Tables  : pip install pdfplumber            (primary, borderless tables)
          pip install "camelot-py[cv]"      (secondary, ruled grids -- ALSO needs the Ghostscript
                                             binary; if Ghostscript is absent camelot is skipped
                                             automatically and pdfplumber carries the load)
OCR     : pip install pytesseract pillow    + the Tesseract binary
"""
import sys, os, re, io, json, argparse
from datetime import datetime

try:
    import pymupdf as fitz
except ImportError:
    import fitz  # PyMuPDF (import name)

# --- Tesseract discovery -------------------------------------------------------------------
# On Windows the binary is often installed but NOT on PATH. Prepend its folder to PATH (so
# img2table's Tesseract subprocess finds it) AND point pytesseract at the .exe. No-op on any
# machine where tesseract is already on PATH. Edit this one line if your install path differs.
_TESSERACT_DIR = r"C:\Program Files\Tesseract-OCR"
if os.path.isdir(_TESSERACT_DIR):
    os.environ["PATH"] = _TESSERACT_DIR + os.pathsep + os.environ.get("PATH", "")
    try:
        import pytesseract as _pt
        _exe = os.path.join(_TESSERACT_DIR, "tesseract.exe")
        if os.path.isfile(_exe):
            _pt.pytesseract.tesseract_cmd = _exe
    except Exception:
        pass

# table engines are optional and checked once here so the CLI can report what's available
try:
    import pdfplumber as _pdfplumber
    _HAS_PDFPLUMBER = True
except Exception:
    _pdfplumber = None
    _HAS_PDFPLUMBER = False
try:
    import camelot as _camelot
    _HAS_CAMELOT = True
except Exception:
    _camelot = None
    _HAS_CAMELOT = False
try:
    from img2table.document import PDF as _I2T_PDF
    from img2table.ocr import TesseractOCR as _I2T_OCR
    _HAS_IMG2TABLE = True
except Exception:
    _I2T_PDF = _I2T_OCR = None
    _HAS_IMG2TABLE = False

MIN_VALID_BYTES = 500     # a .txt smaller than this is treated as empty/stub and re-ripped
MIN_PAGE_CHARS  = 20      # a page with fewer chars is "no text layer"
OUT_DIRNAME     = "text"
_multi_blank    = re.compile(r"\n{3,}")

# =========================================================================================
# COVER SNIFF  ->  "transcript" | "report"
# =========================================================================================
_RE_CALL_TRANSCRIPT = re.compile(r"call\s+transcript", re.I)          # "Earnings Call Transcript(s)"
_RE_SPGMI           = re.compile(r"s&p\s+global\s+market\s+intelligence|capital\s+iq", re.I)
_RE_TRANSCRIPT_WORD = re.compile(r"\btranscript", re.I)
# transcript BODY structure -- standalone section headers that only a spoken CapIQ transcript has
# (earnings AND specials: M&A calls, investor days, shareholder/annual meetings). Decks & reports never do.
_RE_PARTICIPANTS    = re.compile(r"(?mi)^\s*(call|corporate)\s+participants\s*$")
_RE_QA_HEADER       = re.compile(r"(?mi)^\s*question[-\s]and[-\s]answer\s*$")

def sniff_doc_type(doc):
    """Decide transcript vs report. Reads the first few pages so it sees both the cover title
    AND the 'Call Participants' header (which sits a page or two in on special-event transcripts)."""
    n = min(6, doc.page_count)
    txt = "\n".join(doc[i].get_text("text") for i in range(n))
    low = txt.lower()
    if _RE_CALL_TRANSCRIPT.search(low):                       # cover title "... Call Transcript(s)"
        return "transcript"
    if _RE_PARTICIPANTS.search(txt) or _RE_QA_HEADER.search(txt):
        return "transcript"                                   # spoken-transcript structure (catches specials)
    if _RE_SPGMI.search(low) and _RE_TRANSCRIPT_WORD.search(low):
        return "transcript"                                   # belt-and-suspenders
    return "report"

# =========================================================================================
# TRANSCRIPT PATH  (ported from rip_earnings.py)
# =========================================================================================
NAME_TICKER = {
    "nextera energy partners":"XIFR","xplr":"XIFR",
    "nextera":"NEE","dominion":"D","entergy":"ETR","cms energy":"CMS",
    "ameren":"AEE","portland general":"POR","edison":"EIX","pg&e":"PCG",
    "pgande":"PCG","pacific gas":"PCG","hawaiian electric":"HE","evergy":"EVRG",
    "eversource":"ES","vistra":"VST","talen":"TLN",
    "ppl":"PPL","american states water":"AWR","california water":"CWT",
    "york water":"YORW","global water":"GWRS","american water":"AWK",
    "essential utilities":"WTRG","h2o america":"HTO","sjw":"HTO","middlesex":"MSEX",
}
def ticker_from_name(fn):
    low = fn.lower().replace("_"," ").replace(","," ")
    for key in sorted(NAME_TICKER, key=len, reverse=True):
        if key in low: return NAME_TICKER[key]
    return "UNK"
def period_from_name(fn):
    m = re.search(r'Q([1-4])[ ,_-]*(20\d{2})', fn, re.I)
    if m: return f"Q{m.group(1)} {m.group(2)}"
    m = re.search(r'(?<!\d)(20\d{2})(?!\d)', fn)
    return f"FY {m.group(1)}" if m else "ND"
def date_from_name(fn):
    m = re.search(r'([A-Z][a-z]{2})[ ,_-]*(\d{1,2})[ ,_-]*(20\d{2})', fn)
    if not m: return "ND"
    mon = {"Jan":"01","Feb":"02","Mar":"03","Apr":"04","May":"05","Jun":"06",
           "Jul":"07","Aug":"08","Sep":"09","Oct":"10","Nov":"11","Dec":"12"}.get(m.group(1),"01")
    return f"{m.group(3)}-{mon}-{int(m.group(2)):02d}"

_DROP = [
    re.compile(r'^\s*spglobal\.com/marketintelligence\s*\d*\s*$', re.I),
    re.compile(r'^\s*COPYRIGHT\s+.*S&P Global', re.I),
    re.compile(r'^\s*Copyright\s+.*All Rights reserved', re.I),
    re.compile(r'.*EARNINGS CALL.*[A-Z]{3}\s+\d{1,2},\s+20\d{2}\s*$'),
    re.compile(r'^\s*\d{1,3}\s*$'),
]
def _clean(t):
    out=[l.rstrip() for l in t.split("\n") if not any(p.search(l) for p in _DROP)]
    return re.sub(r'\n{3,}', '\n\n', "\n".join(out)).strip()

def _split_sections(full):
    def pos(label):
        m=re.search(rf'(?mi)^\s*{re.escape(label)}\s*$', full); return m.start() if m else None
    marks=sorted([x for x in [("participants",pos("Call Participants")),
                              ("presentation",pos("Presentation")),
                              ("qa",pos("Question and Answer"))] if x[1] is not None], key=lambda t:t[1])
    secs={}
    for i,(nm,p) in enumerate(marks):
        end=marks[i+1][1] if i+1<len(marks) else len(full)
        secs[nm]=full[p:end].strip()
    return secs

def _ocr_doc(doc):
    try:
        import pytesseract; from PIL import Image
    except Exception:
        return None
    out=[]
    for pg in doc:
        pix=pg.get_pixmap(dpi=300)
        out.append(f"\n[[PAGE {pg.number+1}]]\n"+pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes("png")))))
    return "\n".join(out)

def _build_transcript_txt(meta, raw, image_only=False):
    md=["---",f"ticker: {meta['ticker']}",f"period: {meta['period']}",
        f"call_date: {meta['call_date']}",f"call_type: {meta['call_type']}",
        f"source_folder: {meta['source_folder']}",f"source_file: {meta['source_file']}",
        f"pages: {meta['pages']}",f"flag: {meta['flag']}","---",""]
    if image_only:
        md += ["[[IMAGE-ONLY - NO TEXT LAYER - RUN OCR]]",
               "This PDF has no extractable text and Tesseract OCR was not available.",""]
        return "\n".join(md)
    secs=_split_sections(raw); added=False
    for k,lab in [("participants","## Call Participants"),("presentation","## Presentation"),("qa","## Question and Answer")]:
        if k in secs: md += [lab,"",secs[k],""]; added=True
    if not added:
        md += ["## Transcript","",raw,""]
    return "\n".join(md)

def rip_transcript(path, folder, out_dir, used):
    d=fitz.open(path)
    raw="\n".join(f"\n[[PAGE {i+1}]]\n"+pg.get_text("text") for i,pg in enumerate(d))
    pages=d.page_count; flag="OK"
    if len(raw.strip()) < 100*max(pages,1):
        ocr=_ocr_doc(d)
        if ocr and len(ocr.strip())>100*max(pages,1): raw=ocr; flag="OCR"
        else: flag="IMAGE_ONLY_NO_OCR"
    d.close()
    fn=os.path.basename(path)
    cleaned=_clean(raw)
    if flag in ("OK","OCR"):
        _secs=_split_sections(cleaned)
        if "presentation" not in _secs and "qa" not in _secs:
            flag="TRANSCRIPT_COVER_BUT_NO_QA_LIKELY_DECK"
    meta={"ticker":ticker_from_name(fn),"period":period_from_name(fn),
          "call_date":date_from_name(fn),
          "call_type":("special" if "special" in folder.lower() else "earnings"),
          "source_folder":folder,"source_file":fn,
          "source_url_path":f"transcripts/{folder}/{fn}",
          "pages":pages,"chars":len(cleaned),"flag":flag,"doc_type":"transcript"}
    # out name: TICKER_PERIOD.txt (specials get the date), de-duped across folders
    base=f"{meta['ticker']}_{meta['period'].replace(' ','-')}"
    if meta['call_type']=='special': base += "_SPECIAL_"+meta['call_date']
    name=base+".txt"; key=name
    while key in used and used[key]!=path:
        name=name[:-4]+"_2.txt"; key=name
    used[key]=path
    out_path=os.path.join(out_dir,name)
    txt=_build_transcript_txt(meta, cleaned, image_only=(flag=="IMAGE_ONLY_NO_OCR"))
    with open(out_path,"w",encoding="utf-8") as fh: fh.write(txt)
    meta["out_file"]=name
    return meta, out_path

# =========================================================================================
# REPORT PATH  (ported from rip_text.py) + TABLES
# =========================================================================================
def _ocr_page(page):
    try:
        from PIL import Image; import pytesseract
    except Exception:
        return ""
    try:
        pix=page.get_pixmap(dpi=300)
        return pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes("png")))).strip()
    except Exception:
        return ""

def _rows_to_md(rows):
    """list-of-rows -> pipe-delimited markdown table (drops empty rows, escapes pipes)."""
    def _cell(c):
        if c is None: return ""
        if isinstance(c, float) and c != c: return ""   # NaN
        return str(c)
    rows=[[_cell(c).replace("\n"," ").replace("|","\\|").strip() for c in r] for r in rows]
    rows=[r for r in rows if any(c for c in r)]
    if not rows: return ""
    ncol=max(len(r) for r in rows)
    rows=[r+[""]*(ncol-len(r)) for r in rows]
    out=["| "+" | ".join(rows[0])+" |", "| "+" | ".join(["---"]*ncol)+" |"]
    for r in rows[1:]: out.append("| "+" | ".join(r)+" |")
    return "\n".join(out)

def _tables_img2table(pdf_path):
    """{page_1based: [md, ...]} or None if img2table unavailable.
    IMAGE-based: detects the grid from the rasterized page and OCRs cells in place, so it
    works on SCANNED PDFs where camelot/pdfplumber (which need a vector text layer) find nothing."""
    if not _HAS_IMG2TABLE:
        return None
    out = {}
    try:
        ocr = _I2T_OCR(n_threads=1, lang="eng")
        res = _I2T_PDF(pdf_path).extract_tables(
            ocr=ocr, borderless_tables=True, implicit_rows=True, min_confidence=50)
        for pg0, tables in res.items():
            mds = []
            for t in tables:
                md = _rows_to_md(t.df.values.tolist())
                if md and len(md.splitlines()) > 2:
                    mds.append(md)
            if mds:
                out[pg0 + 1] = mds   # img2table pages are 0-based -> 1-based
    except Exception:
        return out
    return out

_TEXT_TS = {"vertical_strategy": "text", "horizontal_strategy": "text",
            "snap_tolerance": 4, "join_tolerance": 4}

def _tables_pdfplumber(pdf_path):
    """{page_1based: [md, ...]} or None if pdfplumber unavailable.
    Runs BOTH strategies: 'lines' (vector-ruled tables in native PDFs) and 'text'
    (word-position alignment -- the only thing that works on borderless / OCR'd-scan tables)."""
    if not _HAS_PDFPLUMBER:
        return None
    out = {}
    try:
        with _pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                grids = []
                try: grids += (page.extract_tables() or [])                       # ruled lines
                except Exception: pass
                try: grids += (page.extract_tables(table_settings=_TEXT_TS) or []) # text alignment
                except Exception: pass
                mds, seen = [], set()
                for g in grids:
                    md = _rows_to_md(g)
                    if md and md not in seen and len(md.splitlines()) > 2:         # drop 1-row noise
                        seen.add(md); mds.append(md)
                if mds: out[i] = mds
    except Exception:
        pass
    return out

def _tables_camelot(pdf_path):
    """{page_1based: [md, ...]} or None if camelot unavailable.
    lattice = ruled grids (needs vector lines + Ghostscript); stream = whitespace/text
    alignment (works without ruled lines). Both tried; per-page dedup across flavors."""
    if not _HAS_CAMELOT:
        return None
    raw = {}
    for flavor in ("lattice", "stream"):
        try:
            tl = _camelot.read_pdf(pdf_path, pages="all", flavor=flavor)
        except Exception:
            continue   # lattice needs Ghostscript; if missing, stream may still run
        for t in tl:
            try: pg = int(t.parsing_report.get("page", 0))
            except Exception: pg = 0
            md = _rows_to_md(t.df.values.tolist())
            if pg and md and len(md.splitlines()) > 2:
                raw.setdefault(pg, []).append(md)
    out = {}
    for pg, mds in raw.items():
        seen, keep = set(), []
        for md in mds:
            if md not in seen: seen.add(md); keep.append(md)
        out[pg] = keep
    return out

def rip_report(pdf_path, out_dir, use_ocr, do_tables, do_camelot, do_img2table):
    doc=fitz.open(pdf_path)
    base=os.path.splitext(os.path.basename(pdf_path))[0]
    out_path=os.path.join(out_dir, base+".txt")
    pages=doc.page_count

    # tables (whole-PDF passes, done once). img2table is IMAGE-based -> the primary engine for
    # your scanned PDFs; camelot/pdfplumber are text/vector-based and only catch native PDFs.
    im = _tables_img2table(pdf_path) if (do_tables and do_img2table) else None
    cm = _tables_camelot(pdf_path)   if (do_tables and do_camelot)   else None
    pp = _tables_pdfplumber(pdf_path) if do_tables                   else None
    tbl_engines=set()
    n_tables=0

    parts, empty_pages, ocr_pages = [], [], []
    total=0
    for i,page in enumerate(doc, start=1):
        text=page.get_text("text").strip()
        if len(text)<MIN_PAGE_CHARS:
            rec=_ocr_page(page) if use_ocr else ""
            if len(rec)>=MIN_PAGE_CHARS: text=rec; ocr_pages.append(i)
            else: empty_pages.append(i); text="[[NO TEXT LAYER - PAGE NEEDS OCR]]"
        text=_multi_blank.sub("\n\n", text)
        total+=len(text)
        block=f"[[PAGE {i}]]\n{text}"
        # belt-and-suspenders, image first: img2table (scans) -> camelot (ruled) -> pdfplumber (borderless)
        page_tbls=[]
        if im and i in im:
            for k,md in enumerate(im[i],1): page_tbls.append(f"[[TABLE p.{i} #{k} img2table]]\n{md}"); tbl_engines.add("img2table")
        elif cm and i in cm:
            for k,md in enumerate(cm[i],1): page_tbls.append(f"[[TABLE p.{i} #{k} camelot]]\n{md}"); tbl_engines.add("camelot")
        elif pp and i in pp:
            for k,md in enumerate(pp[i],1): page_tbls.append(f"[[TABLE p.{i} #{k} pdfplumber]]\n{md}"); tbl_engines.add("pdfplumber")
        if page_tbls:
            n_tables+=len(page_tbls)
            block += "\n\n" + "\n\n".join(page_tbls)
        parts.append(block)
    doc.close()

    if empty_pages and len(empty_pages)==pages: flag="no_text_layer"
    elif empty_pages: flag="has_empty_pages"
    elif ocr_pages:   flag="ocr_recovered"
    else:             flag="ok"
    tbl_note = ("+"+"/".join(sorted(tbl_engines))) if tbl_engines else ("no-tables" if not do_tables else "")

    header=(f"[[FILE: {os.path.basename(pdf_path)} | {pages} pages | flag={flag} | "
            f"tables={n_tables}{(' '+tbl_note) if tbl_note else ''} | "
            f"ripped {datetime.now().isoformat(timespec='seconds')}]]")
    with open(out_path,"w",encoding="utf-8") as f:
        f.write(header+"\n\n"+"\n\n".join(parts)+"\n")

    return {
        "source_pdf":os.path.basename(pdf_path),"source_path":os.path.abspath(pdf_path),
        "out_txt":os.path.basename(out_path),"pages":pages,"chars":total,
        "avg_chars_per_page":round(total/pages) if pages else 0,
        "empty_pages":empty_pages,"ocr_pages":ocr_pages,"tables":n_tables,
        "table_engines":sorted(tbl_engines),"flag":flag,"doc_type":"report",
        "ripped_at":datetime.now().isoformat(timespec="seconds"),
    }

# =========================================================================================
# SHARED: iter, up-to-date, manifests, main
# =========================================================================================
def iter_pdfs(paths, recursive):
    for p in paths:
        if os.path.isfile(p):
            if p.lower().endswith(".pdf"): yield p
            else: print(f"  skipped (not a PDF): {p}")
        elif os.path.isdir(p):
            if recursive:
                for dp,dn,fns in os.walk(p):
                    dn[:] = [d for d in dn if d.lower()!=OUT_DIRNAME]
                    for fn in sorted(fns):
                        if fn.lower().endswith(".pdf"): yield os.path.join(dp,fn)
            else:
                for fn in sorted(os.listdir(p)):
                    fp=os.path.join(p,fn)
                    if os.path.isfile(fp) and fn.lower().endswith(".pdf"): yield fp
        else:
            print(f"  path not found: {p}")

def is_up_to_date(pdf_path, out_path):
    if not os.path.exists(out_path): return False
    if os.path.getsize(out_path) < MIN_VALID_BYTES: return False
    return os.path.getmtime(out_path) >= os.path.getmtime(pdf_path)

def write_rip_index(out_dir, entries, force):
    ip=os.path.join(out_dir,"_rip_index.json"); existing={}
    if os.path.exists(ip) and not force:
        try:
            for e in json.load(open(ip,encoding="utf-8")).get("files",[]): existing[e["source_pdf"]]=e
        except Exception: pass
    for e in entries: existing[e["source_pdf"]]=e
    files=sorted(existing.values(), key=lambda e:e["source_pdf"])
    json.dump({"_note":"Text-layer rip manifest (reports) for Power Academy handoff. One entry per source PDF.",
               "generated_at":datetime.now().isoformat(timespec="seconds"),
               "out_dir":os.path.abspath(out_dir),"count":len(files),
               "flagged":[e["source_pdf"] for e in files if e["flag"]!="ok"],
               "files":files}, open(ip,"w",encoding="utf-8"), indent=2, ensure_ascii=False)

def write_earnings_index(out_dir, entries, force):
    ip=os.path.join(out_dir,"_earnings_index.json"); existing={}
    if os.path.exists(ip) and not force:
        try:
            for e in json.load(open(ip,encoding="utf-8")): existing[e.get("source_file",e.get("out_file"))]=e
        except Exception: pass
    for e in entries: existing[e["source_file"]]=e
    rows=sorted(existing.values(), key=lambda e:(e.get("ticker",""),e.get("period","")))
    json.dump(rows, open(ip,"w",encoding="utf-8"), ensure_ascii=False, indent=2)

def main():
    ap=argparse.ArgumentParser(description="One ripper: CapIQ transcripts -> Q&A sections; everything else -> text + tables.")
    ap.add_argument("paths", nargs="+", help="folder(s) or PDF file(s)")
    ap.add_argument("-r","--recursive", action="store_true", help="walk subfolders (skips text\\ dirs)")
    ap.add_argument("-f","--force", action="store_true", help="re-rip even if the .txt is up to date")
    ap.add_argument("--out", help="write all .txt to this ONE dir instead of per-folder text\\")
    ap.add_argument("--no-tables", action="store_true", help="report path: skip table extraction")
    ap.add_argument("--no-camelot", action="store_true", help="report path: skip camelot")
    ap.add_argument("--no-img2table", action="store_true", help="report path: skip img2table (image/OCR table engine)")
    ap.add_argument("--ocr", action="store_true", help="report path: OCR empty pages (needs Tesseract)")
    a=ap.parse_args()

    if not a.no_tables:
        im_s = ("on (primary; works on scans)" if _HAS_IMG2TABLE else "MISSING -> pip install img2table") \
               if not a.no_img2table else "off (--no-img2table)"
        cm_s = ("on" if _HAS_CAMELOT else "MISSING") if not a.no_camelot else "off"
        pp_s = "on" if _HAS_PDFPLUMBER else "MISSING"
        print(f"  table engines: img2table={im_s} | camelot={cm_s} | pdfplumber={pp_s}")
        if (a.no_img2table or not _HAS_IMG2TABLE) and not _HAS_PDFPLUMBER and (a.no_camelot or not _HAS_CAMELOT):
            print("  NOTE: no table engine available -> reports show 0 tables (text still rips fine).")

    rip_entries={}     # out_dir -> [report entries]
    ecall_entries={}   # out_dir -> [transcript entries]
    used={}            # transcript out-name de-dup
    n_tx=n_rep=skipped=0; flagged=[]

    for pdf in iter_pdfs(a.paths, a.recursive):
        out_dir = a.out or os.path.join(os.path.dirname(pdf), OUT_DIRNAME)
        os.makedirs(out_dir, exist_ok=True)
        folder = os.path.basename(os.path.dirname(pdf))
        try:
            doc=fitz.open(pdf); dtype=sniff_doc_type(doc); doc.close()
        except Exception as e:
            print(f"  ERROR opening {os.path.basename(pdf)}: {e}"); flagged.append((os.path.basename(pdf),f"open error: {e}")); continue

        # figure the intended out path for the incremental check
        if dtype=="transcript":
            fn=os.path.basename(pdf)
            b=f"{ticker_from_name(fn)}_{period_from_name(fn).replace(' ','-')}"
            if "special" in folder.lower(): b+="_SPECIAL_"+date_from_name(fn)
            probe=os.path.join(out_dir,b+".txt")
        else:
            probe=os.path.join(out_dir, os.path.splitext(os.path.basename(pdf))[0]+".txt")

        if not a.force and is_up_to_date(pdf, probe):
            skipped+=1; continue

        try:
            if dtype=="transcript":
                meta,_=rip_transcript(pdf, folder, out_dir, used)
                ecall_entries.setdefault(out_dir,[]).append(meta); n_tx+=1
                tag={"OK":"","OCR":" [OCR]","IMAGE_ONLY_NO_OCR":"  !! IMAGE-ONLY, needs OCR",
                     "TRANSCRIPT_COVER_BUT_NO_QA_LIKELY_DECK":"  ?? cover says transcript but no Q&A - likely a DECK"}.get(meta["flag"],"")
                if meta["flag"] not in ("OK","OCR"): flagged.append((meta["source_file"],meta["flag"]))
                print(f"  [transcript] {meta['ticker']:5} {meta['period']:8} -> {meta['out_file']}  ({meta['chars']:,} chars){tag}")
            else:
                e=rip_report(pdf, out_dir, a.ocr, not a.no_tables, not a.no_camelot, not a.no_img2table)
                rip_entries.setdefault(out_dir,[]).append(e); n_rep+=1
                note=f"  <- {e['flag']} {e['empty_pages'] or ''}" if e["flag"]!="ok" else ""
                if e["flag"]!="ok": flagged.append((e["source_pdf"],e["flag"]))
                print(f"  [report]     {e['out_txt']}  ({e['pages']}p, {e['chars']:,} chars, {e['tables']} tables){note}")
        except Exception as e:
            print(f"  ERROR {os.path.basename(pdf)}: {e}"); flagged.append((os.path.basename(pdf),f"error: {e}"))

    for od,ents in rip_entries.items():   write_rip_index(od, ents, a.force)
    for od,ents in ecall_entries.items(): write_earnings_index(od, ents, a.force)

    print("\n=== rip complete ===")
    print(f"  transcripts: {n_tx}   reports: {n_rep}   skipped(up-to-date): {skipped}")
    if flagged:
        print(f"  flagged: {len(flagged)}")
        for name,why in flagged: print(f"     - {name}: {why}")
    for od in set(list(rip_entries)+list(ecall_entries)):
        print(f"  out: {od}")

if __name__=="__main__":
    main()