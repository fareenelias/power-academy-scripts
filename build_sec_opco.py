# -*- coding: utf-8 -*-
r"""build_sec_opco.py - SEC-by-subsidiary phase 2: per-registrant financials, ASC 280 segments and
derived ROE (segment ROE on a STATED capital allocation) from the 10-K XBRL instances that
fetch_sec_xbrl.py downloads into data\_sec_xbrl\.

  python build_sec_opco.py [--xbrl DIR] [--out data\sec_opco.json]

Why the instance document: in a combined 10-K each co-registrant's facts are dimensioned by
dei:LegalEntityAxis; companyfacts serves only undimensioned (parent) facts.
Rules (Fareen 2026-09-21): all SEC-registrant opcos; segment ROE COMPUTED with a stated capital
allocation and labelled derived; FERC (jurisdictional) and SEC (managerial) views never mixed.
"""
import os, sys, json, re, collections, datetime as dt
from lxml import etree

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# LegalEntityAxis member -> co-registrant. Explicit on purpose: member names are free text chosen by
# each filer, and a fuzzy matcher would attach e.g. 'AmerenMissouriSecuritizationFundingI' to Union
# Electric. Every registrant here is a verified CIK in opco_cik_map.json.
REGISTRANT_MEMBERS = {
 'AEE': {'aee:UnionElectricCompanyMember': 'Union Electric Company (Ameren Missouri)',
         'aee:AmerenIllinoisCompanyMember': 'Ameren Illinois Company'},
 'AEP': {'aep:AppalachianPowerCompanyMember': 'Appalachian Power Company',
         'aep:IndianaMichiganPowerCompanyMember': 'Indiana Michigan Power Company',
         'aep:OhioPowerCompanyMember': 'Ohio Power Company',
         'aep:PublicServiceCompanyOfOklahomaMember': 'Public Service Company of Oklahoma',
         'aep:SouthwesternElectricPowerCompanyMember': 'Southwestern Electric Power Company',
         'aep:AEPTexasInc.Member': 'AEP Texas Inc.',
         'aep:AEPTransmissionCompanyLLCMember': 'AEP Transmission Company, LLC'},
 'CMS': {'cms:ConsumersEnergyCompanyMember': 'Consumers Energy Company'},
 'D':   {'d:VirginiaElectricAndPowerCompanyMember': 'Virginia Electric and Power Company'},
 'EIX': {'eix:SouthernCaliforniaEdisonCompanyMember': 'Southern California Edison Company'},
 'ES':  {'es:TheConnecticutLightAndPowerCompanyMember': 'The Connecticut Light and Power Company',
         'es:NstarElectricCompanyMember': 'NSTAR Electric Company',
         'es:PublicServiceCompanyOfNewHampshirePSNHMember': 'Public Service Company of New Hampshire'},
 'ETR': {'etr:EntergyArkansasMember': 'Entergy Arkansas, LLC',
         'etr:EntergyLouisianaMember': 'Entergy Louisiana, LLC',
         'etr:EntergyMississippiMember': 'Entergy Mississippi, LLC',
         'etr:EntergyNewOrleansMember': 'Entergy New Orleans, LLC',
         'etr:EntergyTexasMember': 'Entergy Texas, Inc.',
         'etr:SystemEnergyMember': 'System Energy Resources, Inc.'},
 'EVRG': {'evrg:EvergyKansasCentralIncMember': 'Evergy Kansas Central, Inc.',
          'evrg:EvergyMetroIncMember': 'Evergy Metro, Inc.'},
 'HE':  {'he:HawaiianElectricCompanyAndSubsidiariesMember': 'Hawaiian Electric Company, Inc. (consolidated)'},
 'NEE': {'nee:FloridaPowerLightCompanyMember': 'Florida Power & Light Company'},
 'PCG': {'pcg:PacificGasElectricCoMember': 'Pacific Gas and Electric Company'},
 'PPL': {'ppl:PplElectricUtilitiesCorpMember': 'PPL Electric Utilities Corporation',
         'ppl:LouisvilleGasAndElectricCoMember': 'Louisville Gas and Electric Company',
         'ppl:KentuckyUtilitiesCoMember': 'Kentucky Utilities Company'},
}
# registrants that file their OWN 10-K (not combined with the parent): whole-file = that registrant
STANDALONE_OPCO_FILES = {'0001193125-26-063138': ('D', 'Dominion Energy South Carolina, Inc.')}
# single-registrant parents that ARE the utility
PARENT_IS_OPCO = {'POR': 'Portland General Electric Company'}

