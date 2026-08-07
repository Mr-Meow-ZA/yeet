#!/usr/bin/env python3
from __future__ import annotations
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CLOUD=ROOT/'data'/'cloud-state.json'; RESEARCH=ROOT/'data'/'research-state.json'; FROZEN=ROOT/'v3'/'data'/'frozen-alpha.json'; RETRO=ROOT/'v3'/'data'/'retrospective.json'; OUT=ROOT/'v3'/'data'/'v3-state.json'

def load(path,default):
    try:return json.loads(path.read_text())
    except Exception:return default

def main():
    cloud=load(CLOUD,{"virtual":{"tickets":[]},"results":[]}); research=load(RESEARCH,{}); frozen=load(FROZEN,{}); retro=load(RETRO,{})
    grouped=defaultdict(lambda:{"tickets":0,"settled":0,"spend":0.0,"won":0.0,"matches":0,"best":0,"wins":0})
    settled=[]
    for t in cloud.get('virtual',{}).get('tickets',[]):
        name=t.get('strategy','Unknown'); a=grouped[name]; a['tickets']+=1; a['spend']+=float(t.get('cost',0) or 0)
        if t.get('status')=='Settled':
            a['settled']+=1; won=float(t.get('won',0) or 0); m=int(t.get('matches',0) or 0); a['won']+=won;a['matches']+=m;a['best']=max(a['best'],m);a['wins']+=int(won>0);settled.append(t)
    live=[]
    for name,a in grouped.items():
        live.append({"strategy":name,"tickets":a['tickets'],"settled":a['settled'],"spend":round(a['spend'],2),"won":round(a['won'],2),"net":round(a['won']-a['spend'],2),"roi_pct":round((a['won']-a['spend'])/a['spend']*100,2) if a['spend'] else None,"avg_matches":round(a['matches']/a['settled'],3) if a['settled'] else None,"best_matches":a['best'],"winning_ticket_rate":round(a['wins']/a['settled']*100,2) if a['settled'] else None})
    live.sort(key=lambda x:(x['roi_pct'] if x['roi_pct'] is not None else -999,x['best_matches']),reverse=True)
    top=sorted(settled,key=lambda t:(int(t.get('matches',0) or 0),float(t.get('won',0) or 0),t.get('date','')),reverse=True)[:20]
    records=[]
    for i,t in enumerate(top,1):
        records.append({"rank":i,"date":t.get('date'),"game":t.get('game'),"strategy":t.get('strategy'),"version":t.get('strategy_version'),"numbers":t.get('numbers',[]),"bonus":t.get('bonus'),"matches":t.get('matches',0),"won":float(t.get('won',0) or 0),"payout_type":t.get('payout_type')})
    wf=research.get('walk_forward',[])
    evidence=[r for r in wf if r.get('horizon')==1]
    payload={
      "schema_version":3,"generated_at":datetime.now(timezone.utc).isoformat(),"platform":"DrawLab v3 Research Platform",
      "cloud_status":cloud.get('status'),"cloud_updated_at":cloud.get('updated_at'),"history_quality":cloud.get('history_quality',{}),
      "live_league":live,"hall_of_records":records,"frozen":frozen,
      "research":{"methodology_version":research.get('methodology_version'),"null_hypothesis":research.get('null_hypothesis'),"data_quality":research.get('data_quality',{}),"chance_baselines":research.get('chance_baselines',{}),"horizon1":evidence,"best_hold":research.get('best_hold',[]),"challengers":research.get('challengers',{})},
      "retrospective":retro,
      "principles":["No future leakage","Immutable historical predictions","Version every algorithm","Live results evaluate models but do not directly reward or punish individual numbers","Randomness is the null hypothesis","ROI alone does not establish predictive ability","Adjust for multiple testing","Respect rule eras","Exclude questionable data rather than inventing it"]
    }
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(payload,indent=2)+"\n")
    print(json.dumps({"live_strategies":len(live),"records":len(records),"cloud_status":cloud.get('status')},indent=2))
if __name__=='__main__':main()
