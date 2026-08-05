#!/usr/bin/env python3
import json, re
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "data" / "cloud-state.json"
HISTORY_PATH = ROOT / "data" / "historical-results.json"
TZ = ZoneInfo("Africa/Johannesburg")
NOW = datetime.now(TZ)
TODAY = NOW.date().isoformat()

RULES = {
    "Daily Lotto": {"count": 5, "max": 36, "days": set(range(7)), "cost": 3},
    "Lotto": {"count": 6, "max": 52, "days": {2, 5}, "cost": 5},
    "PowerBall": {"count": 5, "max": 50, "days": {1, 4}, "bonus_max": 16, "cost": 5},
}
SOURCES = {
    "Daily Lotto": ["https://za.national-lottery.com/daily-lotto/results", "https://www.lottery.co.za/daily-lotto/results"],
    "Lotto": ["https://za.national-lottery.com/lotto/results", "https://www.lottery.co.za/lotto/results"],
    "PowerBall": ["https://za.national-lottery.com/powerball/results", "https://www.lottery.co.za/powerball/results"],
}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DrawLabSA/3.0; +https://mr-meow-za.github.io/yeet/drawlab-sa/)"}

STRATEGIES = {
    "Hot 6M": {"version": "1.0", "hypothesis": "Recent high-frequency numbers persist."},
    "Weighted Historical": {"version": "1.0", "hypothesis": "A fixed blend of long-term, six-month, momentum and gap signals performs best."},
    "Cold 6M": {"version": "1.0", "hypothesis": "Recently underrepresented numbers revert toward expected frequency."},
    "Diversified Coverage": {"version": "1.0", "hypothesis": "Structured range coverage with low overlap diversifies the portfolio."},
}

FALLBACK = {
    "Daily Lotto": {"2": 5.00, "3": 19.00, "4": 330.00, "5": 400000.00},
    "Lotto": {"3": 20.00, "2+B": 30.00, "3+B": 200.00, "4": 200.00, "4+B": 4000.00, "5": 45000.00, "5+B": 500000.00, "6": 5000000.00},
    "PowerBall": {"0+PB": 10.00, "1+PB": 20.00, "2+PB": 100.00, "3": 100.00, "3+PB": 500.00, "4": 2000.00, "4+PB": 25000.00, "5": 350000.00, "5+PB": 5000000.00},
}

def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"updated_at": None, "status": "initialising", "virtual": {"starting_bankroll": 1000, "costs": {}, "tickets": []}, "results": [], "errors": []}

def save_state(state):
    state["updated_at"] = NOW.isoformat()
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=False) + "\n")

def games_for_date(dt):
    return [g for g, r in RULES.items() if dt.weekday() in r["days"]]

def historical_results(state, game):
    rows = [r for r in state.get("results", []) if r.get("game") == game and r.get("date")]
    if HISTORY_PATH.exists():
        try:
            history = json.loads(HISTORY_PATH.read_text())
            rows.extend(r for r in history.get("results", []) if r.get("game") == game and r.get("date"))
        except Exception:
            pass
    dedup = {(r.get("date"), r.get("game")): r for r in rows}
    return sorted(dedup.values(), key=lambda r: r["date"], reverse=True)

def counts_for_window(rows, days=None, draw_limit=None):
    selected = rows
    if days is not None:
        cutoff = (NOW.date()).toordinal() - days
        selected = [r for r in rows if datetime.fromisoformat(r["date"]).date().toordinal() >= cutoff]
    if draw_limit is not None:
        selected = selected[:draw_limit]
    return Counter(n for r in selected for n in r.get("numbers", []))

def draw_gaps(rows, maximum):
    gaps = {n: len(rows) + 1 for n in range(1, maximum + 1)}
    for idx, row in enumerate(rows):
        for n in row.get("numbers", []):
            if gaps[n] == len(rows) + 1:
                gaps[n] = idx
    return gaps

def normalise(values):
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi == lo:
        return {k: 0.5 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}

def valid_add(picked, n):
    trial = sorted(picked + [n])
    return not any(trial[i] + 1 == trial[i + 1] and trial[i + 1] + 1 == trial[i + 2] for i in range(len(trial) - 2))

