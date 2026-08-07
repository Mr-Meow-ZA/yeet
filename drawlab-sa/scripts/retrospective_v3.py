#!/usr/bin/env python3
"""DrawLab v3 one-year retrospective simulator.

Replays historical draws without future leakage. Predictions for each target draw
use only rows strictly earlier than that draw. The five competitors are the four
v1 dynamic strategies plus Frozen Alpha, generated once at the simulation start.
Exact draw-specific payouts are fetched only when at least one simulated ticket
qualifies for a prize. Network failures fall back to clearly-labelled estimates.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
HISTORY_PATH = ROOT / "data" / "historical-results.json"
OUT_PATH = ROOT / "v3" / "data" / "retrospective.json"
START = date(2025, 8, 7)
END = date(2026, 8, 6)
STRATEGIES = ("Hot 6M", "Weighted Historical", "Cold 6M", "Diversified Coverage")
FROZEN = "Frozen Alpha"
HEADERS = {"User-Agent":"Mozilla/5.0 (compatible; DrawLabSA/3.0; research only)"}
SESSION = requests.Session(); SESSION.headers.update(HEADERS)

FALLBACK = {
    "Daily Lotto": {"2":5.0,"3":19.0,"4":330.0,"5":400000.0},
    "Lotto": {"3":20.0,"2+B":30.0,"3+B":200.0,"4":200.0,"4+B":4000.0,"5":45000.0,"5+B":500000.0,"6":5000000.0},
    "PowerBall": {"0+PB":5.0,"1+PB":10.0,"2+PB":50.0,"3":50.0,"3+PB":250.0,"4":1000.0,"4+PB":21660.0,"5":350000.0,"5+PB":5000000.0},
}

def rule_for(game:str, d:date):
    if game == "Daily Lotto": return {"count":5,"max":36,"bonus_max":None,"cost":3.0}
    if game == "Lotto":
        return {"count":6,"max":58 if d < date(2026,6,1) else 52,"bonus_max":58 if d < date(2026,6,1) else 52,"cost":5.0}
    return {"count":5,"max":50,"bonus_max":20 if d < date(2026,6,1) else 16,"cost":5.0 if d < date(2026,6,1) else 10.0}

def load_rows():
    raw=json.loads(HISTORY_PATH.read_text()).get("results",[])
    out=[]
    for r in raw:
        try: d=date.fromisoformat(r["date"])
        except Exception: continue
        game=r.get("game"); rule=rule_for(game,d) if game in {"Daily Lotto","Lotto","PowerBall"} else None
        nums=r.get("numbers")
        if not rule or not isinstance(nums,list) or len(nums)!=rule["count"] or len(set(nums))!=len(nums): continue
        if any(not isinstance(n,int) or n<1 or n>rule["max"] for n in nums): continue
        bonus=r.get("bonus")
        if game=="PowerBall" and (not isinstance(bonus,int) or bonus<1 or bonus>rule["bonus_max"]): continue
        out.append({**r,"_date":d})
    return sorted(out,key=lambda x:(x["_date"],x["game"]))

def counts(rows, anchor, days=None, limit=None):
    selected=rows
    if days is not None:
        cutoff=anchor-timedelta(days=days)
        selected=[r for r in rows if r["_date"]>=cutoff]
    if limit is not None: selected=selected[-limit:]
    return Counter(n for r in selected for n in r["numbers"])

def gaps(rows, maximum):
    g={n:len(rows)+1 for n in range(1,maximum+1)}
    for i,r in enumerate(reversed(rows)):
        for n in r["numbers"]:
            if g[n]==len(rows)+1:g[n]=i
    return g

def normalise(v):
    if not v:return {}
    lo,hi=min(v.values()),max(v.values())
    if hi==lo:return {k:.5 for k in v}
    return {k:(x-lo)/(hi-lo) for k,x in v.items()}

def valid_add(picked,n):
    t=sorted(picked+[n])
    return not any(t[i]+1==t[i+1] and t[i+1]+1==t[i+2] for i in range(len(t)-2))

def select_spread(ranked,count,maximum,avoid=None):
    avoid=avoid or []; zones=[(int(i*maximum/count)+1,int((i+1)*maximum/count)) for i in range(count)]
    picked=[]; pos={n:i for i,n in enumerate(ranked)}
    for lo,hi in zones:
        opts=[n for n in ranked if lo<=n<=hi and n not in picked and valid_add(picked,n)]
        if avoid: opts.sort(key=lambda n:(sum(n in line for line in avoid),pos[n],n))
        if opts:picked.append(opts[0])
    for n in ranked:
        if len(picked)>=count:break
        if n not in picked and valid_add(picked,n):picked.append(n)
    return sorted(picked[:count])

def bonus_number(rows,strategy,maximum):
    eligible=[r for r in rows if isinstance(r.get("bonus"),int) and 1<=r["bonus"]<=maximum]
    c=Counter(r["bonus"] for r in eligible); g={n:len(eligible)+1 for n in range(1,maximum+1)}
    for i,r in enumerate(reversed(eligible)):
        b=r["bonus"]
        if g[b]==len(eligible)+1:g[b]=i
    nums=range(1,maximum+1)
    if strategy=="Hot 6M": return min(nums,key=lambda n:(-c[n],n))
    if strategy=="Cold 6M": return min(nums,key=lambda n:(c[n],-g[n],n))
    if strategy=="Weighted Historical": return min(nums,key=lambda n:(-(c[n]*2+g[n]*.15),n))
    return min(nums,key=lambda n:(c[n],n))

def make_line(rows,game,strategy,target,avoid=None):
    rule=rule_for(game,target); nums=list(range(1,rule["max"]+1))
    lc=counts(rows,target); c6=counts(rows,target,183); c3=counts(rows,target,92); cr=counts(rows,target,limit=10); gp=gaps(rows,rule["max"])
    if strategy=="Hot 6M": ranked=sorted(nums,key=lambda n:(-c6[n],-c3[n],-cr[n],n))
    elif strategy=="Cold 6M": ranked=sorted(nums,key=lambda n:(c6[n],-gp[n],c3[n],n))
    elif strategy=="Weighted Historical":
        nl=normalise({n:lc[n] for n in nums}); n6=normalise({n:c6[n] for n in nums}); nr=normalise({n:cr[n] for n in nums}); ng=normalise(gp)
        score={n:.30*nl[n]+.25*n6[n]+.15*nr[n]+.15*ng[n]+.15*(1-abs((n/(rule["max"]+1))-.5)*2) for n in nums}
        ranked=sorted(nums,key=lambda n:(-score[n],-c6[n],n))
    else:
        pop={n:c6[n]+cr[n] for n in nums}; ranked=sorted(nums,key=lambda n:(sum(n in line for line in (avoid or [])),pop[n],n))
    picked=select_spread(ranked,rule["count"],rule["max"],avoid if strategy=="Diversified Coverage" else None)
    bonus=bonus_number(rows,strategy,rule["bonus_max"]) if game=="PowerBall" else None
    return picked,bonus

def prize_key(game,ticket,draw):
    m=len(set(ticket[0])&set(draw["numbers"])); b=ticket[1]
    if game=="Daily Lotto": return str(m),m,False
    if game=="PowerBall":
        hit=b is not None and b==draw.get("bonus"); return (f"{m}+PB" if hit else str(m)),m,hit
    hit=draw.get("bonus") in ticket[0] if draw.get("bonus") is not None else False
    return (f"{m}+B" if hit else str(m)),m,hit

def potentially_paid(game,key):
    if game=="Daily Lotto": return key in {"2","3","4","5"}
    if game=="Lotto": return key in {"3","2+B","3+B","4","4+B","5","5+B","6"}
    return key in {"0+PB","1+PB","2+PB","3","3+PB","4","4+PB","5","5+PB"}

def payout_url(game,d):
    if game=="PowerBall": return f"https://www.powerball.net/southafrica/results/{d.isoformat()}"
    slug="daily-lotto" if game=="Daily Lotto" else "lotto"
    return f"https://za.national-lottery.com/{slug}/results/{d.strftime('%d-%B-%Y').lower()}"

def money(text):
    m=re.search(r"R\s*([\d,]+(?:\.\d+)?)",text.replace("\xa0"," "),re.I); return float(m.group(1).replace(",","")) if m else None

def parse_payouts(game,html):
    soup=BeautifulSoup(html,"html.parser"); out={}
    for row in soup.select("tr"):
        cells=[c.get_text(" ",strip=True) for c in row.select("th,td")]
        if len(cells)<2:continue
        left=" ".join(cells[:-1]).lower(); amount=money(cells[-1])
        if amount is None:continue
        key=None
        if game=="Daily Lotto":
            m=re.search(r"(?:match|matches?)\s*(\d)",left); key=m.group(1) if m else None
        elif game=="Lotto":
            m=re.search(r"(?:match|matches?)\s*(\d)",left)
            if m:key=m.group(1)+( "+B" if "bonus" in left else "")
        else:
            m=re.search(r"(?:match|matches?)\s*(\d)",left)
            if m:key=m.group(1)+( "+PB" if "powerball" in left or "+ pb" in left else "")
            elif "powerball" in left and ("0" in left or "only" in left):key="0+PB"
        if key:out[key]=amount
    return out

def fetch_payouts(game,d,cache):
    k=f"{game}|{d.isoformat()}"
    if k in cache:return cache[k]
    url=payout_url(game,d)
    try:
        r=SESSION.get(url,timeout=(4,8)); r.raise_for_status(); p=parse_payouts(game,r.text)
        if p: cache[k]=(p,"exact",url); return cache[k]
    except Exception: pass
    cache[k]=(FALLBACK[game],"estimated",url); return cache[k]

def streak_loss(seq):
    best=cur=0
    for won in seq:
        if won<=0:cur+=1;best=max(best,cur)
        else:cur=0
    return best

def main():
    all_rows=load_rows(); by_game=defaultdict(list)
    for r in all_rows:by_game[r["game"]].append(r)
    stats={}; record_tickets=[]; payout_cache={}
    for game,rows in by_game.items():
        targets=[r for r in rows if START<=r["_date"]<=END]
        if not targets:continue
        names=list(STRATEGIES)+[FROZEN]
        acc={s:{"tickets":0,"spend":0.0,"won":0.0,"matches":0,"ge2":0,"ge3":0,"best":0,"returns":[],"exact":0,"estimated":0} for s in names}
        frozen=None
        for draw in targets:
            prior=[r for r in rows if r["_date"]<draw["_date"]]
            if len(prior)<60:continue
            generated=[]; lines={}
            for s in STRATEGIES:
                line=make_line(prior,game,s,draw["_date"],generated); generated.append(line[0]); lines[s]=line
            if frozen is None:
                # Frozen Alpha is generated once from the same information available at the first simulated draw.
                frozen=make_line(prior,game,"Weighted Historical",draw["_date"])
            lines[FROZEN]=frozen
            outcomes={}
            for s,line in lines.items():
                key,m,b=prize_key(game,line,draw); outcomes[s]=(key,m,b)
            need_payout=any(potentially_paid(game,o[0]) for o in outcomes.values())
            payouts=ptype=source=None
            if need_payout:payouts,ptype,source=fetch_payouts(game,draw["_date"],payout_cache)
            for s,line in lines.items():
                key,m,b=outcomes[s]; cost=rule_for(game,draw["_date"])["cost"]; won=float((payouts or {}).get(key,0.0)) if potentially_paid(game,key) else 0.0
                a=acc[s]; a["tickets"]+=1;a["spend"]+=cost;a["won"]+=won;a["matches"]+=m;a["ge2"]+=int(m>=2);a["ge3"]+=int(m>=3);a["best"]=max(a["best"],m);a["returns"].append(won)
                if won>0:a[ptype]+=1
                record_tickets.append({"game":game,"date":draw["date"],"strategy":s,"numbers":line[0],"bonus":line[1],"matches":m,"bonus_match":b,"won":round(won,2),"payout_type":ptype if won>0 else None,"source":source if won>0 else None})
        for s,a in acc.items():
            n=a["tickets"]; spend=a["spend"]; won=a["won"]
            stats.setdefault(game,{})[s]={
                "tickets":n,"spend":round(spend,2),"won":round(won,2),"net":round(won-spend,2),"roi_pct":round((won-spend)/spend*100,2) if spend else None,
                "avg_matches":round(a["matches"]/n,4) if n else None,"ge2_rate":round(a["ge2"]/n*100,2) if n else None,"ge3_rate":round(a["ge3"]/n*100,2) if n else None,
                "best_matches":a["best"],"longest_losing_streak":streak_loss(a["returns"]),"exact_winning_draws":a["exact"],"estimated_winning_draws":a["estimated"]
            }
    top=sorted(record_tickets,key=lambda r:(r["matches"],r["won"],r["date"]),reverse=True)[:50]
    payload={"schema_version":1,"generated_at":datetime.now(timezone.utc).isoformat(),"simulation":{"start":START.isoformat(),"end":END.isoformat(),"method":"strict walk-forward; no future leakage","frozen_policy":"generated once at first eligible simulated draw and never changed"},"summary":stats,"top_tickets":top,"payout_quality":{"exact_draws":sum(1 for _,v in payout_cache.values() if v=="exact"),"estimated_draws":sum(1 for _,v in payout_cache.values() if v=="estimated")}}
    OUT_PATH.parent.mkdir(parents=True,exist_ok=True);OUT_PATH.write_text(json.dumps(payload,indent=2)+"\n")
    print(json.dumps({"games":list(stats),"top":top[:3],"payout_cache":len(payout_cache)},indent=2))

if __name__=="__main__":main()
