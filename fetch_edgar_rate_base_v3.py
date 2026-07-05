"""
fetch_edgar_rate_base_v3.py
============================
Third attempt — correct architecture based on confirmed EDGAR behavior.

KEY FINDING from debugging:
  The investor presentation PDF (e.g. PPL_2025_Q4_Investor_Update_FINAL.pdf)
  is NOT uploaded to EDGAR. Companies file 8-Ks under Item 7.01 (Reg FD) that
  simply say "slides are available at www.pplweb.com/investors." The actual
  PDF lives on the IR website, not in the EDGAR archive.

  The 8-K EX-99.1 is the earnings press release (HTML), which:
    - DOES contain: "10.3% rate base CAGR", "~$29B" type references
    - DOES contain: balance sheet (net utility plant, GAAP)
    - Does NOT contain: the slide 31 rate base table by opco

TWO-TRACK APPROACH:
  Track 1 (EDGAR press release):
    - Fetch EX-99.1 htm from each quarterly earnings 8-K
    - Extract rate base dollar mentions + balance sheet net utility plant
    - Yields Tier 1b (mgmt press release) and Tier 3 (balance sheet)

  Track 2 (IR website PDF):
    - Fetch each company's IR events/presentations page
    - Find the most recent quarterly investor update PDF link
    - Download and extract text via pdfminer
    - Yields Tier 1a (investor deck slide 31-type tables) — best quality

EDGAR index structure (confirmed from live testing):
  - data.sec.gov/submissions/CIK{10digit}.json   <- WORKS (confirmed in log)
  - www.sec.gov/Archives/edgar/data/{cik}/{acc}/{acc-dashed}-index.htm  <- WORKS
  - www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json  <- WORKS
    (not data.sec.gov/Archives — that was v2's bug #1)
  - Column structure of index.htm: Seq | Description | Document | Type | Size
    (Type is col index 3, not 0 — that was v2's bug #2)

Unicode fix: all log messages use ASCII-safe symbols ([OK] not checkmark)
to avoid cp1252 encoding errors on Windows console.

Run from E:\\PowerAcademy\\scripts\\:
  pip install requests beautifulsoup4 pdfminer.six
  python fetch_edgar_rate_base_v3.py
"""

import json, os, re, sys, time, logging, tempfile
from pathlib import Path
from datetime import datetime

import requests
from bs4 import BeautifulSoup

try:
    from pdfminer.high_level import extract_text as pdf_extract_text
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    print("WARNING: pdfminer.six not installed. Run: pip install pdfminer.six")

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
DATA_DIR   = SCRIPT_DIR.parent / "data"
CAPIQ_PATH = DATA_DIR / "capiq_export.json"
AUDIT_PATH = DATA_DIR / "edgar_rate_base_raw_v3.json"
CACHE_DIR  = DATA_DIR / "edgar_cache_v3"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── Logging: ASCII only to avoid cp1252 crash on Windows console ──────────────
class AsciiSafeStreamHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            msg = self.format(record)
            # Replace common unicode symbols with ASCII equivalents
            msg = msg.replace('\u2713', '[OK]').replace('\u26a0', '[WARN]') \
                     .replace('\u2717', '[FAIL]').replace('\u2014', '-') \
                     .replace('\u2019', "'").replace('\u2026', '...')
            stream = self.stream
            stream.write(msg + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        AsciiSafeStreamHandler(),
        logging.FileHandler(DATA_DIR / "fetch_edgar_rate_base_v3.log",
                            encoding="utf-8")
    ]
)
log = logging.getLogger(__name__)

# ── Request config ────────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": "PowerAcademy/3.0 research-tool fareen.elias@gmail.com",
    "Accept": "text/html,application/json,*/*",
}
EDGAR_DELAY = 0.2   # seconds between requests

def sec_get(url: str, stream: bool = False) -> requests.Response:
    """GET with polite delay. Raises on HTTP error."""
    time.sleep(EDGAR_DELAY)
    r = requests.get(url, headers=HEADERS, timeout=45, stream=stream)
    if r.status_code == 429:
        log.warning("Rate limited, sleeping 15s")
        time.sleep(15)
        r = requests.get(url, headers=HEADERS, timeout=45, stream=stream)
    r.raise_for_status()
    return r

