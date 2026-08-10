#!/usr/bin/env python3
"""DrawLab strategy discovery engine.

Searches a small, pre-declared set of interpretable challenger families using
historical data only. Candidate selection happens on a validation window and the
selected model is judged once on a later untouched hold-out window.

This script never mutates live strategy definitions or live tickets. It appends
research-only discovery output to data/research-state.json.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from research_engine import (
    MIN_TRAIN,
    RULES,
    STRATEGIES,
    chance_baseline,
    game_history,
    gaps,
    metric,
    normalise,
    score_line,
    select_ranked,
    v1_set,
)

ROOT = Path(__file__).resolve().parents[1]
RESEARCH_PATH = ROOT / "data" / "research-state.json"


def candidate_catalog() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    # Smooth momentum. Half-life is measured in historical draws, not days.
    for half_life in (8, 16, 32, 64):
        for gap_weight in (0.0, 0.15):
            out.append({
                "id": f"ewma_momentum_h{half_life}_g{int(gap_weight*100)}",
                "name": f"EWMA Momentum h{half_life}" + (" + gap" if gap_weight else ""),
                "family": "EWMA Momentum",
                "params": {"half_life": half_life, "gap_weight": gap_weight},
            })

    # Mean-reversion hypotheses. These are explicitly research-only because an
    # independent lottery does not make an underrepresented number 'due'.
    for window in (30, 60, 120, 180):
        for gap_weight in (0.30, 0.50):
            out.append({
                "id": f"frequency_reversion_w{window}_g{int(gap_weight*100)}",
                "name": f"Frequency Reversion {window}" + (" strong gap" if gap_weight >= .5 else ""),
                "family": "Frequency Reversion",
                "params": {"window": window, "gap_weight": gap_weight},
            })

    # Fast-vs-slow trend models, in both momentum and reversion directions.
    for fast, slow in ((8, 40), (16, 80), (32, 160)):
        out.append({
            "id": f"trend_momentum_{fast}_{slow}",
            "name": f"Trend Momentum {fast}/{slow}",
            "family": "Trend",
            "params": {"fast": fast, "slow": slow, "direction": 1},
        })
        out.append({
            "id": f"trend_reversion_{fast}_{slow}",
            "name": f"Trend Reversion {fast}/{slow}",
            "family": "Trend",
            "params": {"fast": fast, "slow": slow, "direction": -1},
        })

    # Conditional transition-response models: do numbers following recent draw
    # numbers repeat more often than the null would imply?
    for memory in (1, 3):
        out.append({
            "id": f"transition_response_m{memory}",
            "name": f"Transition Response m{memory}",
            "family": "Transition Response",
            "params": {"memory": memory},
        })

    # Empirical recurrence hazard: estimate whether a number's observed gap has
    # historically been followed by a hit at a different rate than average.
    for band in (2, 4):
        out.append({
            "id": f"gap_hazard_b{band}",
            "name": f"Gap Hazard ±{band}",
            "family": "Gap Hazard",
            "params": {"band": band},
        })

    return out


CANDIDATES = candidate_catalog()
MULTIPLE_COMPARISONS = len(CANDIDATES)


def ewma_feature(rows: list[dict[str, Any]], maximum: int, half_life: float) -> dict[int, float]:
    raw = {n: 0.0 for n in range(1, maximum + 1)}
    if not rows:
        return {n: .5 for n in raw}
    for age, row in enumerate(reversed(rows)):
        weight = 0.5 ** (age / max(1.0, half_life))
        if weight < 1e-5:
            break
        for n in row["numbers"]:
            if n in raw:
                raw[n] += weight
    return normalise(raw)


def residual_feature(rows: list[dict[str, Any]], game: str, window: int) -> dict[int, float]:
    rule = RULES[game]
    maximum, count_ = rule["max"], rule["count"]
    selected = rows[-window:]
    n_draws = len(selected)
    if not n_draws:
        return {n: .5 for n in range(1, maximum + 1)}
    c = Counter(n for row in selected for n in row["numbers"])
    p = count_ / maximum
    sd = math.sqrt(max(n_draws * p * (1 - p), 1e-9))
    z = {n: (c[n] - n_draws * p) / sd for n in range(1, maximum + 1)}
    return normalise(z)


def transition_feature(rows: list[dict[str, Any]], game: str, memory: int) -> dict[int, float]:
    maximum = RULES[game]["max"]
    raw = {n: 0.0 for n in range(1, maximum + 1)}
    if len(rows) < 3:
        return {n: .5 for n in raw}

    transitions: dict[int, Counter] = defaultdict(Counter)
    source_counts = Counter()
    for prev, nxt in zip(rows[:-1], rows[1:]):
        for a in prev["numbers"]:
            source_counts[a] += 1
            for b in nxt["numbers"]:
                if b <= maximum:
                    transitions[a][b] += 1

    recent = rows[-memory:]
    for age, row in enumerate(reversed(recent)):
        recency = 1.0 / (age + 1)
        for a in row["numbers"]:
            denom = max(1, source_counts[a])
            for b, count_ in transitions.get(a, {}).items():
                raw[b] += recency * count_ / denom
    return normalise(raw)


def empirical_gap_hazard(rows: list[dict[str, Any]], game: str, band: int) -> dict[int, float]:
    """Estimate next-draw hit rate around each number's current historical gap."""
    maximum = RULES[game]["max"]
    if len(rows) < 25:
        return {n: .5 for n in range(1, maximum + 1)}

    current = gaps(rows, maximum)
    opportunities: dict[int, Counter] = {n: Counter() for n in range(1, maximum + 1)}
    last_seen = {n: None for n in range(1, maximum + 1)}

    # At each historical step record the gap before the next draw and whether
    # the number then appeared. This uses only history preceding the target.
    for idx, row in enumerate(rows):
        present = set(row["numbers"])
        if idx > 0:
            for n in range(1, maximum + 1):
                if last_seen[n] is None:
                    continue
                gap_before = idx - last_seen[n] - 1
                key = int(gap_before)
                opportunities[n][("opp", key)] += 1
                if n in present:
                    opportunities[n][("hit", key)] += 1
        for n in present:
            if n <= maximum:
                last_seen[n] = idx

    raw: dict[int, float] = {}
    base = RULES[game]["count"] / maximum
    for n in range(1, maximum + 1):
        cg = current[n]
        opp = hit = 0
        stats = opportunities[n]
        for g in range(max(0, cg - band), cg + band + 1):
            opp += stats[("opp", g)]
            hit += stats[("hit", g)]
        # Conservative shrinkage toward the theoretical base rate.
        raw[n] = (hit + 12 * base) / (opp + 12) if opp else base
    return normalise(raw)