# metric -> concept preference list (first present wins, per entity/period); all $ except noted
METRICS = [
 ('revenue', ['us-gaap:Revenues', 'us-gaap:RegulatedAndUnregulatedOperatingRevenue',
              'us-gaap:RegulatedOperatingRevenue', 'us-gaap:ElectricUtilityRevenue',
              # contract revenue EXCLUDES alternative-revenue programs / leases - last resort only
              'us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax',
              'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax']),
 ('operating_income', ['us-gaap:OperatingIncomeLoss']),
 ('da', ['us-gaap:DepreciationDepletionAndAmortization', 'us-gaap:DepreciationAndAmortization',
         'us-gaap:DepreciationAmortizationAndAccretionNet', 'us-gaap:Depreciation']),
 ('interest_expense', ['us-gaap:InterestExpense', 'us-gaap:InterestExpenseNonoperating',
                       'us-gaap:InterestExpenseDebt', 'us-gaap:InterestAndDebtExpense']),
 ('income_tax', ['us-gaap:IncomeTaxExpenseBenefit']),
 ('net_income', ['us-gaap:NetIncomeLossAvailableToCommonStockholdersBasic', 'us-gaap:NetIncomeLoss',
                 'us-gaap:ProfitLoss']),
 ('cfo', ['us-gaap:NetCashProvidedByUsedInOperatingActivities']),
 ('capex', ['us-gaap:PaymentsToAcquirePropertyPlantAndEquipment', 'us-gaap:PaymentsForConstructionInProcess',
            'd:PaymentsToAcquirePropertyPlantAndEquipmentIncludingNuclearFuel',
            'us-gaap:PaymentsToAcquireWaterAndWasteWaterSystems', 'hto:PaymentsToAcquireWaterSystemsUsingCompanyFunds',
            'msex:PaymentForUtilityPlantCapitalExpenditures', 'us-gaap:PaymentsToAcquireOtherPropertyPlantAndEquipment']),
 ('total_assets', ['us-gaap:Assets']),
 ('net_utility_plant', ['us-gaap:PublicUtilitiesPropertyPlantAndEquipmentNet',
                        'us-gaap:PropertyPlantAndEquipmentNet']),
 ('lt_debt', ['us-gaap:LongTermDebtNoncurrent', 'us-gaap:LongTermDebtAndCapitalLeaseObligations',
              'us-gaap:LongTermDebt']),
 ('equity', ['us-gaap:StockholdersEquity', 'us-gaap:MembersEquity',
             'us-gaap:CommonStockholdersEquity',
             'us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest']),
]
# (ticker, entity member or '') -> {metric: [concepts]}; checked by hand against each cash-flow statement
OVERRIDES = {
 ('NEE', ''): {'capex': []},   # NEE prints capex by business (FPL / NEER / other), no total tag - left blank
 ('NEE', 'nee:FloridaPowerLightCompanyMember'): {'capex': ['@parent:nee:CapitalExpendituresOfFPL']},
 ('WTRG', ''): {'capex': ['us-gaap:PaymentsToAcquireBuildings']},   # WTRG tags 'property plant and equipment additions' with this element
}
INSTANT = {'total_assets', 'net_utility_plant', 'lt_debt', 'equity'}
SEG_METRICS = [
 ('revenue', ['us-gaap:Revenues', 'us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax',
              'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax',
              'us-gaap:RegulatedAndUnregulatedOperatingRevenue']),
 ('operating_income', ['us-gaap:OperatingIncomeLoss']),
 ('net_income', ['us-gaap:NetIncomeLoss', 'us-gaap:NetIncomeLossAvailableToCommonStockholdersBasic',
                 'us-gaap:ProfitLoss']),
 ('da', ['us-gaap:DepreciationDepletionAndAmortization', 'us-gaap:DepreciationAndAmortization']),
 ('capex', ['us-gaap:PaymentsToAcquirePropertyPlantAndEquipment',
            'us-gaap:PaymentsToAcquireProductiveAssets']),
 ('total_assets', ['us-gaap:Assets']),
]
YEARS = [2023, 2024, 2025]
SEG_AXIS = 'us-gaap:StatementBusinessSegmentsAxis'
LE_AXIS = 'dei:LegalEntityAxis'
OK_EXTRA_AXES = {'srt:ConsolidationItemsAxis'}   # OperatingSegmentsMember etc. - harmless on segment facts


