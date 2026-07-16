#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rip_earnings.py  -  rip earnings-call PDFs anywhere under a transcripts root to .txt.

Design goals (folder- & filename-agnostic, drop-in-and-forget):
  * Recursively walks the WHOLE transcripts tree; the only thing skipped is the
    output \text folder. Any new subfolder (e.g. "Q2 2026 Earnings") is picked up
    automatically. Any *.pdf found is processed.
  * NEVER leaves a file unpopulated. Text-layer PDFs extract directly (with
    [[PAGE N]] markers). Image-only PDFs get OCR'd if Tesseract is installed;
    if it isn't, a .txt is STILL written with front matter + an explicit
    "[[IMAGE-ONLY - NO TEXT LAYER - RUN OCR]]" flag so nothing goes missing silently.
  * Incremental by default: a PDF is (re)processed only if its .txt is missing,
    empty/stub, or older than the PDF. Use --force to reprocess everything.

USAGE (PowerShell):
    python rip_earnings.py "E:\\PowerAcademy\\Documents\\transcripts"
    python rip_earnings.py "E:\\PowerAcademy\\Documents\\transcripts" --force
    # optional custom out dir (default: <root>\text):
    python rip_earnings.py "E:\\PowerAcademy\\Documents\\transcripts" "E:\\out" 