# ── Company universe: 12 regulated utilities ──────────────────────────────────
COMPANIES = [
    {
        "ticker": "NEE", "cik": "0000037634", "name": "NextEra Energy",
        "ir_presentations_url": "https://investor.nexteraenergy.com/investor-resources/events-and-presentations",
        "opco_labels": ["FPL", "Florida Power & Light", "NEER", "Gulf Power"],
        "keywords": ["FPL", "NEER", "Florida Power", "Gulf"],
    },
    {
        "ticker": "D", "cik": "0000715957", "name": "Dominion Energy",
        "ir_presentations_url": "https://investors.dominionenergy.com/events-and-presentations/presentations",
        "opco_labels": ["Virginia Power", "DEV", "DESC", "Dominion Energy Virginia",
                        "Dominion Energy South Carolina", "Hope Gas"],
        "keywords": ["Virginia", "South Carolina", "DESC", "DEV"],
    },
    {
        "ticker": "ETR", "cik": "0000049600", "name": "Entergy",
        "ir_presentations_url": "https://investor.entergy.com/news-and-events/events-and-presentations",
        "opco_labels": ["Entergy Arkansas", "Entergy Louisiana", "Entergy Mississippi",
                        "Entergy New Orleans", "Entergy Texas"],
        "keywords": ["Arkansas", "Louisiana", "Mississippi", "New Orleans", "Texas"],
    },
    {
        "ticker": "CMS", "cik": "0000811156", "name": "CMS Energy",
        "ir_presentations_url": "https://ir.cmsenergy.com/events-and-presentations/presentations",
        "opco_labels": ["Consumers Energy", "Consumers"],
        "keywords": ["Consumers", "Electric", "Gas"],
    },
    {
        "ticker": "AEE", "cik": "0001002910", "name": "Ameren",
        "ir_presentations_url": "https://ir.ameren.com/events-and-presentations/presentations",
        "opco_labels": ["Ameren Missouri", "Ameren Illinois", "AIC", "AmerenMO"],
        "keywords": ["Missouri", "Illinois", "Electric", "Gas"],
    },
    {
        "ticker": "EIX", "cik": "0000827054", "name": "Edison International",
        "ir_presentations_url": "https://www.edisonir.com/events-presentations/presentations",
        "opco_labels": ["SCE", "Southern California Edison"],
        "keywords": ["SCE", "Southern California", "Edison"],
    },
    {
        "ticker": "PCG", "cik": "0001004440", "name": "PG&E",
        "ir_presentations_url": "https://investor.pgecorp.com/investor-relations/events-and-presentations",
        "opco_labels": ["PG&E", "Pacific Gas", "Electric", "Gas"],
        "keywords": ["Electric", "Gas", "Transmission", "Distribution"],
    },
    {
        "ticker": "HE", "cik": "0000354963", "name": "Hawaiian Electric",
        "ir_presentations_url": "https://www.heco.com/about-heco/investor-relations/events-and-presentations",
        "opco_labels": ["HECO", "MECO", "HELCO", "Hawaiian Electric"],
        "keywords": ["HECO", "MECO", "HELCO", "Oahu", "Maui", "Hawaii Island"],
    },
    {
        "ticker": "EVRG", "cik": "0001711269", "name": "Evergy",
        "ir_presentations_url": "https://investors.evergy.com/presentations",
        "opco_labels": ["Evergy Kansas Central", "Evergy Metro", "Evergy Missouri West",
                        "KPL", "KCP&L", "GMO", "Westar"],
        "keywords": ["Kansas", "Missouri", "Metro", "West"],
    },
    {
        "ticker": "ES", "cik": "0000072741", "name": "Eversource Energy",
        "ir_presentations_url": "https://investor.eversource.com/events-and-presentations/presentations",
        "opco_labels": ["CL&P", "NSTAR", "PSNH", "WMECo", "Yankee Gas", "Aquarion"],
        "keywords": ["Connecticut", "Massachusetts", "New Hampshire", "CL&P", "NSTAR"],
    },
    {
        "ticker": "POR", "cik": "0000784977", "name": "Portland General Electric",
        "ir_presentations_url": "https://investors.portlandgeneral.com/events-and-presentations/presentations",
        "opco_labels": ["PGE", "Portland General"],
        "keywords": ["PGE", "Portland", "Oregon"],
    },
    {
        "ticker": "PPL", "cik": "0000922224", "name": "PPL Corporation",
        "ir_presentations_url": "https://www.pplweb.com/investors/events-and-presentations/",
        "opco_labels": ["PPL Electric", "LG&E", "KU", "Louisville Gas",
                        "Kentucky Utilities", "Rhode Island Energy", "RIE"],
        "keywords": ["Pennsylvania", "Kentucky", "Rhode Island", "PA", "KY", "RI"],
    },
]

