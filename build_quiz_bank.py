r"""build_quiz_bank.py - question banks for roadmap III (deal dynamics & process) and IV (tax &
structuring). Output data\quiz_bank.json, read by the Tests & Grades screen (Tests.js).

III is GENERATED from data\merger_valuation.json - the 'Background of the Merger' extraction
of 47 utility merger proxies - so every answer is a fact on file with a deep link to the
anchored proxy paragraph, and new proxies grow the bank on the next run. Pattern questions
(medians, most-common process type) are computed across the whole set.

III-curated and IV are a hand-written bank (CURATED below). They are general-knowledge
statements of law and precedent as of 2026-09; each carries its statutory cite or the
precedents.json deal id it leans on. Verify against the primary source before citing to a client.

    python scripts\build_quiz_bank.py          (Windows default path)
    python scripts/build_quiz_bank.py <data_dir>
"""
import sys, os, re, json, random, datetime, statistics, collections

DATA = sys.argv[1] if len(sys.argv) > 1 else r'E:\PowerAcademy\data'
rng = random.Random(20260926)          # deterministic: the same inputs give the same bank

PTYPE = {'proprietary_bilateral': 'Proprietary / bilateral negotiation', 'limited_auction': 'Limited auction (a handful of invited bidders)',
         'broad_auction': 'Broad auction', 'merger_of_equals': 'Merger of equals'}
INIT = {'acquirer': 'The acquirer approached the target', 'target': 'The target (or its board) started the process',
        'third_party': 'A third party / banker introduced the parties'}


def bank_key(name):
    n = (name or '').lower()
    for k in ('goldman', 'morgan stanley', 'j.p. morgan', 'jp morgan', 'jpmorgan', 'lazard', 'moelis', 'wells fargo', 'bofa', 'merrill', 'citi',
              'barclays', 'credit suisse', 'ubs', 'evercore', 'guggenheim', 'rbc', 'centerview', 'perella', 'greenhill', 'mizuho', 'scotia', 'bmo',
              'td ', 'deutsche', 'jefferies', 'lehman', 'bear stearns', 'houlihan', 'macquarie', 'blackstone', 'kbw', 'wachovia'):
        if k in n:
            return {'jp morgan': 'j.p. morgan', 'jpmorgan': 'j.p. morgan', 'merrill': 'bofa'}.get(k, k)
    return n.split(',')[0].strip()


def q(qid, section, topic, prompt, options, answer_idx, explain, source=None, deal=None, difficulty='core'):
    return {'id': qid, 'section': section, 'topic': topic, 'prompt': prompt, 'options': options, 'answer': answer_idx,
            'explain': explain, 'source': source, 'deal': deal, 'difficulty': difficulty}


def shuffled(correct, wrong):
    opts = [correct] + [w for w in wrong if w != correct]
    rng.shuffle(opts)
    return opts, opts.index(correct)


def bucket(v, edges, labels):
    for e, l in zip(edges, labels):
        if v <= e:
            return l
    return labels[-1]