Requires: pip install pymupdf   (OCR fallback also needs: pip install pytesseract pillow + Tesseract binary)
"""
import sys, os, re, json

try:
    import pymupdf
except ImportError:
    import fitz as pymupdf

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

DROP = [
    re.compile(r'^\s*spglobal\.com/marketintelligence\s*\d*\s*$', re.I),
    re.compile(r'^\s*COPYRIGHT\s+.*S&P Global', re.I),
    re.compile(r'^\s*Copyright\s+.*All Rights reserved', re.I),
    re.compile(r'.*EARNINGS CALL.*[A-Z]{3}\s+\d{1,2},\s+20\d{2}\s*$'),
    re.compile(r'^\s*\d{1,3}\s*$'),
]
def clean(t):
    out=[l.rstrip() for l in t.split("\n") if not any(p.search(l) for p in DROP)]
    return re.sub(r'\n{3,}', '\n\n', "\n".join(out)).strip()

def split_sections(full):
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

def ocr_doc(doc):
    try:
        import pytesseract; from PIL import Image; import io
    except Exception:
        return None
    out=[]
    for pg in doc:
        pix=pg.get_pixmap(dpi=300)
        out.append(f"\n[[PAGE {pg.number+1}]]\n"+pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes("png")))))
    return "\n".join(out)

def build_txt(meta, body_sections_or_raw, image_only=False):
    md=["---",f"ticker: {meta['ticker']}",f"period: {meta['period']}",
        f"call_date: {meta['call_date']}",f"call_type: {meta['call_type']}",
        f"source_folder: {meta['source_folder']}",f"source_file: {meta['source_file']}",
        f"pages: {meta['pages']}",f"flag: {meta['flag']}","---",""]
    if image_only:
        md += ["[[IMAGE-ONLY - NO TEXT LAYER - RUN OCR]]",
               "This PDF has no extractable text and Tesseract OCR was not available.",
               "Install pytesseract + the Tesseract binary and re-run to populate this file.",""]
        return "\n".join(md)
    secs=split_sections(body_sections_or_raw); added=False
    for k,lab in [("participants","## Call Participants"),("presentation","## Presentation"),("qa","## Question and Answer")]:
        if k in secs: md += [lab,"",secs[k],""]; added=True
    if not added:
        md += ["## Transcript","",body_sections_or_raw,""]
    return "\n".join(md)

def rip_one(path, folder):
    d=pymupdf.open(path)
    raw="\n".join(f"\n[[PAGE {i+1}]]\n"+pg.get_text("text") for i,pg in enumerate(d))
    pages=d.page_count
    flag="OK"
    if len(raw.strip()) < 100*max(pages,1):
        ocr=ocr_doc(d)
        if ocr and len(ocr.strip())>100*max(pages,1):
            raw=ocr; flag="OCR"
        else:
            flag="IMAGE_ONLY_NO_OCR"
    d.close()
    fn=os.path.basename(path)
    # structure check: a real transcript has a Presentation and/or Q&A section.
    # If neither is present (and there is text), it's almost certainly a slide DECK, not a transcript.
    if flag in ("OK","OCR"):
        _secs=split_sections(clean(raw))
        if "presentation" not in _secs and "qa" not in _secs:
            flag="NO_QA_STRUCTURE_LIKELY_DECK"
    meta={"ticker":ticker_from_name(fn),"period":period_from_name(fn),
          "call_date":date_from_name(fn),"call_type":("special" if "special" in folder.lower() else "earnings"),
          "source_folder":folder,"source_file":fn,"source_url_path":f"transcripts/{folder}/{fn}",
          "pages":pages,"chars":len(raw.strip()),"flag":flag}
    txt=build_txt(meta, clean(raw), image_only=(flag=="IMAGE_ONLY_NO_OCR"))
    return meta, txt

def out_name_for(meta):
    base=f"{meta['ticker']}_{meta['period'].replace(' ','-')}"
    if meta['call_type']=='special': base += "_SPECIAL_"+meta['call_date']
    return base+".txt"

def needs_processing(pdf_path, out_path, force):
    if force: return True
    if not os.path.exists(out_path): return True
    try:
        if os.path.getsize(out_path) < 500: return True          # empty / stub
        if os.path.getmtime(pdf_path) > os.path.getmtime(out_path): return True  # PDF newer
    except OSError:
        return True
    return False

def main():
    args=[a for a in sys.argv[1:] if not a.startswith("--")]
    force="--force" in sys.argv
    root   = args[0] if len(args)>0 else "."
    outdir = args[1] if len(args)>1 else os.path.join(root,"text")
    os.makedirs(outdir, exist_ok=True)
    out_abs=os.path.abspath(outdir)

    index=[]; used={}; processed=0; skipped=0
    for dirpath, dirs, files in os.walk(root):
        if os.path.abspath(dirpath).startswith(out_abs):   # never rip our own output
            continue
        folder=os.path.basename(dirpath)
        for f in sorted(files):
            if not f.lower().endswith(".pdf"): continue
            # peek at names to compute the intended out file (cheap; no PDF open)
            meta_stub={"ticker":ticker_from_name(f),"period":period_from_name(f),
                       "call_date":date_from_name(f),
                       "call_type":("special" if "special" in folder.lower() else "earnings")}
            name=out_name_for(meta_stub)
            # de-dup identical output names across folders
            key=name
            while key in used and used[key]!=os.path.join(dirpath,f):
                name=name[:-4]+"_2.txt"; key=name
            used[key]=os.path.join(dirpath,f)
            out_path=os.path.join(outdir,name)
            pdf_path=os.path.join(dirpath,f)
            if not needs_processing(pdf_path,out_path,force):
                skipped+=1
                # still record in index from existing (light)
                index.append({"ticker":meta_stub["ticker"],"period":meta_stub["period"],
                              "call_date":meta_stub["call_date"],"call_type":meta_stub["call_type"],
                              "source_folder":folder,"source_file":f,"out_file":name,"flag":"CACHED"})
                continue
            meta, txt = rip_one(pdf_path, folder)
            with open(out_path,"w",encoding="utf-8") as fh: fh.write(txt)
            rec={k:v for k,v in meta.items()}; rec["out_file"]=name
            index.append(rec); processed+=1
            tag={"OK":"","OCR":" [OCR]","IMAGE_ONLY_NO_OCR":"  !! IMAGE-ONLY, needs OCR","NO_QA_STRUCTURE_LIKELY_DECK":"  ?? no Presentation/Q&A - likely a DECK, not a transcript"}.get(meta['flag'],"")
            print(f"  {meta['ticker']:5} {meta['period']:8} -> {name}  ({meta['chars']:,} chars){tag}")

    with open(os.path.join(outdir,"_earnings_index.json"),"w",encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=2)
    print(f"\nDone. processed={processed}, skipped(up-to-date)={skipped}, total={len(index)} -> {outdir}")
    bad=[r['source_file'] for r in index if r.get('flag')=='IMAGE_ONLY_NO_OCR']
    if bad: print("IMAGE-ONLY (install Tesseract + re-run):", ", ".join(bad))
    decks=[r['source_file'] for r in index if r.get('flag')=='NO_QA_STRUCTURE_LIKELY_DECK']
    if decks: print("LIKELY DECKS (no Q&A - grab the transcript instead?):", ", ".join(decks))

if __name__=="__main__":
    main()