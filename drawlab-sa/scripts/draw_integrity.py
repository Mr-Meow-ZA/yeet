#!/usr/bin/env python3
"""DrawLab Draw Integrity Auditor v1.0.

Tests whether the observed draw archive is broadly consistent with the current
lottery rules. This is a falsification tool, not a number predictor. It uses
conservative multiple-testing corrections and reports anomalies for review
instead of feeding them automatically into the live strategy league.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import date, datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / "data" / "historical-results.json"
CLOUD = ROOT / "data" / "cloud-state.json"
OUT = ROOT / "data" / "integrity-state.json"
RULE_CHANGE = date(2026, 6, 1)
MODEL_VERSION = "Draw Integrity Auditor v1.0"
RULES = {
    "Daily Lotto": {"count": 5, "max": 36, "min_draws": 90},
    "Lotto": {"count": 6, "max": 52, "min_draws": 60},
    "PowerBall": {"count": 5, "max": 50, "min_draws": 90},
}


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text()) if path.exists() else default
    except Exception:
        return default


def norm_two_sided(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2.0))


def poisson_tail_at_least(k: int, lam: float) -> float:
    if k <= 0:
        return 1.0
    if lam <= 0:
        return 0.0
    # P(X >= k) = 1 - sum_0^(k-1)
    term = math.exp(-lam)
    cdf = term
    for i in range(1, k):
        term *= lam / i
        cdf += term
    return max(0.0, min(1.0, 1.0 - cdf))


def rows() -> list[dict[str, Any]]:
    all_rows = []
    all_rows.extend(load(HISTORY, {"results": []}).get("results", []))
    all_rows.extend(load(CLOUD, {"results": []}).get("results", []))
    dedup = {(r.get("date"), r.get("game")): r for r in all_rows if r.get("date") and r.get("game")}
    return sorted(dedup.values(), key=lambda r: (r.get("date", ""), r.get("game", "")))


def eligible(game: str, row: dict[str, Any]) -> bool:
    try:
        d = datetime.fromisoformat(row.get("date", "")).date()
    except Exception:
        return False
    rule = RULES[game]
    nums = row.get("numbers")
    if game == "Lotto" and d < RULE_CHANGE:
        return False
    if not isinstance(nums, list) or len(nums) != rule["count"] or len(set(nums)) != rule["count"]:
        return False
    return all(isinstance(n, int) and 1 <= n <= rule["max"] for n in nums)


def frequency_test(game: str, game_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rule = RULES[game]
    dcount = len(game_rows)
    p = rule["count"] / rule["max"]
    expected = dcount * p
    sd = math.sqrt(dcount * p * (1 - p))
    counts = Counter(n for r in game_rows for n in r["numbers"])
    tests = []
    for n in range(1, rule["max"] + 1):
        z = (counts[n] - expected) / sd if sd else 0.0
        raw = norm_two_sided(z)
        tests.append((raw, n, counts[n], z))
    raw, number, observed, z = min(tests)
    adjusted = min(1.0, raw * rule["max"])
    return {
        "expected_per_number": round(expected, 3),
        "most_extreme_number": number,
        "observed": observed,
        "z_score": round(z, 4),
        "p_raw": round(raw, 8),
        "p_adjusted": round(adjusted, 8),
        "comparisons": rule["max"],
    }


def pair_test(game: str, game_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rule = RULES[game]
    dcount = len(game_rows)
    prob = rule["count"] * (rule["count"] - 1) / (rule["max"] * (rule["max"] - 1))
    expected = dcount * prob
    sd = math.sqrt(dcount * prob * (1 - prob))
    counts: Counter[tuple[int, int]] = Counter()
    for r in game_rows:
        for pair in combinations(sorted(r["numbers"]), 2):
            counts[pair] += 1
    all_pairs = list(combinations(range(1, rule["max"] + 1), 2))
    tests = []
    for pair in all_pairs:
        observed = counts[pair]
        z = (observed - expected) / sd if sd else 0.0
        raw = norm_two_sided(z)
        tests.append((raw, pair, observed, z))
    raw, pair, observed, z = min(tests)
    adjusted = min(1.0, raw * len(all_pairs))
    return {
        "expected_per_pair": round(expected, 4),
        "most_extreme_pair": list(pair),
        "observed": observed,
        "z_score": round(z, 4),
        "p_raw": round(raw, 10),
        "p_adjusted": round(adjusted, 8),
        "comparisons": len(all_pairs),
    }


def overlap_test(game: str, game_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rule = RULES[game]
    overlaps = [len(set(a["numbers"]) & set(b["numbers"])) for a, b in zip(game_rows, game_rows[1:])]
    if not overlaps:
        return {"samples": 0, "p_value": None}
    m, n = rule["count"], rule["max"]
    expected = m * m / n
    variance = m * (m / n) * (1 - m / n) * ((n - m) / (n - 1))
    observed = sum(overlaps) / len(overlaps)
    se = math.sqrt(variance / len(overlaps)) if variance > 0 else 0.0
    z = (observed - expected) / se if se else 0.0
    return {
        "samples": len(overlaps),
        "expected_overlap": round(expected, 6),
        "observed_overlap": round(observed, 6),
        "z_score": round(z, 4),
        "p_value": round(norm_two_sided(z), 8),
    }


def duplicate_test(game: str, game_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rule = RULES[game]
    counts = Counter(tuple(sorted(r["numbers"])) for r in game_rows)
    observed_pairs = sum(c * (c - 1) // 2 for c in counts.values() if c > 1)
    universe = math.comb(rule["max"], rule["count"])
    draw_pairs = len(game_rows) * (len(game_rows) - 1) / 2
    expected_pairs = draw_pairs / universe
    p = poisson_tail_at_least(observed_pairs, expected_pairs)
    return {
        "observed_duplicate_pairs": int(observed_pairs),
        "expected_duplicate_pairs": round(expected_pairs, 8),
        "p_value": round(p, 8),
    }


def bonus_test(game_rows: list[dict[str, Any]]) -> dict[str, Any]:
    current = []
    for r in game_rows:
        try:
            d = datetime.fromisoformat(r["date"]).date()
        except Exception:
            continue
        if d >= RULE_CHANGE and isinstance(r.get("bonus"), int) and 1 <= r["bonus"] <= 16:
            current.append(r["bonus"])
    if len(current) < 30:
        return {"status": "insufficient_data", "samples": len(current), "minimum": 30}
    counts = Counter(current)
    expected = len(current) / 16
    p = 1 / 16
    sd = math.sqrt(len(current) * p * (1 - p))
    tests = []
    for n in range(1, 17):
        z = (counts[n] - expected) / sd if sd else 0.0
        raw = norm_two_sided(z)
        tests.append((raw, n, counts[n], z))
    raw, number, observed, z = min(tests)
    return {
        "status": "tested",
        "samples": len(current),
        "expected_per_ball": round(expected, 3),
        "most_extreme_ball": number,
        "observed": observed,
        "z_score": round(z, 4),
        "p_adjusted": round(min(1.0, raw * 16), 8),
        "comparisons": 16,
    }


def analyse(game: str, all_rows: list[dict[str, Any]]) -> dict[str, Any]:
    data = [r for r in all_rows if r.get("game") == game and eligible(game, r)]
    minimum = RULES[game]["min_draws"]
    if len(data) < minimum:
        return {
            "status": "insufficient_data",
            "draws": len(data),
            "minimum": minimum,
            "rule_scope": "current legal number space only",
        }
    freq = frequency_test(game, data)
    pair = pair_test(game, data)
    overlap = overlap_test(game, data)
    dup = duplicate_test(game, data)
    pvals = [freq["p_adjusted"], pair["p_adjusted"], overlap.get("p_value", 1.0), dup.get("p_value", 1.0)]
    bonus = bonus_test(data) if game == "PowerBall" else None
    if bonus and bonus.get("p_adjusted") is not None:
        pvals.append(bonus["p_adjusted"])
    min_p = min(float(p) for p in pvals if p is not None)
    status = "review" if min_p < 0.01 else ("watch" if min_p < 0.05 else "consistent_with_randomness")
    return {
        "status": status,
        "draws": len(data),
        "first_draw": data[0]["date"],
        "last_draw": data[-1]["date"],
        "frequency": freq,
        "pairs": pair,
        "serial_overlap": overlap,
        "duplicates": dup,
        "powerball_special": bonus,
        "minimum_adjusted_p": round(min_p, 8),
        "interpretation": "Passing these tests does not prove perfect randomness; it means this archive does not currently show a corrected anomaly large enough to reject the random/independent null on these predeclared diagnostics.",
    }


def main() -> None:
    data = rows()
    games = {game: analyse(game, data) for game in RULES}
    overall = "review" if any(v.get("status") == "review" for v in games.values()) else (
        "watch" if any(v.get("status") == "watch" for v in games.values()) else "consistent_with_randomness"
    )
    payload = {
        "schema_version": 1,
        "model_version": MODEL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "null_hypothesis": "Draws are random and independent within each compatible rule era.",
        "overall_status": overall,
        "games": games,
        "tests": ["individual-number frequency", "pair frequency", "consecutive-draw overlap", "exact-line duplicates", "current PowerBall special-ball frequency"],
        "policy": "No integrity result automatically changes live recommendations. Any flagged anomaly requires independent verification, source-quality checks and prospective confirmation.",
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({g: {"status": v.get("status"), "draws": v.get("draws"), "minimum_adjusted_p": v.get("minimum_adjusted_p")} for g, v in games.items()}, indent=2))


if __name__ == "__main__":
    main()
