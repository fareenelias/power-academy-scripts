# -*- coding: utf-8 -*-
r"""apply_local_docs.py - link deal documents FE saved locally (served by Caddy :8080 from E:\PowerAcademy\documents)
into data\precedents.json. Backup: precedents.json.bak-prelocal-20260925.

  python E:\PowerAcademy\scripts\apply_local_docs.py

Links are absolute Caddy URLs (http://100.86.108.51:8080/<path under documents>), so they open from the dashboard
(a relative 'transcripts/...' path would resolve against :3000 and 404). Licensed transcripts (S&P Capital IQ)
stay on this machine - only the local URL is stored. Each file is checked to exist before it is linked.
"""
import os, sys, json, shutil
from urllib.parse import quote

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(BASE, 'documents')
CADDY = 'http://100.86.108.51:8080/'
TODAY = '2026-09-25'
U = 'transcripts/Undated/'

# deal -> {field: (path under documents, provenance, page or None)}
LOCAL = {
 'blackhills_sourcegas_2015': {
   'deck': ('special_presentations/Black Hills Corporation_MP_2015-07-13_English.pdf',
            'BKH "Acquisition of SourceGas" presentation, July 13, 2015 (21 pp; saved by FE)', None),
   'transcript': (U + 'Black Hills Gas Holdings LLC_MA Call_2015-07-13_English.pdf',
                  'BKH M&A call transcript, July 13, 2015 (S&P Capital IQ; saved by FE)', None)},
 # M&A-call transcripts already in the library but not linked to their deals
 'algonquin_kentuckypower_2021': {
   'transcript': (U + 'Algonquin_Power_And_Utilities_Corp.,_Kentucky_Power_Company,_Aep_Kentucky_Transmission_Company,_Inc.,_American_Electric_Power_Company,_Inc._-_MAndA_Call.pdf',
                  'AQN M&A call transcript (S&P Capital IQ, library)', None)},
 'enbridge_dominion_gas_2023': {
   'transcript': (U + 'Dominion_Energy,_Inc.,_Enbridge_Inc.,_The_East_Ohio_Gas_Company_-_MAndA_Call.pdf',
                  'Dominion/Enbridge M&A call transcript (S&P Capital IQ, library)', None)},
 'awk_essential_2025': {
   'transcript': (U + 'American_Water_Works_Company,_Inc.,_Essential_Utilities,_Inc._-_MAndA_Call.pdf',
                  'AWK/Essential M&A call transcript (S&P Capital IQ, library)', None)},
 'h2o_quadvest_2025': {
   'transcript': (U + 'H2O_America,_Texas_Water_Operation_Services_LLC,_Texas_Water_Supply_Company,_LLC,_Quadvest,_L.P._-_MAndA_Call.pdf',
                  'H2O America/Quadvest M&A call transcript (S&P Capital IQ, library)', None)},
 'ppl_narragansett_2021': {
   'transcript': (U + 'PPL_Corporation,_National_Grid_plc_-_MAndA_Call.pdf',
                  'PPL/National Grid (Narragansett) M&A call transcript (S&P Capital IQ, library)', None)},
 # broken relative path 'transcripts/Special Call/...' (no such folder) -> the file in Undated
 'nee_dominion_2026': {
   'transcript': (U + 'Dominion_Energy,_Inc.,_NextEra_Energy,_Inc._-_MAndA_Call.pdf',
                  'Dominion/NextEra M&A call transcript (S&P Capital IQ, library) - path fixed', None)},
}
# figures printed in FE's BKH deck (p.5) - stated multiple added; debt difference flagged, not changed
BKH_DECK = CADDY + quote(LOCAL['blackhills_sourcegas_2015']['deck'][0])


def url(path, page=None):
    return CADDY + quote(path) + (f'#page={page}' if page else '')


def main():
    a = sys.argv[1:]
    p = a[a.index('--precedents') + 1] if '--precedents' in a else os.path.join(BASE, 'data', 'precedents.json')
    doc = json.load(open(p, encoding='utf-8'))
    bak = p + '.bak-prelocal-20260925'
    if not os.path.exists(bak): shutil.copy(p, bak)
    D = {d['id']: d for d in doc['deals']}
    log = []
    for did, fields in LOCAL.items():
        d = D.get(did)
        if not d: log.append(f'?? no deal {did}'); continue
        L = d.setdefault('links', {})
        for f, (path, why, page) in fields.items():
            if not os.path.exists(os.path.join(DOCS, *path.split('/'))):
                log.append(f'MISSING  {did:30} {f:11} {path}'); continue
            old = L.get(f); L[f] = url(path, page)
            L.setdefault('_link_confidence', {})[f] = 'verified' if did == 'blackhills_sourcegas_2015' else 'strong'
            if did == 'blackhills_sourcegas_2015': L.setdefault('_verified', {})[f] = 'human'
            L[f'_{f}_src'] = f'local {TODAY}: {why}' + (f' (was {old})' if old and old != L[f] else '')
            (L.get('_not_found') or {}).pop(f, None)
            if L.get('_needs_find'): L['_needs_find'] = [x for x in L['_needs_find'] if x != f]
            if L.get('_needs_find') == []: L.pop('_needs_find')
            if L.get('_not_found') == {}: L.pop('_not_found')
            log.append(f'set      {did:30} {f:11} {L[f]}')
    b = D['blackhills_sourcegas_2015']
    b.setdefault('multiples_stated', {})['ev_rb'] = 1.9
    b['_multiples_stated_src'] = {'ev_rb': {'basis': '$1.74bn effective price (after ~$150M tax benefits) / ~$900M projected rate base at closing',
                                            'source': BKH_DECK + '#page=5'}}
    b['_deck_check'] = (f'{TODAY}: BKH deck p.5 - $1.89bn total consideration incl. ~$200M capex reimbursement and '
                        f'$720M projected debt assumed at closing (file raw.net_debt_usd_b = 0.76); 1.9x stated on effective price, '
                        f'file rate_base_mult 2.1 = $1.89bn / $900M')
    log.append('stated   blackhills_sourcegas_2015 rate_base_mult 1.9x (deck p.5); debt $720M (deck) vs $760M (file) flagged')
    doc.setdefault('_review_log', []).append({'date': TODAY, 'what': 'apply_local_docs.py: FE-saved deck/transcript + library M&A-call transcripts linked', 'lines': log})
    json.dump(doc, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print('\n'.join(log))


if __name__ == '__main__':
    main()