# ── EDGAR helpers ─────────────────────────────────────────────────────────────

def get_recent_8k_filings(cik: str, max_count: int = 20) -> list:
    """
    Returns [(acc_clean, acc_dashed, date), ...] for recent 8-Ks.
    Uses data.sec.gov/submissions/ — confirmed working.
    """
    cik_padded = cik.lstrip("0").zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    r = sec_get(url)
    data = r.json()
    recent = data.get("filings", {}).get("recent", {})
    forms  = recent.get("form", [])
    accs   = recent.get("accessionNumber", [])
    dates  = recent.get("filingDate", [])
    result = []
    for f, a, d in zip(forms, accs, dates):
        if f == "8-K":
            clean  = a.replace("-", "")
            result.append((clean, a, d))
        if len(result) >= max_count:
            break
    return result


def get_exhibits_from_index(cik_bare: str, acc_clean: str,
                             acc_dashed: str, filing_date: str) -> list:
    """
    Fetch filing index and return EX-99.X exhibit dicts.
    
    Tries index.json first (www.sec.gov, NOT data.sec.gov),
    then falls back to index.htm.
    
    Returns [{url, type, filename, is_pdf, filing_date}, ...]
    """
    # Try index.json (www.sec.gov/Archives)
    json_url = (f"https://www.sec.gov/Archives/edgar/data/{cik_bare}"
                f"/{acc_clean}/index.json")
    try:
        r = sec_get(json_url)
        items = r.json().get("directory", {}).get("item", [])
        exhibits = []
        for item in items:
            ex_type = item.get("type", "")
            if not re.match(r"EX-99\.\d", ex_type, re.IGNORECASE):
                continue
            name = item.get("name", "")
            url  = (f"https://www.sec.gov/Archives/edgar/data/{cik_bare}"
                    f"/{acc_clean}/{name}")
            exhibits.append({
                "url": url, "type": ex_type, "filename": name,
                "is_pdf": name.lower().endswith(".pdf"),
                "filing_date": filing_date,
            })
        if exhibits:
            log.info(f"      index.json: {len(exhibits)} EX-99.X exhibit(s)")
            return exhibits
    except Exception as e:
        log.debug(f"      index.json failed: {e}")

    # Fallback: parse index.htm (www.sec.gov/Archives)
    # EDGAR index.htm column structure: Seq | Description | Document | Type | Size
    # Type is col index 3 (0-based), NOT col 0
    htm_url = (f"https://www.sec.gov/Archives/edgar/data/{cik_bare}"
               f"/{acc_clean}/{acc_dashed}-index.htm")
    try:
        r = sec_get(htm_url)
        soup = BeautifulSoup(r.text, "html.parser")
        exhibits = []
        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            # Type is in col 3 (Seq=0, Desc=1, Document=2, Type=3, Size=4)
            ex_type = cells[3].get_text(strip=True)
            if not re.match(r"EX-99\.\d", ex_type, re.IGNORECASE):
                continue
            # Document link is in col 2
            a = cells[2].find("a", href=True)
            if not a:
                continue
            href = a["href"]
            if not href.startswith("http"):
                href = "https://www.sec.gov" + href
            name = href.split("/")[-1]
            exhibits.append({
                "url": href, "type": ex_type, "filename": name,
                "is_pdf": name.lower().endswith(".pdf"),
                "filing_date": filing_date,
            })
        log.info(f"      index.htm: {len(exhibits)} EX-99.X exhibit(s)")
        return exhibits
    except Exception as e:
        log.warning(f"      index.htm also failed: {e}")
        return []


# ── Text extraction ───────────────────────────────────────────────────────────