def generated():
    mv = json.load(open(os.path.join(DATA, 'merger_valuation.json'), encoding='utf-8'))['deals']
    out = []
    all_banks = collections.OrderedDict()
    for k, d in mv.items():
        for a in d.get('advisors') or []:
            all_banks.setdefault(bank_key(a.get('bank')), a.get('bank'))
    for k, d in sorted(mv.items()):
        p, deal = d.get('process') or {}, d.get('deal') or {}
        name = f"{deal.get('target')} ← {deal.get('acquirer')} ({(deal.get('announced') or '')[:4]})"
        src = p.get('src') or (d.get('document') or {}).get('url')
        why = '; '.join((p.get('notable') or [])[:2]) or '; '.join((p.get('board_reasons_summary') or [])[:1])
        if p.get('type') in PTYPE:
            opts, ai = shuffled(PTYPE[p['type']], list(PTYPE.values()))
            out.append(q(f'III-{k}-type', 'III', 'Process type', f'{name}: how was the sale process run?', opts, ai,
                         f"Per the proxy's Background of the Merger: {PTYPE[p['type']].lower()}. {why}", src, k))
        if p.get('initiated_by') in INIT:
            opts, ai = shuffled(INIT[p['initiated_by']], list(INIT.values()))
            fc = (p.get('first_contact') or {})
            out.append(q(f'III-{k}-init', 'III', 'Who moved first', f'{name}: who initiated the discussions that led to signing?', opts, ai,
                         f"{INIT[p['initiated_by']]}. First contact {fc.get('date') or 'n/a'}: {fc.get('what') or fc.get('who') or ''}", src, k))
        n = p.get('ndas_signed')
        if isinstance(n, int):
            lab = ['0-1 (effectively bilateral)', '2-4', '5-9', '10 or more']
            c = bucket(n, [1, 4, 9], lab)
            opts, ai = shuffled(c, lab)
            out.append(q(f'III-{k}-ndas', 'III', 'Breadth of process', f'{name}: how many parties signed confidentiality agreements?', opts, ai,
                         f'{n} NDAs' + (f", {p.get('parties_contacted')} parties contacted" if p.get('parties_contacted') else '') +
                         (f", {p.get('final_bids')} final bid(s)." if p.get('final_bids') is not None else '.'), src, k, 'detail'))
        dd = p.get('days_first_contact_to_signing')
        if isinstance(dd, (int, float)):
            lab = ['Under 3 months', '3-6 months', '6-12 months', 'Over a year']
            c = bucket(dd, [90, 182, 365], lab)
            opts, ai = shuffled(c, lab)
            out.append(q(f'III-{k}-days', 'III', 'Time to signing', f'{name}: how long from first contact to signed merger agreement?', opts, ai,
                         f'{int(dd)} days on the proxy timeline.', src, k, 'detail'))
        tf = p.get('termination_fee') or {}
        if tf.get('pct_equity_value'):
            v = tf['pct_equity_value']
            lab = ['Under 2.5% of equity value', '2.5%-3.5%', 'Over 3.5%']
            c = bucket(v, [2.49, 3.5], lab)
            opts, ai = shuffled(c, lab)
            rev = f"; reverse fee ${tf['reverse_fee_m']}M" if tf.get('reverse_fee_m') else '; no reverse fee disclosed'
            out.append(q(f'III-{k}-fee', 'III', 'Deal protection', f'{name}: what target termination fee did the board accept?', opts, ai,
                         f"${tf.get('target_pays_m')}M = {v}% of equity value{rev}.", src, k))
        tgt = [a for a in d.get('advisors') or [] if a.get('side') == 'target' and a.get('bank')]
        if tgt:
            a = tgt[0]
            right = bank_key(a['bank'])
            wrong = [b for b in all_banks if b != right]
            rng.shuffle(wrong)
            opts_k, ai = shuffled(right, wrong[:3])
            opts = [all_banks[x] for x in opts_k]
            fee = a.get('fee') or {}
            out.append(q(f'III-{k}-adv', 'III', 'Advisors', f"{name}: which bank gave the target board's fairness opinion?", opts, ai,
                         f"{a['bank']}" + (f" (fee ${fee.get('total_m')}M, ${fee.get('contingent_m')}M contingent)" if fee.get('total_m') else '') +
                         (f". Relationships disclosed: {a.get('relationships')[:180]}" if a.get('relationships') else ''),
                         a.get('src') or src, k, 'detail'))
    # pattern questions over the whole set
    types = collections.Counter(d['process'].get('type') for d in mv.values() if d.get('process'))
    top = types.most_common(1)[0][0]
    opts, ai = shuffled(PTYPE[top], list(PTYPE.values()))
    out.append(q('III-pattern-type', 'III', 'Patterns', f'Across the {len(mv)} utility merger proxies on file, which process type is most common?', opts, ai,
                 'Counts: ' + ', '.join(f"{PTYPE.get(t, t)} {n}" for t, n in types.most_common()) + '. Utility targets are usually sold to a pre-identified strategic or a short list - regulatory approval risk and the small buyer universe make broad auctions rare.', None, None, 'pattern'))
    fees = [d['process']['termination_fee']['pct_equity_value'] for d in mv.values() if (d.get('process') or {}).get('termination_fee', {}).get('pct_equity_value')]
    if fees:
        med = statistics.median(fees)
        lab = ['About 1-2%', 'About 3%', 'About 5%', 'About 8%']
        opts, ai = shuffled('About 3%' if 2.5 <= med <= 3.5 else ('About 1-2%' if med < 2.5 else 'About 5%'), lab)
        out.append(q('III-pattern-fee', 'III', 'Patterns', 'What is the median target termination fee (as % of equity value) in the proxies on file?', opts, ai,
                     f'Median {med}% over {len(fees)} deals that state the percentage (range {min(fees)}-{max(fees)}%).', None, None, 'pattern'))
    gs = sum(1 for d in mv.values() if (d.get('process') or {}).get('go_shop', {}).get('present'))
    opts, ai = shuffled(f'Rare - {gs} of {len(mv)}', [f'Rare - {gs} of {len(mv)}', 'About a quarter of deals', 'About half of deals', 'Most deals'])
    out.append(q('III-pattern-goshop', 'III', 'Patterns', 'How common is a go-shop in the utility merger agreements on file?', opts, ai,
                 f'{gs} of {len(mv)} carry a go-shop. Go-shops belong to sponsor take-privates signed without a pre-market check; strategic utility deals rely on the fiduciary out plus a ~3% break fee instead.', None, None, 'pattern'))
    days = [d['process']['days_first_contact_to_signing'] for d in mv.values() if isinstance((d.get('process') or {}).get('days_first_contact_to_signing'), (int, float))]
    if days:
        med = statistics.median(days)
        lab = ['About 2 months', 'About 6 months', 'About 12 months', 'About 2 years']
        c = 'About 6 months' if 120 <= med <= 270 else ('About 2 months' if med < 120 else 'About 12 months')
        opts, ai = shuffled(c, lab)
        out.append(q('III-pattern-days', 'III', 'Patterns', 'Median time from first contact to signing across the proxies that date both?', opts, ai,
                     f'Median {int(med)} days over {len(days)} deals (range {int(min(days))}-{int(max(days))}).', None, None, 'pattern'))
    return out


