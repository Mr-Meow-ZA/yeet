#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGE = "2026-06-01"


def between(text: str, start: str, end: str, replacement: str) -> str:
    a = text.find(start)
    if a < 0:
        raise RuntimeError(f"Missing start marker: {start}")
    b = text.find(end, a)
    if b < 0:
        raise RuntimeError(f"Missing end marker: {end}")
    return text[:a] + replacement.rstrip() + "\n\n\n" + text[b:]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            return text
        raise RuntimeError(f"Missing {label}")
    return text.replace(old, new, 1)


def patch_cloud() -> None:
    path = ROOT / "scripts" / "update_cloud.py"
    text = path.read_text()
    text = replace_once(
        text,
        'HTTP_TIMEOUT = (5, 9)\n',
        'HTTP_TIMEOUT = (5, 9)\nRULE_CHANGE_DATE = datetime(2026, 6, 1).date()\nDATA_POLICY_VERSION = "2.0-rule-aware"\n',
        "cloud constants",
    )
    text = replace_once(
        text,
        '"PowerBall": {"count": 5, "max": 50, "days": {1, 4}, "bonus_max": 20, "cost": 5},',
        '"PowerBall": {"count": 5, "max": 50, "days": {1, 4}, "bonus_max": 16, "cost": 10},',
        "current PowerBall rules",
    )

    valid_block = '''def history_limits(game, date_str):
    try:
        draw_date = datetime.fromisoformat(str(date_str)).date()
    except (TypeError, ValueError):
        return None, None
    if game == "Lotto":
        return (58 if draw_date < RULE_CHANGE_DATE else 52), None
    if game == "PowerBall":
        return 50, (20 if draw_date < RULE_CHANGE_DATE else 16)
    return 36, None


def valid_history_row(row, game):
    rule = RULES[game]
    numbers = row.get("numbers")
    maximum, historical_bonus_max = history_limits(game, row.get("date"))
    if maximum is None:
        return False
    if not isinstance(numbers, list) or len(numbers) != rule["count"]:
        return False
    if len(set(numbers)) != len(numbers):
        return False
    if any(not isinstance(n, int) or not 1 <= n <= maximum for n in numbers):
        return False
    try:
        datetime.fromisoformat(row.get("date", ""))
    except (TypeError, ValueError):
        return False
    if game == "PowerBall":
        bonus = row.get("bonus")
        if not isinstance(bonus, int) or historical_bonus_max is None or not 1 <= bonus <= historical_bonus_max:
            return False
    return True'''
    text = between(text, "def valid_history_row", "def load_valid_history", valid_block)

    load_block = '''def load_valid_history():
    global _HISTORY_CACHE, _HISTORY_QUALITY
    if _HISTORY_CACHE is not None:
        return _HISTORY_CACHE

    accepted = []
    quality = {}
    raw_rows = []
    if HISTORY_PATH.exists():
        try:
            raw_rows = json.loads(HISTORY_PATH.read_text()).get("results", [])
        except Exception:
            raw_rows = []

    for game in RULES:
        candidate = [row for row in raw_rows if row.get("game") == game and valid_history_row(row, game)]
        line_counts = Counter(tuple(row["numbers"]) for row in candidate)
        bad_lines = {line for line, count in line_counts.items() if count > 2}
        clean = [row for row in candidate if tuple(row["numbers"]) not in bad_lines]
        accepted.extend(clean)
        eligible = clean
        if game == "Lotto":
            eligible = [row for row in clean if datetime.fromisoformat(row["date"]).date() >= RULE_CHANGE_DATE]
        quality[game] = {
            "raw": sum(1 for row in raw_rows if row.get("game") == game),
            "accepted": len(clean),
            "model_eligible": len(eligible),
            "rejected": sum(1 for row in raw_rows if row.get("game") == game) - len(clean),
            "status": "usable" if eligible else "unavailable",
            "rule_scope": "current 6/52 era from 2026-06-01" if game == "Lotto" else ("5/50 main history; current PB 1-16 from 2026-06-01" if game == "PowerBall" else "5/36 unchanged"),
        }

    _HISTORY_CACHE = accepted
    _HISTORY_QUALITY = quality
    return accepted'''
    text = between(text, "def load_valid_history", "def historical_results", load_block)

    history_block = '''def historical_results(state, game):
    rows = [
        row
        for row in state.get("results", [])
        if row.get("game") == game and valid_history_row(row, game)
    ]
    rows.extend(row for row in load_valid_history() if row.get("game") == game)
    dedup = {(row.get("date"), row.get("game")): row for row in rows}
    rows = sorted(dedup.values(), key=lambda row: row["date"], reverse=True)
    if game == "Lotto":
        rows = [row for row in rows if datetime.fromisoformat(row["date"]).date() >= RULE_CHANGE_DATE]
    return rows'''
    text = between(text, "def historical_results", "def counts_for_window", history_block)

    bonus_block = '''def bonus_number(rows, strategy, maximum):
    # The PowerBall pool changed from 1-20 to 1-16 on 1 June 2026.
    # Main-number history can span both eras, but special-ball ranking must not.
    rows = [row for row in rows if datetime.fromisoformat(row["date"]).date() >= RULE_CHANGE_DATE]
    counts = Counter(
        row.get("bonus")
        for row in rows
        if isinstance(row.get("bonus"), int) and 1 <= row["bonus"] <= maximum
    )
    gaps = {n: len(rows) + 1 for n in range(1, maximum + 1)}
    for index, row in enumerate(rows):
        bonus = row.get("bonus")
        if isinstance(bonus, int) and 1 <= bonus <= maximum and gaps[bonus] == len(rows) + 1:
            gaps[bonus] = index
    numbers = list(range(1, maximum + 1))
    if strategy == "Hot 6M":
        return min(numbers, key=lambda n: (-counts[n], n))
    if strategy == "Cold 6M":
        return min(numbers, key=lambda n: (counts[n], -gaps[n], n))
    if strategy == "Weighted Historical":
        return min(numbers, key=lambda n: (-(counts[n] * 2 + gaps[n] * 0.15), n))
    return min(numbers, key=lambda n: (counts[n], n))'''
    text = between(text, "def bonus_number", "def make_line", bonus_block)

    text = replace_once(
        text,
        '    state["strategy_catalog"] = STRATEGIES\n\n    if NOW.hour < ENTRY_OPEN_HOUR or NOW.hour >= ENTRY_CUTOFF_HOUR:',
        '    state["strategy_catalog"] = STRATEGIES\n    state["data_policy"] = {\n        "version": DATA_POLICY_VERSION,\n        "rule_change_date": RULE_CHANGE_DATE.isoformat(),\n        "Lotto": "current model uses 6/52 draws from 2026-06-01 onward",\n        "PowerBall": "main model uses 5/50 history; special ball uses current 1-16 era",\n        "Daily Lotto": "5/36 format unchanged",\n    }\n\n    if NOW.hour < ENTRY_OPEN_HOUR or NOW.hour >= ENTRY_CUTOFF_HOUR:',
        "cloud data policy",
    )
    text = replace_once(text, '        costs.setdefault(game, RULES[game]["cost"])', '        costs[game] = RULES[game]["cost"]', "current game costs")
    text = replace_once(
        text,
        '                    "deterministic": True,\n                    "numbers": numbers,',
        '                    "deterministic": True,\n                    "data_policy_version": DATA_POLICY_VERSION,\n                    "numbers": numbers,',
        "ticket data policy version",
    )
    path.write_text(text)


