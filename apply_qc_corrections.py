r"""
apply_qc_corrections.py — precedents.json

Fareen's human-QC findings, applied as ground truth and marked so no resolver
overwrites them.

GLOBAL RULE (Fareen, 2026-07-22): links must point at SEC.gov, never bamsec.
bamsec is a paywalled wrapper; the underlying document is public on EDGAR. Every
correction below is recorded as (cik, accession, document-number) and resolved to
the real sec.gov document URL at run time -- falling back to the accession folder
(always valid, never a dead link) if the network is unavailable.

Idempotent.  Use --no-net to skip document resolution and store folder urls.
"""

import json, io, os, sys, shutil, datetime, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    'ra', os.path.join(HERE, 'resolve_agreements.py'))
ra = importlib.util.module_from_spec(_spec)
_argv = sys.argv; sys.argv = ['qc']
_spec.loader.exec_module(ra)
sys.argv = _argv

SRC = ra.SRC

# --file must be honoured by THIS script: the ra import masks sys.argv so the
# shared locator never sees it, which silently wrote to the default file.
def _src_override(default):
    import sys, os
    for i, a in enumerate(sys.argv):
        if a == '--file' and i + 1 < len(sys.argv):
            p = os.path.abspath(sys.argv[i + 1])
            if not os.path.isfile(p):
                raise SystemExit('--file not found: %s' % p)
            return p
    return default


SRC = _src_override(SRC)



def sec(cik, accession, doc=None, fetch=True):
    """(cik, accession, doc#) -> exact sec.gov document url, else the folder.

    Accession numbers are 18 digits (10-digit filer + 2-digit year + 6-digit
    sequence); bamsec drops leading zeros, so zero-pad before building.
    """
    acc = str(accession).zfill(18)
    folder = 'https://www.sec.gov/Archives/edgar/data/%d/%s/' % (int(cik), acc)
    if not doc or not fetch:
        return folder
    try:
        html = ra.get(ra.accession_index(folder))
        docs = ra.parse_index(html, folder) if html else []
        if 0 < doc <= len(docs):
            return docs[doc - 1]['url']
    except Exception:
        pass
    return folder


# Each value: a literal url, a (cik, accession, doc) tuple resolved at run time,
# or None meaning "this link was found WRONG — clear it and flag for a find".
CORRECTIONS = {
    'nee_dominion_2026': {
        'agreement': (715957, 119312526227930, 2),
        'deck':      (715957, 119312526227930, 4),
        '_agreement_note': 'Agreement of Merger — separate 8-K accession, doc 2. '
                           'Resolver had the d107428d425 Form 425.',
        '_deck_note': 'Deck is doc 4 of the SAME accession as the agreement — the '
                      'earlier pass took one document and discarded the rest.',
    },
    'blackhills_northwestern_2025': {
        'agreement': (1130464, 110465925080276, 2),
        '_agreement_note': 'EX-2.1, doc 2 of accession 0001104659-25-080276.',
        '_pr_note': 'target and acquirer links are two hostings of ONE joint '
                    'release, not two separately-framed releases.',
    },
    'gip_eqt_aes_2026': {
        'press_release_acquirer':
            'https://www.global-infra.com/news/consortium-led-by-global-infrastructure-partners-and-eqt-agrees-to-acquire-aes/',
        '_pr_acquirer_note': 'Correct GIP release (GIP AND EQT); resolver had a '
                             'superseded slug on the same domain.',
    },
    'gip_cpp_allete_2024': {
        'press_release_acquirer':
            'https://www.cppinvestments.com/newsroom/allete-enters-agreement-to-be-acquired-by-a-partnership-led-by-canada-pension-plan-investment-board-and-global-infrastructure-partners-to-advance-sustainability-in-action-strategy/',
        'agreement': (66756, 6675624000034, 2),
        'deck': None,
        '_pr_acquirer_note': 'Correct CPP Investments release; resolver had a '
                             'superseded slug.',
        '_deck_note': 'CLEARED — linked EX-99 was "ALLETE Board declares stub period '
                      'dividend", not a deal deck. No deck identified.',
    },
    'centerpoint_vectren_2018': {
        'deck': (1096385, 119312518125839, 4),
        '_deck_note': 'Investor deck, doc 4.',
        '_pr_acquirer_note': None,     # Fareen: acquirer PR is correct, drop caveat
    },
    'dominion_scana_2018': {
        'press_release':
            'https://www.prnewswire.com/news-releases/dominion-energy-scana-announce-all-stock-merger-with-1000-immediate-cash-payment-to-average-south-carolina-electric--gas-residential-electric-customer-after-closing-300576938.html',
        'press_release_filed': (754737, 75473718000003, None),
        'deck':       (754737, 75473718000003, 6),
        'transcript': (754737, 75473718000003, 9),
        '_pr_note': 'previous press_release url was a 404. PRNewswire release is the '
                    'live one; the SEC-filed copy, deck (doc 6) and conference-call '
                    'transcript (doc 9) are all in accession 0000754737-18-000003.',
    },
    'emera_teco_2015': {
        'deck': (350563, 119312515314517, 3),
        '_deck_note': 'Investor deck, doc 3.',
    },
    # FLAGGED, not fixed — resolver matched the PRESS RELEASE on an agreement-like
    # description. The real SPA (MidAmerican/ScottishPower/PHI, 2005-05-23) is a
    # separate exhibit still to be located.
    'midamerican_pacificorp_2005': {
        'agreement': None,
        '_agreement_qc': 'RESOLVER MISLINK: matched exh99_2.htm on "STOCK PURCHASE '
                         'AGREEMENT" in its description, but that exhibit is the PRESS '
                         'RELEASE. Real doc = Stock Purchase Agreement dated 2005-05-23. '
                         'ScottishPower filed as a foreign issuer (6-K), so look under '
                         'MidAmerican CIK 1081316.',
    },
}


def main():
    offline = '--no-net' in sys.argv
    db = json.load(open(SRC, encoding='utf-8'))
    D = {d['id']: d for d in db['deals']}

    applied = cleared = 0
    for did, fields in CORRECTIONS.items():
        d = D.get(did)
        if not d:
            print('  !! deal not found: %s' % did)
            continue
        L = d.setdefault('links', {})
        ver = L.setdefault('_verified', {})
        done = []
        for k, v in fields.items():
            if isinstance(v, tuple):
                v = sec(v[0], v[1], v[2], fetch=not offline)
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
                if k not in nf:
                    nf.append(k)
                cleared += 1
                done.append(k + ' (cleared)')
            else:
                L[k] = v
                ver[k] = 'human'
                applied += 1
                done.append(k)
        print('  %-32s %s' % (did, ', '.join(done)))

    db.setdefault('_merge_meta', {})['qc_corrections_2026_07_22'] = {
        'applied': datetime.date.today().isoformat(),
        'rule': 'SEC links only — never bamsec. Human-verified fields carry '
                'links._verified[field]="human" and are immune to re-resolution. '
                'Fields found wrong are cleared into links._needs_find, never left '
                'pointing at a known-bad document.',
    }

    shutil.copyfile(SRC, SRC + '.bak_qc')
    with io.open(SRC, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
        f.write('\n')
    print('\n%d links verified · %d cleared as wrong' % (applied, cleared))
    print('backup: %s.bak_qc' % os.path.basename(SRC))


if __name__ == '__main__':
    main()