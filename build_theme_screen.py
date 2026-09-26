r"""build_theme_screen.py - structured strategy/risk themes off every dated earnings-call transcript.

Extends build_theme_timeline.py (data centers only) to the themes the tracker kept marking
'Call Notes only'. For every coverage name x theme it records, from the transcripts in
corpus_manifest.json:

  first      - first dated call that mentions the theme (date, period, page, doc link)
  last       - most recent call that mentions it
  calls      - number of calls mentioning it / calls scanned for that name
  series     - per call: date, period, hit count, first page, url  (discrete facts only)
  recent_4q  - hits in the name's last 4 calls vs the 4 before (rising / fading / steady)
  terms      - which match terms fired, with counts (so a reader can judge the match)

Stored content is DISCRETE FACTS ONLY (dates, pages, counts, the matched term) - never
transcript prose, per the S&P no-reproduction rule used by earnings_calls.json and
theme_timeline.json. The page deep-link is the way to read the passage.

Boilerplate is excluded: the safe-harbour / forward-looking-statement paragraph and the
S&P cover pages (text before the first 'Presentation' header) are not scanned, so
'hedging' in a risk-factor list does not count.

    python scripts\build_theme_screen.py            (Windows default: E:\PowerAcademy\data)
    python scripts/build_theme_screen.py <data_dir>
"""
import sys, os, re, json, datetime, collections

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')