def parse(path):
    ctxs, facts, nsmap = {}, [], {}
    for ev, el in etree.iterparse(path, events=('end',), huge_tree=True):
        q = etree.QName(el.tag); ln, ns = q.localname, q.namespace or ''
        if ln == 'context':
            c = {'dims': {}}
            for x in el.iter():
                l = etree.QName(x.tag).localname
                if l == 'startDate': c['start'] = x.text.strip()
                elif l == 'endDate': c['end'] = x.text.strip()
                elif l == 'instant': c['instant'] = x.text.strip()
                elif l == 'explicitMember': c['dims'][x.get('dimension')] = x.text.strip()
                elif l == 'typedMember': c['dims'][x.get('dimension')] = 'typed'
            ctxs[el.get('id')] = c; el.clear()
        elif el.get('contextRef') is not None:
            if el.text is not None and len(el) == 0 and el.get('unitRef'):
                pre = next((k for k, v in (el.nsmap or {}).items() if v == ns), ns)
                try:
                    v = float(el.text.strip())
                    if el.get('sign') == '-': v = -v
                    facts.append((f'{pre}:{ln}', el.get('contextRef'), v, el.get('unitRef')))
                except ValueError:
                    pass
            el.clear()
    return ctxs, facts


def fy(c, instant):
    """FY year for a full-year duration (330-380 days) or a year-end instant."""
    try:
        if instant:
            d = dt.date.fromisoformat(c['instant'])
            return d.year if (d.month, d.day) == (12, 31) else None
        s, e = dt.date.fromisoformat(c['start']), dt.date.fromisoformat(c['end'])
        return e.year if 330 <= (e - s).days <= 380 and (e.month, e.day) == (12, 31) else None
    except (KeyError, ValueError):
        return None


def index(ctxs, facts):
    """(entity_key, concept, year, instant?) -> value, where entity_key = '' (parent/undimensioned)
    or the LegalEntityAxis member; and segment facts separately keyed by (entity, segment)."""
    ent, seg = {}, {}
    for concept, cref, v, unit in facts:
        if unit and 'shares' in unit.lower():
            continue
        c = ctxs.get(cref)
        if not c: continue
        dims = dict(c['dims'])
        le = dims.pop(LE_AXIS, '')
        sm = dims.pop(SEG_AXIS, None)
        extra = {k: m for k, m in dims.items() if k not in OK_EXTRA_AXES}
        if extra:
            continue
        if dims.get('srt:ConsolidationItemsAxis') not in (None, 'us-gaap:OperatingSegmentsMember'):
            continue
        inst = 'instant' in c
        y = fy(c, inst)
        if y not in YEARS: continue
        if sm is None:
            if 'srt:ConsolidationItemsAxis' in dims: continue
            ent.setdefault((le, concept, y, inst), v)
        else:
            seg.setdefault((le, sm, concept, y, inst), v)
    return ent, seg


def pick(store, key_prefix, concepts, y, inst):
    for con in concepts:
        v = store.get(key_prefix + (con, y, inst))
        if v is not None:
            return v, con
    return None, None