def candidate_line(rows: list[dict[str, Any]], game: str, candidate: dict[str, Any]) -> list[int]:
    rule = RULES[game]
    maximum, count_ = rule["max"], rule["count"]
    nums = list(range(1, maximum + 1))
    g = normalise(gaps(rows, maximum))
    family = candidate["family"]
    p = candidate["params"]

    if family == "EWMA Momentum":
        e = ewma_feature(rows, maximum, p["half_life"])
        gw = p["gap_weight"]
        score = {n: (1 - gw) * e[n] + gw * g[n] for n in nums}

    elif family == "Frequency Reversion":
        residual = residual_feature(rows, game, p["window"])
        gw = p["gap_weight"]
        score = {n: (1 - gw) * (1 - residual[n]) + gw * g[n] for n in nums}

    elif family == "Trend":
        fast = ewma_feature(rows, maximum, p["fast"])
        slow = ewma_feature(rows, maximum, p["slow"])
        trend = normalise({n: fast[n] - slow[n] for n in nums})
        if p["direction"] > 0:
            score = {n: .65 * trend[n] + .35 * slow[n] for n in nums}
        else:
            score = {n: .65 * (1 - trend[n]) + .35 * slow[n] for n in nums}

    elif family == "Transition Response":
        trans = transition_feature(rows, game, p["memory"])
        base = ewma_feature(rows, maximum, 32)
        score = {n: .65 * trans[n] + .25 * base[n] + .10 * g[n] for n in nums}

    elif family == "Gap Hazard":
        hazard = empirical_gap_hazard(rows, game, p["band"])
        base = ewma_feature(rows, maximum, 64)
        score = {n: .70 * hazard[n] + .20 * base[n] + .10 * g[n] for n in nums}

    else:
        raise ValueError(f"unknown candidate family: {family}")

    ranked = sorted(nums, key=lambda n: (-score[n], n))
    return select_ranked(ranked, count_, maximum)