def select_spread(ranked, count, maximum, avoid=None):
    avoid = avoid or []
    zones = []
    for i in range(count):
        lo = int(i * maximum / count) + 1
        hi = int((i + 1) * maximum / count)
        zones.append((lo, hi))
    picked = []
    for lo, hi in zones:
        options = [n for n in ranked if lo <= n <= hi and n not in picked and valid_add(picked, n)]
        if avoid:
            options.sort(key=lambda n: (sum(n in line for line in avoid), ranked.index(n), n))
        if options:
            picked.append(options[0])
    for n in ranked:
        if len(picked) >= count:
            break
        if n not in picked and valid_add(picked, n):
            picked.append(n)
    return sorted(picked[:count])

def bonus_number(rows, strategy, maximum):
    counts = Counter(r.get("bonus") for r in rows if isinstance(r.get("bonus"), int) and 1 <= r.get("bonus") <= maximum)
    gaps = {n: len(rows) + 1 for n in range(1, maximum + 1)}
    for idx, row in enumerate(rows):
        b = row.get("bonus")
        if isinstance(b, int) and 1 <= b <= maximum and gaps[b] == len(rows) + 1:
            gaps[b] = idx
    nums = list(range(1, maximum + 1))
    if strategy == "Hot 6M":
        return sorted(nums, key=lambda n: (-counts[n], n))[0]
    if strategy == "Cold 6M":
        return sorted(nums, key=lambda n: (counts[n], -gaps[n], n))[0]
    if strategy == "Weighted Historical":
        return sorted(nums, key=lambda n: (-(counts[n] * 2 + gaps[n] * 0.15), n))[0]
    return sorted(nums, key=lambda n: (counts[n], n))[0]

def make_line(state, game, strategy, date_str, avoid=None):
    rule = RULES[game]
    rows = historical_results(state, game)
    all_nums = list(range(1, rule["max"] + 1))
    c_long = counts_for_window(rows)
    c_6m = counts_for_window(rows, days=183)
    c_3m = counts_for_window(rows, days=92)
    c_recent = counts_for_window(rows, draw_limit=10)
    gaps = draw_gaps(rows, rule["max"])

    if strategy == "Hot 6M":
        ranked = sorted(all_nums, key=lambda n: (-c_6m[n], -c_3m[n], -c_recent[n], n))
    elif strategy == "Cold 6M":
        ranked = sorted(all_nums, key=lambda n: (c_6m[n], -gaps[n], c_3m[n], n))
    elif strategy == "Weighted Historical":
        nl, n6, nr, ng = normalise(c_long), normalise(c_6m), normalise(c_recent), normalise(gaps)
        scores = {n: .30*nl.get(n,0) + .25*n6.get(n,0) + .15*nr.get(n,0) + .15*ng.get(n,0) + .15*(1-abs((n/(rule["max"]+1))-.5)*2) for n in all_nums}
        ranked = sorted(all_nums, key=lambda n: (-scores[n], -c_6m[n], n))
    else:
        popularity = {n: c_6m[n] + c_recent[n] for n in all_nums}
        ranked = sorted(all_nums, key=lambda n: (sum(n in line for line in (avoid or [])), popularity[n], n))

    picked = select_spread(ranked, rule["count"], rule["max"], avoid if strategy == "Diversified Coverage" else None)
    bonus = bonus_number(rows, strategy, rule["bonus_max"]) if game == "PowerBall" else None
    return picked, bonus

def ensure_virtual_entries(state):
    tickets = state.setdefault("virtual", {}).setdefault("tickets", [])
    costs = state["virtual"].setdefault("costs", {})
    state["strategy_catalog"] = STRATEGIES
    order = ("Hot 6M", "Weighted Historical", "Cold 6M", "Diversified Coverage")
    for game in games_for_date(NOW.date()):
        # Never create a virtual ticket after that game's result is already known.
        if any(r.get("date") == TODAY and r.get("game") == game for r in state.get("results", [])):
            continue
        costs.setdefault(game, RULES[game]["cost"])
        generated = []
        for strategy in order:
            version = STRATEGIES[strategy]["version"]
            tid = f"{TODAY}|{game}|{strategy}|v{version}"
            existing = next((t for t in tickets if t.get("id") == tid), None)
            if existing:
                generated.append(existing.get("numbers", []))
                continue
            numbers, bonus = make_line(state, game, strategy, TODAY, generated)
            generated.append(numbers)
            tickets.append({"id": tid, "date": TODAY, "game": game, "strategy": strategy, "strategy_version": version,
                            "strategy_hypothesis": STRATEGIES[strategy]["hypothesis"], "deterministic": True,
                            "numbers": numbers, "bonus": bonus, "cost": float(costs[game]), "won": 0,
                            "payout_type": None, "status": "Pending result", "created_at": NOW.isoformat()})

