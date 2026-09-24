# -*- coding: utf-8 -*-
r"""build_xplr_plant_map.py - S&P Global XPLR plant list -> data\xplr_plant_map.json (2026-09-24h).

Matches each operating plant in the S&P 'XPLR Infrastructure, LP | Power Plants' export to EIA-860
plant code(s): name + state + nameplate check, with MANUAL overrides for renamed plants and a
technology filter for hybrids. build_fleet.py (SP_AUTHORITATIVE) uses the output as the source of
XIFR's owned view. Re-run after a new S&P export; review every MISMATCH and each new unmatched name.

  python build_xplr_plant_map.py [path_to_SP_export.xlsx]
"""
import zipfile, io, openpyxl, json, os, re, sys, collections, glob
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
z=zipfile.ZipFile(os.path.join(BASE,'data','eia_cache','eia860.zip'))
def rows(fn,sheet=None):
    wb=openpyxl.load_workbook(io.BytesIO(z.read(fn)),read_only=True); ws=wb[sheet] if sheet else wb.worksheets[0]; hdr=None
    for r in ws.iter_rows(values_only=True):
        if hdr is None:
            if r and r[0] in ('Utility ID',): hdr=[str(c).strip() if c else '' for c in r]
            continue
        if r and r[0] not in (None,''): yield dict(zip(hdr,r))
P={}
for d in rows('2___Plant_Y2025_Early_Release.xlsx'):
    P[str(d['Plant Code'])]={'name':d['Plant Name'],'state':d['State'],'county':d.get('County'),'op_id':str(d['Utility ID']),'op':d['Utility Name'],'mw':0.0,'tech':collections.Counter(),'gens':[]}
for d in rows('3_1_Generator_Y2025_Early_Release.xlsx','Operable'):
    p=P.get(str(d['Plant Code']))
    if not p: continue
    try: mw=float(d['Nameplate Capacity (MW)'] or 0)
    except: mw=0
    p['mw']+=mw; p['tech'][d['Technology']]+=mw; p['gens'].append(str(d['Generator ID']))
for p in P.values(): p['tech']=dict(p['tech'])


xl = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob(os.path.join(BASE, 'data', 'eia_cache', 'SPGlobal_XPLR*PowerPlants*.xlsx')))[-1]
ws = openpyxl.load_workbook(xl, read_only=True, data_only=True).worksheets[0]
rows = list(ws.iter_rows(values_only=True))
hi = next(i for i, r in enumerate(rows) if r and r[0] == 'Power Plant Name')
hdr = rows[hi]; S = []
for r in rows[hi + 1:]:
    if not r or r[0] in (None, 'Power Plant Name') or not isinstance(r[1], int): break   # plant section ends at the unit section
    S.append(dict(zip(hdr, r)))
STOP=set('wind solar farm farms project projects energy center centre power plant llc lp inc facility the of phase i ii iii iv v nextera storage battery ess generating station renewable renewables resources park ranch'.split())
def toks(s):
    s=re.sub(r'[–\-_/,.&]',' ',str(s).lower()); return [t for t in re.findall(r'[a-z0-9]+',s) if t not in STOP]
def variants(n):
    base=re.sub(r'\(.*?\)','',n); par=re.findall(r'\((.*?)\)',n)
    return [base]+par
byst=collections.defaultdict(list)
for code,p in P.items(): byst[p['state']].append((code,p))
out=[]
for r in S:
    st=r['State, Province, or Admin Region']; own=r['Operating Ownership (%)']; mw=r['Owned Existing Capacity (MW)']
    tot = (mw/(own/100)) if isinstance(mw,(int,float)) and isinstance(own,(int,float)) and own else None
    best=[]
    for code,p in byst.get(st,[]):
        pt=set(toks(p['name'])); 
        sc=0
        for v in variants(r['Power Plant Name']):
            vt=set(toks(v))
            if vt and pt: sc=max(sc,len(vt&pt)/len(vt|pt))
        if sc>0: best.append((round(sc,2),code,p['name'],round(p['mw'],1),p['op'],list(p['tech'])[:2]))
    best.sort(reverse=True)
    out.append({'sp':r['Power Plant Name'],'key':r['Power Plant Key'],'state':st,'own_pct':own,'owned_mw':mw,'implied_total_mw':round(tot,1) if tot else None,'status':r['Operating Status'],'pm':r['Prime Mover'],'yr':r['Year First Unit in Service'],'cands':best[:3]})
M=out
for o in out:
    c=o['cands'][0] if o['cands'] else None
    cap_ok = c and o['implied_total_mw'] and abs(c[3]-o['implied_total_mw'])<=max(5,0.15*o['implied_total_mw'])
    flag='OK ' if c and c[0]>=0.5 and cap_ok else '?? '
    print(flag,o['sp'][:45].ljust(45),o['state'],o['own_pct'],o['implied_total_mw'],o['status'],'->',(c[1],c[2][:35],c[3],c[4][:30],c[0]) if c else None)