def patch_importer() -> None:
    path = ROOT / "scripts" / "import_history.py"
    text = path.read_text()
    text = replace_once(text, 'OUT = ROOT / "data" / "historical-results.json"\n', 'OUT = ROOT / "data" / "historical-results.json"\nRULE_CHANGE_DATE = date(2026, 6, 1)\n', "importer rule date")
    text = replace_once(text, '        "max": 52,\n        "weekdays": {2, 5},', '        "max": 52,\n        "legacy_max": 58,\n        "weekdays": {2, 5},', "Lotto legacy max")
    text = replace_once(text, '        "bonus_max": 20,\n        "weekdays": {1, 4},', '        "bonus_max": 16,\n        "legacy_bonus_max": 20,\n        "weekdays": {1, 4},', "PowerBall legacy bonus")

    build_block = '''def limits_for_draw(game, date_str):
    draw_date = date.fromisoformat(date_str)
    if game == "Lotto":
        return (58 if draw_date < RULE_CHANGE_DATE else 52), None
    if game == "PowerBall":
        return 50, (20 if draw_date < RULE_CHANGE_DATE else 16)
    return 36, None


def rule_version(game, date_str):
    draw_date = date.fromisoformat(date_str)
    if game == "Lotto":
        return "legacy-6of58" if draw_date < RULE_CHANGE_DATE else "current-6of52"
    if game == "PowerBall":
        return "legacy-5of50-pb20" if draw_date < RULE_CHANGE_DATE else "current-5of50-pb16"
    return "5of36"


def build_row(game, date_str, sequence):
    spec = GAMES[game]
    required = spec["count"] + (1 if game in ("Lotto", "PowerBall") else 0)
    if len(sequence) < required:
        return None

    main_max, bonus_max = limits_for_draw(game, date_str)
    main = sequence[: spec["count"]]
    if len(set(main)) != spec["count"]:
        return None
    if any(not 1 <= number <= main_max for number in main):
        return None

    bonus = None
    if game == "Lotto":
        bonus = sequence[spec["count"]]
        if not 1 <= bonus <= main_max or bonus in main:
            return None
    elif game == "PowerBall":
        bonus = sequence[spec["count"]]
        if bonus_max is None or not 1 <= bonus <= bonus_max:
            return None

    return {
        "date": date_str,
        "game": game,
        "numbers": sorted(main),
        "bonus": bonus,
        "source": draw_url(game, date_str),
        "archive_source": GAMES[game]["archive"].format(year=date_str[:4]),
        "verified": True,
        "parser_version": "archive-v3-rule-aware",
        "rule_version": rule_version(game, date_str),
    }'''
    text = between(text, "def build_row", "def parse_table_rows", build_block)
    path.write_text(text)