# ── curated bank: III concepts + IV tax & structuring ────────────────────────
C = []
def cq(qid, section, topic, prompt, options, answer, explain, source, difficulty='core'):
    C.append(q(qid, section, topic, prompt, options, answer, explain, source, None, difficulty))

cq('III-c-oncor', 'III', 'Regulatory approval', "Why did the Texas PUC reject NextEra's 2017 acquisition of Oncor?",
   ['NextEra would not accept ring-fencing conditions (independent board, dividend limits)', 'Price was too low for EFH creditors',
    'FERC blocked it on market-power grounds', 'NRC objected to NextEra nuclear operations'], 0,
   "The PUCT denied the deal in April 2017 largely over governance: NextEra would not accept Oncor's ring-fence (independent board control, dividend restrictions). Sempra later bought Oncor with the ring-fence intact.",
   'precedents.json nee_oncor_2016')
cq('III-c-hei', 'III', 'Regulatory approval', "What ended NextEra's 2014 agreement to acquire Hawaiian Electric Industries?",
   ['The Hawaii PUC rejected it in 2016 as not in the public interest', 'HEI shareholders voted it down', 'A topping bid from Macquarie', 'FERC section 203 denial'], 0,
   'The Hawaii PUC rejected the change of control in July 2016 (insufficient ratepayer benefits and clean-energy commitments). NextEra terminated and paid HEI a $90M termination fee plus expense reimbursement - a reverse fee in practice.',
   'precedents.json nee_hawaiian_2014')
cq('III-c-westar', 'III', 'Deal re-cuts', "After the Kansas Corporation Commission rejected Great Plains' 2016 cash-and-stock bid for Westar, how was the deal restructured?",
   ['As an all-stock merger of equals with no acquisition premium and no holdco acquisition debt', 'As a higher cash bid with more equity', 'As an asset purchase of Westar\'s generation only', 'It was abandoned for good'], 0,
   'The KCC rejected the $12.2B deal in April 2017 over the acquisition premium and leverage. The parties re-signed in July 2017 as an all-stock merger of equals (Evergy), which removed the premium-recovery and debt objections.',
   'precedents.json greatplains_westar_orig_2016 / greatplains_westar_2018')