def evaluate_candidate(
    game: str,
    rows: list[dict[str, Any]],
    candidate: dict[str, Any],
    start: int,
    end: int,
    *,
    comparisons: int = 1,
) -> tuple[dict[str, Any], list[int]]:
    hits: list[int] = []
    for idx in range(start, end):
        line = candidate_line(rows[:idx], game, candidate)
        hits.append(score_line(line, rows[idx]))
    return metric(hits, game, comparisons=comparisons), hits


def validation_objective(stats: dict[str, Any], hits: list[int]) -> float:
    if not hits:
        return -999.0
    split = max(1, len(hits) // 2)
    first = sum(hits[:split]) / len(hits[:split])
    second = sum(hits[split:]) / max(1, len(hits[split:]))
    stable_floor = min(first, second)
    # Main-number match expectation remains primary. The tiny >=2 term only
    # breaks near-ties and cannot dominate the score.
    return .75 * stats["avg_matches"] + .25 * stable_floor + stats["ge2_rate"] / 100000


def evaluate_v1_baselines(game: str, rows: list[dict[str, Any]], start: int, end: int) -> dict[str, Any]:
    collected = {s: [] for s in STRATEGIES}
    for idx in range(start, end):
        lines = v1_set(rows[:idx], game)
        draw = rows[idx]
        for s in STRATEGIES:
            collected[s].append(score_line(lines[s], draw))
    out = {s: metric(hits, game) for s, hits in collected.items()}
    best_name = max(out, key=lambda s: (out[s]["avg_matches"], out[s]["ge2_rate"], s))
    return {"strategies": out, "best": {"strategy": best_name, **out[best_name]}}


def discover_game(game: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    minimum = MIN_TRAIN[game]
    # We need enough room for meaningful validation and a genuinely later test.
    if len(rows) < minimum + 80:
        return {
            "status": "insufficient_data",
            "draws": len(rows),
            "minimum_needed": minimum + 80,
            "reason": "Not enough compatible-rule draws for train/validation/test discovery.",
        }

    validation_start = max(minimum, int(len(rows) * .45))
    test_start = max(validation_start + 40, int(len(rows) * .72))
    if test_start >= len(rows) - 20:
        return {
            "status": "insufficient_data",
            "draws": len(rows),
            "minimum_needed": minimum + 80,
            "reason": "Hold-out window would be too small.",
        }

    ranked: list[dict[str, Any]] = []
    for candidate in CANDIDATES:
        stats, hits = evaluate_candidate(game, rows, candidate, validation_start, test_start, comparisons=MULTIPLE_COMPARISONS)
        ranked.append({
            "candidate": candidate,
            "validation": stats,
            "objective": round(validation_objective(stats, hits), 6),
        })
    ranked.sort(key=lambda x: (x["objective"], x["validation"]["ge2_rate"], x["candidate"]["id"]), reverse=True)

    selected = ranked[0]["candidate"]
    selected_validation = ranked[0]["validation"]
    test, _ = evaluate_candidate(game, rows, selected, test_start, len(rows), comparisons=MULTIPLE_COMPARISONS)
    baselines = evaluate_v1_baselines(game, rows, test_start, len(rows))
    best_v1 = baselines["best"]
    expected = chance_baseline(game)["expected_matches"]

    delta_v1 = test["avg_matches"] - best_v1["avg_matches"]
    delta_chance = test["avg_matches"] - expected
    enough = test["samples"] >= 100
    statistically_positive = test["p_adjusted"] < .05 and delta_chance > 0

    if enough and statistically_positive and delta_v1 > 0:
        status = "promotion_candidate"
    elif delta_v1 > 0 and delta_chance > 0:
        status = "promising_unproven"
    elif test["samples"] < 100 and delta_v1 > 0:
        status = "early_promising"
    else:
        status = "no_improvement"

    return {
        "status": status,
        "candidate_count": len(CANDIDATES),
        "selected": selected,
        "development_window": {
            "from": rows[0]["date"],
            "to": rows[validation_start - 1]["date"],
            "draws_available_before_validation": validation_start,
        },
        "validation_window": {
            "from": rows[validation_start]["date"],
            "to": rows[test_start - 1]["date"],
            "selected_metrics": selected_validation,
        },
        "held_out_test": {
            "from": rows[test_start]["date"],
            "to": rows[-1]["date"],
            "candidate": test,
            "best_current_v1": best_v1,
            "all_current_v1": baselines["strategies"],
            "delta_avg_matches_vs_best_v1": round(delta_v1, 4),
            "delta_avg_matches_vs_chance": round(delta_chance, 4),
            "promotion_ready": status == "promotion_candidate",
        },
        "validation_leaderboard": [
            {
                "rank": i + 1,
                "id": row["candidate"]["id"],
                "name": row["candidate"]["name"],
                "family": row["candidate"]["family"],
                "objective": row["objective"],
                "avg_matches": row["validation"]["avg_matches"],
                "ge2_rate": row["validation"]["ge2_rate"],
                "evidence": row["validation"]["evidence"],
            }
            for i, row in enumerate(ranked[:5])
        ],
        "interpretation": (
            "A candidate is selected only on the validation window. The later hold-out window is then opened once. "
            "No live strategy is changed automatically, even if a challenger looks better."
        ),
    }


def main() -> None:
    state = json.loads(RESEARCH_PATH.read_text())
    histories = {game: game_history(game) for game in RULES}
    discovery = {
        "methodology_version": "1.0",
        "candidate_count": len(CANDIDATES),
        "candidate_families": sorted({c["family"] for c in CANDIDATES}),
        "selection_rule": "Select on validation stability and main-number matches; judge exactly once on later untouched draws.",
        "promotion_rule": "Never auto-promote. Promotion requires sufficient held-out samples, multiple-testing-adjusted evidence above chance, and improvement over the best locked v1 comparator.",
        "games": {game: discover_game(game, rows) for game, rows in histories.items()},
        "notes": [
            "Candidate families are pre-declared before the held-out test is inspected.",
            "The search optimizes main-number match behaviour, not retrospective jackpot ROI.",
            "Every candidate still has the same base mathematical lottery odds as any other valid line.",
            "Current-format Lotto remains data-limited and is not optimized using incompatible legacy 6/58 outcomes.",
        ],
    }
    state["strategy_discovery"] = discovery
    RESEARCH_PATH.write_text(json.dumps(state, indent=2) + "\n")
    summary = {
        game: {
            "status": result.get("status"),
            "selected": (result.get("selected") or {}).get("name"),
            "test_avg": ((result.get("held_out_test") or {}).get("candidate") or {}).get("avg_matches"),
            "best_v1_avg": ((result.get("held_out_test") or {}).get("best_current_v1") or {}).get("avg_matches"),
        }
        for game, result in discovery["games"].items()
    }
    print(json.dumps({"candidate_count": len(CANDIDATES), "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