def entity_block(ent, le, label, role, src, ticker=''):
    out = {'name': label, 'role': role, 'source': src, 'years': YEARS, 'metrics': {}, 'concepts': {}}
    ov = OVERRIDES.get((ticker, le), {})
    for m, cons in METRICS:
        inst = m in INSTANT
        cons = ov.get(m, cons)
        vals, used = {}, set()
        for y in YEARS:
            v = con = None
            for cc in cons:
                if cc.startswith('@parent:'):
                    v = ent.get(('', cc[8:], y, inst)); con = cc[8:]
                else:
                    v, con = pick(ent, (le,), [cc], y, inst)
                if v is not None: break
            vals[str(y)] = None if v is None else round(v / 1e6, 1)
            if con and v is not None: used.add(con.split(':')[1])
        out['metrics'][m] = vals
        if used: out['concepts'][m] = sorted(used)
    # equity: one year of balance sheet before the first income year is usually absent (10-K prints 2)
    ni, eq = out['metrics']['net_income'], out['metrics']['equity']
    roe = {}
    for y in YEARS:
        e1, e0, n = eq.get(str(y)), eq.get(str(y - 1)), ni.get(str(y))
        if n is None or e1 is None:
            roe[str(y)] = None
        else:
            base = (e1 + e0) / 2 if e0 is not None else e1
            roe[str(y)] = round(100 * n / base, 2) if base else None
    out['metrics']['roe_pct'] = roe
    out['roe_basis'] = ('derived: net income / average of year-end and prior year-end equity, both from the '
                        '10-K; a year whose prior year-end equity is not in this filing uses year-end equity only')
    return out


def segment_blocks(seg, le, entity_equity, entity_ni=None):
    segs = sorted({k[1] for k in seg if k[0] == le})
    rows = []
    for sm in segs:
        r = {'segment': sm.split(':')[1].replace('Member', ''), 'member': sm, 'metrics': {}}
        for m, cons in SEG_METRICS:
            inst = m == 'total_assets'
            r['metrics'][m] = {str(y): (None if (v := pick(seg, (le, sm), cons, y, inst)[0]) is None
                                        else round(v / 1e6, 1)) for y in YEARS}
        rows.append(r)
    rows = [r for r in rows if any(v is not None for mv in r['metrics'].values() for v in mv.values())]
    # Sign check: PPL's FY2025 XBRL tags segment net income with the sign INVERTED (Kentucky -674,
    # Pennsylvania -639, Corporate +217 against consolidated NI of +1,179; the printed 10-K table is
    # positive). If the segment rows (excluding any 'Total' row) sum to minus the entity's NI, flip
    # them and say so - the statement is the source of truth, not the tag.
    for y in YEARS:
        ys = str(y)
        ni_ent = entity_ni.get(ys) if entity_ni else None
        parts = [r for r in rows if 'total' not in r['segment'].lower() and r['metrics']['net_income'][ys] is not None]
        s_ = sum(r['metrics']['net_income'][ys] for r in parts)
        if ni_ent and parts and abs(s_ + ni_ent) <= 0.02 * abs(ni_ent) and abs(s_ - ni_ent) > 0.02 * abs(ni_ent):
            for r in rows:
                if r['metrics']['net_income'][ys] is not None:
                    r['metrics']['net_income'][ys] = -r['metrics']['net_income'][ys]
                r.setdefault('flags', []).append(f'{ys}: segment net income sign inverted in the XBRL tags; '
                                                 f'flipped so segments sum to consolidated net income')
    # ---- stated capital allocation: equity allocated pro rata to segment year-end TOTAL ASSETS
    # (all segment rows printing assets, Corporate/Other included when printed, so the shares sum to 1).
    for y in YEARS:
        ys = str(y)
        tot = sum(r['metrics']['total_assets'][ys] or 0 for r in rows)
        eq = entity_equity.get(ys)
        for r in rows:
            a, ni = r['metrics']['total_assets'][ys], r['metrics']['net_income'][ys]
            r.setdefault('allocated_equity', {})[ys] = (round(eq * a / tot, 1)
                                                          if (eq and a and tot) else None)
            r.setdefault('roe_pct_derived', {})[ys] = (round(100 * ni / r['allocated_equity'][ys], 2)
                                                        if (ni is not None and r['allocated_equity'][ys]) else None)
            if r['allocated_equity'][ys] and eq and r['allocated_equity'][ys] < 0.05 * eq:
                r.setdefault('flags', []).append(f'{ys}: allocated equity under 5% of the total - ROE on a small '
                                                 f'asset base is not meaningful')
    return rows


