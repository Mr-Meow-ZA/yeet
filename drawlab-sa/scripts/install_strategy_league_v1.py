from pathlib import Path
import re

path = Path('drawlab-sa/scripts/update_cloud.py')
text = path.read_text()
text = text.replace('import json, re, random, hashlib', 'import json, re')

marker = 'HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DrawLabSA/2.0; +https://sa-lotto-lab.vercel.app)"}\n'
catalog = '''HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DrawLabSA/3.0; +https://mr-meow-za.github.io/yeet/drawlab-sa/)"}\n\nSTRATEGIES = {\n    "Hot 6M": {"version": "1.0", "hypothesis": "Recent high-frequency numbers persist."},\n    "Weighted Historical": {"version": "1.0", "hypothesis": "A fixed blend of long-term, six-month, momentum and gap signals performs best."},\n    "Cold 6M": {"version": "1.0", "hypothesis": "Recently underrepresented numbers revert toward expected frequency."},\n    "Diversified Coverage": {"version": "1.0", "hypothesis": "Structured range coverage with low overlap diversifies the portfolio."},\n}\n'''
if marker not in text:
    raise SystemExit('HEADERS marker not found')
text = text.replace(marker, catalog)

start = text.index('def historical_numbers(state, game):')
end = text.index('def extract_date(text):')
new_block = r'''def historical_results(state, game):
    rows = [r for r in state.get("results", []) if r.get("game") == game and r.get("date")]
    return sorted(rows, key=lambda r: r["date"], reverse=True)

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

'''
text = text[:start] + new_block + text[end:]
path.write_text(text)
print('Installed deterministic four-strategy league v1.0')
