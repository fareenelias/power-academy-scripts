import re
DASH=r'[\-‐‑‒–—―−]'
WIN=r'(20\d\d)\s*(?:%s|to|through)\s*(20\d\d)'%DASH
FALSE=re.compile(r'(?i)return on equity|equity ratio|equity layer|equity credit|equity method|'
                 r'equity repurchase|equity buyback|social justice|equity and inclusion|'
                 r'common equity ratio|authorized equity|\bROE\b|equity earnings|equity income')
# $X.XB  ... equity issuance(s)/plan/needs   ... optionally "in YYYY-YYYY plan"
A=re.compile(r'(?i)~?\$\s?(?P<v>\d{1,2}(?:\.\d{1,2})?)\s*(?:B\b|billion)\s*(?:of\s+|in\s+)?'
             r'equity\s*(?:issuances?|plan|needs|program)')
B=re.compile(r'(?i)equity\s*(?:issuances?|plan|needs|program)[^$]{0,45}?~?\$\s?(?P<v>\d{1,2}(?:\.\d{1,2})?)\s*(?:B\b|billion)')
# $M forms: "Equity Issuances $2,500" (a $ in millions table)
C=re.compile(r'(?i)equity\s*issuances?\s*\$\s?(?P<v>\d{3,5}(?:,\d{3})?)\b')
def equity_from_text(fb):
    for tier,rx,scale in ((1,A,1.0),(2,B,1.0),(3,C,0.001)):
        for m in rx.finditer(fb):
            pre=fb[max(0,m.start()-60):m.start()]
            if FALSE.search(pre) or FALSE.search(fb[m.start():m.end()+40]): continue
            v=float(m.group('v').replace(',',''))*scale
            if not (0.05<=v<=60): continue
            w=re.search(WIN,fb[max(0,m.start()-90):m.end()+110])
            return v,(('%s-%s'%w.groups()) if w else None),fb[max(0,m.start()-80):m.end()+80],tier
    return None,None,None,None
