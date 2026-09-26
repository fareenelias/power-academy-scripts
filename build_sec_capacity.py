r"""build_sec_capacity.py - liquidity & tax-capacity facts from the 10-K XBRL instances.

Reads the latest 10-K instance per coverage parent in data\_sec_xbrl\ (the ones
fetch_sec_xbrl.py downloaded; manifest = data\_sec_xbrl\_manifest.json) and writes
data\sec_capacity.json with, per ticker, for the fiscal year-end instant:

  commercial_paper   - CP outstanding: us-gaap:CommercialPaper, or ShortTermBorrowings /
                       DebtInstrumentCarryingAmount on ShortTermDebtTypeAxis=CommercialPaperMember
  short_term_borrowings
  revolver           - LineOfCreditFacilityMaximumBorrowingCapacity (+ Remaining, + drawn)
  nol                - OperatingLossCarryforwards (gross) by tax authority, and
                       DeferredTaxAssetsOperatingLossCarryforwards (tax-effected)
  tax_credits        - TaxCreditCarryforwardAmount / DeferredTaxAssetsTaxCreditCarryforwards
                       (PTC/ITC and other general business credits live here)

Every value is split by entity: undimensioned = the filer's consolidated figure; a
LegalEntityAxis member = a co-registrant opco (member local-name kept as printed).
Facts carrying any OTHER dimension are kept as 'detail' rows with their members, never
summed - the filer's own total is the only total reported. Units: $M.

  python scripts\build_sec_capacity.py            (Windows; paths default to E:\PowerAcademy)
  python scripts/build_sec_capacity.py <data_dir> (anywhere)
"""
import sys, os, re, json, datetime, collections
import xml.etree.ElementTree as ET

DATA = sys.argv[1] if len(sys.argv) > 1 else r'E:\PowerAcademy\data'
XDIR = os.path.join(DATA, '_sec_xbrl')

CONCEPTS = {
    'CommercialPaper': 'commercial_paper',
    'ShortTermBorrowings': 'short_term_borrowings',
    'LineOfCreditFacilityMaximumBorrowingCapacity': 'revolver_capacity',
    'LineOfCreditFacilityRemainingBorrowingCapacity': 'revolver_available',
    'LineOfCredit': 'revolver_drawn',
    'LongTermLineOfCredit': 'revolver_drawn',
    'OperatingLossCarryforwards': 'nol_gross',
    'DeferredTaxAssetsOperatingLossCarryforwards': 'nol_dta',
    'DeferredTaxAssetsOperatingLossCarryforwardsDomestic': 'nol_dta',
    'DeferredTaxAssetsOperatingLossCarryforwardsStateAndLocal': 'nol_dta',
    'TaxCreditCarryforwardAmount': 'tax_credit_cf',
    'DeferredTaxAssetsTaxCreditCarryforwards': 'tax_credit_dta',
    'DeferredTaxAssetsTaxCreditCarryforwardsGeneralBusiness': 'tax_credit_dta',
}
CP_MEMBER = re.compile(r'CommercialPaper', re.I)
NS_XBRLI = '{http://www.xbrl.org/2003/instance}'
NS_XBRLDI = '{http://xbrl.org/2006/xbrldi}'


def local(tag):
    return tag.split('}', 1)[-1]


def parse(path):
    """-> (contexts, facts). contexts: id -> {'instant'|'end', 'dims': {axis: member}}"""
    ctx, facts = {}, []
    for ev, el in ET.iterparse(path, events=('end',)):
        tag = el.tag
        if tag == NS_XBRLI + 'context':
            per = el.find(NS_XBRLI + 'period')
            inst = per.find(NS_XBRLI + 'instant') if per is not None else None
            end = per.find(NS_XBRLI + 'endDate') if per is not None else None
            dims = {}
            for m in el.iter(NS_XBRLDI + 'explicitMember'):
                dims[m.get('dimension').split(':')[-1]] = (m.text or '').split(':')[-1]
            ctx[el.get('id')] = {'date': (inst.text if inst is not None else (end.text if end is not None else None)),
                                 'instant': inst is not None, 'dims': dims}
            el.clear()
        elif local(tag) == 'DocumentPeriodEndDate' and 'dei' in tag:
            ctx.setdefault('__dped__', {'date': None, 'dims': {}, 'instant': True})
            if el.text and (ctx['__dped__']['date'] is None or el.text.strip() > ctx['__dped__']['date']):
                ctx['__dped__']['date'] = el.text.strip()
            el.clear()
        elif tag.startswith('{http://fasb.org/us-gaap/'):
            name = local(tag)
            if name in CONCEPTS or name in ('DebtInstrumentCarryingAmount', 'ShortTermBorrowings'):
                txt = (el.text or '').strip()
                if txt and el.get('contextRef'):
                    try:
                        facts.append((name, el.get('contextRef'), float(txt)))
                    except ValueError:
                        pass
            el.clear()
    return ctx, facts


def latest_instances():
    man = json.load(open(os.path.join(XDIR, '_manifest.json'), encoding='utf-8'))
    out = {}
    for t, recs in man['tickers'].items():
        for r in recs:
            if r.get('role') == 'parent' and r.get('instance'):
                fn = f"{r['accession']}_{r['instance']}"
                if os.path.exists(os.path.join(XDIR, fn)):
                    out[t] = (fn, r.get('filed'), r.get('accession'), r.get('primary'), r.get('cik'))
    return out


