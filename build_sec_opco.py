# -*- coding: utf-8 -*-
r"""build_sec_opco.py - SEC-by-subsidiary phase 2: per-registrant financials, ASC 280 segments and
derived ROE (segment ROE on a STATED capital allocation) from the 10-K XBRL instances that
fetch_sec_xbrl.py downloads into data\_sec_xbrl\.

  python build_sec_opco.py [--xbrl DIR] [--out data\sec_opco.json]

History (2026-09-25): reads every 10-K the manifest lists per registrant - the latest plus the FY2023/2021/2019
10-Ks that `fetch_sec_xbrl.py --history` adds - newest first, so a restated year keeps the NEWER filing's
figure. Co-registrants are keyed by CIK via the dei:EntityCentralIndexKey tag each combined 10-K puts on its
LegalEntityAxis members (member names drift between years; CIKs do not). REGISTRANT_MEMBERS is the fallback
for a filing that lacks those tags. Each entity's `years` covers only the years actually on disk.

Why the instance document: in a combined 10-K each co-registrant's facts are dimensioned by
dei:LegalEntityAxis; companyfacts serves only undimensioned (parent) facts.
Rules (Fareen 2026-09-21): all SEC-registrant opcos; segment ROE COMPUTED with a stated capital
allocation and labelled derived; FERC (jurisdictional) and SEC (managerial) views never mixed.
"""
import os, sys, json, re, collections, datetime as dt
try:                                   # lxml is faster; the stdlib parser is the fallback (no pip needed)
    from lxml import etree
    _LXML = True
except ImportError:
    import xml.etree.ElementTree as etree
    _LXML = False


def _split(tag):
    if tag[:1] == '{':
        ns, ln = tag[1:].split('}', 1)
        return ln, ns
    return tag, ''


def _iter(path):
    """yield (localname, namespace, element, uri->prefix) at each element end, lxml or stdlib."""
    if _LXML:
        for ev, el in etree.iterparse(path, events=('end',), huge_tree=True):
            ln, ns = _split(el.tag)
            yield ln, ns, el, {v: k for k, v in (el.nsmap or {}).items()}
    else:
        pref = {}
        for ev, el in etree.iterparse(path, events=('start-ns', 'end')):
            if ev == 'start-ns':
                pref.setdefault(el[1], el[0]); continue
            ln, ns = _split(el.tag)
            yield ln, ns, el, pref

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
YEARS = list(range(2017, 2026))   # FY2019 10-K prints income 2017-19; entity `years` trims to what is on disk
SEG_AXIS = 'us-gaap:StatementBusinessSegmentsAxis'
LE_AXIS = 'dei:LegalEntityAxis'
OK_EXTRA_AXES = {'srt:ConsolidationItemsAxis'}   # OperatingSegmentsMember etc. - harmless on segment facts


def parse(path):
    """-> (contexts, numeric facts, {LegalEntityAxis member or '': CIK int})"""
    ctxs, facts, ciks = {}, [], []
    for ln, ns, el, pref_map in _iter(path):
        if ln == 'context':
            c = {'dims': {}}
            for x in el.iter():
                l = _split(x.tag)[0]
                if l == 'startDate': c['start'] = x.text.strip()
                elif l == 'endDate': c['end'] = x.text.strip()
                elif l == 'instant': c['instant'] = x.text.strip()
                elif l == 'explicitMember': c['dims'][x.get('dimension')] = x.text.strip()
                elif l == 'typedMember': c['dims'][x.get('dimension')] = 'typed'
            ctxs[el.get('id')] = c; el.clear()
        elif ln == 'EntityCentralIndexKey' and el.get('contextRef') is not None and el.text:
            ciks.append((el.get('contextRef'), el.text.strip())); el.clear()
        elif el.get('contextRef') is not None:
            if el.text is not None and len(el) == 0 and el.get('unitRef'):
                pre = pref_map.get(ns, ns)
                try:
                    v = float(el.text.strip())
                    if el.get('sign') == '-': v = -v
                    facts.append((f'{pre}:{ln}', el.get('contextRef'), v, el.get('unitRef')))
                except ValueError:
                    pass
            el.clear()
    member_cik = {}
    for cref, cik in ciks:
        try:
            member_cik[ctxs.get(cref, {}).get('dims', {}).get(LE_AXIS, '')] = int(cik)
        except ValueError:
            pass
    return ctxs, facts, member_cik


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


