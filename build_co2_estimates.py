r"""build_co2_estimates.py - estimated 2024 CO2 per coverage name (tracker 392 'emissions') -> data\co2_estimates.json

Method (ESTIMATE, labelled as such in the app): for each fossil technology in fleet.json perf (EIA-923 2024,
operated view), fuel burn (MMBtu) = net generation (MWh) x heat rate (Btu/kWh) / 1000, then CO2 = fuel x EPA
emission factor (40 CFR 98 Subpart C, Table C-1, kg CO2 per MMBtu): coal 95.5 (blend of bituminous 93.28 /
sub-bituminous 97.17), natural gas 53.06, distillate oil 73.96. Where a fossil tech has generation but no heat rate,
a default heat rate is used and the row is flagged. Intensity = CO2 / total net generation (all techs, excl. storage).
Not a substitute for EPA GHGRP / CAMPD reported tonnages (those need the EPA download - blocked from the cloud).

    python scripts\build_co2_estimates.py [data_dir]
"""
import sys, os, json, datetime
DATA = sys.argv[1] if len(sys.argv) > 1 else r'E:\PowerAcademy\data'
EF = {'coal': 95.5, 'gas': 53.06, 'oil': 73.96}
DEFAULT_HR = {'coal': 10500, 'gas': 8000, 'oil': 11000}


def fuel_of(tech):
    t = tech.lower()
    if 'coal' in t: return 'coal'
    if t.startswith('gas') or 'natural gas' in t: return 'gas'
    if 'oil' in t or 'petroleum' in t: return 'oil'
    return None


def main():
    fl = json.load(open(os.path.join(DATA, 'fleet.json'), encoding='utf-8'))['tickers']
    out = {}
    for t, v in sorted(fl.items()):
        perf = v.get('perf') or {}
        bt = perf.get('by_tech') or {}
        if not bt: continue
        tot_gen = sum(max(x.get('net_gen_gwh') or 0, 0) for k, x in bt.items() if k != 'Storage')
        rows, co2, flags = {}, 0.0, []
        for tech, x in bt.items():
            f = fuel_of(tech)
            if not f or not (x.get('net_gen_gwh') or 0) > 0: continue
            hr = x.get('heat_rate_btu_kwh')
            if not hr: hr = DEFAULT_HR[f]; flags.append(f'{tech}: default heat rate')
            mmbtu = x['net_gen_gwh'] * 1e6 * hr / 1e6          # kWh*Btu/kWh/1e6 = MMBtu
            t_co2 = mmbtu * EF[f] / 1000                         # tonnes
            co2 += t_co2
            rows[tech] = {'net_gen_gwh': x['net_gen_gwh'], 'heat_rate_btu_kwh': hr, 'fuel_mmbtu_m': round(mmbtu / 1e6, 2), 'co2_mt': round(t_co2 / 1e6, 2)}
        out[t] = {'year': perf.get('year'), 'co2_mt': round(co2 / 1e6, 2), 'total_net_gen_gwh': round(tot_gen, 1),
                  'intensity_t_per_mwh': round(co2 / (tot_gen * 1000), 3) if tot_gen else None,
                  'by_tech': rows, 'flags': flags}
        print(f"{t:5} {out[t]['co2_mt']:7} Mt  {out[t]['intensity_t_per_mwh']} t/MWh  {flags}")
    doc = {'_schema_version': '1.0', '_generated': datetime.date.today().isoformat(),
           '_method': __doc__.split('Method')[1].split('python scripts')[0].strip(),
           '_caveat': 'ESTIMATED from generation x heat rate x EPA emission factors (operated fleet, EIA-923 2024) - not reported GHGRP tonnages; operated not ownership-share view.',
           'names': out}
    json.dump(doc, open(os.path.join(DATA, 'co2_estimates.json'), 'w', encoding='utf-8'), indent=1)
    print('wrote co2_estimates.json')


if __name__ == '__main__':
    main()
