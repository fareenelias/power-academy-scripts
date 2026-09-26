r"""build_deal_crosslinks.py - join precedents.json deals to Infralogic sponsor portco transactions and live_deals.json
(tracker Ops 1499: "TXNM appears in both - a systematic join is unbuilt").

Match rule (conservative - a missed link is better than a wrong one):
  * name tokens: target (precedent) vs asset (portco tx), legal suffixes, deal words and years removed;
    Jaccard >= 0.5, or one side's tokens all contained in the other with >= 2 tokens;
  * dates: portco tx_date within 18 months of the precedent's announced date;
  * sponsor side: the precedent acquirer text must mention the portco's sponsor (first word match) OR the Jaccard is >= 0.75.
Live deals: a live_deals.json row links when the acquirer matches AND (the target ticker equals the precedent's target_ticker or the name rule passes).

    python scripts\build_deal_crosslinks.py [data_dir]   -> data\deal_crosslinks.json
"""
import sys, os, re, json, datetime, collections

DATA = sys.argv[1] if len(sys.argv) > 1 else r'E:\PowerAcademy\data'
STOP = set(('inc incorporated corp corporation co company llc lp l p ltd limited the of and holdings holding group plc sa '
            'acquisition acquisitions stake sale sales merger mergers deal portfolio take private takeprivate buyout buy '
            'minority majority interest interests assets asset business businesses operations energy utility utilities '
            'services partners capital infrastructure investment investments fund us usa north america american').split())


def toks(s):
    s = re.sub(r'\(.*?\)', ' ', str(s or '').lower())
    return {t for t in re.findall(r'[a-z0-9&]+', s) if t not in STOP and not re.fullmatch(r'(19|20)\d\d|\d+mw|\d+', t)}


def ym(s):
    m = re.match(r'(\d{4})-(\d{2})', str(s or ''))
    return int(m.group(1)) * 12 + int(m.group(2)) - 1 if m else None


def main():
    prec = json.load(open(os.path.join(DATA, 'precedents.json'), encoding='utf-8'))['deals']
    sp = json.load(open(os.path.join(DATA, 'sponsor_portcos.json'), encoding='utf-8'))['sponsors']
    live = (json.load(open(os.path.join(DATA, 'live_deals.json'), encoding='utf-8')) or {}).get('deals', [])
    txs = [(sname, p) for sname, v in sp.items() for p in (v.get('portcos') or [])]
    out = collections.OrderedDict()
    by_tx = collections.defaultdict(list)
    for d in prec:
        tt, dm = toks(d.get('target')), ym(d.get('announced'))
        acq = str(d.get('acquirer') or '').lower()
        hits = []
        for sname, p in txs:
            at = toks(p.get('asset'))
            if not tt or not at:
                continue
            inter = tt & at
            jac = len(inter) / len(tt | at)
            contained = len(inter) >= 2 and (inter == tt or inter == at)
            if not (jac >= 0.5 or contained):
                continue
            pm = ym(p.get('tx_date'))
            if dm is None or pm is None or abs(pm - dm) > 18:
                continue
            sponsor_ok = sname.split()[0].lower() in acq or jac >= 0.75
            if not sponsor_ok:
                continue
            hits.append({'sponsor': sname, 'asset': p.get('asset'), 'tx_id': p.get('tx_id'), 'tx_date': p.get('tx_date'),
                         'status': p.get('status'), 'score': round(jac, 2)})
        # live: same target (ticker or name) AND same acquirer first word - a parent's earlier asset sale is not the live deal
        lv = [x['id'] for x in live
              if str(x.get('acquirer', '')).split()[:1] and str(x.get('acquirer', '')).split()[0].lower() in acq
              and ((d.get('target_ticker') and d.get('target_ticker') in (x.get('tickers') or []))
                   or (toks(x.get('target')) and len(toks(x.get('target')) & tt) / len(toks(x.get('target')) | tt) >= 0.6))]
        if hits or lv:
            out[d['id']] = {'target': d.get('target'), 'acquirer': d.get('acquirer'), 'announced': d.get('announced'),
                            'infralogic': hits, 'live_deals': lv}
            for h in hits:
                by_tx[h['tx_id']].append(d['id'])
    doc = {'_schema_version': '1.0', '_generated': datetime.date.today().isoformat(),
           '_method': __doc__.split('\n\n')[1].strip(),
           'by_precedent': out, 'by_portco_tx': by_tx,
           'counts': {'precedents': len(prec), 'linked': len(out), 'infralogic_links': sum(len(v['infralogic']) for v in out.values()),
                      'live_links': sum(len(v['live_deals']) for v in out.values())}}
    json.dump(doc, open(os.path.join(DATA, 'deal_crosslinks.json'), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    print(doc['counts'])
    for k, v in out.items():
        print(f"  {k:40} {v['target'][:40]:40} <- {', '.join(h['sponsor'] + ':' + h['asset'][:40] for h in v['infralogic'])} {v['live_deals']}")


if __name__ == '__main__':
    main()
