#!/usr/bin/env python3
"""DrawLab EV Hunter v1.0.

Research-only expected-value engine. It does not alter the five live prediction
strategies and never claims that any number is more likely to be drawn.

The model asks a different question: is an upcoming draw economically attractive
at the advertised jackpot, after accounting for ticket cost, lower-tier payouts
and expected jackpot sharing? A deterministic anti-crowd line is produced only
as a prize-sharing research control; the conservative EV gate does not credit
that heuristic with any probability advantage or sharing benefit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
HISTORY_PATH = ROOT / "data" / "historical-results.json"
CLOUD_PATH = ROOT / "data" / "cloud-state.json"
CACHE_PATH = ROOT / "data" / "ev-history.json"
STATE_PATH = ROOT / "data" / "ev-state.json"
TZ = ZoneInfo("Africa/Johannesburg")
NOW = datetime.now(TZ)
RULE_CHANGE_DATE = date(2026, 6, 1)
SOURCE_ROOT = "https://za.national-lottery.com"
RESULTS_URL = f"{SOURCE_ROOT}/results"
HTTP_TIMEOUT = (5, 12)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DrawLabSA-EV/1.0; +https://mr-meow-za.github.io/yeet/drawlab-sa/)"}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

RULES: dict[str, dict[str, Any]] = {
    "Daily Lotto": {"count": 5, "max": 36, "bonus_max": None, "fallback_cost": 3.0, "days": set(range(7))},
    "Lotto": {"count": 6, "max": 52, "bonus_max": 52, "fallback_cost": 5.0, "days": {2, 5}},
    "PowerBall": {"count": 5, "max": 50, "bonus_max": 16, "fallback_cost": 10.0, "days": {1, 4}},
}
PATHS = {
    "Daily Lotto": "daily-lotto",
    "Lotto": "lotto",
    "PowerBall": "powerball",
}
TOP_KEY = {"Daily Lotto": "5", "Lotto": "6", "PowerBall": "5+PB"}
MIN_ECON_ROWS = {"Daily Lotto": 20, "Lotto": 10, "PowerBall": 10}
ENTRY_MARGIN = 1.02
WATCH_MARGIN = 0.90


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text()) if path.exists() else default
    except Exception:
        return default


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")


def money(text: str | None) -> float | None:
    if not text:
        return None
    clean = text.replace("\xa0", " ").replace(",", "")
    m = re.search(r"R\s*([0-9]+(?:\.[0-9]+)?)\s*(billion|million|m|bn)?", clean, re.I)
    if not m:
        return None
    value = float(m.group(1))
    suffix = (m.group(2) or "").lower()
    if suffix in {"million", "m"}:
        value *= 1_000_000
    elif suffix in {"billion", "bn"}:
        value *= 1_000_000_000
    return value


def int_value(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"([0-9][0-9,]*)", text)
    return int(m.group(1).replace(",", "")) if m else None


def slug(draw_date: str) -> str:
    d = datetime.fromisoformat(draw_date).date()
    return f"{d.day:02d}-{d.strftime('%B').lower()}-{d.year}"


def result_url(game: str, draw_date: str) -> str:
    return f"{SOURCE_ROOT}/{PATHS[game]}/results/{slug(draw_date)}"


def canonical_key(game: str, label: str) -> str | None:
    text = re.sub(r"\s+", " ", label.strip().lower())
    text = text.replace("powerball", "pb").replace("bonus ball", "bonus")
    nums = [int(x) for x in re.findall(r"\d+", text)]
    if not nums:
        return None
    k = nums[0]
    if game == "Daily Lotto":
        return str(k) if 2 <= k <= 5 else None
    if game == "PowerBall":
        return f"{k}+PB" if "pb" in text else str(k)
    if game == "Lotto":
        return f"{k}+B" if "bonus" in text else str(k)
    return None


def era_key(game: str, when: date) -> str:
    if game == "PowerBall":
        return "pb-5x50-pb20-r5" if when < RULE_CHANGE_DATE else "pb-5x50-pb16-r10"
    if game == "Lotto":
        return "lotto-6x58" if when < RULE_CHANGE_DATE else "lotto-6x52-r5"
    return "daily-5x36-r3"


def ticket_cost_for(game: str, when: date) -> float:
    if game == "PowerBall":
        return 5.0 if when < RULE_CHANGE_DATE else 10.0
    return RULES[game]["fallback_cost"]


def parse_economics_page(game: str, draw_date: str, html: str, url: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    jackpot_match = re.search(r"Jackpot for this draw:\s*(R\s*[0-9,.]+(?:\s*(?:Million|Billion|M|Bn))?)", text, re.I)
    tickets_match = re.search(r"Tickets Sold:\s*([0-9,]+)", text, re.I)
    sales_match = re.search(r"Total Sales:\s*(R\s*[0-9,.]+)", text, re.I)
    jackpot = money(jackpot_match.group(1)) if jackpot_match else None
    tickets_sold = int_value(tickets_match.group(1)) if tickets_match else None
    total_sales = money(sales_match.group(1)) if sales_match else None
    divisions: dict[str, dict[str, Any]] = {}
    for row in soup.select("table tr"):
        cells = [c.get_text(" ", strip=True) for c in row.select("th,td")]
        if len(cells) < 4:
            continue
        label = cells[1]
        key = canonical_key(game, label)
        if not key:
            continue
        payout = money(cells[2])
        winners = int_value(cells[3])
        pool = money(cells[4]) if len(cells) >= 5 else None
        divisions[key] = {
            "label": label,
            "payout": payout if payout is not None else 0.0,
            "winners": winners if winners is not None else 0,
            "pool": pool,
        }
    if jackpot is None or tickets_sold is None or total_sales is None or len(divisions) < 4:
        return None
    d = datetime.fromisoformat(draw_date).date()
    observed_sales_unit = total_sales / tickets_sold if tickets_sold else None
    ticket_cost = ticket_cost_for(game, d)
    equivalent_lines = total_sales / ticket_cost if ticket_cost else None
    if not equivalent_lines or equivalent_lines <= 0:
        return None
    return {
        "date": draw_date,
        "game": game,
        "era": era_key(game, d),
        "jackpot": round(jackpot, 2),
        "tickets_sold_reported": tickets_sold,
        "total_sales": round(total_sales, 2),
        "observed_sales_unit": round(observed_sales_unit, 4) if observed_sales_unit else None,
        "ticket_cost": ticket_cost,
        "equivalent_lines": int(round(equivalent_lines)),
        "divisions": divisions,
        "source": url,
        "quality": "exact_archive",
    }


def fetch_economics(game: str, draw_date: str) -> dict[str, Any] | None:
    url = result_url(game, draw_date)
    for attempt in range(3):
        # The archive throttles bursty crawlers. A deliberate pause keeps the
        # research cache polite and reproducible; normal cloud runs do not use
        # this historical fetch path.
        time.sleep(0.75)
        try:
            r = SESSION.get(url, timeout=HTTP_TIMEOUT)
            if r.status_code in {403, 429, 500, 502, 503, 504}:
                time.sleep(2.0 * (attempt + 1))
                continue
            r.raise_for_status()
            parsed = parse_economics_page(game, draw_date, r.text, url)
            if parsed:
                return parsed
        except Exception:
            time.sleep(1.0 * (attempt + 1))
    return None


def combined_results() -> list[dict[str, Any]]:
    history = load_json(HISTORY_PATH, {"results": []})
    cloud = load_json(CLOUD_PATH, {"results": []})
    rows = list(history.get("results", [])) + list(cloud.get("results", []))
    dedup: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        game = row.get("game")
        draw_date = row.get("date")
        if game in RULES and isinstance(draw_date, str):
            dedup[(draw_date, game)] = row
    return sorted(dedup.values(), key=lambda r: (r["date"], r["game"]))


def refresh_history(max_workers: int = 6) -> dict[str, Any]:
    existing = load_json(CACHE_PATH, {"schema_version": 1, "rows": []})
    cached = {(r.get("date"), r.get("game")): r for r in existing.get("rows", []) if r.get("quality") == "exact_archive"}
    results = combined_results()
    today = NOW.date()
    candidates: dict[str, list[tuple[str, str]]] = defaultdict(list)

    # Work newest-first so the current rule era becomes useful immediately.
    # Limit each refresh to a small batch; future weekly runs gradually deepen
    # the exact economics archive without hammering the source.
    for row in reversed(results):
        game, draw_date = row.get("game"), row.get("date")
        if game not in RULES or not draw_date:
            continue
        d = datetime.fromisoformat(draw_date).date()
        if game == "Lotto" and d < RULE_CHANGE_DATE:
            continue
        if game == "PowerBall" and d < date(2025, 1, 1):
            continue
        if game == "Daily Lotto" and d < today - timedelta(days=120):
            continue
        key = (draw_date, game)
        if key not in cached:
            candidates[game].append(key)

    per_game_cap = 28
    targets: list[tuple[str, str]] = []
    for game in RULES:
        targets.extend(candidates.get(game, [])[:per_game_cap])

    fetched = 0
    failed = 0
    # A single worker is intentional. The source accepts ordinary sequential
    # traffic but throttles aggressive parallel crawls.
    worker_count = 1
    if targets:
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            future_map = {pool.submit(fetch_economics, game, draw_date): (draw_date, game) for draw_date, game in targets}
            for fut in as_completed(future_map):
                key = future_map[fut]
                try:
                    row = fut.result()
                except Exception:
                    row = None
                if row:
                    cached[key] = row
                    fetched += 1
                else:
                    failed += 1
    rows = sorted(cached.values(), key=lambda r: (r["date"], r["game"]))
    output = {
        "schema_version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source_policy": "Exact public result pages; newest-first paced cache. Ticket cost is rule-era configured and effective line volume is derived from Total Sales / ticket cost.",
        "rows": rows,
        "coverage": {game: sum(r.get("game") == game for r in rows) for game in RULES},
        "refresh": {"requested": len(targets), "fetched": fetched, "failed": failed, "per_game_cap": per_game_cap, "workers": worker_count},
    }
    save_json(CACHE_PATH, output)
    return output


def median(values: list[float], default: float = 0.0) -> float:
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return float(statistics.median(vals)) if vals else default


def line_cost(game: str, prior: list[dict[str, Any]], when: date | None = None) -> tuple[float, str]:
    target = when or NOW.date()
    return ticket_cost_for(game, target), "rule_era_verified"


def match_probabilities(game: str, when: date | None = None) -> dict[str, float]:
    if game == "Daily Lotto":
        n, m = 36, 5
        den = math.comb(n, m)
        return {str(k): math.comb(m, k) * math.comb(n-m, m-k) / den for k in range(2, 6)}
    if game == "PowerBall":
        n, m = 50, 5
        pb_max = 20 if when and when < RULE_CHANGE_DATE else 16
        den_main = math.comb(n, m)
        out: dict[str, float] = {}
        for k in range(0, 6):
            p_main = math.comb(m, k) * math.comb(n-m, m-k) / den_main
            out[f"{k}+PB"] = p_main / pb_max
            out[str(k)] = p_main * (pb_max - 1) / pb_max
        return {k: v for k, v in out.items() if k in {"5+PB","5","4+PB","4","3+PB","3","2+PB","1+PB","0+PB"}}
    n, m = 52, 6
    den = math.comb(n, m)
    other = n - m - 1
    return {
        "6": 1 / den,
        "5+B": math.comb(6, 5) / den,
        "5": math.comb(6, 5) * other / den,
        "4+B": math.comb(6, 4) * other / den,
        "4": math.comb(6, 4) * math.comb(other, 2) / den,
        "3+B": math.comb(6, 3) * math.comb(other, 2) / den,
        "2+B": math.comb(6, 2) * math.comb(other, 3) / den,
        "3": math.comb(6, 3) * math.comb(other, 3) / den,
    }


def typical_payouts(game: str, prior: list[dict[str, Any]]) -> dict[str, float]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for row in prior[-60:]:
        for key, div in (row.get("divisions") or {}).items():
            payout = float(div.get("payout") or 0)
            if payout > 0 and key != TOP_KEY[game]:
                buckets[key].append(payout)
    return {k: round(median(v), 2) for k, v in buckets.items() if v}


def fit_sales(game: str, prior: list[dict[str, Any]]) -> dict[str, float]:
    rows = [r for r in prior[-80:] if r.get("jackpot") and r.get("equivalent_lines")]
    if not rows:
        return {"intercept": 0.0, "slope_per_rand": 0.0, "median": 0.0, "samples": 0}
    xs = [float(r["jackpot"]) for r in rows]
    ys = [float(r["equivalent_lines"]) for r in rows]
    xbar, ybar = sum(xs)/len(xs), sum(ys)/len(ys)
    denom = sum((x-xbar)**2 for x in xs)
    slope = sum((x-xbar)*(y-ybar) for x, y in zip(xs, ys)) / denom if denom else 0.0
    slope = max(0.0, slope)
    intercept = ybar - slope*xbar
    return {"intercept": intercept, "slope_per_rand": slope, "median": median(ys), "samples": len(rows)}


def predict_sales(model: dict[str, float], jackpot: float) -> int:
    med = max(1.0, float(model.get("median") or 1.0))
    raw = float(model.get("intercept") or 0.0) + float(model.get("slope_per_rand") or 0.0) * jackpot
    return int(round(min(max(raw, med*0.60), med*4.00)))


def share_factor(expected_other_winners: float) -> float:
    if expected_other_winners <= 1e-12:
        return 1.0
    return (1.0 - math.exp(-expected_other_winners)) / expected_other_winners


def evaluate_ev(game: str, jackpot: float, prior: list[dict[str, Any]], when: date) -> dict[str, Any]:
    probs = match_probabilities(game, when)
    cost, cost_source = line_cost(game, prior, when)
    payouts = typical_payouts(game, prior)
    sales_model = fit_sales(game, prior)
    lines = predict_sales(sales_model, jackpot)
    top_key = TOP_KEY[game]
    combos = 1 / probs[top_key]
    lam = lines / combos
    share = share_factor(lam)
    lower_ev = sum(probs.get(key, 0.0) * amount for key, amount in payouts.items())
    jackpot_ev = probs[top_key] * jackpot * share
    expected_return = lower_ev + jackpot_ev
    ratio = expected_return / cost if cost else 0.0
    if len(prior) < MIN_ECON_ROWS[game]:
        decision = "INSUFFICIENT_DATA"
    elif ratio >= ENTRY_MARGIN:
        decision = "ENTER_CANDIDATE"
    elif ratio >= WATCH_MARGIN:
        decision = "WATCH"
    else:
        decision = "SKIP"
    return {
        "ticket_cost": round(cost, 2),
        "ticket_cost_source": cost_source,
        "advertised_jackpot": round(jackpot, 2),
        "predicted_line_volume": lines,
        "sales_model_samples": int(sales_model.get("samples", 0)),
        "expected_other_jackpot_winners_uniform": round(lam, 6),
        "expected_jackpot_share_fraction_uniform": round(share, 6),
        "lower_tier_ev": round(lower_ev, 4),
        "jackpot_ev_uniform": round(jackpot_ev, 4),
        "expected_return": round(expected_return, 4),
        "expected_roi_pct": round((ratio - 1) * 100, 2),
        "ev_ratio": round(ratio, 4),
        "decision": decision,
        "economics_samples": len(prior),
        "payout_model": payouts,
        "conservative_policy": "Anti-crowd sharing uplift is excluded from the EV gate; uniform ticket selection is used for jackpot sharing.",
    }


def break_even_jackpot(game: str, prior: list[dict[str, Any]], when: date) -> float | None:
    cost, _ = line_cost(game, prior, when)
    if len(prior) < max(5, MIN_ECON_ROWS[game] // 2):
        return None
    ceiling = 1_000_000_000.0
    lo, hi = 0.0, 1_000_000.0
    while hi <= ceiling and evaluate_ev(game, hi, prior, when)["expected_return"] < cost:
        lo, hi = hi, hi * 1.5
    if hi > ceiling:
        return None
    for _ in range(45):
        mid = (lo + hi) / 2
        if evaluate_ev(game, mid, prior, when)["expected_return"] >= cost:
            hi = mid
        else:
            lo = mid
    return round(hi, -3)


def candidate_combination(game: str, key: str, iteration: int) -> tuple[list[int], int | None]:
    rule = RULES[game]
    seed = f"DrawLab-EV-AntiCrowd-v1|{game}|{key}|{iteration}".encode()
    digest = hashlib.sha256(seed).digest()
    pool = list(range(1, rule["max"] + 1))
    chosen: list[int] = []
    counter = 0
    stream = digest
    while len(chosen) < rule["count"]:
        if counter >= len(stream):
            stream += hashlib.sha256(stream).digest()
        idx = stream[counter] % len(pool)
        chosen.append(pool.pop(idx))
        counter += 1
    bonus = None
    if game == "PowerBall":
        bonus = 1 + hashlib.sha256(seed + b"|PB").digest()[0] % int(rule["bonus_max"])
    return sorted(chosen), bonus


def arithmetic_triplets(nums: list[int]) -> int:
    s = set(nums)
    count = 0
    for a, b in combinations(nums, 2):
        c = 2*b - a
        if c in s and c > b:
            count += 1
    return count


def crowd_score(game: str, nums: list[int]) -> float:
    count = len(nums)
    birthday = sum(n <= 31 for n in nums) / count
    consecutive = sum(b == a + 1 for a, b in zip(nums, nums[1:]))
    same_last_digit = sum(1 for a, b in combinations(nums, 2) if a % 10 == b % 10)
    round_nums = sum(n % 5 == 0 for n in nums)
    progression = arithmetic_triplets(nums)
    span = max(nums) - min(nums)
    span_penalty = max(0.0, (RULES[game]["max"] * 0.55 - span) / RULES[game]["max"])
    return round(2.5*birthday + 1.4*consecutive + 0.45*same_last_digit + 0.18*round_nums + 0.9*progression + 0.8*span_penalty, 6)


def anti_crowd_line(game: str, key: str) -> dict[str, Any]:
    best = None
    for i in range(4096):
        nums, bonus = candidate_combination(game, key, i)
        score = crowd_score(game, nums)
        tie = hashlib.sha256(f"{game}|{key}|{i}".encode()).hexdigest()
        item = (score, tie, nums, bonus)
        if best is None or item[:2] < best[:2]:
            best = item
    assert best is not None
    return {
        "numbers": best[2],
        "bonus": best[3],
        "crowding_score": best[0],
        "model": "anti-crowd-v1",
        "meaning": "Lower heuristic crowding is intended to reduce prize-sharing risk only; it does not change draw odds.",
    }


def upcoming_draw_date(game: str, anchor: date) -> date:
    for offset in range(0, 8):
        d = anchor + timedelta(days=offset)
        if d.weekday() not in RULES[game]["days"]:
            continue
        if offset == 0 and NOW.hour >= 20:
            continue
        return d
    return anchor


def parse_current_jackpots(html: str) -> dict[str, float]:
    soup = BeautifulSoup(html, "html.parser")
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    patterns = {
        "Daily Lotto": [
            r"Daily Lotto jackpot:\s*(R\s*[0-9,.]+(?:\s*(?:Million|Billion|M|Bn))?)",
            r"Daily Lotto.*?jackpot[^R]{0,80}(R\s*[0-9,.]+(?:\s*(?:Million|Billion|M|Bn))?)",
        ],
        "Lotto": [
            r"next Lotto top prize is:\s*(R\s*[0-9,.]+(?:\s*(?:Million|Billion|M|Bn))?)",
            r"Lotto.*?top prize[^R]{0,80}(R\s*[0-9,.]+(?:\s*(?:Million|Billion|M|Bn))?)",
        ],
        "PowerBall": [
            r"PowerBall draw:\s*(R\s*[0-9,.]+(?:\s*(?:Million|Billion|M|Bn))?)",
            r"PowerBall.*?up for grabs[^R]{0,80}(R\s*[0-9,.]+(?:\s*(?:Million|Billion|M|Bn))?)",
        ],
    }
    out: dict[str, float] = {}
    for game, variants in patterns.items():
        for pattern in variants:
            m = re.search(pattern, text, re.I)
            if m:
                value = money(m.group(1))
                if value:
                    out[game] = value
                    break
    return out


def fetch_current_jackpots() -> tuple[dict[str, float], str | None]:
    for attempt in range(3):
        try:
            r = SESSION.get(RESULTS_URL, timeout=HTTP_TIMEOUT)
            if r.status_code in {403, 429, 500, 502, 503, 504}:
                time.sleep(2.0 * (attempt + 1))
                continue
            r.raise_for_status()
            jackpots = parse_current_jackpots(r.text)
            if jackpots:
                return jackpots, RESULTS_URL
        except Exception:
            pass
        time.sleep(1.5 * (attempt + 1))
    return {}, None


def prior_rows(cache_rows: list[dict[str, Any]], game: str, before: date | None = None, target: date | None = None) -> list[dict[str, Any]]:
    rows = [r for r in cache_rows if r.get("game") == game]
    if before:
        rows = [r for r in rows if datetime.fromisoformat(r["date"]).date() < before]
    if target:
        wanted = era_key(game, target)
        rows = [r for r in rows if r.get("era") == wanted]
    return sorted(rows, key=lambda r: r["date"])


def result_lookup() -> dict[tuple[str, str], dict[str, Any]]:
    return {(r["date"], r["game"]): r for r in combined_results() if r.get("date") and r.get("game")}


def prize_key(game: str, numbers: list[int], bonus: int | None, draw: dict[str, Any]) -> tuple[str, int, bool]:
    matches = len(set(numbers) & set(draw.get("numbers", [])))
    bonus_match = False
    if game == "PowerBall":
        bonus_match = bonus is not None and bonus == draw.get("bonus")
        return (f"{matches}+PB" if bonus_match else str(matches), matches, bonus_match)
    if game == "Lotto":
        bonus_match = draw.get("bonus") in numbers if draw.get("bonus") is not None else False
        return (f"{matches}+B" if bonus_match else str(matches), matches, bonus_match)
    return str(matches), matches, False


def backtest(cache_rows: list[dict[str, Any]]) -> dict[str, Any]:
    draws = result_lookup()
    output: dict[str, Any] = {}
    for game in RULES:
        econ = sorted([r for r in cache_rows if r.get("game") == game], key=lambda r: r["date"])
        decisions = []
        spent = won = 0.0
        entries = 0
        for idx, row in enumerate(econ):
            d = datetime.fromisoformat(row["date"]).date()
            prior = [p for p in econ[:idx] if p.get("era") == row.get("era")]
            if len(prior) < MIN_ECON_ROWS[game]:
                continue
            evaluation = evaluate_ev(game, float(row["jackpot"]), prior, d)
            if evaluation["decision"] != "ENTER_CANDIDATE":
                continue
            draw = draws.get((row["date"], game))
            if not draw:
                continue
            line = anti_crowd_line(game, row["date"])
            key, matches, bonus_hit = prize_key(game, line["numbers"], line.get("bonus"), draw)
            payout = float((row.get("divisions") or {}).get(key, {}).get("payout") or 0.0)
            cost = float(evaluation["ticket_cost"])
            spent += cost
            won += payout
            entries += 1
            decisions.append({
                "date": row["date"], "jackpot": row["jackpot"], "ev_ratio": evaluation["ev_ratio"],
                "numbers": line["numbers"], "bonus": line.get("bonus"), "prize_key": key,
                "matches": matches, "bonus_match": bonus_hit, "cost": cost, "won": payout,
            })
        output[game] = {
            "entries": entries,
            "spend": round(spent, 2),
            "won": round(won, 2),
            "net": round(won-spent, 2),
            "roi_pct": round((won/spent-1)*100, 2) if spent else None,
            "decisions": decisions,
            "interpretation": "Historical target jackpot was public pre-draw information; payout and winning numbers are used only after the entry decision for settlement.",
        }
    return output


def settle_shadow_tickets(state: dict[str, Any], cache_rows: list[dict[str, Any]]) -> int:
    lookup = result_lookup()
    econ = {(r["date"], r["game"]): r for r in cache_rows}
    changed = 0
    for ticket in state.setdefault("shadow_tickets", []):
        if ticket.get("status") == "Settled":
            continue
        key = (ticket.get("date"), ticket.get("game"))
        draw = lookup.get(key)
        row = econ.get(key)
        if not draw or not row:
            continue
        pkey, matches, bonus_hit = prize_key(ticket["game"], ticket["numbers"], ticket.get("bonus"), draw)
        payout = float((row.get("divisions") or {}).get(pkey, {}).get("payout") or 0.0)
        ticket.update({"status": "Settled", "matches": matches, "bonus_match": bonus_hit, "prize_key": pkey, "won": payout, "settled_at": datetime.now(timezone.utc).isoformat()})
        changed += 1
    return changed


def build_current(cache: dict[str, Any]) -> dict[str, Any]:
    rows = cache.get("rows", [])
    old = load_json(STATE_PATH, {"shadow_tickets": [], "decisions": []})
    old.setdefault("shadow_tickets", [])
    old.setdefault("decisions", [])
    jackpots, jackpot_source = fetch_current_jackpots()
    current: dict[str, Any] = {}
    for game in RULES:
        draw_date = upcoming_draw_date(game, NOW.date())
        prior = prior_rows(rows, game, before=draw_date + timedelta(days=1), target=draw_date)
        be = break_even_jackpot(game, prior, draw_date)
        if game in jackpots:
            ev = evaluate_ev(game, jackpots[game], prior, draw_date)
            line = anti_crowd_line(game, draw_date.isoformat())
            current[game] = {"draw_date": draw_date.isoformat(), "jackpot_source": jackpot_source, **ev, "anti_crowd_line": line, "break_even_jackpot": be}
        else:
            cost, cost_source = line_cost(game, prior, draw_date)
            current[game] = {
                "draw_date": draw_date.isoformat(), "decision": "SOURCE_UNAVAILABLE", "ticket_cost": cost,
                "ticket_cost_source": cost_source, "advertised_jackpot": None, "expected_return": None,
                "expected_roi_pct": None, "break_even_jackpot": be, "jackpot_source": None,
                "anti_crowd_line": anti_crowd_line(game, draw_date.isoformat()),
            }

    existing_decisions = {(d.get("date"), d.get("game")) for d in old["decisions"]}
    for game, row in current.items():
        key = (row["draw_date"], game)
        if key not in existing_decisions and NOW.hour < 20:
            old["decisions"].append({"date": row["draw_date"], "game": game, "recorded_at": NOW.isoformat(), "decision": row.get("decision"), "ev_ratio": row.get("ev_ratio"), "expected_roi_pct": row.get("expected_roi_pct"), "advertised_jackpot": row.get("advertised_jackpot"), "break_even_jackpot": row.get("break_even_jackpot"), "ticket_cost": row.get("ticket_cost"), "source": row.get("jackpot_source")})
    old["decisions"] = sorted(old["decisions"], key=lambda d: (d.get("date", ""), d.get("game", "")), reverse=True)[:600]

    ticket_keys = {(t.get("date"), t.get("game")) for t in old["shadow_tickets"]}
    created = 0
    if NOW.hour < 20:
        for game, row in current.items():
            key = (row["draw_date"], game)
            if row.get("decision") != "ENTER_CANDIDATE" or key in ticket_keys:
                continue
            line = row["anti_crowd_line"]
            old["shadow_tickets"].append({
                "id": f"{row['draw_date']}|{game}|EV Hunter|v1.0",
                "date": row["draw_date"], "game": game, "strategy": "EV Hunter", "strategy_version": "1.0",
                "numbers": line["numbers"], "bonus": line.get("bonus"), "crowding_score": line["crowding_score"],
                "cost": row["ticket_cost"], "advertised_jackpot": row["advertised_jackpot"], "ev_ratio_at_entry": row.get("ev_ratio"),
                "expected_roi_pct_at_entry": row.get("expected_roi_pct"), "status": "Pending result", "won": 0.0,
                "created_at": NOW.isoformat(), "research_only": True,
            })
            ticket_keys.add(key)
            created += 1
    settled_now = settle_shadow_tickets(old, rows)
    tickets = old["shadow_tickets"]
    settled = [t for t in tickets if t.get("status") == "Settled"]
    spend = sum(float(t.get("cost") or 0) for t in tickets)
    won = sum(float(t.get("won") or 0) for t in settled)
    output = {
        "schema_version": 1,
        "model_version": "EV Hunter v1.0",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Selective expected-value research. This model changes when to participate and how to reduce sharing risk; it does not predict winning numbers.",
        "current": current,
        "historical_backtest": backtest(rows),
        "shadow_tickets": sorted(tickets, key=lambda t: (t.get("date", ""), t.get("game", "")), reverse=True)[:500],
        "shadow_summary": {
            "tickets": len(tickets), "settled": len(settled), "pending": len(tickets)-len(settled),
            "spend": round(spend, 2), "won": round(won, 2), "net": round(won-spend, 2),
            "roi_pct": round((won/spend-1)*100, 2) if spend else None,
            "created_now": created, "settled_now": settled_now,
        },
        "decisions": old["decisions"],
        "methodology": {
            "gate": f"ENTER only when modelled expected return >= {ENTRY_MARGIN:.2f}x ticket cost and economics sample minimum is met.",
            "sharing": "Jackpot split risk uses a Poisson collision model under uniform other-ticket selection. This is deliberately conservative for anti-crowd lines.",
            "anti_crowd": "Deterministic heuristic penalizes birthday-heavy and simple patterned combinations. It changes expected sharing only, never draw probability; no sharing uplift is credited in the gate.",
            "payouts": "Lower-tier payout estimates are medians of positive exact archived per-winner payouts available before the target draw.",
            "sales": "Equivalent line volume is derived from historical Total Sales divided by the verified rule-era ticket cost, then forecast from prior jackpot observations with conservative clamps.",
            "historical_test": "Each historical entry decision uses the target jackpot but only earlier economics to estimate payout and sales behavior; result and target payout table are used only for settlement.",
        },
        "cache_coverage": cache.get("coverage", {}),
        "sources": [RESULTS_URL, f"{SOURCE_ROOT}/<game>/results/<date>"],
    }
    save_json(STATE_PATH, output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-history", action="store_true")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    cache = refresh_history(args.workers) if args.refresh_history or not CACHE_PATH.exists() else load_json(CACHE_PATH, {"rows": [], "coverage": {}})
    state = build_current(cache)
    print(json.dumps({
        "model": state["model_version"],
        "cache_coverage": state["cache_coverage"],
        "current": {g: {k: v for k, v in r.items() if k in {"decision","advertised_jackpot","expected_return","expected_roi_pct","break_even_jackpot","ticket_cost"}} for g, r in state["current"].items()},
        "shadow": state["shadow_summary"],
        "backtest": {g: {k: v for k, v in r.items() if k in {"entries","spend","won","net","roi_pct"}} for g, r in state["historical_backtest"].items()},
    }, indent=2))


if __name__ == "__main__":
    main()
