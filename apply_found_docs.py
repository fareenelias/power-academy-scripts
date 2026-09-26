# -*- coding: utf-8 -*-
r"""apply_found_docs.py - fill the _needs_find document gaps in data\precedents.json with the documents found
2026-09-25 (EDGAR filing indexes around each announcement date + company IR sites), and fix three wrong links
found along the way. Backup: precedents.json.bak-prefound-20260925.

  python E:\PowerAcademy\scripts\apply_found_docs.py

Every link set here is confidence 'strong' (content checked by Claude: names the deal, right date, right type),
not 'verified' - that stays for FE's review. Gaps that could not be found are listed in links._not_found with why.
"""
import os, sys, json, shutil

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = '2026-09-25'
S = 'https://www.sec.gov/Archives/edgar/data/'

# deal -> {field: (url, provenance)}
FOUND = {
 'enbridge_dominion_gas_2023': {
   'deck': (S + '895728/000110465923098325/tm2325426d4_ex99-3.htm', 'Enbridge 8-K 2023-09-05 ex-99.3: acquisition slides (Ebel/Murray, Sept 5, 2023)')},
 'algonquin_kentuckypower_2021': {
   'deck': ('https://s25.q4cdn.com/253745149/files/doc_presentations/2021/10/26/AQN-Investor-Presentation-2021-10-26.pdf', 'AQN investor presentation Oct 26, 2021 "Algonquin to Acquire Kentucky Power..." ($2.846bn incl. $1.221bn debt; 1.3x mid-2022 rate base)'),
   'agreement': (S + '1174169/000114036121035654/ny20001090x3_ex99-2.htm', 'AQN 6-K 2021-10-27 ex-99.2: Stock Purchase Agreement AEP / AEP Transmission / Liberty Utilities, Oct 26, 2021'),
   'press_release_acquirer': ('https://www.globenewswire.com/news-release/2021/10/26/2321226/0/en/Algonquin-Power-Utilities-Corp-Announces-Agreement-to-Acquire-Kentucky-Power-Company-and-Concurrent-Bought-Deal-Common-Equity-Financing.html', 'AQN news release Oct 26, 2021 (also attached to the material change report, 6-K ex-99.1). REPLACES a2021q3-ex991 = AQN Q3 financial statements (wrong document)'),
   'filing': (S + '1174169/000114036121035654/ny20001090x3_6k.htm', 'AQN 6-K 2021-10-27 (material change report + SPA)')},
 'nee_oncor_2016': {
   'deck': ('https://www.investor.nexteraenergy.com/~/media/Files/N/NEE-IR/news-and-events/events-and-presentations/2016/07292016/investor-presentation-final.pdf', 'NEE investor presentation July 29, 2016 "NextEra Energy Reaches Agreement to Acquire Oncor" ($9.5bn consideration, $18.4bn EV)'),
   'transcript': ('https://www.investor.nexteraenergy.com/~/media/Files/N/NEE-IR/news-and-events/events-and-presentations/2016/07292016/investor-call-script-final.pdf', 'NEE investor call script, July 29, 2016 (prepared remarks)'),
   'filing': (S + '753308/000075330816000404/form8k07292016.htm', 'NEE 8-K 2016-07-29 (ex-99 = announcement release)')},
 'gip_cpp_allete_2024': {
   'deck': (S + '66756/000006675624000055/a2024defa14acommunications.htm', 'ALLETE DEFA14A 2024-05-09: deal presentation + transcript given to the Minnesota PUC (May 9, 2024). No investor deck was filed - ALLETE held no deal call. FLAG: regulator deck, not an investor deck')},
 'greatplains_aquila_2007': {
   'deck': (S + '66960/000114306807000037/f425irweb.htm', 'GXP Rule 425 2007-02-07: "Two Strategic Transactions" slides (Chesser / Green / Emery)'),
   'transcript': (S + '66960/000114306807000050/f425transc.htm', 'GXP Rule 425 2007-02-08: investor web conference transcript')},
 'duke_cinergy_2005': {
   'deck': (S + '30371/000095017205001470/ny996384.htm', 'Duke Rule 425 2005-05-09: analyst-meeting slides (images)'),
   'transcript': (S + '30371/000095017205001471/ny996383.htm', 'Duke Rule 425 2005-05-09: analyst meeting script, slide by slide'),
   'press_release_acquirer': (S + '30371/000095017205001467/ny591593.txt', 'Duke 8-K 2005-05-09 ex-99.1: joint announcement "Cinergy & Duke agree to merge". REPLACES dex991 of 000119312506072085 = April 3, 2006 merger-completion release')},
 'exelon_pseg_2004': {
   'press_release_acquirer': (S + '1109357/000095013704011198/c90619exv99w1.htm', 'Exelon 8-K 2004-12-20 ex-99.1: joint announcement release'),
   'press_release_target': (S + '81033/000095011704004537/ex99-1.htm', 'PSEG 8-K 2004-12-21 ex-99.1: same joint release as filed by PSEG'),
   'deck': (S + '788784/000095013704011202/c90622e425.htm', 'Exelon Rule 425 2004-12-20: investor webcast slides (40 images)')},
 'altagas_wgl_2017': {
   'press_release_acquirer': (S + '1103601/000119312517018363/d336997ddfan14a.htm', 'AltaGas DFAN14A 2017-01-26: AltaGas announcement release'),
   'press_release_target': (S + '1103601/000119312517018218/d316578dex991.htm', 'WGL 8-K 2017-01-25 ex-99.1: WGL announcement release'),
   'deck': (S + '1103601/000119312517018368/d323222ddfan14a.htm', 'AltaGas DFAN14A 2017-01-26: investor presentation'),
   'transcript': (S + '1103601/000119312517021769/d330248ddfan14a.htm', 'AltaGas DFAN14A 2017-01-27: announcement conference call transcript'),
   'agreement': (S + '1103601/000119312517020186/d319734dex21.htm', 'WGL 8-K 2017-01-27 ex-2.1: Agreement and Plan of Merger (AltaGas / Wrangler / WGL)'),
   'filing': (S + '1103601/000119312517020186/d319734d8k.htm', 'WGL 8-K 2017-01-27 (merger agreement)')},
 'southern_agl_2015': {
   'press_release_acquirer': (S + '92122/000009212215000071/falconsk1x1.htm', 'Southern 8-K 2015-08-24 ex-99.1: "Southern Company to Acquire AGL Resources in $12 Billion Transaction"')},
 'blackhills_sourcegas_2015': {
   'press_release_acquirer': (S + '1130464/000113046415000133/ex991pressrelease.htm', 'BKH 8-K 2015-07-14 ex-99.1 (the existing generic link - it is the acquirer\'s release)')},
 'emera_teco_2015': {
   'press_release_target': (S + '350563/000119312515313189/d28513ddefa14a.htm', 'TECO DEFA14A 2015-09-04: TECO-filed announcement release "Emera to Acquire TECO Energy"'),
   'transcript': (S + '350563/000119312515314640/d70339ddefa14a.htm', 'TECO DEFA14A 2015-09-08: webcast / investor call transcript (Sept 8, 2015)')},
 'bbi_northwestern_2006': {
   'press_release_target': (S + '73088/000110465906027919/a06-10528_1ex99d1.htm', 'NWE 8-K 2006-04-26 ex-99.1 (the existing generic link - it is the target\'s release)'),
   'transcript': (S + '73088/000110465906027978/a06-10528_4defa14a.htm', 'NWE DEFA14A 2006-04-26: conference call transcript')},
 'coned_nu_1999': {
   'press_release_target': (S + '72741/0000072741-99-000180.txt', 'NU 8-K 1999-10-19, EX-99 "Press release regarding merger" (1999 filing: only the full submission text exists; the release is the EX-99 document inside)')},
 'fortis_chenergy_2012': {
   'press_release_target': (S + '1061393/000089882212000077/chenergygrouprelease.htm', 'CH Energy 8-K/DEFA14A 2012-02-21 ex-99.1 news release'),
   'press_release_acquirer': ('https://www.globenewswire.com/news-release/2012/02/21/1469976/0/en/Fortis-Inc-to-Acquire-CH-Energy-Group-Inc-for-US-1-5-Billion.html', 'Fortis news release Feb 21, 2012')},
 'firstenergy_gpu_2000': {
   'press_release': (S + '1031296/000103129600000036/0001031296-00-000036-0002.txt', 'FE 8-K 2000-08-10 ex-99.1: joint FE/GPU announcement release'),
   'transcript': (S + '1031296/000103129600000038/0001031296-00-000038-0001.txt', 'FE Rule 425 2000-08-10: Aug 9, 2000 analyst meeting & teleconference transcript')},
 'nsp_newcentury_1999': {
   'press_release': (S + '72903/0000898822-99-000169.txt', 'NSP 8-K 1999-03-25, EX-99.1 "Joint news release" (1999: full submission text only)')},
}
# needs_find items resolved without a new link: the existing link is right, or the gap is structural
RESOLVED = {
 'brookfield_dukefl_2025': {'deck': 'existing deck = Duke 8-K 2025-08-05 ex-99.2 (tm2522347d1_ex99-2)'},
 'spire_piedmont_tn_2025': {'deck': 'existing deck = Spire 8-K ex-99.2 (d936634dex992)'},
 'dominion_questar_2016': {'deck': 'existing deck = Dominion 8-K 2016-02-01 ex-99.3 (d131314dex993)'},
 'emera_teco_2015': {'press_release': 'generic left empty by design (side-specific acquirer + target releases set)'},
 'awk_nexus_2025': {'press_release': 'target Nexus Water Group is private - no target release; acquirer release covers it'},
 'coned_nu_1999': {'press_release': 'generic left empty by design (acquirer + target releases set)'},
 'macquarie_duquesne_2006': {'press_release': 'existing link = Duquesne 8-K 2006-07-06 EX-99 "Press release" - the announcement'},
 'midamerican_pacificorp_2005': {'agreement': 'existing link = MEHC 8-K 2005-05-24 EX-99.1 "Stock Purchase Agreement" - correct'},
}
NOT_FOUND = {
 'blackhills_sourcegas_2015': {'deck': 'no slides in the 8-K; the IR PDF (blackhillscorp.com/.../acquisition-of-sourcegas.pdf) now redirects to the IR home page',
                               'transcript': 'cash deal - no 425/DEFA14A transcript on EDGAR; only paywalled transcript services'},
 'fortis_chenergy_2012': {'deck': 'Fortis (not an SEC filer in 2012) - deck not on EDGAR or fortisinc.com archive'},
 'macquarie_duquesne_2006': {'deck': 'no deal slides filed (8-K has agreement + release only); buyer consortium not an SEC filer'},
 'firstenergy_gpu_2000': {'deck': '2000 Rule 425 filings are text only - slides not filed; analyst-meeting transcript added instead'},
 'nsp_newcentury_1999': {'deck': 'pre-2000 (before Rule 425) - no slides on EDGAR; joint news release added'},
}
# field set -> the generic 'press_release' is now a duplicate of a side-specific link: clear it (FE rule, 2026-09-25)
DEDUP_GENERIC = {'blackhills_sourcegas_2015', 'bbi_northwestern_2006'}
# generic press_release that is the wrong document
WRONG_GENERIC = {'exelon_pseg_2004': 'c90624exv99w1 = Operating Services Contract (EX-99.1 of the merger-agreement 8-K), not a release'}


