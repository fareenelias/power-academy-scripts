r"""
apply_qc_batch2.py — precedents.json

Fareen's QC of every deal through 2023. Applied as ground truth, SEC-resolved.

The error pattern she surfaced is NOT "the script failed to find a document" --
it is "the script found A document and never checked it was THE document":

  * 5 deals had the CLOSING press release where the ANNOUNCEMENT release belongs
  * awk_nexus_2025 carried the AWK/ESSENTIAL deck -- right filer, wrong deal
  * oregontrail_idacorp got a Q4 earnings deck, not a transaction deck
  * agreements sat unfound because the search used one party's CIK

Every correction below is (cik, accession, doc#) resolved to a real sec.gov URL
at run time -- Fareen supplied bamsec urls, which are a paywalled wrapper; the
underlying document is public on EDGAR and that is what gets stored.

  python apply_qc_batch2.py --dry-run
  python apply_qc_batch2.py
  python apply_qc_batch2.py --no-net     # store accession folders, skip doc lookup
"""

import json, io, os, sys, shutil, datetime, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    'ra', os.path.join(HERE, 'resolve_agreements.py'))
ra = importlib.util.module_from_spec(_spec)
_argv = sys.argv; sys.argv = ['qc2']
_spec.loader.exec_module(ra)
sys.argv = _argv

SRC = ra.SRC
for i, _a in enumerate(sys.argv):
    if _a == '--file' and i + 1 < len(sys.argv):
        SRC = os.path.abspath(sys.argv[i + 1])

DRY = '--dry-run' in sys.argv
OFFLINE = '--no-net' in sys.argv


def sec(cik, accession, doc=None):
    """(cik, accession, doc#) -> sec.gov document url; falls back to the folder."""
    acc = str(accession).zfill(18)
    folder = 'https://www.sec.gov/Archives/edgar/data/%d/%s/' % (int(cik), acc)
    if not doc or OFFLINE:
        return folder
    try:
        html = ra.get(ra.accession_index(folder))
        docs = ra.parse_index(html, folder) if html else []
        if 0 < doc <= len(docs):
            return docs[doc - 1]['url']
    except Exception:
        pass
    return folder


# ---------------------------------------------------------------- corrections
# None  => the link was found WRONG: clear it and queue a fresh find
# tuple => (cik, accession, doc) resolved to SEC
C = {
    'delta_spire_mississippi_2026': {
        'agreement': (1126956, 119312526168301, 2),
    },
    'gip_eqt_aes_2026': {
        'agreement': (874761, 119312526084157, 2),
        'deck':      (874761, 119312526084157, 4),
    },
    'oregontrail_idacorp_or_2026': {
        'deck': None,
        '_deck_note': 'CLEARED — the linked deck was the Q4 earnings call deck, not a '
                      'transaction deck. No announcement deck appears to exist.',
    },
    'nfg_centerpoint_ohio_2025': {
        'agreement':            (1130310, 119312525245197, 2),
        'press_release_target': (1130310, 119312525245197, 3),
        'deck':                 (1130310, 119312525245197, 4),
    },
    'h2o_southcentral_2025': {
        'press_release_acquirer': (766829, 110465925066289, 4),
        '_advisor_note': 'acquirer release names J.P. Morgan as buy-side advisor.',
        '_dup_note': 'SAME TRANSACTION as h2o_quadvest_2025 — one of the two rows is '
                     'a duplicate and should be removed after confirming which id to keep.',
    },
    'h2o_quadvest_2025': {
        '_dup_note': 'SAME TRANSACTION as h2o_southcentral_2025 — duplicate row.',
    },
    'blackhills_northwestern_2025': {
        '_pr_note': 'target and acquirer releases are verbatim identical — ONE joint '
                    'release; collapse to press_release_joint.',
    },
    'brookfield_dukefl_2025': {
        'deck':      (1326160, 110465925073897, 3),
        'agreement': (1326160, 110465926022610, 2),
        '_agreement_note': 'final agreement filed 2026 (a later accession than the '
                           'announcement) — the 6-month search window missed it.',
    },
    'spire_piedmont_tn_2025': {
        'press_release_acquirer': (1126956, 119312525167129, 2),
        'deck':                   (1126956, 119312525167129, 3),
        'deck_seller':            (1326160, 110465925071391, 3),
        '_advisor_note': 'BMO is acquirer-side advisor.',
        '_deck_note': 'two decks: acquirer (Spire) and seller (Duke).',
    },
    'awk_nexus_2025': {
        'deck': None,
        '_deck_note': 'CLEARED — the linked deck was the October 2025 AWK/Essential '
                      'deck, a DIFFERENT transaction by the same filer. No Nexus deck '
                      'identified. This is the deal-specificity failure: the harvest '
                      'verified the filer, never the deal.',
    },
    'unitil_aquarion_nh_2025': {
        'press_release_acquirer': (755001, 119312525117855, 3),
    },
    'unitil_maine_naturalgas_2025': {
        'press_release': (755001, 119312525073493, 3),
        '_pr_note': 'previous link was the CLOSING release; this is the announcement.',
    },
    'rwa_aquarion_2025': {
        'press_release': (72741, 110465925006447, 2),
        '_pr_note': 'previous link was the CLOSING release; this is the announcement.',
    },
    'kkr_psp_aep_transmission_2025': {
        'press_release': (4904, 490425000010, None),
        '_pr_note': 'previous link was the CLOSING release; this is the announcement. '
                    'CONFIRM deal id — Fareen referenced this as the AEP Ohio minority '
                    'stake.',
    },
    'unitil_bangor_naturalgas_2024': {
        'press_release': (755001, 119312524178604, 3),
        '_pr_note': 'previous link was the CLOSING release; this is the announcement.',
    },
    'gip_cpp_allete_2024': {
        'press_release_target': (66756, 6675624000034, 3),
        'deck': None,
        '_pr_note': 'previous target link was the CLOSING release; this is the '
                    'announcement.',
        '_deck_note': 'CLEARED — no deck exists for this transaction.',
    },
    'bernhard_centerpoint_lams_2024': {
        'agreement': (1130310, 119312524039277, 2),
        'deck': None,
        '_agreement_note': 'merger agreement; the previous link was the 8-K body.',
        '_deck_note': 'CLEARED — no deck exists for this transaction.',
    },
    'brookfield_fet_2024': {
        'agreement':     (1031296, 103129624000018, 2),
        'press_release': (1031296, 103129624000018, 3),
        '_close_note': 'ANNOUNCED Feb-2023, CLOSED Mar-2024 — confirm the announced '
                       'date in this row, which reads 2024-02-02 and looks like a '
                       'year transposition.',
        '_pr_note': 'this is the CLOSING release (Mar-2024); the Feb-2023 announcement '
                    'deck is on brookfield_fet_2021.',
    },
    'brookfield_fet_2021': {
        'deck': (1031296, 103129623000007, 3),
        '_deck_note': 'Feb-2023 announcement deck.',
    },
    'bernhard_entergy_lagas_2023': {
        'agreement': (65984, 6598423000087, 2),
    },
    'chesapeake_fcg_2023': {
        '_pr_target_flag': None,      # remove the stale caveat
    },
    'enbridge_dominion_gas_2023': {
        'agreement':   (715957, 119312523228542, 2),
        'agreement_2': (715957, 119312523228542, 3),
        'agreement_3': (715957, 119312523228542, 4),
        'press_release_acquirer':
            'https://www.enbridge.com/media-center/news/details?id=123779&lang=en',
        '_agreement_note': 'THREE separate agreements filed, one per LDC.',
    },
    'blackstone_nipsco_2023': {
        'agreement': (1111711, 119312523169531, 2),
        'press_release':
            'https://www.nisource.com/news/article/nisource-announces-agreement-to-sell-minority-equity-interest-in-nipsco-to-strengthen-financial-foundation-and-support-sustainable-long-term-growth-20230620',
        '_pr_note': 'previous nisource.com link was dead.',
    },
}