def entity_block(ent, le, label, role, src, ticker='', parent_key='', ov_key=None):
    """le = entity key in `ent` (a CIK after the multi-filing merge); parent_key = the parent's key;
    ov_key = LegalEntityAxis member ('' for the parent) used to look up OVERRIDES."""
    out = {'name': label, 'role': role, 'source': src, 'years': YEARS, 'metrics': {}, 'concepts': {}}
    ov = OVERRIDES.get((ticker, le if ov_key is None else ov_key), {})
    for m, cons in METRICS:
        inst = m in INSTANT
        cons = ov.get(m, cons)
        vals, used = {}, set()
        for y in YEARS:
            v = con = None
            for cc in cons:
                if cc.startswith('@parent:'):
                    v = ent.get((parent_key, cc[8:], y, inst)); con = cc[8:]
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
    cache = {}

    def load(acc):
        if acc not in cache:
            c, f, mc = parse(files[acc])
            ent, seg = index(c, f)
            cache[acc] = (ent, seg, mc)
        return cache[acc]

    for t in sorted(man):
        recs = man[t]
        parent = next((r for r in recs if r['role'] == 'parent' and r.get('accession')), None)
        known = {r['cik']: r['name'] for r in recs if r.get('cik')}

        def name_cik(nm, _k=known):
            key = re.sub(r'[^a-z]', '', nm.lower())[:14]
            return next((c for c, n in _k.items() if re.sub(r'[^a-z]', '', (n or '').lower()).startswith(key)), None)
        # filing groups: the parent's filings (latest + history), and each standalone opco's own filings
        groups = []
        if parent:
            accs = [parent['accession']] + [h['accession'] for h in parent.get('history', []) if h.get('accession')]
            groups.append(('parent', parent['cik'], accs))
        for r in recs:
            if r['role'] == 'opco' and r.get('accession') in STANDALONE_OPCO_FILES:
                accs = [r['accession']] + [h['accession'] for h in r.get('history', []) if h.get('accession')]
                groups.append(('standalone', r['cik'], accs))
        blk = {'ticker': t, 'entities': [], 'segments': {}, 'sources': []}
        for kind, gcik, accs in groups:
            accs = [a for a in accs if a in files]           # newest first: latest 10-K, then FY23/21/19
            if not accs:
                continue
            # merged stores keyed by CIK; the NEWER filing wins where years overlap (restatements)
            ent_m, seg_m, used = {}, {}, collections.OrderedDict()
            for acc in accs:
                ent, seg, mc = load(acc)
                if kind == 'standalone':
                    # an older year may have been filed INSIDE the parent's combined 10-K: then take only
                    # this registrant's LegalEntityAxis member, never the file's undimensioned (parent) facts
                    if not mc or mc.get('') == gcik:
                        mc = {'': gcik}
                    else:
                        mem_ = next((m for m, c in mc.items() if c == gcik and m), None)
                        if mem_ is None:
                            continue
                        mc = {mem_: gcik}
                else:
                    # older filings may not tag dei:EntityCentralIndexKey per member: fall back to the
                    # explicit member map, matched to the manifest CIK by registrant name
                    mc = dict(mc)
                    for mem, nm in REGISTRANT_MEMBERS.get(t, {}).items():
                        if mem not in mc:
                            c = name_cik(nm)
                            if c: mc[mem] = c
                for (le, con, y, inst), v in ent.items():
                    cik = mc.get(le) if kind == 'standalone' else (mc.get(le) or (gcik if le == '' else None))
                    if cik is None:
                        continue
                    ent_m.setdefault((cik, con, y, inst), v)
                    used.setdefault(cik, set()).add(acc)
                for (le, sm, con, y, inst), v in seg.items():
                    cik = mc.get(le) if kind == 'standalone' else (mc.get(le) or (gcik if le == '' else None))
                    if cik is None:
                        continue
                    seg_m.setdefault((cik, sm, con, y, inst), v)
                blk['sources'].append({'accession': acc, 'file': os.path.basename(files[acc]),
                                       'url': f'https://www.sec.gov/Archives/edgar/data/{gcik}/{acc.replace("-", "")}/'})
            latest_mc = {'': gcik} if kind == 'standalone' else load(accs[0])[2]
            if kind == 'parent':
                pref = [latest_mc[m] for m in REGISTRANT_MEMBERS.get(t, {}) if m in latest_mc]
                order = [gcik] + list(dict.fromkeys(pref + [c for c in latest_mc.values() if c != gcik]))
                order = [c for i, c in enumerate(order) if c != gcik or i == 0]
            else:
                order = [gcik]
            for cik in order:
                if cik == gcik and kind == 'parent':
                    label = PARENT_IS_OPCO.get(t, t + ' (consolidated)')
                    role = 'opco' if t in PARENT_IS_OPCO else 'parent'
                else:
                    mem = next((m for m, c in latest_mc.items() if c == cik), '')
                    label = (REGISTRANT_MEMBERS.get(t, {}).get(mem) or known.get(cik)
                             or re.sub(r'([a-z])([A-Z])', r'\1 \2', mem.split(':')[-1].replace('Member', '')))
                    label = re.sub(r'\s*\(pudl determined\)', '', label).strip()
                    if label and label[0].islower(): label = label.title()
                    role = 'opco'
                    if kind == 'standalone':
                        label = STANDALONE_OPCO_FILES.get(accs[0], (t, label))[1]
                mem = '' if cik == gcik else next((m for m, c in latest_mc.items() if c == cik), None)
                e = entity_block(ent_m, cik, label, role, os.path.basename(files[accs[0]]), t,
                                 parent_key=gcik, ov_key=mem if kind == 'parent' else None)
                e['cik'] = cik
                # show only years this registrant actually has (FY2019-22 appear once --history is fetched)
                # (income-statement years; a prior year-end equity balance alone still feeds the ROE average)
                have = [y for y in YEARS if any(e['metrics'][k].get(str(y)) is not None
                                                for k in ('revenue', 'net_income', 'total_assets'))]
                if have:
                    e['years'] = list(range(have[0], have[-1] + 1))
                    keep = {str(y) for y in range(have[0] - 1, have[-1] + 1)}   # + prior year-end equity
                    e['metrics'] = {k: {y: v for y, v in mv.items() if y in keep} for k, mv in e['metrics'].items()}
                e['filings'] = sorted(used.get(cik, []), reverse=True)
                if not any(v is not None for k, mv in e['metrics'].items() if k != 'roe_pct' for v in mv.values()):
                    continue
                blk['entities'].append(e)
                s_ = segment_blocks(seg_m, cik, e['metrics']['equity'], e['metrics']['net_income'])
                if s_:
                    live = {y for r in s_ for mv in r['metrics'].values() for y, v in mv.items() if v is not None}
                    for r in s_:
                        for fld in ('metrics',):
                            r[fld] = {k: {y: v for y, v in mv.items() if y in live} for k, mv in r[fld].items()}
                        for fld in ('allocated_equity', 'asset_share', 'roe_pct', 'roe_pct_derived'):
                            if isinstance(r.get(fld), dict):
                                r[fld] = {y: v for y, v in r[fld].items() if y in live}
                    blk['segments'][label] = s_
        if blk['entities']:
            result[t] = blk
    out = collections.OrderedDict([
        ('_schema_version', '1.1'),
        ('_generated', dt.date.today().isoformat()),
        ('_source', 'Latest 10-K XBRL instance per registrant, plus the FY2023/2021/2019 10-Ks when fetched with '
                    'fetch_sec_xbrl.py --history (data\\_sec_xbrl). $ millions.'),
        ('_method', 'Co-registrants are identified by the dei:EntityCentralIndexKey each combined 10-K tags on its '
                    'LegalEntityAxis members (so a renamed member in an older filing still maps to the same CIK); '
                    'parent = undimensioned facts. Where filings overlap, the newer filing wins (restated figures). '
                    'Segments = ASC 280 StatementBusinessSegmentsAxis facts (managerial view - NOT comparable to FERC '
                    'Form 1 jurisdictional figures in opco_financials.json). Entity ROE derived = NI / avg equity.'),
        ('_segment_roe_allocation', 'DERIVED: segment ROE = segment net income / allocated equity; allocated equity = '
                    'registrant year-end total equity x (segment year-end total assets / sum of all segment rows\' '
                    'total assets, Corporate & Other included where printed). An allocation, not a filing: holdco '
                    'debt is spread across segments by asset weight. Blank where the filer prints no segment NI '
                    'or no segment assets.'),
        ('_history_note', 'Years present depend on which 10-Ks are on disk: the latest 10-K alone gives FY2023-25 income '
                    'and FY2024-25 balance sheets; adding the FY2023/2021/2019 10-Ks (fetch_sec_xbrl.py --history) '
                    'gives FY2017-25 income statements and FY2018-25 balance sheets unbroken.'),
        ('tickers', result)])
    json.dump(out, open(outp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('wrote', outp, len(result), 'tickers', sum(len(b['entities']) for b in result.values()), 'entities')


if __name__ == '__main__':
    main()