def extract_text_cached(url: str, is_pdf: bool, cache_dir: Path) -> str:
    """Download and extract text. Cache to avoid re-downloading."""
    cache_key = re.sub(r"[^\w]", "_", url)[-120:]
    cache_path = cache_dir / cache_key

    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8", errors="ignore")

    log.info(f"        Downloading: {url[-80:]}")
    try:
        r = sec_get(url, stream=True)
    except Exception as e:
        log.warning(f"        Download failed: {e}")
        return ""

    content_type = r.headers.get("Content-Type", "")
    is_pdf_actual = "pdf" in content_type or url.lower().endswith(".pdf")

    if is_pdf_actual:
        if not PDF_SUPPORT:
            return ""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
            for chunk in r.iter_content(65536):
                tmp.write(chunk)
        try:
            text = pdf_extract_text(tmp_path)
        except Exception as e:
            log.warning(f"        PDF extract error: {e}")
            text = ""
        finally:
            try: os.unlink(tmp_path)
            except: pass
    else:
        soup = BeautifulSoup(r.content, "html.parser")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)

    text = text[:1_000_000]
    cache_path.write_text(text, encoding="utf-8")
    return text


def fetch_ir_presentation_pdf(co: dict) -> str:
    """
    Track 2: Fetch the IR events/presentations page, find most recent
    quarterly investor update PDF link, return extracted text.
    """
    ir_url = co.get("ir_presentations_url", "")
    if not ir_url:
        return ""

    log.info(f"    [Track 2] IR page: {ir_url}")
    try:
        r = sec_get(ir_url)
    except Exception as e:
        log.warning(f"    IR page fetch failed: {e}")
        return ""

    soup = BeautifulSoup(r.text, "html.parser")
    pdf_candidates = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(strip=True).lower()
        # Score link relevance
        score = 0
        if ".pdf" in href.lower():
            score += 3
        if any(k in text for k in ["investor update", "investor presentation",
                                    "earnings presentation", "quarterly update",
                                    "supplemental", "financial supplement",
                                    "q4", "q3", "q2", "q1", "annual"]):
            score += 2
        if any(k in text for k in ["press release", "news release",
                                    "proxy", "annual report"]):
            score -= 2
        if score >= 2:
            # Make absolute URL
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                from urllib.parse import urlparse
                base = urlparse(ir_url)
                href = f"{base.scheme}://{base.netloc}{href}"
            elif not href.startswith("http"):
                href = ir_url.rstrip("/") + "/" + href
            pdf_candidates.append((score, text[:60], href))

    if not pdf_candidates:
        log.info(f"    No IR PDF links found on {ir_url}")
        return ""

    # Sort by score desc, take top candidate
    pdf_candidates.sort(reverse=True)
    _, link_text, pdf_url = pdf_candidates[0]
    log.info(f"    IR PDF candidate: [{link_text}] {pdf_url[-70:]}")

    return extract_text_cached(pdf_url, True, CACHE_DIR)


# ── Rate base extraction (same as v2, validated) ──────────────────────────────