def main():
    db = json.load(open(SRC, encoding='utf-8'))
    D = {d['id']: d for d in db['deals']}
    setn = cleared = miss = 0

    for did, fields in C.items():
        d = D.get(did)
        if not d:
            print('  !! deal not found: %s' % did)
            miss += 1
            continue
        L = d.setdefault('links', {})
        ver = L.setdefault('_verified', {})
        done = []
        for k, v in fields.items():
            if isinstance(v, tuple):
                v = sec(*v)
            if k.startswith('_'):
                if v is None:
                    L.pop(k, None)
                else:
                    L[k] = v
                continue
            if v is None:
                L[k] = None
                ver.pop(k, None)
                nf = L.setdefault('_needs_find', [])
                if k not in nf and k != 'deck':
                    nf.append(k)
                cleared += 1
                done.append(k + ' (cleared)')
            else:
                L[k] = v
                ver[k] = 'human'
                setn += 1
                done.append(k)
        if done:
            print('  %-34s %s' % (did, ', '.join(done)))

    # joint release for Black Hills / NorthWestern
    bh = D.get('blackhills_northwestern_2025')
    if bh:
        L = bh['links']
        t, a = L.get('press_release_target'), L.get('press_release_acquirer')
        if t and a:
            L['press_release_joint'] = a if 'sec.gov' in str(a) else t
            L['_pr_alt_hosting'] = t if 'sec.gov' in str(a) else a
            L.pop('press_release_target', None)
            L.pop('press_release_acquirer', None)
            print('  %-34s collapsed to one joint release' % bh['id'])

    db.setdefault('_merge_meta', {})['qc_batch2_2026_07_22'] = {
        'applied': datetime.date.today().isoformat(),
        'scope': 'Fareen QC of all deals through 2023',
        'root_cause': 'links were found but never verified as belonging to THIS deal: '
                      'closing releases accepted in place of announcement releases, and '
                      'a deck from a different transaction by the same filer.',
    }

    if not DRY:
        shutil.copyfile(SRC, SRC + '.bak_qc2')
        with io.open(SRC, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
            f.write('\n')

    print('\n%d links set (SEC-resolved) · %d cleared as wrong · %d deals not found'
          % (setn, cleared, miss))
    print('DRY RUN — nothing written' if DRY else 'written (backup .bak_qc2)')
    print('\nSTILL NEEDS YOUR CONFIRMATION:')
    print('  - h2o_southcentral_2025 / h2o_quadvest_2025 are the SAME deal — which id to keep?')
    print('  - kkr_psp_aep_transmission_2025: is that the AEP Ohio minority stake you meant?')
    print('  - brookfield_fet_2024 announced date reads 2024-02-02; you indicate Feb-2023.')


if __name__ == '__main__':
    main()