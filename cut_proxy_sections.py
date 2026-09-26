# -*- coding: utf-8 -*-
r"""cut_proxy_sections.py - cut the sections SPEC_MERGER needs out of each merger proxy's plain text.

  python E:\PowerAcademy\scripts\cut_proxy_sections.py [--dir data\_proxies] [--only id1,id2]

Reads  data\_proxies\<deal_id>.txt          (written by fetch_merger_proxies.py)
Writes data\_proxies\<deal_id>.sections.txt  BACKGROUND / REASONS / OPINION OF <bank> (one per advisor) /
                                            PROJECTIONS blocks, each headed with its start offset
       data\_proxies\_sections.json         what was found per deal, lengths, and misses

How a section is found: every short line matching a section heading is a candidate; the table of contents
repeats the same headings, so the candidate whose body (to the next major heading) is LONGEST wins. A
section that cannot be found is listed as a miss - the extractor then reads the full .txt instead.
"""
import os, re, sys, json

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SECTIONS = [
    ('BACKGROUND', r'^(the\s+merger\s*[-\u2014:]\s*)?background(\s+(of|to)\s+the\s+(proposed\s+)?(merger|mergers|transaction|transactions|offer|acquisition|combination|share\s+exchange)s?\b|\s*$)'),
    ('REASONS', r'^(the\s+)?(.{0,60}\s)?reasons\s+for\s+the\s+(proposed\s+)?(merger|mergers|transaction|acquisition|combination)'),
    ('PROJECTIONS', r'^(certain\s+)?(unaudited\s+)?(prospective\s+financial\s+information|financial\s+(projections|forecasts)|'
                    r'projected\s+financial\s+information|management.{0,3}s?\s+(unaudited\s+)?(projections|forecasts)|'
                    r'.{0,40}(unaudited\s+)?(prospective\s+financial\s+information|financial\s+projections|financial\s+forecasts))\b'),
]
OPINION = r'^opinions?\s+of\s+(?P<bank>[^\n]{3,120}?)\s*(\([^)]*\))?\s*$'
MAJOR = re.compile(r'^(background(\s+(of|to)\s+the|\s*$)|(the\s+)?.{0,60}reasons\s+for\s+the|recommendation\s+of|opinions?\s+of\s|'
                   r'(certain\s+)?(unaudited\s+)?(prospective\s+financial|financial\s+projections|financial\s+forecasts)|'
                   r'certain\s+.{0,40}(projections|forecasts|prospective)|interests\s+of\s|financing\s+of\s+the|'
                   r'regulatory\s+(approvals|matters)|material\s+(u\.s\.\s+)?(united\s+states\s+)?federal\s+income\s+tax|'
                   r'the\s+merger\s+agreement|appraisal\s+rights|dissenters|accounting\s+treatment|litigation\s+relat|'
                   r'delisting|board\s+of\s+directors.{0,20}following|closing\s+and\s+effective|conditions\s+to\s+(the\s+)?(completion|merger))',
                   re.I)
CAP = 300_000


def heads(lines):
    """(line_index, char_offset, text) for heading-like lines: short, no terminal period, not a TOC row."""
    out, off = [], 0
    for i, ln in enumerate(lines):
        s = ln.strip()
        # a heading broken across two lines ('Background of the' / 'Merger')
        if re.search(r'\b(of|to|of the|to the|for the)$', s, re.I) and len(s) < 60 and i + 1 < len(lines) \
                and 0 < len(lines[i + 1].strip()) < 60:
            s = s + ' ' + lines[i + 1].strip()
        if 3 <= len(s) <= 160 and not s.endswith(('.', ',', ';')) and not re.search(r'\.{4,}|\s\d{1,3}$', s):
            out.append((i, off, s))
        off += len(ln) + 1
    return out


def cut(text):
    lines = text.split('\n')
    H = heads(lines)
    offs = [h[1] for h in H]
    major_idx = [k for k, h in enumerate(H) if MAJOR.search(h[2])]

    def body_end(k):
        nxt = next((m for m in major_idx if m > k), None)
        return H[nxt][1] if nxt is not None else len(text)

    found = {}
    for name, rx in SECTIONS:
        best = None
        for k, (i, off, s) in enumerate(H):
            if re.search(rx, s, re.I):
                end = body_end(k)
                if best is None or end - off > best[1] - best[0]:
                    best = (off, end, s)
        if best and best[1] - best[0] > 1500:
            found[name] = best
    # one block per advisor opinion
    banks = {}
    for k, (i, off, s) in enumerate(H):
        m = re.match(OPINION, s, re.I)
        if not m: continue
        bank = re.sub(r'\s+', ' ', m.group('bank')).strip(' ,')
        if re.search(r'counsel|tax|legal', bank, re.I): continue
        end = body_end(k)
        key = bank.lower()
        if key not in banks or end - off > banks[key][1] - banks[key][0]:
            banks[key] = (off, end, s)
    for key, v in banks.items():
        if v[1] - v[0] > 3000:
            found['OPINION :: ' + v[2]] = v
    return found


def main():
    a = sys.argv[1:]
    d = a[a.index('--dir') + 1] if '--dir' in a else os.path.join(BASE, 'data', '_proxies')
    only = set(a[a.index('--only') + 1].split(',')) if '--only' in a else None
    report = {}
    for fn in sorted(os.listdir(d)):
        if not fn.endswith('.txt') or fn.endswith(('.sections.txt', '.raw.txt')): continue
        did = fn[:-4]
        if only and did not in only: continue
        text = open(os.path.join(d, fn), encoding='utf-8', errors='replace').read()
        found = cut(text)
        parts = []
        for name, (s, e, head) in sorted(found.items(), key=lambda kv: kv[1][0]):
            body = text[s:min(e, s + CAP)]
            parts.append(f'\n\n===== {name} | offset {s} | {len(body):,} chars | heading: {head} =====\n\n{body}')
        open(os.path.join(d, did + '.sections.txt'), 'w', encoding='utf-8').write(
            f'# {did} - sections cut by cut_proxy_sections.py from {fn} ({len(text):,} chars)\n' + ''.join(parts))
        miss = [n for n, _ in SECTIONS if n not in found]
        if not any(k.startswith('OPINION') for k in found): miss.append('OPINION')
        report[did] = {'chars': len(text), 'sections': {k: v[1] - v[0] for k, v in found.items()}, 'missing': miss}
        print(f"  {did:40} {len(found)} sections  missing: {', '.join(miss) or '-'}")
    json.dump(report, open(os.path.join(d, '_sections.json'), 'w', encoding='utf-8'), indent=1)


if __name__ == '__main__':
    main()
