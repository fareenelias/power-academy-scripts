r"""build_aro_env.py - asset retirement obligations, nuclear decommissioning trusts and environmental accruals
from the FY2025 10-K inline-XBRL instances in data\_sec_xbrl\ -> data\aro_env.json (tracker 392, env liabilities / decommissioning)

Consolidated values only (contexts with no dimension members = the registrant's consolidated statements).
Instant facts at the fiscal year end; duration facts for the fiscal year. Ticker from _manifest.json (falls back to the file name).

    python scripts\build_aro_env.py [data_dir]
"""
import sys, os, re, glob, json, datetime, collections

DATA = sys.argv[1] if len(sys.argv) > 1 else r'E:\PowerAcademy\data'
XD = os.path.join(DATA, '_sec_xbrl')
INSTANT = {'aro_total': ['AssetRetirementObligation'], 'aro_noncurrent': ['AssetRetirementObligationsNoncurrent'],
           'aro_current': ['AssetRetirementObligationCurrent'],
           'decom_trust': ['DecommissioningTrustAssetsAmount', 'DecommissioningFundInvestments', 'AssetRetirementObligationLegallyRestrictedAssetsFairValue',
                           'SpentNuclearFuelAndDecommissioningTrustsNoncurrent'],
           'env_accrual': ['AccrualForEnvironmentalLossContingencies', 'AccrualForEnvironmentalLossContingenciesGross']}
DURATION = {'aro_accretion': ['AssetRetirementObligationAccretionExpense', 'AccretionExpenseIncludingAssetRetirementObligations'],
            'aro_incurred': ['AssetRetirementObligationLiabilitiesIncurred'], 'aro_settled': ['AssetRetirementObligationLiabilitiesSettled'],
            'aro_revisions': ['AssetRetirementObligationRevisionOfEstimate'],
            'decom_fund_contrib': ['PaymentsToInvestInDecommissioningFund']}
CUSTOM_OK = {'SpentNuclearFuelAndDecommissioningTrustsNoncurrent'}   # AEP's company-extension tag for the Cook NDT + SNF trusts
TICK_FROM_FILE = {'form10k': 'AWK?', 'xplr': 'XIFR', 'vistra': 'VST'}


def parse(path):
    s = open(path, encoding='utf-8', errors='ignore').read()
    ctx = {}
    for m in re.finditer(r'<(?:xbrli:)?context id="([^"]+)">(.*?)</(?:xbrli:)?context>', s, re.S):
        body = m.group(2)
        dims = 'explicitMember' in body or 'typedMember' in body
        inst = re.search(r'<(?:xbrli:)?instant>([\d-]+)<', body)
        st = re.search(r'<(?:xbrli:)?startDate>([\d-]+)<', body); en = re.search(r'<(?:xbrli:)?endDate>([\d-]+)<', body)
        ctx[m.group(1)] = (dims, inst.group(1) if inst else None, (st.group(1), en.group(1)) if st and en else None)
    facts = collections.defaultdict(list)
    for m in re.finditer(r'<([a-z][\w-]*):(\w+)\s+([^>]*?)>([^<]*)</\1:\2>', s):
        pre, name, attrs, val = m.groups()
        if pre not in ('us-gaap',) and name not in CUSTOM_OK:
            continue
        c = re.search(r'contextRef="([^"]+)"', attrs)
        if not c or c.group(1) not in ctx or ctx[c.group(1)][0]:
            continue
        try:
            v = float(val.strip())
        except ValueError:
            continue
        facts[name].append((ctx[c.group(1)], v))
    # fiscal year end = the latest balance-sheet date carrying consolidated us-gaap:Assets
    bs = [c[1] for c, _ in facts.get('Assets', []) if c[1]]
    fye = max(bs) if bs else None
    return facts, fye


def pick(facts, names, fye, duration=False):
    for n in names:
        for (dims, inst, dur), v in facts.get(n, []):
            if not duration and inst == fye:
                return round(v / 1e6, 1), n
            if duration and dur and dur[1] == fye and (datetime.date.fromisoformat(dur[1]) - datetime.date.fromisoformat(dur[0])).days > 300:
                return round(v / 1e6, 1), n
    return None, None


def main():
    man = {}
    mp = os.path.join(XD, '_manifest.json')
    if os.path.exists(mp):
        m = json.load(open(mp, encoding='utf-8'))
        for t, rows in (m.get('tickers') or {}).items():
            for r in rows:
                if r.get('role') == 'parent' and r.get('accession') and r.get('instance'):
                    man[f"{r['accession']}_{r['instance']}"] = t
    out = {}
    for p in sorted(glob.glob(os.path.join(XD, '*.xml'))):
        fn = os.path.basename(p)
        t = man.get(fn)
        if not t:
            stem = fn.split('_')[1].split('-')[0]
            t = {'xplr': 'XIFR', 'vistra': 'VST', 'form10k': None}.get(stem, stem.upper())
        if not t:
            print('  ? no ticker for', fn); continue
        facts, fye = parse(p)
        rec = {'fiscal_year_end': fye, 'source_file': fn, 'concepts': {}}
        for k, names in INSTANT.items():
            v, n = pick(facts, names, fye); rec[k + '_usd_m'] = v
            if n: rec['concepts'][k] = n
        for k, names in DURATION.items():
            v, n = pick(facts, names, fye, True); rec[k + '_usd_m'] = v
            if n: rec['concepts'][k] = n
        if rec['aro_total_usd_m'] is None and (rec['aro_noncurrent_usd_m'] is not None):
            rec['aro_total_usd_m'] = round((rec['aro_noncurrent_usd_m'] or 0) + (rec['aro_current_usd_m'] or 0), 1)
            rec['concepts']['aro_total'] = 'noncurrent + current'
        if rec['aro_total_usd_m'] and rec['decom_trust_usd_m']:
            rec['trust_to_aro_x'] = round(rec['decom_trust_usd_m'] / rec['aro_total_usd_m'], 2)
        out[t] = rec
        print(f"{t:5} FYE {fye}  ARO {rec['aro_total_usd_m']}  trust {rec['decom_trust_usd_m']}  env {rec['env_accrual_usd_m']}  accretion {rec['aro_accretion_usd_m']}")
    doc = {'_schema_version': '1.0', '_generated': datetime.date.today().isoformat(),
           '_source': 'FY2025 10-K inline XBRL instances (data\\_sec_xbrl), consolidated contexts only',
           '_caveat': ('Tagged values as filed, US$ millions. ARO = AssetRetirementObligation (or noncurrent + current when only those are tagged). '
                       'Decommissioning trust = nuclear decommissioning trust assets where tagged. Environmental accrual = AccrualForEnvironmentalLossContingencies '
                       '(many utilities disclose remediation in text only, so a blank is not a zero). Regulated ARO costs are largely recovered in rates.'),
           'names': out}
    json.dump(doc, open(os.path.join(DATA, 'aro_env.json'), 'w', encoding='utf-8'), indent=1)
    print('wrote aro_env.json', len(out))


if __name__ == '__main__':
    main()