cq('III-c-rtf', 'III', 'Deal protection', 'In utility mergers, what risk is a reverse termination fee (paid by the buyer) mainly pricing?',
   ['Failure to obtain regulatory approvals', 'Buyer financing failure', 'A topping bid for the target', 'Target MAC'], 0,
   "Utility deals rarely have a financing condition; the long-tail risk is a state commission or FERC saying no. The reverse fee compensates the target for 12-18 months of operating under interim covenants (e.g. NextEra-HEI).",
   'merger_valuation.json termination_fee.reverse_fee_m (35 of 47 deals disclose one)')
cq('III-c-203', 'III', 'Approvals', 'What does FERC test under Federal Power Act section 203 for a utility merger?',
   ['Effect on competition, on rates, on regulation, and absence of improper cross-subsidization', 'Only whether the price is fair to shareholders',
    'Whether the combined company stays investment grade', 'Retail rate impact in each state'], 0,
   "FPA s.203 requires the transaction be 'consistent with the public interest': FERC looks at horizontal/vertical competition, rates, regulation, and (since EPAct 2005) that it does not result in cross-subsidization of a non-utility affiliate.",
   'Federal Power Act s.203; 18 CFR Part 33')
cq('III-c-timeline', 'III', 'Approvals', 'Why do regulated-utility mergers typically take 12-18 months from signing to close?',
   ['Serial state commission approvals (often with statutory clocks) plus FERC, HSR and sometimes NRC/FCC', 'Shareholder votes take a year',
    'Financing markets require it', 'SEC review of the S-4 takes a year'], 0,
   'State public-interest reviews (e.g. Virginia\'s 6-month clock on NEE-Dominion) run alongside FERC s.203, HSR, NRC licence transfers for nuclear, and FCC for radio licences. The slowest state sets the close date.',
   'live_deals.json (NEE-D, AWK-WTRG)')
cq('III-c-goodwill', 'III', 'Regulatory economics', 'Why do utility buyers rarely earn a return on the acquisition premium they pay?',
   ['Commissions set rates on original-cost rate base and typically exclude goodwill/acquisition premium', 'Goodwill is amortised for tax over 15 years',
    'Premiums are refunded to customers at close', 'FERC caps premiums at 20%'], 0,
   'Rate base is original cost net of depreciation and ADIT. The premium over book sits in goodwill that customers do not pay for, so the buyer earns it back only through rate-base growth, cost synergies it is allowed to keep, or a lower cost of capital - and merger orders usually add hold-harmless commitments that bar recovery.',
   'general regulatory practice; see rra_states.json merger conditions by state', 'core')

cq('IV-coi', 'IV', 'Tax-free reorganisations', 'In a §368 tax-free merger, roughly what minimum share of consideration must be buyer stock to satisfy continuity of interest?',
   ['About 40% (the Treasury regulations example)', 'At least 80%', '100% - any cash taxes the whole deal', 'About 10%'], 0,
   'Treas. Reg. §1.368-1(e) gives an example where 40% stock preserves continuity of interest. Target holders are taxed only on the cash (boot); all-stock deals like NEE-Dominion are tax-free to holders.',
   'IRC §368(a); Treas. Reg. §1.368-1(e)(2)(v) Ex.1')
cq('IV-cash', 'IV', 'Stock vs asset', 'In an all-cash take-private of a utility holdco by reverse triangular merger (e.g. Blackstone-TXNM), what are the tax results?',
   ['Target shareholders recognise gain; the buyer takes carryover (no step-up) inside basis', 'No shareholder tax; buyer gets a basis step-up',
    'Both shareholders and the target are taxed on a deemed asset sale', 'Only the buyer is taxed'], 0,
   'Buying stock is a taxable sale for the selling holders but leaves the target\'s asset basis untouched. A step-up needs an actual asset purchase or a §338/§336(e) election - rarely worth it for a regulated utility.',
   'IRC §1001; precedents.json blackstone_txnm_2025')