def extract_date(text):
    iso = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if iso: return iso.group(1)
    months = "January|February|March|April|May|June|July|August|September|October|November|December"
    m = re.search(rf"\b(\d{{1,2}})\s+({months})\s+(20\d{{2}})\b", text, re.I)
    return datetime.strptime(" ".join(m.groups()), "%d %B %Y").date().isoformat() if m else None

def money_value(text):
    if not text: return None
    m = re.search(r"R\s*([\d,]+(?:\.\d+)?)", text.replace("\xa0", " "), re.I)
    return float(m.group(1).replace(",", "")) if m else None

def parse_result_html(game, html, url):
    soup = BeautifulSoup(html, "html.parser")
    raw = soup.get_text(" ", strip=True)
    draw_date = extract_date(raw)
    candidates = []
    for p in [r'"(?:winningNumbers|mainNumbers|numbers)"\s*:\s*\[([^\]]+)\]', r'"balls"\s*:\s*\[([^\]]+)\]']:
        for match in re.findall(p, html, re.I):
            nums = [int(x) for x in re.findall(r"\b\d{1,2}\b", match)]
            if nums: candidates.append(nums)
    for sel in ['[class*="ball"]', '[class*="number"]', '[data-number]']:
        dom = []
        for el in soup.select(sel):
            txt = el.get("data-number") or el.get_text(" ", strip=True)
            if re.fullmatch(r"\s*\d{1,2}\s*", txt or ""): dom.append(int(txt))
        if len(dom) >= RULES[game]["count"]:
            candidates.insert(0, dom); break
    count, maximum = RULES[game]["count"], RULES[game]["max"]
    for nums in candidates:
        valid=[]
        for n in nums:
            if 1 <= n <= maximum and n not in valid: valid.append(n)
        if len(valid) >= count:
            main=sorted(valid[:count]); bonus=None
            if game=="PowerBall":
                rest=[n for n in nums[count:] if 1<=n<=RULES[game]["bonus_max"]]; bonus=rest[0] if rest else None
            elif game=="Lotto":
                rest=[n for n in nums[count:] if 1<=n<=maximum]; bonus=rest[0] if rest else None
            return {"date":draw_date,"game":game,"numbers":main,"bonus":bonus,"source":url}
    return None

def fetch_latest_result(game):
    errors=[]
    for url in SOURCES[game]:
        try:
            r=requests.get(url,headers=HEADERS,timeout=25); r.raise_for_status()
            parsed=parse_result_html(game,r.text,url)
            if parsed and parsed.get("date"): return parsed,errors
            errors.append(f"{game}: could not parse {url}")
        except Exception as exc: errors.append(f"{game}: {url}: {type(exc).__name__}: {exc}")
    return None,errors

def date_slug(date_str):
    dt=datetime.strptime(date_str,"%Y-%m-%d")
    return f"{dt.day:02d}-{dt.strftime('%B').lower()}-{dt.year}"

def payout_url(result):
    d=result["date"]
    if result["game"]=="Daily Lotto": return f"https://za.national-lottery.com/daily-lotto/results/{date_slug(d)}"
    if result["game"]=="Lotto": return f"https://za.national-lottery.com/lotto/results/{date_slug(d)}"
    return f"https://www.powerball.net/southafrica/results/{d}"

def canonical_match(game,label):
    s=re.sub(r"\s+"," ",label.strip().lower()).replace("powerball","pb").replace("bonus ball","bonus")
    nums=[int(x) for x in re.findall(r"\d+",s)]
    n=nums[0] if nums else None
    if n is None: return None
    if game=="Daily Lotto":
        return str(n) if 2 <= n <= 5 else None
    if game=="PowerBall":
        return (f"{n}+PB" if "pb" in s else str(n)) if 0 <= n <= 5 else None
    if game=="Lotto":
        return (f"{n}+B" if "bonus" in s else str(n)) if 2 <= n <= 6 else None
    return None