def patch_research() -> None:
    path = ROOT / "scripts" / "research_engine.py"
    text = path.read_text()
    text = replace_once(text, 'OUT_PATH = ROOT / "data" / "research-state.json"\n', 'OUT_PATH = ROOT / "data" / "research-state.json"\nRULE_CHANGE_DATE = datetime(2026, 6, 1).date()\n', "research rule date")
    text = replace_once(text, '"PowerBall": {"count": 5, "max": 50, "bonus_max": 20},', '"PowerBall": {"count": 5, "max": 50, "bonus_max": 16},', "research current PowerBall")

    valid_block = '''def valid_row(row: dict[str, Any], game: str) -> bool:
    rule = RULES[game]
    nums = row.get("numbers")
    try:
        draw_date = datetime.fromisoformat(str(row.get("date"))).date()
    except ValueError:
        return False
    main_max = rule["max"]
    bonus_max = rule.get("bonus_max")
    if game == "Lotto" and draw_date < RULE_CHANGE_DATE:
        main_max = 58
    if game == "PowerBall" and draw_date < RULE_CHANGE_DATE:
        bonus_max = 20
    if not isinstance(nums, list) or len(nums) != rule["count"] or len(set(nums)) != len(nums):
        return False
    if any(not isinstance(n, int) or not 1 <= n <= main_max for n in nums):
        return False
    if game == "PowerBall":
        bonus = row.get("bonus")
        if bonus is not None and (not isinstance(bonus, int) or bonus_max is None or not 1 <= bonus <= bonus_max):
            return False
    return True'''
    text = between(text, "def valid_row", "def game_history", valid_block)

    game_history_block = '''def game_history(game: str) -> list[dict[str, Any]]:
    history = load_json(HISTORY_PATH, {"results": []})
    cloud = load_json(CLOUD_PATH, {"results": []})
    rows = [r for r in history.get("results", []) + cloud.get("results", []) if r.get("game") == game and valid_row(r, game)]
    dedup = {(r["date"], game): r for r in rows}
    rows = sorted(dedup.values(), key=lambda r: r["date"])
    # Lotto changed from 6/58 to 6/52 on 1 June 2026. Do not train the
    # current model on a different outcome space.
    if game == "Lotto":
        rows = [r for r in rows if datetime.fromisoformat(r["date"]).date() >= RULE_CHANGE_DATE]
    return rows'''
    text = between(text, "def game_history", "def counts", game_history_block)

    metric_block = '''def metric(matches: list[int], game: str, comparisons: int = 1) -> dict[str, Any]:
    samples = len(matches)
    dist = Counter(matches)
    avg = sum(matches) / samples if samples else 0.0
    baseline = chance_baseline(game)
    expected = baseline["expected_matches"]
    rule = RULES[game]
    draw_variance = rule["count"] * (rule["count"] / rule["max"]) * (1 - rule["count"] / rule["max"]) * ((rule["max"] - rule["count"]) / (rule["max"] - 1))
    standard_error = math.sqrt(draw_variance / samples) if samples else 0.0
    z_score = (avg - expected) / standard_error if standard_error else 0.0
    p_value = math.erfc(abs(z_score) / math.sqrt(2)) if samples else 1.0
    p_adjusted = min(1.0, p_value * max(1, comparisons))
    if samples < 100:
        evidence = "early"
    elif p_adjusted < 0.01:
        evidence = "strong_above_chance" if avg > expected else "strong_below_chance"
    elif p_adjusted < 0.05:
        evidence = "interesting_above_chance" if avg > expected else "interesting_below_chance"
    else:
        evidence = "not_significant"
    return {
        "samples": samples,
        "avg_matches": round(avg, 4),
        "ge2_rate": round(sum(m >= 2 for m in matches) / samples * 100, 2) if samples else 0,
        "ge3_rate": round(sum(m >= 3 for m in matches) / samples * 100, 2) if samples else 0,
        "best_matches": max(matches, default=0),
        "distribution": {str(k): dist.get(k, 0) for k in range(RULES[game]["count"] + 1)},
        "expected_matches": expected,
        "lift_vs_expected_pct": round((avg / expected - 1) * 100, 2) if samples and expected else 0,
        "standard_error": round(standard_error, 6),
        "z_score": round(z_score, 4),
        "p_value": round(p_value, 6),
        "p_adjusted": round(p_adjusted, 6),
        "comparisons_adjusted": max(1, comparisons),
        "evidence": evidence,
    }'''
    text = between(text, "def metric", "def walk_forward", metric_block)
    text = text.replace('return {s: metric([], game) for s in STRATEGIES}', 'return {s: metric([], game, comparisons=16) for s in STRATEGIES}')
    text = text.replace('return {s: metric(collected[s], game) for s in STRATEGIES}', 'return {s: metric(collected[s], game, comparisons=16) for s in STRATEGIES}')
    text = text.replace('    return metric(hits, game)\n\n\ndef evaluate_v1_weighted', '    return metric(hits, game, comparisons=len(WEIGHT_CANDIDATES))\n\n\ndef evaluate_v1_weighted')

    data_quality_block = '''def data_quality(game: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    scope = "5/36 unchanged"
    if game == "Lotto":
        scope = "current 6/52 era from 2026-06-01; legacy 6/58 archived but excluded"
    elif game == "PowerBall":
        scope = "5/50 main-number history spans both eras; current PowerBall pool is 1-16"
    return {
        "draws": len(rows),
        "first_draw": rows[0]["date"] if rows else None,
        "last_draw": rows[-1]["date"] if rows else None,
        "status": "usable" if len(rows) >= MIN_TRAIN[game] else "insufficient",
        "minimum_training_draws": MIN_TRAIN[game],
        "rule_scope": scope,
    }'''
    text = between(text, "def data_quality", "def main", data_quality_block)

    text = text.replace(
        'best_hold.append({"game": game, "strategy": strategy, "best_horizon": best["horizon"], "avg_matches": best["avg_matches"], "ge2_rate": best["ge2_rate"], "samples": best["samples"]})',
        'best_hold.append({"game": game, "strategy": strategy, "best_horizon": best["horizon"], "avg_matches": best["avg_matches"], "ge2_rate": best["ge2_rate"], "samples": best["samples"], "p_adjusted": best["p_adjusted"], "evidence": best["evidence"]})',
    )
    text = replace_once(
        text,
        '            "Theoretical chance is a research control only; no random tickets are added to the live portfolio.",',
        '            "Theoretical chance is a research control only; no random tickets are added to the live portfolio.",\n            "Evidence labels use hypergeometric match-count variance and Bonferroni correction across the strategy/hold comparisons; challenger validation is corrected across candidate weight profiles.",\n            "Rule eras are isolated: legacy Lotto 6/58 is archived but never mixed into the current 6/52 predictor; PowerBall main 5/50 history is compatible across eras while special-ball analysis uses the current 1-16 era.",',
        "research methodology notes",
    )
    path.write_text(text)