cq('IV-338', 'IV', 'Stock vs asset', 'A buyer acquires a subsidiary from a corporate seller group and they make a §338(h)(10) election. What does the election do?',
   ['Treats the stock purchase as an asset purchase for tax: buyer gets a step-up, seller group is taxed on the deemed asset sale', 'Defers all tax until the buyer resells',
    'Makes the deal a tax-free reorganisation', 'Transfers the seller\'s NOLs to the buyer free of §382'], 0,
   'Legal form stays a stock deal (keeping permits, franchises and contracts in place) while tax treats it as an asset sale followed by liquidation. §336(e) is the cousin for sellers that are not a consolidated group or S corp.',
   'IRC §338(h)(10); §336(e)')
cq('IV-stepup-reg', 'IV', 'Stock vs asset', 'Why is a tax basis step-up usually worth much less when buying a regulated utility than an unregulated business?',
   ['Rates are set on original-cost rate base and normalization/ratemaking generally passes tax benefits to customers rather than the buyer', 'Utilities cannot claim depreciation',
    'Step-ups are prohibited for utilities', 'State taxes offset it'], 0,
   'The regulated return is on book rate base, not tax basis; extra tax depreciation mostly shows up as ADIT that reduces rate base. The buyer pays for the step-up (seller tax cost) without a matching earnings benefit.',
   'IRC §168(i)(9); general ratemaking')
cq('IV-382', 'IV', 'NOLs', 'After a §382 ownership change, how much pre-change NOL can the company use each year?',
   ['Equity value immediately before the change × the long-term tax-exempt rate (plus any built-in gains)', 'Nothing - the NOLs expire',
    '80% of taxable income, as usual', '50% of the NOL per year'], 0,
   'An ownership change is a >50-point shift in 5% holders over 3 years. The annual cap = value × IRS long-term tax-exempt rate. Companies with large NOLs (PG&E post-emergence) adopt charter ownership limits to avoid tripping it.',
   'IRC §382(b), (g); sec_capacity.json NOL figures')
cq('IV-norm', 'IV', 'Normalization', 'What happens if a regulator sets rates in a way that violates the IRC normalization rules?',
   ['The utility loses accelerated (MACRS) depreciation on the affected property', 'The regulator is fined', 'Nothing - it is advisory', 'The utility must refund all ADIT'], 0,
   'Accelerated depreciation for public utility property is conditioned on a normalization method of accounting: the timing benefit (ADIT) can reduce rate base, but may not be flowed through to customers faster than book depreciation.',
   'IRC §168(i)(9), (f)(2)')
cq('IV-edit', 'IV', 'Normalization', "After the 2017 TCJA rate cut, how must 'protected' excess deferred income taxes (EDIT) be returned to customers?",
   ['No faster than the average rate assumption method (ARAM) over remaining plant lives', 'Immediately as a one-time bill credit',
    'At the commission\'s discretion, any period', 'They are kept by shareholders'], 0,
   'Protected (plant-related, method/life) EDIT is subject to normalization and must be amortised under ARAM or the alternative method; unprotected EDIT is returned on whatever schedule the commission orders.',
   'TCJA §13001(d); Rev. Proc. 2020-39')
cq('IV-nolc', 'IV', 'Normalization', 'A utility has an NOL carryforward. Under IRS private letter rulings, how should the NOLC deferred tax asset be treated in rate base?',
   ['It must offset ADIT (increasing rate base) to the extent the NOL was caused by accelerated depreciation - excluding it is a normalization violation',
    'It must be excluded from rate base', 'It is added to rate base at twice its value', 'It has no ratemaking effect'], 0,
   "ADIT only reduces rate base to the extent the deferral was actually realised; if accelerated depreciation created an NOL, the 'with-and-without' method limits the ADIT offset. Large-NOL utilities (PCG, ETR per the 10-K XBRL) carry this in rate base.",
   'IRS private letter rulings on NOLC-related ADIT (series from 2014 on); sec_capacity.json')
