#!/usr/bin/env python3
import json, re, random, hashlib
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "data" / "cloud-state.json"
TZ = ZoneInfo("Africa/Johannesburg")
NOW = datetime.now(TZ)
TODAY = NOW.date().isoformat()

RULES = {
    "Daily Lotto": {"count": 5, "max": 36, "days": set(range(7)), "cost": 3},
    "Lotto": {"count": 6, "max": 52, "days": {2, 5}, "cost": 5},
    "PowerBall": {"count": 5, "max": 50, "days": {1, 4}, "bonus_max": 16, "cost": 5},
}
SOURCES = {
    "Daily Lotto": [
        "https://za.national-lottery.com/daily-lotto/results",
        "https://www.lottery.co.za/daily-lotto/results",
    ],
    "Lotto": [
        "https://za.national-lottery.com/lotto/results",
        "https://www.lottery.co.za/lotto/results",
    ],
    "PowerBall": [
        "https://za.national-lottery.com/powerball/results",
        "https://www.lottery.co.za/powerball/results",
    ],
}
HEADERS = {"User-Agent": "Mozilla/5.0 DrawLabSA/1.0"}


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"updated_at": None, "status": "initialising", "virtual": {"starting_bankroll": 1000, "costs": {}, "tickets": []}, "results": [], "errors": []}


def save_state(state):
    state["updated_at"] = NOW.isoformat()
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=False) + "\n")


def games_for_date(dt):
    return [g for g, r in RULES.items() if dt.weekday() in r["days"]]


def historical_numbers(state, game):
    nums = []
    for r in state.get("results", []):
        if r.get("game") == game:
            nums.extend(r.get("numbers", []))
    return nums


def seeded_rng(*parts):
    seed = int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:16], 16)
    return random.Random(seed)


def make_line(state, game, strategy, date_str):
    rule = RULES[game]
    rng = seeded_rng(date_str, game, strategy)
    hist = historical_numbers(state, game)
    counts = Counter(hist)
    all_nums = list(range(1, rule["max"] + 1))

    if strategy == "Hot 6M":
        ranked = sorted(all_nums, key=lambda n: (-counts[n], rng.random()))
        pool = ranked[:max(rule["count"] * 2, 12)]
        picked = rng.sample(pool, rule["count"])
    elif strategy == "Weighted Historical":
        weights = [1 + counts[n] for n in all_nums]
        picked = []
        while len(picked) < rule["count"]:
            n = rng.choices(all_nums, weights=weights, k=1)[0]
            if n not in picked:
                picked.append(n)
    else:
        bands = []
        size = rule["max"] / rule["count"]
        for i in range(rule["count"]):
            lo = int(i * size) + 1
            hi = int((i + 1) * size)
            bands.append(rng.randint(lo, max(lo, hi)))
        picked = list(dict.fromkeys(bands))
        while len(picked) < rule["count"]:
            n = rng.randint(1, rule["max"])
            if n not in picked:
                picked.append(n)

    picked = sorted(picked)
    bonus = rng.randint(1, rule.get("bonus_max", 1)) if game == "PowerBall" else None
    return picked, bonus


def ensure_virtual_entries(state):
    tickets = state.setdefault("virtual", {}).setdefault("tickets", [])
    costs = state["virtual"].setdefault("costs", {})
    strategies = ["Hot 6M", "Weighted Historical", "Diversified Coverage"]
    for game in games_for_date(NOW.date()):
        costs.setdefault(game, RULES[game]["cost"])
        for strategy in strategies:
            tid = f"{TODAY}|{game}|{strategy}"
            if any(t.get("id") == tid for t in tickets):
                continue
            numbers, bonus = make_line(state, game, strategy, TODAY)
            tickets.append({
                "id": tid,
                "date": TODAY,
                "game": game,
                "strategy": strategy,
                "numbers": numbers,
                "bonus": bonus,
                "cost": float(costs[game]),
                "won": 0,
                "status": "Pending result",
                "created_at": NOW.isoformat(),
            })


def extract_date(text):
    iso = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if iso:
        return iso.group(1)
    months = "January|February|March|April|May|June|July|August|September|October|November|December"
    m = re.search(rf"\b(\d{{1,2}})\s+({months})\s+(20\d{{2}})\b", text, re.I)
    if m:
        return datetime.strptime(" ".join(m.groups()), "%d %B %Y").date().isoformat()
    return None


