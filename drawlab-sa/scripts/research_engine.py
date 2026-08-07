#!/usr/bin/env python3
"""DrawLab Research Engine v2.

Research-only analytics. It never creates or mutates live virtual tickets.
All walk-forward predictions are generated using only draws available before
that historical target draw.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HISTORY_PATH = ROOT / "data" / "historical-results.json"
CLOUD_PATH = ROOT / "data" / "cloud-state.json"
OUT_PATH = ROOT / "data" / "research-state.json"

RULES = {
    "Daily Lotto": {"count": 5, "max": 36, "bonus_max": None},
    "Lotto": {"count": 6, "max": 52, "bonus_max": 52},
    "PowerBall": {"count": 5, "max": 50, "bonus_max": 20},
}
STRATEGIES = ("Hot 6M", "Weighted Historical", "Cold 6M", "Diversified Coverage")
HORIZONS = (1, 2, 4, 8)
MIN_TRAIN = {"Daily Lotto": 90, "Lotto": 60, "PowerBall": 60}
WEIGHT_CANDIDATES = (
    {"long": .25, "six": .30, "recent": .15, "gap": .15, "pair": .15},
    {"long": .20, "six": .35, "recent": .15, "gap": .15, "pair": .15},
    {"long": .30, "six": .25, "recent": .15, "gap": .15, "pair": .15},
    {"long": .20, "six": .30, "recent": .20, "gap": .15, "pair": .15},
    {"long": .20, "six": .30, "recent": .15, "gap": .20, "pair": .15},
    {"long": .20, "six": .30, "recent": .15, "gap": .15, "pair": .20},
    {"long": .15, "six": .35, "recent": .20, "gap": .15, "pair": .15},
    {"long": .25, "six": .25, "recent": .20, "gap": .15, "pair": .15},
    {"long": .25, "six": .30, "recent": .10, "gap": .15, "pair": .20},
    {"long": .20, "six": .25, "recent": .20, "gap": .20, "pair": .15},
)


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text()) if path.exists() else default
    except Exception:
        return default


def valid_row(row: dict[str, Any], game: str) -> bool:
    rule = RULES[game]
    nums = row.get("numbers")
    if not isinstance(nums, list) or len(nums) != rule["count"] or len(set(nums)) != len(nums):
        return False
    if any(not isinstance(n, int) or not 1 <= n <= rule["max"] for n in nums):
        return False
    try:
        datetime.fromisoformat(str(row.get("date")))
    except ValueError:
        return False
    if game == "PowerBall":
        bonus = row.get("bonus")
        if bonus is not None and (not isinstance(bonus, int) or not 1 <= bonus <= 20):
            return False
    return True


def game_history(game: str) -> list[dict[str, Any]]:
    history = load_json(HISTORY_PATH, {"results": []})
    cloud = load_json(CLOUD_PATH, {"results": []})
    rows = [r for r in history.get("results", []) + cloud.get("results", []) if r.get("game") == game and valid_row(r, game)]
    dedup = {(r["date"], game): r for r in rows}
    return sorted(dedup.values(), key=lambda r: r["date"])


def counts(rows: list[dict[str, Any]], *, days: int | None = None, limit: int | None = None, anchor: str | None = None) -> Counter:
    selected = rows
    if days is not None and anchor:
        cutoff = datetime.fromisoformat(anchor).date() - timedelta(days=days)
        selected = [r for r in rows if datetime.fromisoformat(r["date"]).date() >= cutoff]
    if limit is not None:
        selected = selected[-limit:]
    return Counter(n for r in selected for n in r.get("numbers", []))


def gaps(rows: list[dict[str, Any]], maximum: int) -> dict[int, int]:
    out = {n: len(rows) + 1 for n in range(1, maximum + 1)}
    for idx, row in enumerate(reversed(rows)):
        for n in row["numbers"]:
            if out[n] == len(rows) + 1:
                out[n] = idx
    return out


def normalise(values: dict[int, float]) -> dict[int, float]:
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi == lo:
        return {k: .5 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


def valid_add(picked: list[int], n: int) -> bool:
    trial = sorted(picked + [n])
    return not any(trial[i] + 1 == trial[i + 1] and trial[i + 1] + 1 == trial[i + 2] for i in range(len(trial) - 2))


def zones(count_: int, maximum: int) -> list[tuple[int, int]]:
    return [(int(i * maximum / count_) + 1, int((i + 1) * maximum / count_)) for i in range(count_)]


def select_ranked(ranked: list[int], count_: int, maximum: int, avoid: list[list[int]] | None = None) -> list[int]:
    avoid = avoid or []
    pos = {n: i for i, n in enumerate(ranked)}
    picked: list[int] = []
    for lo, hi in zones(count_, maximum):
        options = [n for n in ranked if lo <= n <= hi and n not in picked and valid_add(picked, n)]
        if avoid:
            options.sort(key=lambda n: (sum(n in line for line in avoid), pos[n], n))
        if options:
            picked.append(options[0])
    for n in ranked:
        if len(picked) >= count_:
            break
        if n not in picked and valid_add(picked, n):
            picked.append(n)
    return sorted(picked[:count_])


def v1_line(rows: list[dict[str, Any]], game: str, strategy: str, avoid: list[list[int]] | None = None) -> list[int]:
    rule = RULES[game]
    nums = list(range(1, rule["max"] + 1))
    anchor = rows[-1]["date"] if rows else datetime.now(timezone.utc).date().isoformat()
    c_long = counts(rows)
    c_6 = counts(rows, days=183, anchor=anchor)
    c_3 = counts(rows, days=92, anchor=anchor)
    c_recent = counts(rows, limit=10)
    g = gaps(rows, rule["max"])
    if strategy == "Hot 6M":
        ranked = sorted(nums, key=lambda n: (-c_6[n], -c_3[n], -c_recent[n], n))
    elif strategy == "Cold 6M":
        ranked = sorted(nums, key=lambda n: (c_6[n], -g[n], c_3[n], n))
    elif strategy == "Weighted Historical":
        nl = normalise({n: c_long[n] for n in nums})
        n6 = normalise({n: c_6[n] for n in nums})
        nr = normalise({n: c_recent[n] for n in nums})
        ng = normalise(g)
        score = {n: .30*nl[n] + .25*n6[n] + .15*nr[n] + .15*ng[n] + .15*(1-abs((n/(rule["max"]+1))-.5)*2) for n in nums}
        ranked = sorted(nums, key=lambda n: (-score[n], -c_6[n], n))
    else:
        popularity = {n: c_6[n] + c_recent[n] for n in nums}
        ranked = sorted(nums, key=lambda n: (sum(n in line for line in (avoid or [])), popularity[n], n))
    return select_ranked(ranked, rule["count"], rule["max"], avoid if strategy == "Diversified Coverage" else None)


def v1_set(rows: list[dict[str, Any]], game: str) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    generated: list[list[int]] = []
    for strategy in STRATEGIES:
        line = v1_line(rows, game, strategy, generated)
        result[strategy] = line
        generated.append(line)
    return result


def pair_matrix(rows: list[dict[str, Any]]) -> dict[tuple[int, int], float]:
    raw = Counter()
    for row in rows:
        for a, b in combinations(sorted(row["numbers"]), 2):
            raw[(a, b)] += 1
    peak = max(raw.values(), default=1)
    return {key: value / peak for key, value in raw.items()}


def v2_weighted_line(rows: list[dict[str, Any]], game: str, weights: dict[str, float]) -> list[int]:
    rule = RULES[game]
    nums = list(range(1, rule["max"] + 1))
    anchor = rows[-1]["date"] if rows else datetime.now(timezone.utc).date().isoformat()
    c_long = counts(rows)
    c_6 = counts(rows, days=183, anchor=anchor)
    c_recent = counts(rows, limit=10)
    g = gaps(rows, rule["max"])
    nl = normalise({n: c_long[n] for n in nums})
    n6 = normalise({n: c_6[n] for n in nums})
    nr = normalise({n: c_recent[n] for n in nums})
    ng = normalise(g)
    recent_rows = [r for r in rows if datetime.fromisoformat(r["date"]).date() >= datetime.fromisoformat(anchor).date()-timedelta(days=183)]
    pairs = pair_matrix(recent_rows)
    base = {n: weights["long"]*nl[n] + weights["six"]*n6[n] + weights["recent"]*nr[n] + weights["gap"]*ng[n] for n in nums}
    picked: list[int] = []
    for lo, hi in zones(rule["count"], rule["max"]):
        options = [n for n in nums if lo <= n <= hi and n not in picked and valid_add(picked, n)]
        def score(n: int) -> tuple[float, int]:
            affinity = 0.0 if not picked else sum(pairs.get(tuple(sorted((n, p))), 0.0) for p in picked) / len(picked)
            return (base[n] + weights["pair"]*affinity, -n)
        if options:
            picked.append(max(options, key=score))
    for n in sorted(nums, key=lambda n: (-base[n], n)):
        if len(picked) >= rule["count"]:
            break
        if n not in picked and valid_add(picked, n):
            picked.append(n)
    return sorted(picked[:rule["count"]])


def score_line(line: list[int], draw: dict[str, Any]) -> int:
    return len(set(line) & set(draw["numbers"]))


def chance_baseline(game: str) -> dict[str, float]:
    n, m = RULES[game]["max"], RULES[game]["count"]
    denom = math.comb(n, m)
    probs = {}
    for k in range(m + 1):
        probs[k] = math.comb(m, k) * math.comb(n-m, m-k) / denom if m-k <= n-m else 0.0
    return {
        "expected_matches": round(m*m/n, 6),
        "ge2_pct": round(sum(v for k, v in probs.items() if k >= 2)*100, 4),
        "ge3_pct": round(sum(v for k, v in probs.items() if k >= 3)*100, 4),
    }


def metric(matches: list[int], game: str) -> dict[str, Any]:
    samples = len(matches)
    dist = Counter(matches)
    avg = sum(matches) / samples if samples else 0.0
    baseline = chance_baseline(game)
    return {
        "samples": samples,
        "avg_matches": round(avg, 4),
        "ge2_rate": round(sum(m >= 2 for m in matches) / samples * 100, 2) if samples else 0,
        "ge3_rate": round(sum(m >= 3 for m in matches) / samples * 100, 2) if samples else 0,
        "best_matches": max(matches, default=0),
        "distribution": {str(k): dist.get(k, 0) for k in range(RULES[game]["count"] + 1)},
        "expected_matches": baseline["expected_matches"],
        "lift_vs_expected_pct": round((avg / baseline["expected_matches"] - 1) * 100, 2) if samples and baseline["expected_matches"] else 0,
    }


def walk_forward(game: str, rows: list[dict[str, Any]], horizon: int) -> dict[str, dict[str, Any]]:
    start = MIN_TRAIN[game]
    collected = {s: [] for s in STRATEGIES}
    if len(rows) <= start:
        return {s: metric([], game) for s in STRATEGIES}
    idx = start
    while idx < len(rows):
        lines = v1_set(rows[:idx], game)
        for draw in rows[idx:min(idx+horizon, len(rows))]:
            for strategy in STRATEGIES:
                collected[strategy].append(score_line(lines[strategy], draw))
        idx += horizon
    return {s: metric(collected[s], game) for s in STRATEGIES}


def evaluate_weight_candidate(game: str, rows: list[dict[str, Any]], weights: dict[str, float], start: int, end: int) -> dict[str, Any]:
    hits = []
    for idx in range(start, end):
        line = v2_weighted_line(rows[:idx], game, weights)
        hits.append(score_line(line, rows[idx]))
    return metric(hits, game)


def evaluate_v1_weighted(game: str, rows: list[dict[str, Any]], start: int, end: int) -> dict[str, Any]:
    hits = [score_line(v1_line(rows[:idx], game, "Weighted Historical"), rows[idx]) for idx in range(start, end)]
    return metric(hits, game)


def train_challenger(game: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    minimum = MIN_TRAIN[game]
    if len(rows) < minimum + 40:
        return {"status": "insufficient_data", "draws": len(rows), "minimum_needed": minimum + 40}
    validation_start = max(minimum, int(len(rows)*.50))
    test_start = max(validation_start + 20, int(len(rows)*.75))
    if test_start >= len(rows):
        return {"status": "insufficient_data", "draws": len(rows), "minimum_needed": minimum + 40}
    ranked = []
    for weights in WEIGHT_CANDIDATES:
        val = evaluate_weight_candidate(game, rows, weights, validation_start, test_start)
        objective = val["avg_matches"] + val["ge2_rate"] / 10000
        ranked.append((objective, tuple(weights[k] for k in ("long","six","recent","gap","pair")), weights, val))
    ranked.sort(reverse=True, key=lambda item: (item[0], item[1]))
    _, _, best_weights, validation = ranked[0]
    challenger_test = evaluate_weight_candidate(game, rows, best_weights, test_start, len(rows))
    champion_test = evaluate_v1_weighted(game, rows, test_start, len(rows))
    return {
        "status": "candidate",
        "model": "Weighted Historical v2.0 challenger",
        "weights": best_weights,
        "validation_window": {"from": rows[validation_start]["date"], "to": rows[test_start-1]["date"], "metrics": validation},
        "held_out_test": {
            "from": rows[test_start]["date"],
            "to": rows[-1]["date"],
            "challenger": challenger_test,
            "champion_v1": champion_test,
            "promote": False,
            "reason": "Research-only challenger. Promotion requires a pre-defined evidence threshold and sufficient out-of-sample samples.",
        },
    }


def data_quality(game: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "draws": len(rows),
        "first_draw": rows[0]["date"] if rows else None,
        "last_draw": rows[-1]["date"] if rows else None,
        "status": "usable" if len(rows) >= MIN_TRAIN[game] else "insufficient",
        "minimum_training_draws": MIN_TRAIN[game],
    }


def main() -> None:
    histories = {game: game_history(game) for game in RULES}
    walk_rows = []
    best_hold = []
    for game, rows in histories.items():
        for horizon in HORIZONS:
            results = walk_forward(game, rows, horizon)
            for strategy, stats in results.items():
                walk_rows.append({"game": game, "strategy": strategy, "horizon": horizon, **stats})
        for strategy in STRATEGIES:
            candidates = [r for r in walk_rows if r["game"] == game and r["strategy"] == strategy and r["samples"] > 0]
            if candidates:
                best = max(candidates, key=lambda r: (r["avg_matches"], r["ge2_rate"], -r["horizon"]))
                best_hold.append({"game": game, "strategy": strategy, "best_horizon": best["horizon"], "avg_matches": best["avg_matches"], "ge2_rate": best["ge2_rate"], "samples": best["samples"]})

    output = {
        "schema_version": 1,
        "methodology_version": "2.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "null_hypothesis": "Lottery draws are treated as random and independent unless out-of-sample evidence shows otherwise.",
        "live_policy": "The four v1.0 strategies remain frozen champions. Research results do not alter live recommendations automatically.",
        "feedback_policy": "Played-ticket outcomes are used to evaluate models, not as direct number-level features for future recommendations.",
        "data_quality": {game: data_quality(game, rows) for game, rows in histories.items()},
        "chance_baselines": {game: chance_baseline(game) for game in RULES},
        "walk_forward": walk_rows,
        "best_hold": best_hold,
        "challengers": {game: train_challenger(game, rows) for game, rows in histories.items()},
        "notes": [
            "All backtests are walk-forward: a target draw is never visible when its prediction is generated.",
            "Hold horizons compare refreshing every draw with holding the same deterministic recommendation for 2, 4 or 8 draws.",
            "ROI is intentionally not used as the primary research score because lottery payout variance can dominate small samples.",
            "Theoretical chance is a research control only; no random tickets are added to the live portfolio.",
        ],
    }
    OUT_PATH.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({"generated_at": output["generated_at"], "data_quality": output["data_quality"], "research_rows": len(walk_rows)}, indent=2))


if __name__ == "__main__":
    main()