cq('IV-tcja-util', 'IV', 'Utility-specific rules', 'Under the 2017 TCJA, what did regulated public utilities give up and what did they keep?',
   ['Gave up bonus depreciation on regulated property; kept full business interest deductibility (exempt from §163(j))', 'Gave up interest deductibility; kept bonus depreciation',
    'Gave up both', 'Kept both'], 0,
   'Regulated utility property was carved out of 100% bonus depreciation (preserving rate base) and utilities were carved out of the 30%-of-EBITDA interest cap. Unregulated IPP subsidiaries do not get the interest carve-out.',
   'IRC §168(k)(9)(A); §163(j)(7)(A)(iv)')
cq('IV-ptc-itc', 'IV', 'Clean-energy credits', 'For a new generating project choosing between the PTC (§45/§45Y) and the ITC (§48/§48E), which variables mostly decide the election?',
   ['Expected capacity factor and capital cost per kW', 'The state renewable portfolio standard', 'The size of the utility\'s rate base', 'Whether the project has a PPA'], 0,
   'The PTC pays per MWh for 10 years, so high-output, low-capex projects (strong wind, high-yield tracking solar) favour it; the ITC is a percentage of basis, favouring capex-heavy, lower-output assets like storage.',
   'IRC §45Y, §48E')
cq('IV-obbba', 'IV', 'Clean-energy credits', 'Under the July 2025 budget law (OBBBA), what deadline now governs §45Y/§48E credits for new wind and solar?',
   ['Begin construction by early July 2026, or else be placed in service by end-2027', 'Credits run unchanged to 2032', 'Credits ended on enactment for all technologies', 'Begin construction by end-2029'], 0,
   'OBBBA accelerated the wind/solar phase-out: projects starting construction after ~4 July 2026 must be in service by 31 Dec 2027. Storage, nuclear, geothermal and hydro kept a longer runway, and foreign-entity-of-concern limits were added. Verify current Treasury guidance on beginning of construction before citing.',
   'Public Law 119-21 (2025), amending IRC §45Y/§48E')
cq('IV-6418', 'IV', 'Monetisation', 'Under §6418 transferability, how is the cash paid for a transferred credit taxed?',
   ['Not income to the seller and not deductible to the buyer', 'Ordinary income to the seller, deductible to the buyer', 'Capital gain to the seller', 'Taxed as a dividend'], 0,
   'Credits can be sold once, for cash, to an unrelated taxpayer; the cash is excluded from the seller\'s income and the buyer\'s discount (paying ~$0.90-0.95 per $1) is its return. It is what let tax-light developers skip tax equity.',
   'IRC §6418(b)')
cq('IV-6417', 'IV', 'Monetisation', 'Which entities can elect direct (elective) pay for §45Y/§48E credits?',
   ['Tax-exempt and governmental entities, rural electric co-ops and similar - not investor-owned utilities', 'Any taxpayer', 'Only investor-owned utilities', 'Only foreign investors'], 0,
   'Elective pay under §6417 is limited to applicable entities (tax-exempts, states and political subdivisions, TVA, Alaska Native corporations, rural co-ops). Taxable IOUs and IPPs monetise through use or §6418 transfer.',
   'IRC §6417(d)(1)')
cq('IV-flip', 'IV', 'Tax equity', 'In a partnership-flip tax equity deal, what flips?',
   ['The allocation of income, tax credits and losses - from mostly the investor (e.g. 99%) to mostly the sponsor once the investor hits its target return', 'Ownership of the land',
    'The PPA counterparty', 'The depreciation method'], 0,
   'The investor takes ~99% of tax attributes until a target IRR or date, then drops to ~5%; the sponsor usually holds a call option to buy out the residual.',
   'Rev. Proc. 2007-65 (wind safe harbour)')