# theme id -> (label, tracker items it feeds, [(term label, regex)])
# Regexes are word-bounded and case-insensitive unless noted; each is written to avoid the
# obvious false friends noted beside it.
THEMES = {
 'supply_chain': ('Supply chain / labor constraints', ['I.C Supply chain / labor'], [
    ('supply chain', r'supply[\s-]chains?'),
    ('transformer / breaker lead times', r'(?:transformers?|breakers?|switchgear)\b[^.]{0,80}\blead[\s-]times?|\blead[\s-]times?\b[^.]{0,80}\b(?:transformers?|breakers?|switchgear)'),
    ('turbine slots / reservations', r'turbine\s+(?:slots?|reservations?)|gas\s+turbines?\b[^.]{0,60}\b(?:backlog|slots?|reserv)'),
    ('labor availability', r'labou?r\s+(?:shortage|availability|constraints?|market)|skilled\s+(?:labou?r|workforce|craft)'),
    ('tariffs', r'\btariffs?\b[^.]{0,60}\b(?:solar|panels?|steel|imports?|china|section\s+232|AD/?CVD)|\bAD/?CVD\b|section\s+232'),
 ]),
 'storm_hardening': ('Storm hardening / undergrounding / vegetation', ['I.F Storm hardening / veg mgmt'], [
    ('undergrounding', r'undergrounding|underground(?:ed)?\s+(?:lines?|miles|distribution)'),
    ('storm / grid hardening', r'(?:storm|grid|system)\s+hardening|hardening\s+(?:program|plan|investments?)'),
    ('vegetation management', r'vegetation\s+management'),
    ('wildfire mitigation', r'wildfire\s+mitigation|public\s+safety\s+power\s+shut|\bPSPS\b|fast[\s-]trip'),
    ('resilience plan', r'resilien(?:ce|cy)\s+(?:plan|program|investments?|filing)'),
 ]),
 'storm_recovery': ('Storm cost recovery', ['I.B Past storm recovery', 'I.D Storm cost applications'], [
    ('storm cost / restoration cost', r'storm\s+(?:costs?|restoration\s+costs?|recovery|reserve|deferr\w*)'),
    ('named hurricanes / winter storms', r'hurricane\s+[A-Z][a-z]+|winter\s+storm\s+[A-Z][a-z]+|\bderecho\b'),
 ]),
 'securitization': ('Securitization', ['I.D Expected future securitization'], [
    ('securitization', r'securiti[sz]\w+'),
 ]),
 'riders': ('Riders, trackers & formula rates', ['I.D Special riders', 'I.D Recovery mechanisms / trackers', 'II.C Inflationary rider mechanisms'], [
    ('rider', r'\briders?\b'),
    ('tracker / surcharge', r'\b(?:capital|infrastructure|investment)\s+(?:tracker|recovery\s+mechanism|surcharge)|\bDSIC\b|\btrackers?\b'),
    ('formula rate', r'formula\s+rates?|formula[\s-]based\s+rate'),
    ('multi-year rate plan / PBR', r'multi[\s-]year\s+rate\s+plans?|performance[\s-]based\s+(?:rate|regulation)|\bPBR\b'),
    ('decoupling', r'\bdecoupl\w+'),
 ]),
 'grid_mod': ('Grid modernization', ['I.D Grid modernization filings'], [
    ('grid modernization', r'grid\s+moderni[sz]\w+|grid\s+mod\b'),
    ('AMI / smart meters', r'\bAMI\b|smart\s+meters?|advanced\s+metering'),
    ('distribution automation', r'distribution\s+automation|self[\s-]healing\s+grid'),
 ]),
 'nuclear_life': ('Nuclear relicensing / uprates / life extension', ['I.C Nuclear relicensing/retirement', 'I.F Nuclear license status'], [
    ('license renewal / extension', r'(?:subsequent\s+)?license\s+(?:renewal|extension)|relicens\w+|\bSLR\b'),
    ('uprate', r'\buprates?\b'),
    ('nuclear life extension / restart', r'(?:life|operating)\s+extension\b[^.]{0,60}nuclear|nuclear\b[^.]{0,60}\b(?:life|operating)\s+extension|\brestart\b[^.]{0,40}\b(?:plant|unit|nuclear|reactor)'),
 ]),
 'gen_replacement': ('Generation replacement (coal exit, IRP, new build)', ['I.C Long-term generation replacement'], [
    ('coal retirement', r'(?:retire|retirement|retiring|exit)\w*\b[^.]{0,40}\bcoal|\bcoal\b[^.]{0,40}\b(?:retire|retirement|retiring|exit)\w*'),
    ('IRP', r'integrated\s+resource\s+plan|\bIRP\b'),
    ('RFP for new resources', r'\bRFPs?\b|request\s+for\s+proposals?'),
    ('new gas generation', r'combined[\s-]cycle|\bCCGTs?\b|combustion\s+turbines?|peakers?\b'),
 ]),
 'decarb': ('Decarbonization targets', ['I.C Decarbonization pathway', 'V Emissions / decarb targets'], [
    ('net zero', r'net[\s-]zero'),
    ('carbon / emissions reduction target', r'(?:carbon|CO2|emissions?)\s+(?:reduction\s+)?(?:targets?|goals?)|carbon[\s-](?:free|neutral)'),
    ('decarbonization', r'decarboni[sz]\w+'),
 ]),
 'electrification_gas': ('Electrification / gas bans / future of gas', ['II.D Gas ban trends'], [
    ('electrification', r'electrification'),
    ('gas ban / moratorium', r'gas\s+(?:bans?|moratori\w+|hookup\s+ban)|ban\w*\b[^.]{0,30}\bnatural\s+gas|all[\s-]electric'),
    ('future of gas proceeding', r'future\s+of\s+(?:natural\s+)?gas|gas\s+planning\s+proceeding'),
    ('heat pumps', r'heat\s+pumps?'),
 ]),
 'state_clean_policy': ('State clean-energy policy (RPS, OSW, storage, DER)', ['I.C State policy alignment', 'II.D OSW / storage / DER'], [
    ('RPS / clean energy standard', r'renewable\s+portfolio\s+standard|\bRPS\b|clean\s+energy\s+standard|\bCES\b'),
    ('offshore wind', r'offshore\s+wind|\bOSW\b'),
    ('storage mandate / procurement', r'storage\s+(?:mandate|procurement|target|requirement)s?'),
    ('net metering / DER', r'net\s+(?:energy\s+)?metering|\bNEM\b|distributed\s+(?:energy|generation)|\bDERs?\b|rooftop\s+solar'),
    ('state clean energy law', r'Clean\s+Economy\s+Act|\bVCEA\b|Inflation\s+Reduction\s+Act|\bIRA\b|\bCEJA\b|climate\s+act'),
 ]),
 'hedging': ('Commodity hedging', ['I.F Intermittency & hedging', 'II.C Commodity hedging structures'], [
    ('hedged / hedging', r'\bhedg\w+'),
    ('fuel / commodity price exposure', r'(?:natural\s+gas|fuel|power|commodity)\s+prices?\b[^.]{0,40}\b(?:exposure|sensitivity|volatility)'),
 ]),
 'monetization': ('Asset sales / minority sell-downs / monetization', ['I.I Monetization opportunities', 'I.I Long-term optionality'], [
    ('asset sale / divestiture', r'asset\s+sales?|divest\w+|sale\s+of\s+(?:our|the)\b[^.]{0,40}\b(?:business|utility|assets?|stake|interest)'),
    ('minority interest / sell-down', r'minority\s+(?:interest|stake|investment)|sell[\s-]?down|equity\s+partner'),
    ('monetize', r'moneti[sz]\w+'),
    ('capital recycling', r'capital\s+recycling|recycl\w+\s+capital'),
 ]),
 'simplification': ('Portfolio simplification / spin / strategic review', ['I.I Long-term optionality', 'I.I Recent reorgs signaling strategy'], [
    ('spin-off / separation', r'spin[\s-]?offs?\b|spin\s+off|tax[\s-]free\s+separation|separation\s+of\b'),
    ('strategic / portfolio review', r'strategic\s+(?:review|alternatives)|portfolio\s+review|business\s+review'),
    ('simplification / pure-play', r'simplif\w+|pure[\s-]play|fully\s+regulated'),
    ('reorganization / realignment', r'reorgani[sz]\w+|realign\w+|segment\s+reporting\s+change|new\s+segment'),
 ]),
 'capex_approval': ('Regulatory approval for capex (CPCN, pre-approval)', ['I.C Regulatory-approval visibility for capex'], [
    ('CPCN / certificate', r'\bCPCNs?\b|certificate\s+of\s+(?:public\s+)?(?:convenience|need)'),
    ('pre-approval / approved projects', r'pre[\s-]?approv\w+|approved\s+(?:capital|projects?|investments?)|prudence\s+(?:review|determination)'),
 ]),
 'interconnection': ('Interconnection queues & transmission constraints', ['I.C Interconnection queue / interties', 'I.F Transmission congestion', 'II.B Congestion / load pockets'], [
    ('interconnection queue', r'interconnection\s+(?:queue|requests?|process|backlog)|\bqueue\b[^.]{0,40}\binterconnection'),
    ('congestion / constraint', r'\bcongestion\b|transmission\s+constraints?|load\s+pockets?'),
    ('surplus interconnection / co-location', r'surplus\s+interconnection|co[\s-]?locat\w+'),
 ]),
}