def main():
    args = sys.argv[1:]
    xdir = args[args.index('--xbrl') + 1] if '--xbrl' in args else os.path.join(BASE, 'data', '_sec_xbrl')
    outp = args[args.index('--out') + 1] if '--out' in args else os.path.join(BASE, 'data', 'sec_opco.json')
    man = json.load(open(os.path.join(xdir, '_manifest.json'), encoding='utf-8'))['tickers']
    files = {f[:20]: os.path.join(xdir, f) for f in os.listdir(xdir) if f.endswith('.xml')}
    result = collections.OrderedDict()
    done_acc = set()
    for t in sorted(man):
        parent = next((r for r in man[t] if r['role'] == 'parent' and r.get('accession')), None)
        accs = []
        if parent: accs.append((parent['accession'], 'parent'))
        ciks = {parent['accession']: parent['cik']} if parent else {}
        for r in man[t]:
            if r['role'] == 'opco' and r.get('accession') in STANDALONE_OPCO_FILES:
                accs.append((r['accession'], 'standalone')); ciks[r['accession']] = r['cik']
        blk = {'ticker': t, 'entities': [], 'segments': {}, 'sources': []}
        for acc, kind in accs:
            if (t, acc) in done_acc or acc not in files: continue
            done_acc.add((t, acc))
            ctxs, facts = parse(files[acc])
            ent, seg = index(ctxs, facts)
            src = {'accession': acc, 'file': os.path.basename(files[acc]),
                   'url': f'https://www.sec.gov/Archives/edgar/data/{ciks.get(acc, "")}/{acc.replace("-", "")}/'}
            blk['sources'].append(src)
            if kind == 'standalone':
                label = STANDALONE_OPCO_FILES[acc][1]
                e = entity_block(ent, '', label, 'opco', src['file'], t)
                blk['entities'].append(e)
                blk['segments'][label] = segment_blocks(seg, '', e['metrics']['equity'], e['metrics']['net_income'])
                continue
            plabel = PARENT_IS_OPCO.get(t, t + ' (consolidated)')
            pe = entity_block(ent, '', plabel, 'opco' if t in PARENT_IS_OPCO else 'parent', src['file'], t)
            blk['entities'].append(pe)
            blk['segments'][plabel] = segment_blocks(seg, '', pe['metrics']['equity'], pe['metrics']['net_income'])
            for mem, label in REGISTRANT_MEMBERS.get(t, {}).items():
                e = entity_block(ent, mem, label, 'opco', src['file'], t)
                if not any(v is not None for mv in e['metrics'].values() for v in mv.values()):
                    e['note'] = 'member present in filing map but no undimensioned facts found'
                blk['entities'].append(e)
                s = segment_blocks(seg, mem, e['metrics']['equity'], e['metrics']['net_income'])
                if s: blk['segments'][label] = s
        if blk['entities']:
            result[t] = blk
    out = collections.OrderedDict([
        ('_schema_version', '1.0'),
        ('_generated', dt.date.today().isoformat()),
        ('_source', 'Latest 10-K XBRL instance per registrant (data\\_sec_xbrl, fetch_sec_xbrl.py). $ millions.'),
        ('_method', 'Co-registrant facts are the dei:LegalEntityAxis-dimensioned facts of the combined 10-K '
                    '(explicit member map, no fuzzy matching); parent = undimensioned facts. Segments = ASC 280 '
                    'StatementBusinessSegmentsAxis facts (managerial view - NOT comparable to FERC Form 1 '
                    'jurisdictional figures, which are in opco_financials.json). Entity ROE derived = NI / avg equity.'),
        ('_segment_roe_allocation', 'DERIVED: segment ROE = segment net income / allocated equity; allocated equity = '
                    'registrant year-end total equity x (segment year-end total assets / sum of all segment rows\' '
                    'total assets, Corporate & Other included where printed). An allocation, not a filing: holdco '
                    'debt is spread across segments by asset weight. Blank where the filer prints no segment NI '
                    'or no segment assets.'),
        ('_history_note', 'FY2023-2025 from the current 10-Ks (income 3 yrs, balance sheet 2 yrs -> 2023 ROE uses '
                    'year-end equity only). Extending to 2019 needs the FY2022 and FY2019 10-Ks.'),
        ('tickers', result)])
    json.dump(out, open(outp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('wrote', outp, len(result), 'tickers', sum(len(b['entities']) for b in result.values()), 'entities')


if __name__ == '__main__':
    main()