cq('IV-45u', 'IV', 'Clean-energy credits', 'How does the §45U zero-emission nuclear credit behave for merchant nuclear owners like VST and TLN?',
   ['It shrinks as the plant\'s realised power price rises above ~$25/MWh - a revenue floor, not a bonus', 'A fixed $15/MWh regardless of prices',
    'An investment credit on uprates only', 'Available only to regulated utilities'], 0,
   'Up to $15/MWh (with prevailing wage) reduced by 80% of gross receipts above $25/MWh, 2024-2032. At high prices it is zero; at low prices it props up revenue - which is why merchant nuclear credit spreads tightened after 2022.',
   'IRC §45U(b)')
cq('IV-storage-norm', 'IV', 'Utility-specific rules', 'What did the IRA change about ITC normalization for utility-owned energy storage?',
   ['Utilities may elect out of normalization for storage ITCs, letting the benefit flow to customers faster', 'Storage ITCs became unavailable to utilities',
    'Storage ITC must be amortised over 60 years', 'Nothing'], 0,
   'The IRA let regulated utilities opt out of ITC normalization for energy storage property, so the credit can be returned to customers more quickly without a violation. Generation ITCs remain subject to normalization.',
   'Inflation Reduction Act of 2022 storage opt-out from ITC normalization (IRC §50(d) / former §46(f) rules)')
cq('IV-ptp', 'IV', 'Structures', 'Why does XPLR Infrastructure (formerly NextEra Energy Partners) issue 1099s rather than K-1s despite being an LP?',
   ['It is taxed as a corporation - renewable power income is not qualifying income for a publicly traded partnership', 'LPs always issue 1099s',
    'It is a REIT', 'It elected to be disregarded'], 0,
   'A PTP avoids corporate tax only if ~90% of income is qualifying under §7704(d) (minerals and natural-resource activities, among others). Electricity generation from wind and solar does not qualify, so the yieldco is taxed as a corporation.',
   'IRC §7704(c)-(d)')
cq('IV-ringfence', 'IV', 'Structures', 'What is the purpose of regulatory ring-fencing around a utility opco inside a leveraged holdco?',
   ['Keep opco assets and credit insulated from a holdco bankruptcy (independent directors, dividend limits, separate ratings, non-consolidation)', 'Lower the opco tax rate',
    'Allow the holdco to guarantee opco debt', 'Avoid FERC jurisdiction'], 0,
   "Oncor's ring-fence kept it investment grade and out of Energy Future Holdings' 2014 bankruptcy - and was the condition NextEra refused in 2017.",
   'precedents.json nee_oncor_2016')
cq('IV-statetax', 'IV', 'Utility-specific rules', 'When a state cuts its corporate income tax rate, what typically happens on a utility\'s balance sheet?',
   ['Excess ADIT is remeasured into a regulatory liability to be returned to customers', 'Rate base immediately rises by the same amount',
    'Nothing until the next rate case', 'The utility books a one-time gain it keeps'], 0,
   'Deferred taxes are remeasured at the new rate; for regulated utilities the excess is owed back to customers, so it goes to a regulatory liability rather than earnings - the state-level echo of TCJA EDIT.',
   'ASC 740 / ASC 980')


def main():
    gen = generated()
    bank = gen + C
    ids = [b['id'] for b in bank]
    assert len(ids) == len(set(ids)), 'duplicate question ids'
    for b in bank:
        assert 0 <= b['answer'] < len(b['options']), b['id']
    out = {'_schema_version': '1.0', '_generated': datetime.date.today().isoformat(),
           '_source': 'scripts\\build_quiz_bank.py - III generated from merger_valuation.json; III-curated and IV hand-written (see source per question)',
           '_caveat': 'Curated questions state law and precedent as of 2026-09 from general knowledge with the cite shown; check the primary source before relying on one with a client.',
           'sections': {'III': 'Deal dynamics & process', 'IV': 'Tax & structuring'},
           'questions': bank}
    json.dump(out, open(os.path.join(DATA, 'quiz_bank.json'), 'w', encoding='utf-8'), indent=1)
    c = collections.Counter((b['section'], b['topic']) for b in bank)
    print(f'wrote quiz_bank.json: {len(bank)} questions ({len(gen)} generated, {len(C)} curated)')
    for k, v in sorted(c.items()):
        print(f'  {k[0]} {k[1]}: {v}')


if __name__ == '__main__':
    main()
