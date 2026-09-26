r"""build_consolidation.py - regional consolidation view over data\precedents.json (roadmap II.B).

precedents.json carries no geography, so this script holds an explicit TARGET_STATES table
(the target's primary operating states, first = primary; written from general knowledge of
each company's service territory, 2026-09-26 - correct it here, never in the UI). Regions are
the nine US Census divisions, plus 'International'.

Output data\consolidation.json:
  divisions[div] = {deals, by_era{...}, fv_usd_b, financial_buyer_share, deals_list[...]}
  by_state[st]   = deal ids touching that state
  deals[id]      = {states, division, era, year, buyer_type, asset_class, fv_usd_b}
Buyer type: 'financial' when the acquirer is on SPONSORS (infrastructure funds, pensions,
sovereigns, PE), else 'strategic'.

    python scripts\build_consolidation.py          (Windows default path)
    python scripts/build_consolidation.py <data_dir>
"""
import sys, os, json, datetime, collections

DATA = sys.argv[1] if len(sys.argv) > 1 else r'E:\PowerAcademy\data'

DIV = {
 'New England': 'CT ME MA NH RI VT', 'Middle Atlantic': 'NJ NY PA', 'East North Central': 'IL IN MI OH WI',
 'West North Central': 'IA KS MN MO NE ND SD', 'South Atlantic': 'DE DC FL GA MD NC SC VA WV',
 'East South Central': 'AL KY MS TN', 'West South Central': 'AR LA OK TX', 'Mountain': 'AZ CO ID MT NV NM UT WY',
 'Pacific': 'AK CA HI OR WA'}
ST2DIV = {s: d for d, ss in DIV.items() for s in ss.split()}

