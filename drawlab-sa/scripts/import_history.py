#!/usr/bin/env python3
import argparse, json, re, time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "historical-results.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DrawLabSA-History/1.0; +https://mr-meow-za.github.io/yeet/drawlab-sa/)"}
GAMES = {
    "Daily Lotto": {
        "archive": "https://za.national-lottery.com/daily-lotto/results/{year}-archive",
        "count": 5, "max": 36, "bonus": False,
    },
    "Lotto": {
        "archive": "https://za.national-lottery.com/lotto/results/{year}-archive",
        "count": 6, "max": 52, "bonus": True,
    },
    "PowerBall": {
        "archive": "https://www.powerball.net/southafrica/results/history/{year}",
        "count": 5, "max": 50, "bonus": True,
    },
}

def load():
    if OUT.exists():
        return json.loads(OUT.read_text())
    return {"schema_version": 1, "updated_at": None, "coverage": {}, "results": [], "errors": []}

def extract_date(text):
    m = re.search(r'\b(20\d{2})-(\d{2})-(\d{2})\b', text)
    if m: return m.group(0)
    months = 'January|February|March|April|May|June|July|August|September|October|November|December'
    m = re.search(rf'\b(\d{{1,2}})\s+({months})\s+(20\d{{2}})\b', text, re.I)
    if m:
        return datetime.strptime(' '.join(m.groups()), '%d %B %Y').date().isoformat()
    return None

def valid_numbers(nums, count, maximum):
    out=[]
    for n in nums:
        if 1 <= n <= maximum and n not in out: out.append(n)
    return out if len(out) >= count else None

def parse_draw_page(game, html, url):
    spec=GAMES[game]; soup=BeautifulSoup(html,'html.parser'); raw=soup.get_text(' ',strip=True)
    date=extract_date(raw)
    candidates=[]
    for p in [r'"(?:winningNumbers|mainNumbers|numbers)"\s*:\s*\[([^\]]+)\]', r'"balls"\s*:\s*\[([^\]]+)\]']:
        for hit in re.findall(p,html,re.I): candidates.append([int(x) for x in re.findall(r'\b\d{1,2}\b',hit)])
    for container in soup.select('[class*="result"], [class*="draw"], [class*="ball"]'):
        nums=[int(x) for x in re.findall(r'\b\d{1,2}\b',container.get_text(' ',strip=True))]
        if len(nums)>=spec['count']: candidates.append(nums)
    for nums in candidates:
        valid=valid_numbers(nums,spec['count'],spec['max'])
        if not valid: continue
        main=sorted(valid[:spec['count']]); bonus=None
        rest=nums[spec['count']:]
        if game=='PowerBall':
            bonus=next((n for n in rest if 1<=n<=16),None)
        elif game=='Lotto':
            bonus=next((n for n in rest if 1<=n<=52 and n not in main),None)
        if date:
            return {"date":date,"game":game,"numbers":main,"bonus":bonus,"source":url,"verified":True}
    return None

def archive_links(game, year):
    url=GAMES[game]['archive'].format(year=year)
    r=requests.get(url,headers=HEADERS,timeout=35); r.raise_for_status()
    soup=BeautifulSoup(r.text,'html.parser'); links=[]
    for a in soup.select('a[href]'):
        href=a.get('href',''); text=a.get_text(' ',strip=True)
        if game=='PowerBall':
            m=re.search(r'/southafrica/results/(20\d{2}-\d{2}-\d{2})$',href)
        else:
            m=re.search(r'/results/(\d{1,2}-[a-z]+-20\d{2})$',href,re.I)
        if m:
            links.append(requests.compat.urljoin(url,href))
    return sorted(set(links))

def import_year(game,year,existing,errors,delay):
    try: links=archive_links(game,year)
    except Exception as exc:
        errors.append(f'{game} {year} archive: {type(exc).__name__}: {exc}'); return 0
    added=0
    for url in links:
        try:
            r=requests.get(url,headers=HEADERS,timeout=35); r.raise_for_status()
            row=parse_draw_page(game,r.text,url)
            if row:
                existing[(row['date'],game)]=row; added+=1
            else: errors.append(f'{game}: parse failed {url}')
        except Exception as exc: errors.append(f'{game}: {url}: {type(exc).__name__}: {exc}')
        time.sleep(delay)
    return added

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--start-year',type=int,default=2024); ap.add_argument('--end-year',type=int,default=datetime.now().year); ap.add_argument('--delay',type=float,default=.08)
    args=ap.parse_args(); state=load(); errors=[]
    existing={(r['date'],r['game']):r for r in state.get('results',[]) if r.get('date') and r.get('game')}
    coverage={}
    for game in GAMES:
        coverage[game]={}
        for year in range(args.start_year,args.end_year+1):
            before=len(existing); import_year(game,year,existing,errors,args.delay)
            coverage[game][str(year)]=sum(1 for d,g in existing if g==game and d.startswith(str(year)))
    rows=sorted(existing.values(),key=lambda r:(r['date'],r['game']),reverse=True)
    state.update({"schema_version":1,"updated_at":datetime.now().astimezone().isoformat(),"coverage":coverage,"results":rows,"errors":errors[:200]})
    OUT.write_text(json.dumps(state,indent=2)+"\n")
    print(json.dumps({"results":len(rows),"coverage":coverage,"errors":len(errors)},indent=2))
if __name__=='__main__': main()
