r"""extract_gp_profiles.py - Infralogic GP / investor profile PDFs (data\infralogic\*_.pdf) -> data\gp_profiles.json

Fills the two `_missing` sponsor fields (tracker 1498 / 360):
  aum        header 'AUM:' and 'Infrastructure AUM:' (GP) or 'AUM:' + infra allocation (institutional), native currency as printed
  mandate    DERIVED sector / sub-sector / region mix of the holdings table in the profile (count of asset rows),
             plus the fund list (strategy, vintage, size, status) where the funds table prints it.
Contact details (emails, phones, people) are NOT kept. The profile's overview prose is not copied.

    python scripts\extract_gp_profiles.py [data_dir]
"""
import sys, os, re, glob, json, collections, datetime
import pymupdf

DATA = sys.argv[1] if len(sys.argv) > 1 else r'E:\PowerAcademy\data'
SRC = os.path.join(DATA, 'infralogic')
SECTORS = {'Energy', 'Power', 'Renewables', 'Telecommunications', 'Transport', 'Social Infrastructure', 'Environment',
           'Water', 'Other', 'Mining', 'Utilities', 'Digital Infrastructure', 'Healthcare', 'Education', 'Defence', 'Government Buildings', 'Leisure', 'Real Estate', 'Oil & Gas'}
REGIONS = {'North America', 'Europe', 'Asia Pacific', 'Latin America', 'Middle East & Africa', 'Middle East and Africa', 'Africa', 'Oceania', 'Global', 'Asia', 'Middle East'}
AMT = r'(USD|EUR|GBP|AUD|CAD|NOK|CHF|JPY|SGD)\s*([\d,.]+)\s*(bn|m)'


def money(s):
    m = re.search(AMT, s)
    if not m:
        return None
    v = float(m.group(2).replace(',', ''))
    return {'ccy': m.group(1), 'value_b': round(v / 1000 if m.group(3) == 'm' else v, 2)}


def parse(path):
    doc = pymupdf.open(path)
    pages = [p.get_text() for p in doc]
    head, txt = pages[0], '\n'.join(pages)
    lines = [l.strip() for l in txt.split('\n') if l.strip()]
    name = lines[0].strip()
    out = {'name': name, 'source_file': os.path.basename(path), 'pages': doc.page_count}
    out['country'] = lines[1] if len(lines) > 1 else None
    out['type'] = lines[2] if len(lines) > 2 and lines[2] != 'OVERVIEW' else None
    for key, pat in (('active_funds', r'Active funds:\s*(\d+)'), ('realized_funds', r'Realized funds:\s*(\d+)'),
                     ('co_investment_funds', r'Co-investment funds:\s*(\d+)')):
        m = re.search(pat, head)
        out[key] = int(m.group(1)) if m else None
    m = re.search(r'(?<!Infrastructure )AUM:\s*' + AMT, head)
    out['aum'] = money(m.group(0)) if m else None
    m = re.search(r'Infrastructure AUM:\s*' + AMT, head)
    out['infra_aum'] = money(m.group(0)) if m else None
    for key, pat in (('target_infra_allocation_pct', r'Target infra allocation:\s*([\d.]+)%'),
                     ('current_infra_allocation_pct', r'Current infra allocation:\s*([\d.]+)%')):
        m = re.search(pat, head)
        out[key] = float(m.group(1)) if m else None
    # holdings table -> sector / sub-sector / region mix
    sec, sub, reg, n = collections.Counter(), collections.Counter(), collections.Counter(), 0
    for i, l in enumerate(lines):
        if l in SECTORS:
            for j in range(i + 1, min(i + 5, len(lines))):
                if lines[j] in REGIONS:
                    sub_s = ' '.join(lines[i + 1:j]).strip()
                    if not sub_s or len(sub_s) > 60:
                        break
                    sec[l] += 1; sub[sub_s] += 1; reg[lines[j]] += 1; n += 1
                    break
    out['holdings_rows'] = n
    tot = sum(sec.values()) or 1
    out['sector_mix_pct'] = {k: round(100 * v / tot) for k, v in sec.most_common()}
    out['top_subsectors'] = [k for k, _ in sub.most_common(8)]
    out['region_mix_pct'] = {k: round(100 * v / tot) for k, v in reg.most_common()}
    utilish = sum(v for k, v in sub.items() if re.search(r'Transmission|Distribution|Utilit|Gas Pipeline|Water|Power Other|Gas Distribution', k))
    out['utility_like_share_pct'] = round(100 * utilish / tot) if n else None
    # fund closes from the timeline ("Final Close - USD 7200m")
    closes = []
    for m in re.finditer(r'(\d{4})\n((?:[A-Z][a-z]{2} .+\n)+)', txt):
        yr = m.group(1)
        for row in m.group(2).split('\n'):
            mm = re.match(r'([A-Z][a-z]{2}) (.+?): Final Close - ' + AMT, row)
            if mm:
                mv = money(row[row.find('Final Close'):])
                if mv and mv['value_b'] < 100:          # the profile timeline prints some early closes in 'bn' for 'm' (Stonepeak Fund I 'USD 619bn')
                    closes.append({'year': int(yr), 'fund': mm.group(2).strip(), **mv})
    out['final_closes'] = closes[-8:]
    return out


def main():
    rows = {}
    for p in sorted(glob.glob(os.path.join(SRC, '*_.pdf'))):
        r = parse(p)
        rows[r['name']] = r
        a = r['aum']; ia = r['infra_aum']
        print(f"{r['name'][:45]:45} {r['type'] or '':22} AUM {a and (a['ccy'], a['value_b'])}  infra {ia and (ia['ccy'], ia['value_b'])}  rows {r['holdings_rows']}  {list(r['sector_mix_pct'].items())[:3]}")
    doc = {'_schema_version': '1.0', '_generated': datetime.date.today().isoformat(),
           '_source': 'Infralogic GP / investor profile PDFs in data\\infralogic\\*_.pdf (desktop download, 2026-08-24/25)',
           '_caveat': ('AUM as printed on the profile header, native currency, as of the download date. sector_mix_pct and region_mix_pct are '
                       'DERIVED: the share of asset rows in the profile holdings table by sector / region (counts, not value) - a proxy for '
                       'mandate, not the fund documents. Contact details and overview prose are deliberately not kept.'),
           'profiles': rows}
    json.dump(doc, open(os.path.join(DATA, 'gp_profiles.json'), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    print('wrote gp_profiles.json', len(rows))


if __name__ == '__main__':
    main()