def main():
    a = sys.argv[1:]
    p = a[a.index('--precedents') + 1] if '--precedents' in a else os.path.join(BASE, 'data', 'precedents.json')
    doc = json.load(open(p, encoding='utf-8'))
    bak = p + '.bak-prefound-20260925'
    if not os.path.exists(bak): shutil.copy(p, bak)
    D = {d['id']: d for d in doc['deals']}
    log = []
    for did, fields in FOUND.items():
        L = D[did]['links']
        for f, (url, why) in fields.items():
            old = L.get(f)
            L[f] = url
            L.setdefault('_link_confidence', {})[f] = 'strong'
            (L.get('_link_verify') or {}).pop(f, None)
            L[f'_{f}_src'] = f'found {TODAY}: {why}' + (f' (was {old})' if old and old != url else '')
            log.append(f'set      {did:32} {f:24} {url}')
    for did, fields in RESOLVED.items():
        L = D[did]['links']
        for f, why in fields.items():
            L.setdefault('_needs_find_resolved', {})[f] = f'{TODAY}: {why}'
            log.append(f'resolved {did:32} {f:24} {why}')
    for did, why in WRONG_GENERIC.items():
        L = D[did]['links']; old = L.get('press_release'); L['press_release'] = None
        (L.get('_link_confidence') or {}).pop('press_release', None)
        L['_press_release_removed'] = f'{TODAY}: {why} ({old})'; log.append(f'removed  {did:32} press_release (wrong document)')
    for did in DEDUP_GENERIC:
        L = D[did]['links']; old = L.get('press_release'); L['press_release'] = None
        (L.get('_link_confidence') or {}).pop('press_release', None)
        L['_press_release_removed'] = f'{TODAY}: duplicate of the side-specific release ({old})'
    for did, fields in NOT_FOUND.items():
        L = D[did]['links']
        for f, why in fields.items():
            L.setdefault('_not_found', {})[f] = f'{TODAY}: {why}'
            log.append(f'NOTFOUND {did:32} {f:24} {why}')
    # shrink _needs_find to what is still open
    for d in D.values():
        L = d.get('links') or {}
        if not L.get('_needs_find'): continue
        L['_needs_find'] = [f for f in L['_needs_find'] if not L.get(f) and f not in (L.get('_needs_find_resolved') or {})]
        if not L['_needs_find']: L.pop('_needs_find')
    doc.setdefault('_review_log', []).append({'date': TODAY, 'what': 'apply_found_docs.py: needs_find documents located', 'lines': log})
    json.dump(doc, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print('\n'.join(log))
    still = {d['id']: d['links']['_needs_find'] for d in D.values() if (d.get('links') or {}).get('_needs_find')}
    print(f'\nstill open: {sum(len(v) for v in still.values())} across {len(still)} deals')
    for k, v in still.items(): print(f'  {k:32} {", ".join(v)}')


if __name__ == '__main__':
    main()
