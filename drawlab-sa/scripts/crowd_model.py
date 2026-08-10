#!/usr/bin/env python3
"""DrawLab Crowd Model v1.0.

Estimates how strongly South African player choices crowd around the *shape* of a
winning line. It does not predict the winning numbers. The target is the ratio
between observed prize-winning tickets and the number expected under uniform
player selection, using exact archived ticket-sales/payout tables.

The model is deliberately small, fixed-feature, ridge-regularised and evaluated
on a chronological hold-out. Its output may guide anti-crowd line construction,
but no crowding uplift is credited to the EV entry gate until prospective
confirmation exists.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import ev_hunter as legacy

ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT / "data" / "ev-history.json"
HISTORY_PATH = ROOT / "data" / "historical-results.json"
CLOUD_PATH = ROOT / "data" / "cloud-state.json"
OUT_PATH = ROOT / "data" / "crowd-state.json"
MODEL_VERSION = "Crowd Model v1.0"
RIDGE = 2.0
FEATURES = [
    "birthday_share",
    "lucky7",
    "round_share",
    "consecutive_rate",
    "same_last_digit_rate",
    "span_norm",
    "sum_norm",
    "odd_imbalance",
    "progression_rate",
    "repeat_prev",
]


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text()) if path.exists() else default
    except Exception:
        return default


def all_draws() -> dict[tuple[str, str], dict[str, Any]]:
    rows = []
    rows.extend(load(HISTORY_PATH, {"results": []}).get("results", []))
    rows.extend(load(CLOUD_PATH, {"results": []}).get("results", []))
    return {
        (r.get("date"), r.get("game")): r
        for r in rows
        if r.get("date") and r.get("game") and isinstance(r.get("numbers"), list)
    }


def previous_draws(draws: dict[tuple[str, str], dict[str, Any]]) -> dict[tuple[str, str], list[int]]:
    out: dict[tuple[str, str], list[int]] = {}
    by_game: dict[str, list[dict[str, Any]]] = {}
    for (_, game), row in draws.items():
        by_game.setdefault(game, []).append(row)
    for game, rows in by_game.items():
        rows.sort(key=lambda r: r["date"])
        prev: list[int] = []
        for row in rows:
            out[(row["date"], game)] = prev
            prev = list(row.get("numbers") or [])
    return out


def arithmetic_triplets(nums: list[int]) -> int:
    s = set(nums)
    count = 0
    for a in nums:
        for b in nums:
            if b <= a:
                continue
            c = 2 * b - a
            if c > b and c in s:
                count += 1
    return count


def line_features(game: str, nums: list[int], previous: list[int] | None = None) -> dict[str, float]:
    previous = previous or []
    maximum = 36 if game == "Daily Lotto" else (52 if game == "Lotto" else 50)
    count = len(nums)
    pair_count = max(1, count * (count - 1) / 2)
    nums = sorted(nums)
    same_last = sum(1 for i, a in enumerate(nums) for b in nums[i + 1 :] if a % 10 == b % 10)
    consecutive = sum(1 for a, b in zip(nums, nums[1:]) if b == a + 1)
    odd = sum(n % 2 for n in nums)
    return {
        "birthday_share": sum(n <= 31 for n in nums) / count,
        "lucky7": 1.0 if 7 in nums else 0.0,
        "round_share": sum(n % 5 == 0 for n in nums) / count,
        "consecutive_rate": consecutive / max(1, count - 1),
        "same_last_digit_rate": same_last / pair_count,
        "span_norm": (max(nums) - min(nums)) / maximum,
        "sum_norm": sum(nums) / (count * maximum),
        "odd_imbalance": abs(odd - count / 2) / (count / 2),
        "progression_rate": arithmetic_triplets(nums) / max(1, count - 2),
        "repeat_prev": len(set(nums) & set(previous)) / count,
    }


def observed_winners(row: dict[str, Any]) -> int:
    return int(sum(int((d or {}).get("winners") or 0) for d in (row.get("divisions") or {}).values()))


def expected_winners(game: str, row: dict[str, Any]) -> float:
    d = datetime.fromisoformat(row["date"]).date()
    probs = legacy.match_probabilities(game, d)
    return float(row.get("equivalent_lines") or 0) * sum(probs.values())


def solve_linear(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    aug = [list(a[i]) + [b[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            continue
        aug[col], aug[pivot] = aug[pivot], aug[col]
        div = aug[col][col]
        aug[col] = [v / div for v in aug[col]]
        for r in range(n):
            if r == col:
                continue
            factor = aug[r][col]
            if factor:
                aug[r] = [x - factor * y for x, y in zip(aug[r], aug[col])]
    return [aug[i][-1] for i in range(n)]


def fit_ridge(rows: list[dict[str, Any]]) -> dict[str, Any]:
    means = {f: sum(r["features"][f] for r in rows) / len(rows) for f in FEATURES}
    stds = {}
    for f in FEATURES:
        var = sum((r["features"][f] - means[f]) ** 2 for r in rows) / max(1, len(rows) - 1)
        stds[f] = math.sqrt(var) if var > 1e-10 else 1.0
    ymean = sum(r["target"] for r in rows) / len(rows)
    xrows = [[(r["features"][f] - means[f]) / stds[f] for f in FEATURES] for r in rows]
    p = len(FEATURES)
    xtx = [[0.0] * p for _ in range(p)]
    xty = [0.0] * p
    for x, r in zip(xrows, rows):
        y = r["target"] - ymean
        for i in range(p):
            xty[i] += x[i] * y
            for j in range(p):
                xtx[i][j] += x[i] * x[j]
    for i in range(p):
        xtx[i][i] += RIDGE
    coefs = solve_linear(xtx, xty)
    return {
        "intercept": ymean,
        "coefficients": {f: coefs[i] for i, f in enumerate(FEATURES)},
        "means": means,
        "stds": stds,
    }


def predict(model: dict[str, Any], features: dict[str, float]) -> float:
    value = float(model["intercept"])
    for f in FEATURES:
        z = (features[f] - float(model["means"][f])) / max(1e-9, float(model["stds"][f]))
        value += float(model["coefficients"][f]) * z
    return value


def rmse(actual: list[float], pred: list[float]) -> float:
    return math.sqrt(sum((a - p) ** 2 for a, p in zip(actual, pred)) / max(1, len(actual)))


def mae(actual: list[float], pred: list[float]) -> float:
    return sum(abs(a - p) for a, p in zip(actual, pred)) / max(1, len(actual))


def training_rows(game: str, cache_rows: list[dict[str, Any]], draws: dict[tuple[str, str], dict[str, Any]], prev_map: dict[tuple[str, str], list[int]]) -> list[dict[str, Any]]:
    output = []
    for econ in sorted((r for r in cache_rows if r.get("game") == game), key=lambda r: r["date"]):
        draw = draws.get((econ["date"], game))
        if not draw:
            continue
        exp = expected_winners(game, econ)
        obs = observed_winners(econ)
        if exp <= 0 or obs < 0:
            continue
        multiplier = (obs + 0.5) / (exp + 0.5)
        output.append({
            "date": econ["date"],
            "observed_winners": obs,
            "expected_uniform": round(exp, 4),
            "crowding_multiplier": round(multiplier, 6),
            "target": math.log(max(1e-6, multiplier)),
            "features": line_features(game, list(draw["numbers"]), prev_map.get((econ["date"], game), [])),
        })
    return output


def analyse_game(game: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len(rows) < 24:
        return {"status": "insufficient_data", "samples": len(rows), "minimum": 24}
    split = max(16, int(len(rows) * 0.75))
    if len(rows) - split < 6:
        split = len(rows) - 6
    train, test = rows[:split], rows[split:]
    model = fit_ridge(train)
    y = [r["target"] for r in test]
    pred = [predict(model, r["features"]) for r in test]
    baseline_value = sum(r["target"] for r in train) / len(train)
    baseline = [baseline_value] * len(test)
    model_rmse, base_rmse = rmse(y, pred), rmse(y, baseline)
    model_mae, base_mae = mae(y, pred), mae(y, baseline)
    improve = (base_rmse - model_rmse) / base_rmse * 100 if base_rmse else 0.0
    improve_mae = (base_mae - model_mae) / base_mae * 100 if base_mae else 0.0
    status = "empirical_signal" if len(rows) >= 60 and improve >= 5 and improve_mae > 0 else "exploratory"
    effects = sorted(model["coefficients"].items(), key=lambda kv: abs(kv[1]), reverse=True)
    return {
        "status": status,
        "samples": len(rows),
        "train_samples": len(train),
        "holdout_samples": len(test),
        "holdout_rmse": round(model_rmse, 5),
        "baseline_rmse": round(base_rmse, 5),
        "holdout_improvement_pct": round(improve, 2),
        "holdout_mae_improvement_pct": round(improve_mae, 2),
        "target": "log(observed prize winners / uniform-choice expected prize winners)",
        "model": {
            "intercept": round(model["intercept"], 8),
            "coefficients": {k: round(v, 8) for k, v in model["coefficients"].items()},
            "means": {k: round(v, 8) for k, v in model["means"].items()},
            "stds": {k: round(v, 8) for k, v in model["stds"].items()},
        },
        "largest_effects": [
            {"feature": f, "coefficient": round(c, 5), "direction": "more_crowded" if c > 0 else "less_crowded"}
            for f, c in effects[:5]
        ],
        "interpretation": "A positive coefficient means the feature was associated with more prize-winning tickets than uniform player choice would predict. This is player-behaviour research, not draw prediction.",
    }


def main() -> None:
    cache = load(CACHE_PATH, {"rows": []})
    draws = all_draws()
    prev = previous_draws(draws)
    games = {}
    for game in legacy.RULES:
        rows = training_rows(game, cache.get("rows", []), draws, prev)
        games[game] = analyse_game(game, rows)
    payload = {
        "schema_version": 1,
        "model_version": MODEL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Estimate player-choice crowding from South African ticket sales and winner counts; never used as evidence that a line is more likely to be drawn.",
        "games": games,
        "feature_policy": FEATURES,
        "use_policy": "Empirical crowd scores may rank equal-probability lines for prize-sharing research. No crowding uplift is credited to the EV entry gate until separately confirmed prospectively.",
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({g: {k: v for k, v in r.items() if k in {"status", "samples", "holdout_samples", "holdout_improvement_pct"}} for g, r in games.items()}, indent=2))


if __name__ == "__main__":
    main()