def summarise(ctx, facts):
    # the fiscal year-end is dei:DocumentPeriodEndDate - NOT the latest date in the file
    # (subsequent-event facts dated after year-end, e.g. a Feb-2026 financing, are ignored)
    fy = (ctx.get('__dped__') or {}).get('date')
    if not fy:
        return None
    if not any(ctx.get(c, {}).get('date') == fy for _, c, _ in facts):
        return None
    ent = collections.defaultdict(lambda: collections.defaultdict(dict))   # entity -> key -> {..}
    detail = []
    for name, cref, val in facts:
        c = ctx.get(cref)
        if not c or c['date'] != fy:
            continue
        dims = dict(c['dims'])
        entity = dims.pop('LegalEntityAxis', None)
        ce = dims.get('ConsolidatedEntitiesAxis')
        if not entity and ce:                      # ParentCompanyMember = the holdco on its own
            entity = 'ParentCompanyMember' if ce == 'ParentCompanyMember' else ce
            dims.pop('ConsolidatedEntitiesAxis')
        entity = entity or 'consolidated'
        v = round(val / 1e6, 1)
        if name in ('DebtInstrumentCarryingAmount', 'ShortTermBorrowings') and any(CP_MEMBER.search(m) for m in dims.values()):
            key = 'commercial_paper'
            others = {a: m for a, m in dims.items() if not CP_MEMBER.search(m)}
            if not others:
                ent[entity][key].setdefault('value', v); ent[entity][key].setdefault('concept', name + ' [CommercialPaperMember]')
                continue
            detail.append({'entity': entity, 'key': key, 'concept': name, 'dims': dims, 'value_m': v}); continue
        if name == 'DebtInstrumentCarryingAmount':
            continue
        key = CONCEPTS[name]
        if key.startswith('revolver_') and any(CP_MEMBER.search(m) for m in dims.values()):
            key = 'cp_program_' + key.split('_', 1)[1]          # capacity/available of the CP programme
            dims = {a: m for a, m in dims.items() if not CP_MEMBER.search(m)}
            if not dims:
                ent[entity][key].setdefault('value', v); ent[entity][key].setdefault('concept', name + ' [CommercialPaperMember]')
                continue
        if dims:
            detail.append({'entity': entity, 'key': key, 'concept': name, 'dims': dims, 'value_m': v})
            continue
        slot = ent[entity][key]
        if 'value' not in slot or name in ('CommercialPaper', 'OperatingLossCarryforwards', 'TaxCreditCarryforwardAmount',
                                           'DeferredTaxAssetsOperatingLossCarryforwards', 'DeferredTaxAssetsTaxCreditCarryforwards'):
            slot['value'] = v; slot['concept'] = name
    return fy, {e: dict(k) for e, k in ent.items()}, detail


def main():
    inst = latest_instances()
    out = {'_schema_version': '1.0', '_generated': datetime.date.today().isoformat(),
           '_source': 'SEC 10-K XBRL instances (data\\_sec_xbrl) via scripts\\build_sec_capacity.py',
           '_units': '$M; balance-sheet instants at the fiscal year-end of the latest 10-K on disk',
           '_caveats': [
               'A value exists only where the filer TAGGED it. Many utilities disclose CP and revolver terms in text or tables tagged with facility-specific dimensions; those appear under detail[] with their members and are never summed by this script.',
               'nol_gross is the gross carryforward (pre-tax); nol_dta is its tax-effected deferred tax asset. Filers mix federal/state in one tag or split them by IncomeTaxAuthorityAxis - see detail[].',
               'tax_credit_* is predominantly PTC/ITC general-business-credit carryforwards for utilities with renewables; transferability (IRA s.6418) monetisation is not visible in these tags.',
               'AQN (40-F filer) and names without a 10-K instance on disk are absent.'],
           'tickers': {}}
    for t, (fn, filed, acc, prim, cik) in sorted(inst.items()):
        p = os.path.join(XDIR, fn)
        try:
            ctx, facts = parse(p)
        except ET.ParseError as e:
            print(f'  {t}: parse error {e}'); continue
        r = summarise(ctx, facts)
        if not r:
            print(f'  {t}: no capacity facts'); continue
        fy, ent, detail = r
        src = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{prim}" if cik and acc and prim else None
        seen, dd = set(), []
        for r in detail:                                       # the same fact is often tagged in 2-3 notes
            k = (r['entity'], r['key'], r['value_m'], tuple(sorted(r['dims'].items())))
            if k not in seen:
                seen.add(k); dd.append(r)
        out['tickers'][t] = {'fy_end': fy, 'filed': filed, 'accession': acc, 'source_url': src,
                             'entities': ent, 'detail': dd[:200], 'detail_truncated': max(0, len(dd) - 200)}
        qc = []
        for e, ks in ent.items():
            g2, d2 = (ks.get('nol_gross') or {}).get('value'), (ks.get('nol_dta') or {}).get('value')
            if g2 and d2 and g2 == d2:
                qc.append(f'{e}: NOL gross == NOL deferred tax asset ({g2}) - the filer has likely tagged one figure under both concepts; read the tax note before citing either')
        if qc:
            out['tickers'][t]['qc'] = qc
        c = ent.get('consolidated', {})
        g = lambda k: (c.get(k) or {}).get('value')
        print(f"  {t:5} {fy}  CP {g('commercial_paper')}  STB {g('short_term_borrowings')}  RCF {g('revolver_capacity')}  "
              f"NOL {g('nol_gross')}/{g('nol_dta')}  credits {g('tax_credit_cf')}/{g('tax_credit_dta')}  entities {len(ent)}  detail {len(detail)}")
    json.dump(out, open(os.path.join(DATA, 'sec_capacity.json'), 'w', encoding='utf-8'), indent=1)
    print('wrote sec_capacity.json:', len(out['tickers']), 'tickers')


if __name__ == '__main__':
    main()
