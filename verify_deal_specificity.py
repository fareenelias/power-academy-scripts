r"""
verify_deal_specificity.py — precedents.json  (local; needs sec.gov reachable)

THE CHECK THAT SHOULD HAVE EXISTED FROM THE START.

Every filter built so far removes obvious junk -- XBRL files, dividend notices,
page footers. Not one of them asks the question that actually matters:

    does this document belong to THIS transaction?

That gap produced every error in Fareen's QC of deals through 2023:
  * awk_nexus_2025 held the AWK/ESSENTIAL deck. Right filer, wrong deal. Nothing
    in the pipeline compared the document to the deal.
  * five deals held the CLOSING press release where the ANNOUNCEMENT belongs.
    A closing 8-K names the counterparty and passes every gate ever written.

This fetches each linked document and tests it against the deal:

  NAMES      does it name BOTH counterparties? (one name proves nothing --
             a dividend 8-K filed by ALLETE says "ALLETE")
  STAGE      does it read as an ANNOUNCEMENT ("have entered into", "announced
             today", "agreement to acquire") or as a CLOSING ("completed",
             "closed", "consummated", "has acquired")?
  DATE       does a date in the document sit near the announcement?

Findings are RECORDED, not auto-applied -- a link that fails NAMES is almost
certainly wrong, but a STAGE mismatch may be legitimate (some deals only ever
issued one release). Fareen decides; this makes the evidence visible.

  python verify_deal_specificity.py --dry-run
  python verify_deal_specificity.py            # writes _link_verify per link
  python verify_deal_specificity.py --only <deal_id>
"""

import json, io, os, re, sys, shutil, argparse, datetime, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    'sc', os.path.join(HERE, 'scrub_links.py'))
sc = importlib.util.module_from_spec(_spec)
_argv = sys.argv; sys.argv = ['verify']
_spec.loader.exec_module(sc)
sys.argv = _argv

SRC = sc.SRC
for i, _a in enumerate(sys.argv):
    if _a == '--file' and i + 1 < len(sys.argv):
        SRC = os.path.abspath(sys.argv[i + 1])

GENERIC = {'energy', 'power', 'utilities', 'utility', 'company', 'companies',
           'group', 'holdings', 'holding', 'corp', 'corporation', 'inc', 'llc',
           'ltd', 'natural', 'gas', 'electric', 'water', 'resources', 'partners',
           'capital', 'infrastructure', 'american', 'national', 'services',
           'service', 'systems', 'the', 'and', 'new', 'first'}

ANNOUNCE = re.compile(
    r'(have\s+entered\s+into|has\s+entered\s+into|announced\s+today|'
    r'agreement\s+to\s+acquire|agreed\s+to\s+acquire|definitive\s+agreement|'
    r'to\s+be\s+acquired|announce[sd]?\s+(a\s+)?(definitive|merger|agreement))', re.I)
# PAST-TENSE COMPLETION ONLY. The first version matched "consummat" and "closing
# of the merger" -- both are ordinary contract language that appears throughout
# every merger agreement, describing a FUTURE closing. That produced ~40 false
# flags on agreement links alone.
CLOSING = re.compile(
    r'(ha[sve]+\s+completed\s+(its\s+|the\s+)?(acquisition|merger|sale|purchase)|'
    r'completed\s+(its|the)\s+(previously\s+announced\s+)?(acquisition|merger|sale)|'
    r'transaction\s+ha[sve]+\s+(closed|been\s+completed)|'
    r'successfully\s+(closed|completed)|announce[sd]?\s+the\s+completion|'
    r'completion\s+of\s+(its|the)\s+(previously\s+announced\s+)?(acquisition|merger))', re.I)
# a legal contract is NEITHER an announcement nor a closing notice -- it is the
# instrument. Stage-testing it is a category error.
STAGE_EXEMPT = {'agreement', 'agreement_2', 'agreement_3'}

CHECK_FIELDS = ('agreement', 'deck', 'press_release', 'press_release_joint',
                'press_release_target', 'press_release_acquirer', 'transcript')


def tokens(deal, side):
    out = set()
    for w in re.split(r'[^A-Za-z]+', str(deal.get(side) or '')):
        w = w.lower()
        if len(w) >= 4 and w not in GENERIC:
            out.add(w)
    return out