def extract_rate_base_from_text(text: str, opco_labels: list,
                                 keywords: list) -> list:
    """
    Returns list of candidate dicts sorted by strategy quality.

    Strategies (in priority order):
      1. total_rate_base_row      -- "Total Rate Base $X.X $X.X..."
      2. rate_base_table_header   -- "Rate Base ($B) 27.7 30.4..." + year sequence
         dollar_series_years      -- "$41.2 $42.8 $49.4... 2023 2024 2025..."
      3. regulatory_overview      -- "Year-End Rate Base ($B) $X.X" per opco
      4. dollar_rate_base_phrase  -- strict, rejects capital/invest context
      5. balance_sheet_nup        -- net utility plant (Tier 3 fallback)
    """
    results = []

    # ── Strategy 1: "Total Rate Base $X.X $X.X..." explicit row ──────────────
    p1 = re.compile(
        r'(?:[\w\s&]*?)?Total\s+Rate\s+Base\s*(?:\d+)?\s*'
        r'((?:\$?\s*[\d,\.]+\s*){1,8})',
        re.IGNORECASE
    )
    for m in p1.finditer(text):
        vals = []
        for v in re.findall(r'[\d,\.]+', m.group(1)):
            try:
                f = float(v.replace(',', ''))
                if 0.2 < f < 800:
                    vals.append(f)
            except ValueError:
                pass
        if not vals:
            continue
        ctx = text[max(0, m.start()-400):m.end()+200]
        years_int = sorted(set(int(y) for y in re.findall(r'(20[2-3]\d)', ctx)))
        base_year = str(years_int[0]) if years_int else None
        future = {str(int(base_year)+i): v for i, v in enumerate(vals[1:6], 1)}                  if base_year else {}
        results.append({
            'total_b': vals[0], 'year': base_year, 'future_values': future,
            'opco_breakdown': [], 'strategy': 'total_rate_base_row',
            'context': ctx[:300],
        })

    # ── Strategy 2a: "Rate Base ($B)" header + bare/dollar numbers + years ────
    # Catches: AEE, NEE, ETR, HE, EVRG, PCG, CMS
    # "Rate Base ($B) 27.7 30.4 33.4 2025 2026 2027"
    # "Rate Base, $ in Billions 33.6 7.6 $41.2 $42.8 $49.4 2023 2024 2025"
    header_pat = re.compile(
        r'(?:Total\s+|Projected\s+|Company\s+)?'
        r'(?:\w+\s+)?Rate\s+Base\s*(?:\d+)?\s*'
        r'(?:[,;]?\s*\$\s*in\s+[Bb]illions?'
        r'|\(\$\s*[Bb]\)'
        r'|\(\$\s*in\s+[Bb]illions?\))',
        re.IGNORECASE
    )
    for hm in header_pat.finditer(text):
        window = text[hm.end():hm.end()+400]
        # Dollar-prefixed values (higher confidence)
        dollar_vals = [float(v.replace(',', ''))
                       for v in re.findall(r'\$([\d,\.]+)', window)
                       if 0.1 < float(v.replace(',', '')) < 800]
        # Bare decimal values
        bare_vals = [float(v)
                     for v in re.findall(r'(\d{1,3}\.\d)', window)
                     if 0.1 < float(v) < 800]
        all_vals = dollar_vals if dollar_vals else bare_vals
        years = re.findall(r'(20[2-3]\d)', window)
        if not all_vals or not years:
            continue
        n = min(len(all_vals), len(years))
        yr_map = dict(zip(years[:n], all_vals[:n]))
        base_year = '2025' if '2025' in yr_map else ('2024' if '2024' in yr_map else None)
        if not base_year:
            continue
        future = {y: v for y, v in yr_map.items() if int(y) > int(base_year)}
        ctx = text[max(0, hm.start()-100):hm.end()+300]
        results.append({
            'total_b': yr_map[base_year], 'year': base_year,
            'future_values': future, 'opco_breakdown': [],
            'strategy': 'rate_base_table_header', 'context': ctx[:300],
        })

    # ── Strategy 2b: "$X.X $X.X $X.X... YEAR YEAR" dollar series + years ─────
    # Catches EIX: "$41.2 $42.8 $49.4 $53.0 2023 2024 2025 2026"
    dollar_series_pat = re.compile(
        r'(\$[\d,\.]+(?:\s+\$[\d,\.]+){2,})'
        r'\s+'
        r'(20[2-3]\d(?:\s+20[2-3]\d)+)',
    )
    for m in dollar_series_pat.finditer(text):
        vals = [float(v.replace(',', ''))
                for v in re.findall(r'\$([\d,\.]+)', m.group(1))
                if 0.1 < float(v.replace(',', '')) < 800]
        years = re.findall(r'20[2-3]\d', m.group(2))
        if len(vals) < 3 or len(years) < 3:
            continue
        n = min(len(vals), len(years))
        yr_map = dict(zip(years[:n], vals[:n]))
        base_year = '2025' if '2025' in yr_map else ('2024' if '2024' in yr_map else None)
        if not base_year:
            continue
        ctx = text[max(0, m.start()-200):m.end()+100]
        results.append({
            'total_b': yr_map[base_year], 'year': base_year,
            'future_values': {y: v for y, v in yr_map.items() if int(y) > int(base_year)},
            'opco_breakdown': [], 'strategy': 'dollar_series_years',
            'context': ctx[:300],
        })

    # ── Strategy 3: Per-opco "Year-End Rate Base ($B) $X.X" slides ───────────
    p3 = re.compile(
        r'(?:Year-End\s+)?Rate\s+Base\s+\(\$B\)\s+\$?\s*([\d,\.]+)',
        re.IGNORECASE
    )
    opco_vals = []
    for m in p3.finditer(text):
        val = float(m.group(1).replace(',', ''))
        if not 0.05 < val < 300:
            continue
        ctx = text[max(0, m.start()-300):m.end()+100]
        years = re.findall(r'(20[2-3]\d)', ctx)
        year = years[0] if years else None
        opco = next((lb for lb in opco_labels if lb.lower() in ctx.lower()), None)
        if not opco:
            opco = next((k for k in keywords if k.lower() in ctx.lower()), None)
        opco_vals.append({'opco': opco, 'value_b': val, 'year': year})
    if opco_vals:
        total = round(sum(v['value_b'] for v in opco_vals), 1)
        years = [v['year'] for v in opco_vals if v['year']]
        results.append({
            'total_b': total, 'year': years[0] if years else None,
            'future_values': {}, 'opco_breakdown': opco_vals,
            'strategy': 'regulatory_overview_slides',
            'context': f'Sum of {len(opco_vals)} opco values',
        })

    # ── Strategy 4: Strict dollar phrase — rejects capital/invest context ─────
    for pat in [
        re.compile(
            r'(?:total\s+|projected\s+|year.end\s+)?rate\s+base\s+'
            r'(?:of\s+)?(?:~\s*)?\$\s*([\d,\.]+)\s*(?:billion|B|bn)',
            re.IGNORECASE
        ),
        re.compile(
            r'(?:~\s*)?\$\s*([\d,\.]+)\s*(?:billion|B|bn)\s+'
            r'(?:total\s+|projected\s+)?rate\s+base',
            re.IGNORECASE
        ),
    ]:
        for m in pat.finditer(text):
            val = float(m.group(1).replace(',', ''))
            if not 0.2 < val < 500:
                continue
            # Reject if capital/invest/deploy/spend within 100 chars before
            ctx_before = text[max(0, m.start()-100):m.start()].lower()
            if any(kw in ctx_before for kw in
                   ['capital', 'invest', 'deploy', 'spend', 'program', 'plan']):
                continue
            ctx = text[max(0, m.start()-150):m.end()+200]
            years = re.findall(r'(20[2-3]\d[EF]?)', ctx)
            results.append({
                'total_b': val, 'year': years[0] if years else None,
                'future_values': {}, 'opco_breakdown': [],
                'strategy': 'dollar_rate_base_phrase', 'context': ctx[:250],
            })

    # ── Strategy 5: Net utility plant from balance sheet (Tier 3 fallback) ────
    bs_patterns = [
        re.compile(r'[Rr]egulated\s+utility\s+plant,?\s+net\s+\$?\s*([\d,]+)', re.I),
        re.compile(r'[Nn]et\s+utility\s+plant\s+\$?\s*([\d,]+)', re.I),
        re.compile(r'[Nn]et\s+[Pp]roperty,?\s+[Pp]lant\s+&?\s+[Ee]quipment\s+\$?\s*([\d,]+)', re.I),
    ]
    for pat in bs_patterns:
        for m in pat.finditer(text):
            val_m = float(m.group(1).replace(',', ''))
            if not 100 < val_m < 500_000:
                continue
            val_b = round(val_m / 1000, 1)
            ctx = text[max(0, m.start()-100):m.end()+100]
            years = re.findall(r'(20[2-3]\d)', ctx)
            results.append({
                'total_b': val_b, 'year': years[0] if years else None,
                'future_values': {}, 'opco_breakdown': [],
                'strategy': 'balance_sheet_net_utility_plant',
                'context': 'Net utility plant (GAAP) from balance sheet',
                'is_tier3': True,
            })
            break

    # ── Deduplicate and rank ──────────────────────────────────────────────────
    RANK = {
        'total_rate_base_row': 1,
        'rate_base_table_header': 2,
        'dollar_series_years': 2,
        'regulatory_overview_slides': 3,
        'dollar_rate_base_phrase': 4,
        'balance_sheet_net_utility_plant': 5,
    }
    results.sort(key=lambda r: RANK.get(r.get('strategy'), 9))
    seen = set()
    unique = []
    for r in results:
        key = round(r['total_b'], 0)
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def process_company(co: dict) -> dict:
    ticker   = co["ticker"]
    cik      = co["cik"]
    cik_bare = cik.lstrip("0")
    opcos    = co["opco_labels"]
    kws      = co["keywords"]

    log.info(f"\n{'='*60}\n{ticker} -- {co['name']}\n{'='*60}")

    all_candidates = []

    # ── Track 1: EDGAR press releases ────────────────────────────────────────
    log.info(f"  [Track 1] EDGAR 8-K press releases")
    try:
        filings = get_recent_8k_filings(cik, max_count=20)
        log.info(f"    Found {len(filings)} recent 8-K filings")

        for acc_clean, acc_dashed, filing_date in filings[:15]:
            try:
                exhibits = get_exhibits_from_index(cik_bare, acc_clean,
                                                    acc_dashed, filing_date)
            except Exception as e:
                log.warning(f"    Index error {acc_clean}: {e}")
                continue

            for ex in exhibits:
                # Skip non-press-release PDFs (those would be on EDGAR only for
                # companies that DO upload their deck — check type EX-99.2)
                cache_key = re.sub(r"[^\w]", "_", ex["url"])[-120:]
                text = extract_text_cached(ex["url"], ex["is_pdf"], CACHE_DIR)
                if not text:
                    continue

                # Quick classification
                first500 = text[:500].lower()
                is_pr = any(s in first500 for s in
                            ["news release", "press release", "for immediate release",
                             "for news media", "financial analysts:"])

                candidates = extract_rate_base_from_text(text, opcos, kws)
                # Mark source
                for c in candidates:
                    c["filing_date"]  = filing_date
                    c["exhibit_url"]  = ex["url"]
                    c["source_track"] = "press_release" if is_pr else "edgar_exhibit"
                    # Deprioritize balance sheet from press releases if we have better
                    if is_pr and c.get("is_tier3"):
                        c["pr_balance_sheet"] = True

                if candidates:
                    log.info(f"    {ex['filename']}: {len(candidates)} candidate(s) "
                             f"({'press release' if is_pr else 'exhibit'})")
                    all_candidates.extend(candidates)

            # Stop after finding strong candidates from 2 earnings filings
            strong = [c for c in all_candidates
                      if c.get("strategy") in ("total_rate_base_row",
                                                "dollar_rate_base_phrase",
                                                "regulatory_overview_slides")
                      and not c.get("pr_balance_sheet")]
            if len(strong) >= 2:
                log.info(f"    Sufficient Track 1 data found, stopping")
                break

    except Exception as e:
        log.error(f"  Track 1 error for {ticker}: {e}", exc_info=True)

    # ── Track 2: IR website PDF ───────────────────────────────────────────────
    log.info(f"  [Track 2] IR website investor deck")
    try:
        ir_text = fetch_ir_presentation_pdf(co)
        if ir_text:
            ir_candidates = extract_rate_base_from_text(ir_text, opcos, kws)
            for c in ir_candidates:
                c["source_track"] = "ir_website_pdf"
            if ir_candidates:
                log.info(f"    IR PDF: {len(ir_candidates)} candidate(s)")
                all_candidates.extend(ir_candidates)
    except Exception as e:
        log.warning(f"  Track 2 error for {ticker}: {e}")

    # ── Select best ───────────────────────────────────────────────────────────
    STRAT_RANK = {
        "total_rate_base_row": 1,
        "regulatory_overview_slides": 2,
        "dollar_rate_base_phrase": 3,
        "cagr_context": 4,
        "balance_sheet_net_utility_plant": 5,
    }
    # Prefer IR deck > EDGAR exhibit; prefer Tier 1/2/3 in order
    def sort_key(c):
        track_rank = 0 if c.get("source_track") == "ir_website_pdf" else 1
        strat_rank = STRAT_RANK.get(c.get("strategy"), 9)
        bs_penalty = 10 if c.get("pr_balance_sheet") else 0
        year_desc  = -(int(re.sub(r"[^0-9]", "", c.get("year") or "2020") or 2020))
        return (strat_rank + bs_penalty, track_rank, year_desc)

    all_candidates.sort(key=sort_key)

    best = all_candidates[0] if all_candidates else None
    if best:
        tier = "Tier 3 (balance sheet)" if best.get("is_tier3") else "Tier 1 (mgmt disclosed)"
        log.info(f"  BEST: ${best['total_b']}B ({best.get('year')}) "
                 f"[{best.get('strategy')}] [{tier}] "
                 f"[{best.get('source_track')}]")
        for ob in best.get("opco_breakdown", []):
            log.info(f"    {ob.get('opco','?')}: ${ob['value_b']}B ({ob.get('year','')})")
    else:
        log.warning(f"  No rate base data found for {ticker}")

    return {
        "ticker": ticker,
        "best": best,
        "all_candidates": all_candidates[:20],
        "n_candidates": len(all_candidates),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not CAPIQ_PATH.exists():
        log.error(f"capiq_export.json not found at {CAPIQ_PATH}")
        return

    with open(CAPIQ_PATH, "r", encoding="utf-8") as f:
        capiq = json.load(f)

    log.info(f"Loaded capiq_export.json: {len(capiq)} entries")
    audit   = {}
    updated = 0

    for co in COMPANIES:
        ticker = co["ticker"]
        try:
            result = process_company(co)
        except Exception as e:
            log.error(f"Unhandled error for {ticker}: {e}", exc_info=True)
            result = {"ticker": ticker, "best": None, "error": str(e)}

        audit[ticker] = result
        best = result.get("best")

        if best and best.get("total_b"):
            # Find capiq key
            matched = None
            for k in capiq:
                entry = capiq[k]
                if isinstance(entry, dict) and entry.get("ticker","").upper() == ticker:
                    matched = k
                    break
                if k.upper() == ticker:
                    matched = k
                    break

            if matched:
                capiq[matched]["rate_base_mgmt"] = {
                    "total_b":          best["total_b"],
                    "year":             best.get("year"),
                    "source":           best.get("source_track", "edgar"),
                    "strategy":         best.get("strategy"),
                    "tier":             3 if best.get("is_tier3") else 1,
                    "filing_date":      best.get("filing_date"),
                    "opco_breakdown":   best.get("opco_breakdown", []),
                    "future_values":    best.get("future_values", {}),
                    "extracted_at":     datetime.today().strftime("%Y-%m-%d"),
                }
                log.info(f"[OK] {ticker}: rate_base_mgmt appended to capiq['{matched}']")
                updated += 1
            else:
                log.warning(f"[WARN] {ticker}: key not found in capiq_export.json")
                log.warning(f"       Keys (first 8): {list(capiq.keys())[:8]}")

        time.sleep(1.0)

    # Write outputs (UTF-8 everywhere)
    with open(CAPIQ_PATH, "w", encoding="utf-8") as f:
        json.dump(capiq, f, indent=2, ensure_ascii=False)
    log.info(f"capiq_export.json updated: {updated}/{len(COMPANIES)} companies")

    with open(AUDIT_PATH, "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, ensure_ascii=False, default=str)
    log.info(f"Audit log: {AUDIT_PATH}")

    # Summary table (ASCII only)
    print(f"\n{'='*80}")
    print(f"{'Ticker':<8} {'Rate Base':<12} {'Year':<8} {'Tier':<6} "
          f"{'Strategy':<30} {'Track'}")
    print("-"*80)
    for co in COMPANIES:
        r = audit.get(co["ticker"])
        b = r.get("best") if r else None
        if b and b.get("total_b"):
            tier  = "T3" if b.get("is_tier3") else "T1"
            strat = b.get("strategy","")[:28]
            track = b.get("source_track","")[:12]
            print(f"{co['ticker']:<8} ${b['total_b']:<11.1f} "
                  f"{b.get('year') or 'n/a':<8} {tier:<6} {strat:<30} {track}")
        else:
            err = (r.get("error","no data") if r else "error")[:20]
            print(f"{co['ticker']:<8} {'--':<12} {'--':<8} {'--':<6} "
                  f"{'--':<30} {err}")
    print("="*80)

    missed = [co["ticker"] for co in COMPANIES
              if not ((audit.get(co["ticker"]) or {}).get("best") or {}).get("total_b")]
    if missed:
        print(f"\n[WARN] No data for: {', '.join(missed)}")
        print("Next steps for missed tickers:")
        print("  1. Check edgar_cache_v3/ -- open cached .txt files, search for 'rate base'")
        print("  2. Run with --debug to see all URLs attempted")
        print("  3. Some IR pages use JavaScript rendering -- may need manual PDF download")
        print("     then: python extract_manual_pdf.py <ticker> <path_to_pdf>")


if __name__ == "__main__":
    if "--debug" in sys.argv:
        logging.getLogger().setLevel(logging.DEBUG)
    main()