RE_PAGE = re.compile(r'\[\[PAGE (\d+)\]\]')
RE_BODY_START = re.compile(r'\n\s*Presentation\s*\n', re.I)
RE_SAFE_HARBOR = re.compile(r'(?:forward[\s-]looking\s+statements?|safe\s+harbou?r)', re.I)
COMPILED = {tid: [(lab, re.compile(rx, re.I)) for lab, rx in terms] for tid, (_, _, terms) in THEMES.items()}


def page_at(txt, pos):
    page = None
    for m in RE_PAGE.finditer(txt, 0, pos + 12):
        if m.start() > pos:
            break
        page = int(m.group(1))
    return page


def body_spans(txt):
    """Scan from the first 'Presentation' header (skips the S&P cover/consensus pages);
    blank out +/-600 chars around each safe-harbour mention (the FLS boilerplate)."""
    m = RE_BODY_START.search(txt)
    start = m.end() if m and m.start() < len(txt) * 0.5 else 0
    masks = [(max(0, h.start() - 600), h.end() + 600) for h in RE_SAFE_HARBOR.finditer(txt)]
    return start, masks


def main():
    man = json.load(open(os.path.join(DATA, 'corpus_manifest.json'), encoding='utf-8'))
    docs = [d for d in man['documents'] if d.get('doc_type') == 'transcript' and d.get('date')]
    docs.sort(key=lambda d: d['date'])
    per = collections.defaultdict(lambda: {'calls': [], 'themes': collections.defaultdict(list)})
    missing = 0
    for d in docs:
        tp = os.path.join(DATA, (d.get('text_file') or f"corpus/text/{d['id']}.txt").replace('/', os.sep))
        if not os.path.exists(tp):
            missing += 1
            continue
        txt = open(tp, encoding='utf-8', errors='ignore').read()
        start, masks = body_spans(txt)
        def live(pos):
            return pos >= start and not any(a <= pos <= b for a, b in masks)
        hits = {}
        for tid, terms in COMPILED.items():
            tc, first = collections.Counter(), None
            for lab, rx in terms:
                for m in rx.finditer(txt):
                    if live(m.start()):
                        tc[lab] += 1
                        if first is None or m.start() < first:
                            first = m.start()
            if tc:
                hits[tid] = (sum(tc.values()), page_at(txt, first), dict(tc))
        ref = {'date': d['date'], 'period': d.get('period'), 'event': d.get('event'), 'doc_id': d['id'], 'url': d.get('url')}
        for t in d.get('tickers') or []:
            per[t]['calls'].append(ref)
            for tid, (n, pg, tc) in hits.items():
                per[t]['themes'][tid].append(dict(ref, hits=n, page=pg, terms=tc))
    out = {}
    for t, v in sorted(per.items()):
        calls = v['calls']
        last8 = [c['doc_id'] for c in calls[-8:]]
        rec = {'calls_scanned': len(calls), 'first_call': calls[0]['date'] if calls else None,
               'last_call': calls[-1]['date'] if calls else None, 'themes': {}}
        for tid, (label, _, _) in THEMES.items():
            s = v['themes'].get(tid, [])
            if not s:
                rec['themes'][tid] = {'calls': 0}
                continue
            by_doc = {x['doc_id']: x['hits'] for x in s}
            r4 = sum(by_doc.get(i, 0) for i in last8[-4:])
            p4 = sum(by_doc.get(i, 0) for i in last8[:-4])
            trend = ('new' if r4 and not p4 else 'rising' if r4 >= 1.5 * p4 and r4 - p4 >= 3 else
                     'fading' if p4 >= 1.5 * r4 and p4 - r4 >= 3 else 'steady' if r4 or p4 else 'dormant')
            terms = collections.Counter()
            for x in s:
                terms.update(x['terms'])
            rec['themes'][tid] = {
                'calls': len(s), 'share': round(len(s) / len(calls), 2), 'total_hits': sum(x['hits'] for x in s),
                'first': {k: s[0][k] for k in ('date', 'period', 'page', 'url', 'doc_id')},
                'last': {k: s[-1][k] for k in ('date', 'period', 'page', 'url', 'doc_id')},
                'recent_4q_hits': r4, 'prior_4q_hits': p4, 'trend': trend,
                'terms': dict(terms.most_common()),
                'series': [{k: x[k] for k in ('date', 'period', 'hits', 'page', 'url')} for x in s],
            }
        out[t] = rec
    doc = {'_schema_version': '1.0', '_generated': datetime.date.today().isoformat(),
           '_source': 'Dated earnings-call transcripts in corpus_manifest.json (S&P Capital IQ), scanned by scripts\\build_theme_screen.py',
           '_note': (f'{len(docs)} dated transcripts ({missing} without text on disk). Discrete facts only - dates, pages, counts, '
                     'matched terms - never transcript prose; open the page link to read the passage. Cover/consensus pages and '
                     'forward-looking-statement boilerplate are not scanned. A mention is a signal to read, not a finding: '
                     '"rider" counts a rider whether it is being filed, approved or merely referenced.'),
           '_trend_rule': 'recent = hits in the last 4 calls, prior = the 4 before: new (0 prior), rising (>=1.5x and +3), fading (<=1/1.5x and -3), steady, dormant',
           'themes': {tid: {'label': lab, 'tracker_items': items, 'terms': [l for l, _ in terms]} for tid, (lab, items, terms) in THEMES.items()},
           'tickers': out}
    json.dump(doc, open(os.path.join(DATA, 'theme_screen.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'wrote theme_screen.json: {len(out)} tickers, {len(docs)} transcripts ({missing} missing text)')
    hdr = ''.join(f'{tid[:9]:>10}' for tid in THEMES)
    print(f'{"":6}{hdr}')
    for t, r in out.items():
        print(f'{t:6}' + ''.join(f"{r['themes'][tid].get('calls', 0):>4}/{r['calls_scanned']:<5}" for tid in THEMES))


if __name__ == '__main__':
    main()