TARGET_STATES = {
 'nee_dominion_2026': 'VA NC SC', 'blackhills_northwestern_2025': 'MT SD NE', 'blackstone_txnm_2025': 'NM TX',
 'brookfield_dukefl_2025': 'FL', 'stonepeak_bernhard_cleco_2026': 'LA', 'kkr_psp_aep_transmission_2025': 'OH IN MI',
 'cdpq_aes_ohio_2024': 'OH', 'por_pacificorp_wa_2026': 'WA', 'argo_ugi_pa_electric_2026': 'PA', 'oregontrail_idacorp_or_2026': 'OR',
 'iberdrola_avangrid_2024': 'NY CT ME MA', 'gip_cpp_allete_2024': 'MN WI', 'blackstone_nipsco_2023': 'IN',
 'brookfield_fet_2024': 'OH PA WV MD VA', 'brookfield_fet_2021': 'OH PA WV MD VA', 'algonquin_kentuckypower_2021': 'KY',
 'nationalgrid_wpd_2021': 'INTL:UK', 'ppl_narragansett_2021': 'RI', 'gic_dukeindiana_2021': 'IN', 'jpm_elpaso_2019': 'TX NM',
 'enmax_emeramaine_2019': 'ME', 'sempra_infrareit_2018': 'TX', 'nee_gulfpower_2018': 'FL', 'centerpoint_vectren_2018': 'IN OH',
 'dominion_scana_2018': 'SC NC', 'sempra_oncor_2017': 'TX', 'hydroone_avista_2017': 'WA ID OR AK', 'greatplains_westar_2018': 'KS',
 'bhe_oncor_2017': 'TX', 'nee_oncor_2016': 'TX', 'greatplains_westar_orig_2016': 'KS', 'algonquin_empiredistrict_2016': 'MO KS OK AR',
 'fortis_itc_2016': 'MI IA MN IL MO KS OK', 'emera_teco_2015': 'FL NM', 'iberdrolausa_uil_2015': 'CT MA', 'mira_bcimc_cleco_2014': 'LA',
 'wisconsinenergy_integrys_2014': 'WI IL MI MN', 'exelon_pepco_2014': 'MD DC DE NJ', 'fortis_uns_2013': 'AZ', 'midamerican_nvenergy_2013': 'NV',
 'omers_midlandcogen_2012': 'MI', 'fortis_chenergy_2012': 'NY', 'altagas_semco_2012': 'MI AK', 'aes_dpl_2011': 'OH',
 'duke_progress_2011': 'NC SC FL', 'agl_nicor_2010': 'IL', 'northeastutilities_nstar_2010': 'MA', 'ppl_eonus_2010': 'KY VA',
 'firstenergy_allegheny_2010': 'PA WV MD VA', 'transcanada_ravenswood_2008': 'NY', 'greatplains_aquila_2007': 'MO',
 'avangrid_pnm_2020': 'NM TX', 'nee_hawaiian_2014': 'HI', 'exelon_constellation_2011': 'MD', 'macquarie_puget_2007': 'WA',
 'iberdrola_energyeast_2007': 'NY ME CT MA', 'duke_cinergy_2005': 'OH IN KY', 'midamerican_pacificorp_2005': 'OR UT WY WA ID CA',
 'exelon_pseg_2004': 'NJ', 'macquarie_duquesne_2006': 'PA', 'wps_peoples_2006': 'IL', 'bbi_northwestern_2006': 'MT SD NE',
 'fortis_cvps_2011': 'VT', 'firstenergy_gpu_2000': 'NJ PA', 'nationalgrid_niagaramohawk_2000': 'NY', 'aes_ipalco_2000': 'IN',
 'ameren_cilcorp_2002': 'IL', 'exelon_peco_unicom_1999': 'IL', 'cpl_floridaprogress_1999': 'FL', 'nsp_newcentury_1999': 'CO TX NM',
 'gip_eqt_aes_2026': 'IN OH', 'aep_csw_2000': 'TX OK LA AR', 'fpl_constellation_2005': 'MD', 'coned_nu_1999': 'CT MA NH',
 'nexteratransmission_transbaycable_2019': 'CA', 'itc_entergy_transmission_2013': 'AR LA MS TX', 'bhe_altalink_2014': 'INTL:Canada',
 'brookfield_transbaycable_2025': 'CA', 'delta_spire_mississippi_2026': 'MS', 'spire_piedmont_tn_2025': 'TN', 'bernhard_nmgc_2024': 'NM',
 'bernhard_centerpoint_lams_2024': 'LA MS', 'bernhard_entergy_lagas_2023': 'LA', 'chesapeake_fcg_2023': 'FL',
 'enbridge_dominion_gas_2023': 'OH UT NC WY ID', 'iif_sji_2022': 'NJ', 'ugi_mountaineer_2020': 'WV', 'eversource_columbiagas_ma_2020': 'MA',
 'aqua_peoples_2018': 'PA WV KY', 'sji_elizabethtown_elkton_2017': 'NJ MD', 'altagas_wgl_2017': 'DC MD VA', 'dominion_questar_2016': 'UT WY ID',
 'duke_piedmont_2015': 'NC SC TN', 'blackhills_sourcegas_2015': 'AR CO NE WY', 'spire_energysouth_2016': 'AL',
 'psp_atrf_altagascanada_2019': 'INTL:Canada', 'algonquin_egnb_2018': 'INTL:Canada', 'nfg_centerpoint_ohio_2025': 'OH',
 'unitil_maine_naturalgas_2025': 'ME', 'nwnatural_sienergy_2024': 'TX', 'northwestern_energywestmontana_2024': 'MT',
 'unitil_bangor_naturalgas_2024': 'ME', 'trisummit_altagas_ak_2022': 'AK', 'hearthstone_hopegas_2022': 'WV',
 'summit_centerpoint_ar_ok_2021': 'AR OK', 'nextera_fcg_2018': 'FL', 'southern_agl_2015': 'GA IL VA NJ TN FL MD',
 'uil_iberdrola_ctgas_2010': 'CT MA', 'calwater_nexus_nevada_2026': 'NV', 'awk_essential_2025': 'PA OH IL TX NC NJ IN VA KY',
 'h2o_southcentral_2025': 'TX', 'h2o_quadvest_2025': 'TX', 'awk_nexus_2025': '', 'unitil_aquarion_nh_2025': 'NH',
 'rwa_aquarion_2025': 'CT MA NH', 'sjw_connecticutwater_2018': 'CT ME', 'eversource_aquarion_2017': 'CT MA NH', 'algonquin_park_2014': 'CA',
}
SPONSORS = ('blackstone', 'kkr', 'global infrastructure partners', 'gip', 'brookfield', 'cdpq', 'stonepeak', 'bernhard', 'j.p. morgan',
            'jpm', 'iif', 'infrastructure investments fund', 'mira', 'macquarie', 'bcimc', 'omers', 'gic', 'psp', 'argo', 'trisummit',
            'hearthstone', 'cpp investments', 'eqt', 'babcock & brown', 'alinda', 'ifm', 'ardian', 'apollo', 'carlyle',
            'riverstone', 'atrf')   # deliberately excludes co-ops, municipal/regional authorities and sponsor-backed strategics