def verify(url, deal, field=''):
    html = sc.ra.get(url, timeout=45)
    if not html:
        return None, 'fetch failed'
    text = re.sub(r'\s+', ' ', sc.ra.TAG.sub(' ', html))[:120000]
    low = text.lower()

    tgt, acq = tokens(deal, 'target'), tokens(deal, 'acquirer')
    hit_t = sorted(t for t in tgt if t in low)
    hit_a = sorted(t for t in acq if t in low)

    flags, notes = [], []
    if tgt and acq:
        if not hit_t and not hit_a:
            flags.append('NAMES-NONE')
            notes.append('names neither party')
        elif not hit_t or not hit_a:
            side = 'acquirer' if not hit_t else 'target'
            got = hit_a if not hit_t else hit_t
            # A merger AGREEMENT routinely names an acquisition vehicle or merger
            # sub rather than the sponsor -- Macquarie/BCIMC will not appear in the
            # Cleco contract, "Como 1 Inc." will. Missing one name there is normal.
            # In a PRESS RELEASE it is not: a release about a deal names both sides.
            if field in STAGE_EXEMPT:
                notes.append('names %s only (%s) — normal for a contract '
                             '(acquisition vehicle)' % (side, ','.join(got[:2])))
            else:
                flags.append('NAMES-ONE')
                notes.append('names %s only (%s)' % (side, ','.join(got[:2])))
        else:
            notes.append('names both (%s / %s)' % (hit_t[0], hit_a[0]))

    if field not in STAGE_EXEMPT:
        a_hit = ANNOUNCE.search(text[:40000])
        c_hit = CLOSING.search(text[:40000])
        if c_hit and not a_hit:
            flags.append('CLOSING-DOC')
            notes.append('reads as a CLOSING document ("%s")' % c_hit.group(0)[:40])
        elif a_hit:
            notes.append('reads as an announcement')

    return (not flags), '; '.join(notes) or 'no signal'


def flag_kind(why):
    """Coarse class for the dashboard marker."""
    w = (why or '').lower()
    if 'names neither' in w:
        return 'wrong-deal'
    if 'closing document' in w:
        return 'closing-doc'
    if 'names' in w and ' only' in w:
        return 'one-party'
    return 'other'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--only')
    ap.add_argument('--file')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()

    db = json.load(open(SRC, encoding='utf-8'))
    deals = [d for d in db['deals'] if not a.only or d['id'] == a.only]

    ok = bad = unreach = 0
    problems = []
    for i, d in enumerate(deals, 1):
        L = d.setdefault('links', {})
        ver = L.get('_verified') or {}
        if not a.quiet:
            sys.stdout.write('\r  [%3d/%3d] %-34s   ' % (i, len(deals), d['id'][:34]))
            sys.stdout.flush()
        res = {}
        for f in CHECK_FIELDS:
            u = L.get(f)
            if not isinstance(u, str) or ver.get(f) == 'human':
                continue
            good, why = verify(u, d, f)
            if good is None:
                unreach += 1
                continue
            res[f] = {'ok': bool(good), 'why': why}
            if good:
                ok += 1
            else:
                bad += 1
                sys.stdout.write('\r' + ' ' * 70 + '\r')
                print('  FLAG  %-30s %-22s %s' % (d['id'], f, why[:52]))
                problems.append((d['id'], f, why, u))
        if res and not a.dry_run:
            L['_link_verify'] = res

    if not a.dry_run:
        shutil.copyfile(SRC, SRC + '.bak_verify')
        with io.open(SRC, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
            f.write('\n')

    sys.stdout.write('\r' + ' ' * 70 + '\r')
    print('\n' + '=' * 62)
    print('  links checked   %d' % (ok + bad))
    print('  consistent      %d' % ok)
    print('  FLAGGED         %d   <- wrong deal, or a closing doc in an' % bad)
    print('                        announcement slot')
    print('  unreachable     %d' % unreach)
    if problems:
        dst = os.path.join(os.path.dirname(SRC), 'link_verify.md')
        with io.open(dst, 'w', encoding='utf-8') as f:
            f.write('# Link specificity — %d flagged\n\n'
                    'Each link below was fetched and compared against its deal. A link '
                    'that names neither party is almost certainly the wrong document; a '
                    'closing document in an announcement slot may be legitimate if the '
                    'deal only ever issued one release.\n\n' % len(problems))
            for did, fld, why, u in sorted(problems):
                f.write('- [ ] **%s** · `%s` — %s  \n      %s\n' % (did, fld, why, u))
        print('  wrote %s' % dst)
    print('DRY RUN — nothing written' if a.dry_run else 'written (backup .bak_verify)')


if __name__ == '__main__':
    main()