def parse_result_html(game, html, url):
    soup = BeautifulSoup(html, "html.parser")
    raw = soup.get_text(" ", strip=True)
    draw_date = extract_date(raw)

    patterns = [
        r'"(?:winningNumbers|mainNumbers|numbers)"\s*:\s*\[([^\]]+)\]',
        r'"balls"\s*:\s*\[([^\]]+)\]',
    ]
    candidates = []
    for p in patterns:
        for match in re.findall(p, html, re.I):
            nums = [int(x) for x in re.findall(r"\b\d{1,2}\b", match)]
            if nums:
                candidates.append(nums)

    selectors = ['[class*="ball"]', '[class*="number"]', '[data-number]']
    dom_nums = []
    for sel in selectors:
        for el in soup.select(sel):
            txt = el.get("data-number") or el.get_text(" ", strip=True)
            m = re.fullmatch(r"\s*(\d{1,2})\s*", txt or "")
            if m:
                dom_nums.append(int(m.group(1)))
        if len(dom_nums) >= RULES[game]["count"]:
            break
    if dom_nums:
        candidates.insert(0, dom_nums)

    count = RULES[game]["count"]
    maximum = RULES[game]["max"]
    for nums in candidates:
        valid = []
        for n in nums:
            if 1 <= n <= maximum and n not in valid:
                valid.append(n)
        if len(valid) >= count:
            main = sorted(valid[:count])
            bonus = None
            if game == "PowerBall":
                rest = [n for n in nums[count:] if 1 <= n <= RULES[game]["bonus_max"]]
                bonus = rest[0] if rest else None
            elif game == "Lotto" and len(nums) > count:
                rest = [n for n in nums[count:] if 1 <= n <= maximum]
                bonus = rest[0] if rest else None
            return {"date": draw_date, "game": game, "numbers": main, "bonus": bonus, "source": url}
    return None


def fetch_latest_result(game):
    errors = []
    for url in SOURCES[game]:
        try:
            response = requests.get(url, headers=HEADERS, timeout=25)
            response.raise_for_status()
            parsed = parse_result_html(game, response.text, url)
            if parsed and parsed.get("date"):
                return parsed, errors
            errors.append(f"{game}: could not parse {url}")
        except Exception as exc:
            errors.append(f"{game}: {url}: {type(exc).__name__}: {exc}")
    return None, errors


def merge_result(state, result):
    key = (result["date"], result["game"])
    for existing in state.setdefault("results", []):
        if (existing.get("date"), existing.get("game")) == key:
            existing.update(result)
            return
    state["results"].append(result)


def settle(state):
    result_map = {(r.get("date"), r.get("game")): r for r in state.get("results", [])}
    for t in state.get("virtual", {}).get("tickets", []):
        r = result_map.get((t.get("date"), t.get("game")))
        if not r:
            continue
        matches = len(set(t.get("numbers", [])) & set(r.get("numbers", [])))
        pb_match = t.get("game") == "PowerBall" and t.get("bonus") is not None and t.get("bonus") == r.get("bonus")
        t["matches"] = matches
        t["pb_match"] = pb_match
        t["status"] = "Settled"
        t.setdefault("won", 0)
        t["settled_at"] = NOW.isoformat()


def main():
    state = load_state()
    state["errors"] = []
    ensure_virtual_entries(state)

    # Results are checked on every run. Stale results are harmless because merge uses date+game.
    for game in RULES:
        result, errors = fetch_latest_result(game)
        state["errors"].extend(errors)
        if result:
            merge_result(state, result)

    settle(state)
    state["status"] = "ok" if not state["errors"] else "partial"
    state["results"] = sorted(state["results"], key=lambda x: (x.get("date", ""), x.get("game", "")), reverse=True)[:300]
    state["virtual"]["tickets"] = sorted(state["virtual"]["tickets"], key=lambda x: (x.get("date", ""), x.get("game", ""), x.get("strategy", "")), reverse=True)[:3000]
    save_state(state)
    print(json.dumps({"status": state["status"], "updated_at": state["updated_at"], "tickets": len(state["virtual"]["tickets"]), "results": len(state["results"]), "errors": state["errors"][:5]}, indent=2))


if __name__ == "__main__":
    main()