ERAS = [('pre-2010', 0, 2009), ('2010-14', 2010, 2014), ('2015-19', 2015, 2019), ('2020-26', 2020, 2099)]


def fv_b(d):
    r = d.get('raw') or {}
    if not isinstance(r, dict):
        return None
    if r.get('fv_usd_b') is not None:
        return float(r['fv_usd_b'])
    if r.get('fv_usd_m') is not None:
        return float(r['fv_usd_m']) / 1000
    return None


def main():
    deals = json.load(open(os.path.join(DATA, 'precedents.json'), encoding='utf-8'))['deals']
    missing = [d['id'] for d in deals if d['id'] not in TARGET_STATES]
    out_deals, by_state = {}, collections.defaultdict(list)
    for d in deals:
        st = TARGET_STATES.get(d['id'])
        if st is None:
            continue
        yr = int(str(d.get('announced') or '0')[:4] or 0)
        era = next(e for e, a, b in ERAS if a <= yr <= b)
        acq = (d.get('acquirer') or '').lower()
        btype = 'financial' if any(s in acq for s in SPONSORS) else 'strategic'
        if st.startswith('INTL:'):
            states, div = [], 'International'
        elif not st:
            states, div = [], 'Multi-state / unmapped'
        else:
            states = st.split()
            div = ST2DIV[states[0]]
        out_deals[d['id']] = {'target': d.get('target'), 'acquirer': d.get('acquirer'), 'year': yr, 'era': era, 'states': states,
                              'division': div, 'buyer_type': btype, 'asset_class': d.get('asset_class'), 'status': d.get('status'),
                              'control_type': d.get('control_type'), 'fv_usd_b': fv_b(d)}
        for s in states:
            by_state[s].append(d['id'])
    divs = collections.OrderedDict()
    for dname in list(DIV) + ['International', 'Multi-state / unmapped']:
        ids = [i for i, x in out_deals.items() if x['division'] == dname]
        if not ids:
            continue
        xs = [out_deals[i] for i in ids]
        fvs = [x['fv_usd_b'] for x in xs if x['fv_usd_b']]
        divs[dname] = {'deals': len(ids), 'by_era': {e: sum(1 for x in xs if x['era'] == e) for e, _, _ in ERAS},
                       'fv_usd_b': round(sum(fvs), 1), 'fv_known': len(fvs),
                       'financial_buyer_share': round(sum(1 for x in xs if x['buyer_type'] == 'financial') / len(xs), 2),
                       'by_asset_class': dict(collections.Counter(x['asset_class'] for x in xs)),
                       'deal_ids': sorted(ids, key=lambda i: -out_deals[i]['year'])}
    doc = {'_schema_version': '1.0', '_generated': datetime.date.today().isoformat(),
           '_source': 'data\\precedents.json + TARGET_STATES in scripts\\build_consolidation.py',
           '_caveat': ('Target geography is the primary operating states from general knowledge of each company (first state = '
                       'division). Multi-state targets count once, in their primary division; by_state lists every state touched. '
                       'fv_usd_b is the deal firm value where precedents.json carries one. Buyer type is name-based '
                       '(infrastructure funds / pensions / PE = financial).'),
           'eras': [e for e, _, _ in ERAS], 'divisions': divs, 'by_state': {s: v for s, v in sorted(by_state.items())},
           'deals': out_deals, 'unmapped_ids': missing}
    json.dump(doc, open(os.path.join(DATA, 'consolidation.json'), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    print(f'wrote consolidation.json: {len(out_deals)} deals mapped, {len(missing)} not in TARGET_STATES {missing}')
    for k, v in divs.items():
        print(f"  {k:22} {v['deals']:>3} deals  {v['by_era']}  ${v['fv_usd_b']}B ({v['fv_known']} valued)  financial {v['financial_buyer_share']:.0%}")


if __name__ == '__main__':
    main()