def patch_validator() -> None:
    path = ROOT / "scripts" / "validate_state.py"
    text = path.read_text()
    text = replace_once(text, 'HISTORY_PATH = ROOT / "data" / "historical-results.json"\n', 'HISTORY_PATH = ROOT / "data" / "historical-results.json"\nRULE_CHANGE_DATE = date(2026, 6, 1)\n', "validator rule date")
    text = replace_once(text, '"PowerBall": {"count": 5, "max": 50, "bonus_max": 20},', '"PowerBall": {"count": 5, "max": 50, "bonus_max": 16},', "validator current PowerBall")

    validate_block = '''def validate_draw(draw: dict[str, Any], context: str, historical: bool = False) -> None:
    game = draw.get("game")
    require(game in RULES, f"{context} has unsupported game: {game}")
    rule = RULES[game]
    draw_date = parse_iso_date(draw.get("date"), f"{context}.date")
    maximum = rule["max"]
    bonus_max = rule["bonus_max"]
    if historical and draw_date < RULE_CHANGE_DATE:
        if game == "Lotto":
            maximum = 58
            bonus_max = 58
        elif game == "PowerBall":
            bonus_max = 20

    numbers = draw.get("numbers")
    require(isinstance(numbers, list), f"{context}.numbers must be a list")
    require(len(numbers) == rule["count"], f"{context} must contain exactly {rule['count']} numbers")
    require(all(isinstance(number, int) and not isinstance(number, bool) for number in numbers), f"{context}.numbers must contain integers")
    require(len(set(numbers)) == len(numbers), f"{context}.numbers contains duplicates")
    require(all(1 <= number <= maximum for number in numbers), f"{context}.numbers contains an out-of-range value")

    bonus = draw.get("bonus")
    if bonus is not None:
        require(bonus_max is not None, f"{context} must not contain a bonus number")
        require(isinstance(bonus, int) and not isinstance(bonus, bool), f"{context}.bonus must be an integer or null")
        require(1 <= bonus <= bonus_max, f"{context}.bonus is out of range")'''
    text = between(text, "def validate_draw", "def validate_state", validate_block)
    text = replace_once(text, '        validate_draw(result, f"historical result[{index}]")', '        validate_draw(result, f"historical result[{index}]", historical=True)', "historical validator mode")
    path.write_text(text)