MAN={ # sp name -> list of (eia plant code, tech filter)
 'Adelanto II Solar Farm':[('59440',None)], 'Ashtabula II – NextEra':[('57121',None)], 'Blue Summit III Wind Project':[('62566',None)],
 'Breckinridge Wind Project':[('58994',None)], 'Brady 2 Wind Farm':[('60354',None)], 'Brady Wind Energy Center 1':[('60355',None)],
 'Cool Springs Battery Storage Plant':[('63721','Storage')], 'Cool Springs Solar Power Plant':[('63721','Solar')],
 'Dodge Flat Battery Storage Project':[('63913','Storage')], 'Dodge Flat Solar Energy Center':[('63913','Solar')],
 'Energy Conversion Technology II (Tehachapi 3)':[('54298',None)],
 'Fish Springs Ranch Battery Storage Project':[('64148','Storage')], 'Fish Springs Ranch Solar Farm':[('64148','Solar')],
 'Hubbard Wind Project (Aquilla Lake Wind)':[('65048',None)], 'Javelina Wind CISD':[('60104',None)],
 'McCoy Battery Storage Project':[('58462','Storage')], 'McCoy Solar Energy Project':[('58462','Solar')],
 'Minco III Wind Energy Center':[('58203',None)], 'Ponderosa Wind Farm':[('63590',None)],
 'Saint Solar Project':[('63476',None)], 'Saint Battery Storage Project':[('66716',None)],
 'Sanford Seacoast Regional Airport Solar Project':[('63667',None)], 'Seiling Wind I':[('59311',None)],
 'Silver State South Solar Project':[('58644',None)], 'Stateline Energy Center (OR)':[('55989',None)], 'Stateline Energy Center (WA)':[('55560',None)],
 'Story County II - Garden Wind':[('57469',None)],
 'Tehachapi Wind Farm I (Tehachapi 3)':[('54299',None),('54300',None),('54750',None)],
 'Wilmot Battery Storage Project':[('64426','Storage')], 'Wilmot Energy Center I':[('64426','Solar')],
 'Yellow Pine II Battery Storage':[('67091','Storage')], 'Yellow Pine Solar II Project':[('67091','Solar')], 'Yellow Pine Solar':[('66357','Solar')],
}
TECHMAP={'Solar':('Solar Photovoltaic',),'Storage':('Batteries',),'Wind':('Onshore Wind Turbine',)}
out=[]; skipped=[]
for o in M:
    if o['status']!='Operating' or not o['own_pct']:
        skipped.append({'sp_name':o['sp'],'status':o['status'],'why':'not operating / 0% existing'}); continue
    if o['sp'] in MAN: tgt=MAN[o['sp']]; basis='manual'
    else: tgt=[(o['cands'][0][1],None)]; basis='name+state+capacity'
    eia_mw=0
    for code,tf in tgt:
        p=P[code]; eia_mw+=sum(v for k,v in p['tech'].items() if tf is None or k in TECHMAP[tf])
    imp=o['implied_total_mw']; diff=(eia_mw-imp) if imp else None
    out.append({'sp_name':o['sp'],'sp_key':o['key'],'state':o['state'],'xifr_pct':o['own_pct'],'sp_owned_mw':round(imp*o['own_pct']/100,2) if imp else None,
                'sp_total_mw':imp,'eia':[{'plant_code':c,'plant':P[c]['name'],'tech':tf} for c,tf in tgt],'eia_mw':round(eia_mw,1),
                'cap_check':'ok' if diff is not None and abs(diff)<=max(5,0.15*imp) else 'MISMATCH','match_basis':basis})
doc=collections.OrderedDict([('_source','S&P Global Market Intelligence, "XPLR Infrastructure, LP | Power Plants" export 24-Sep-2026 (data/eia_cache/SPGlobal_XPLRInfrastructure,LP_PowerPlants_24-Sep-2026.xlsx), supplied by Fareen - file: %s' % os.path.basename(xl) + ''),
 ('_method','Each operating S&P plant matched to EIA-860 2025ER plant code(s) by name + state + nameplate check; hybrids split by technology; manual matches reviewed 2026-09-24. xifr_pct = S&P Operating Ownership (%). build_fleet.py treats this as authoritative for XIFR ownership (remaining coverage owners scaled into the remainder) and restricts XIFR operated view to these plants.'),
 ('plants',out),('skipped',skipped)])
json.dump(doc,open(os.path.join(BASE,'data','xplr_plant_map.json'),'w',encoding='utf-8'),indent=1,ensure_ascii=False)
print(len(out),'mapped;',len(skipped),'skipped')
for x in out:
    if x['cap_check']!='ok': print('MISMATCH',x['sp_name'],x['sp_total_mw'],'vs EIA',x['eia_mw'],x['eia'])
codes=collections.Counter((e['plant_code'],e['tech']) for x in out for e in x['eia']); print('dup targets:',[k for k,v in codes.items() if v>1])
print('S&P owned existing MW total:',round(sum(x['sp_owned_mw'] or 0 for x in out),1))
