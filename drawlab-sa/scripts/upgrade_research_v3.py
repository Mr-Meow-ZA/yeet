#!/usr/bin/env python3
from pathlib import Path

P = Path(__file__).with_name('research_engine.py')
s = P.read_text()

s = s.replace(
    'HORIZONS = (1, 2, 4, 8)\n',
    'HORIZONS = (1, 2, 4, 8, 20)\nWALK_COMPARISONS = len(STRATEGIES) * (len(HORIZONS) + 1)\n'
)

old = '''def walk_forward(game: str, rows: list[dict[str, Any]], horizon: int) -> dict[str, dict[str, Any]]:
    start = MIN_TRAIN[game]
    collected = {s: [] for s in STRATEGIES}
    if len(rows) <= start:
        return {s: metric([], game, comparisons=16) for s in STRATEGIES}
    idx = start
    while idx < len(rows):
        lines = v1_set(rows[:idx], game)
        for draw in rows[idx:min(idx+horizon, len(rows))]:
            for strategy in STRATEGIES:
                collected[strategy].append(score_line(lines[strategy], draw))
        idx += horizon
    return {s: metric(collected[s], game, comparisons=16) for s in STRATEGIES}
'''
new = '''def walk_forward(game: str, rows: list[dict[str, Any]], horizon: int | None) -> dict[str, dict[str, Any]]:
    """Replay one refresh policy without future leakage.

    horizon=None is the true never-refresh control: each strategy is generated
    once at the first eligible target draw and then held for the rest of the
    compatible rule era. Numeric horizons regenerate only after that many
    unseen draws have been scored.
    """
    start = MIN_TRAIN[game]
    collected = {s: [] for s in STRATEGIES}
    if len(rows) <= start:
        return {s: metric([], game, comparisons=WALK_COMPARISONS) for s in STRATEGIES}
    if horizon is None:
        lines = v1_set(rows[:start], game)
        for draw in rows[start:]:
            for strategy in STRATEGIES:
                collected[strategy].append(score_line(lines[strategy], draw))
        return {s: metric(collected[s], game, comparisons=WALK_COMPARISONS) for s in STRATEGIES}
    idx = start
    while idx < len(rows):
        lines = v1_set(rows[:idx], game)
        for draw in rows[idx:min(idx+horizon, len(rows))]:
            for strategy in STRATEGIES:
                collected[strategy].append(score_line(lines[strategy], draw))
        idx += horizon
    return {s: metric(collected[s], game, comparisons=WALK_COMPARISONS) for s in STRATEGIES}
'''
if old not in s:
    raise SystemExit('walk_forward block not found')
s = s.replace(old, new)

old = '''        for horizon in HORIZONS:
            results = walk_forward(game, rows, horizon)
            for strategy, stats in results.items():
                walk_rows.append({"game": game, "strategy": strategy, "horizon": horizon, **stats})
        for strategy in STRATEGIES:
            candidates = [r for r in walk_rows if r["game"] == game and r["strategy"] == strategy and r["samples"] > 0]
            if candidates:
                best = max(candidates, key=lambda r: (r["avg_matches"], r["ge2_rate"], -r["horizon"]))
                best_hold.append({"game": game, "strategy": strategy, "best_horizon": best["horizon"], "avg_matches": best["avg_matches"], "ge2_rate": best["ge2_rate"], "samples": best["samples"], "p_adjusted": best["p_adjusted"], "evidence": best["evidence"]})
'''
new = '''        for horizon in (*HORIZONS, None):
            results = walk_forward(game, rows, horizon)
            label = "never" if horizon is None else horizon
            for strategy, stats in results.items():
                walk_rows.append({"game": game, "strategy": strategy, "horizon": label, **stats})
        for strategy in STRATEGIES:
            candidates = [r for r in walk_rows if r["game"] == game and r["strategy"] == strategy and r["samples"] > 0]
            if candidates:
                def hold_order(row: dict[str, Any]) -> int:
                    return 999999 if row["horizon"] == "never" else int(row["horizon"])
                best = max(candidates, key=lambda r: (r["avg_matches"], r["ge2_rate"], -hold_order(r)))
                best_hold.append({"game": game, "strategy": strategy, "best_horizon": best["horizon"], "avg_matches": best["avg_matches"], "ge2_rate": best["ge2_rate"], "samples": best["samples"], "p_adjusted": best["p_adjusted"], "evidence": best["evidence"]})
'''
if old not in s:
    raise SystemExit('main horizon block not found')
s = s.replace(old, new)

s = s.replace('"schema_version": 1,\n        "methodology_version": "2.0",', '"schema_version": 2,\n        "methodology_version": "3.0",')
s = s.replace(
    '"live_policy": "The four v1.0 strategies remain frozen champions. Research results do not alter live recommendations automatically.",',
    '"live_policy": "The four dynamic v1.0 strategies plus Frozen Alpha v1.0 remain locked live competitors. Research results do not alter them automatically.",'
)
s = s.replace(
    '"Hold horizons compare refreshing every draw with holding the same deterministic recommendation for 2, 4 or 8 draws.",',
    '"Hold policies compare refreshing every 1, 2, 4, 8 or 20 draws with a true never-refresh control within a compatible rule era.",'
)

P.write_text(s)
print('Upgraded research_engine.py to v3 hold policies')