def parse_payouts(game, html):
    soup = BeautifulSoup(html, "html.parser")
    payouts = {}
    for tr in soup.select("table tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.select("th,td")]
        if game in ("Daily Lotto", "Lotto"):
            if len(cells) < 3:
                continue
            key = canonical_match(game, cells[1])
            amount = money_value(cells[2])
        else:
            if len(cells) < 2:
                continue
            key = canonical_match(game, cells[0])
            amount = money_value(cells[1])
        if key and amount is not None:
            payouts[key] = amount
    return payouts

def fetch_payouts(result):
    url=payout_url(result)
    try:
        r=requests.get(url,headers=HEADERS,timeout=25); r.raise_for_status()
        payouts=parse_payouts(result["game"],r.text)
        if payouts: return payouts,"exact",url,None
        return FALLBACK[result["game"]],"estimated",url,f"No payout table parsed at {url}"
    except Exception as exc:
        return FALLBACK[result["game"]],"estimated",url,f"{type(exc).__name__}: {exc}"

def merge_result(state,result):
    key=(result["date"],result["game"])
    for existing in state.setdefault("results",[]):
        if (existing.get("date"),existing.get("game"))==key:
            existing.update(result); return
    state["results"].append(result)

def result_key(game,matches,pb_match=False,bonus_match=False):
    if game=="Daily Lotto": return str(matches)
    if game=="PowerBall": return f"{matches}+PB" if pb_match else str(matches)
    return f"{matches}+B" if bonus_match else str(matches)

def settle(state):
    result_map={(r.get("date"),r.get("game")):r for r in state.get("results",[])}
    for t in state.get("virtual",{}).get("tickets",[]):
        r=result_map.get((t.get("date"),t.get("game")))
        if not r: continue
        matches=len(set(t.get("numbers",[])) & set(r.get("numbers",[])))
        pb=t.get("game")=="PowerBall" and t.get("bonus")==r.get("bonus")
        bonus=t.get("game")=="Lotto" and r.get("bonus") in t.get("numbers",[])
        key=result_key(t["game"],matches,pb,bonus)
        payout=float(r.get("payouts",{}).get(key,0))
        t.update({"matches":matches,"pb_match":pb,"bonus_match":bonus,"prize_key":key,"won":payout,
                  "payout_type":r.get("payout_type","estimated"),"payout_source":r.get("payout_source"),
                  "status":"Settled","settled_at":NOW.isoformat()})

def main():
    state=load_state(); state["errors"]=[]
    ensure_virtual_entries(state)
    for game in RULES:
        result,errors=fetch_latest_result(game); state["errors"].extend(errors)
        if result:
            payouts,ptype,purl,perr=fetch_payouts(result)
            result.update({"payouts":payouts,"payout_type":ptype,"payout_source":purl})
            if perr: state["errors"].append(f"{game} payout: {perr}")
            merge_result(state,result)
    for result in state.get("results",[]):
        payouts,ptype,purl,perr=fetch_payouts(result)
        result.update({"payouts":payouts,"payout_type":ptype,"payout_source":purl})
        if perr: state["errors"].append(f"{result.get('game')} {result.get('date')} payout: {perr}")
    settle(state)
    state["status"]="ok" if not state["errors"] else "partial"
    state["results"]=sorted(state["results"],key=lambda x:(x.get("date",""),x.get("game","")),reverse=True)[:300]
    state["virtual"]["tickets"]=sorted(state["virtual"]["tickets"],key=lambda x:(x.get("date",""),x.get("game",""),x.get("strategy","")),reverse=True)[:3000]
    save_state(state)
    exact=sum(1 for r in state["results"] if r.get("payout_type")=="exact")
    estimated=sum(1 for r in state["results"] if r.get("payout_type")=="estimated")
    print(json.dumps({"status":state["status"],"updated_at":state["updated_at"],"tickets":len(state["virtual"]["tickets"]),
                      "results":len(state["results"]),"exact_payout_draws":exact,"estimated_payout_draws":estimated,
                      "errors":state["errors"][:8]},indent=2))

if __name__=="__main__": main()