def patch_index() -> None:
    path = ROOT / "index.html"
    text = path.read_text()
    old = "const rows=(cloud?.virtual?.tickets||[]).filter(t=>t.status==='Settled'&&t.strategy_version==='1.0');"
    new = "const rows=(cloud?.virtual?.tickets||[]).filter(t=>t.status==='Settled'&&t.strategy_version==='1.0'&&t.data_policy_version==='2.0-rule-aware');"
    text = replace_once(text, old, new, "clean live research cohort")
    text = replace_once(
        text,
        'These outcomes evaluate the strategies. A number is not rewarded because one of our tickets won, or punished because one lost; the official draw itself is already the new historical evidence.',
        'These outcomes evaluate the clean rule-aware v1.0 cohort only. Older experimental tickets remain visible elsewhere but are excluded from this evidence panel. A number is not rewarded because one of our tickets won, or punished because one lost; the official draw itself is already the new historical evidence.',
        "research cohort note",
    )
    text = replace_once(
        text,
        '<p>${esc(q.first_draw||\'No history\')} → ${esc(q.last_draw||\'—\')}</p></div>',
        '<p>${esc(q.first_draw||\'No history\')} → ${esc(q.last_draw||\'—\')}</p><p>${esc(q.rule_scope||\'\')}</p></div>',
        "research rule scope UI",
    )
    path.write_text(text)


def main() -> None:
    patch_cloud()
    patch_importer()
    patch_research()
    patch_validator()
    patch_index()
    print("Applied rule-era-aware DrawLab Research v2 migration")


if __name__ == "__main__":
    main()
