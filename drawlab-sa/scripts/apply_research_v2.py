#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"Could not patch {label}: expected text not found")
    return text.replace(old, new, 1)


def patch_research_engine() -> None:
    path = ROOT / "scripts" / "research_engine.py"
    text = path.read_text()

    old_metric = '''def metric(matches: list[int], game: str) -> dict[str, Any]:
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
'''
    new_metric = '''def metric(matches: list[int], game: str, comparisons: int = 1) -> dict[str, Any]:
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
    }
'''
    text = replace_once(text, old_metric, new_metric, "research metric")
    text = text.replace('return {s: metric([], game) for s in STRATEGIES}', 'return {s: metric([], game, comparisons=16) for s in STRATEGIES}')
    text = text.replace('return {s: metric(collected[s], game) for s in STRATEGIES}', 'return {s: metric(collected[s], game, comparisons=16) for s in STRATEGIES}')
    text = replace_once(text, '    return metric(hits, game)\n\n\ndef evaluate_v1_weighted', '    return metric(hits, game, comparisons=len(WEIGHT_CANDIDATES))\n\n\ndef evaluate_v1_weighted', "challenger multiple comparison correction")
    text = replace_once(
        text,
        'best_hold.append({"game": game, "strategy": strategy, "best_horizon": best["horizon"], "avg_matches": best["avg_matches"], "ge2_rate": best["ge2_rate"], "samples": best["samples"]})',
        'best_hold.append({"game": game, "strategy": strategy, "best_horizon": best["horizon"], "avg_matches": best["avg_matches"], "ge2_rate": best["ge2_rate"], "samples": best["samples"], "p_adjusted": best["p_adjusted"], "evidence": best["evidence"]})',
        "best hold evidence",
    )
    text = replace_once(
        text,
        '            "Theoretical chance is a research control only; no random tickets are added to the live portfolio.",',
        '            "Theoretical chance is a research control only; no random tickets are added to the live portfolio.",\n            "Walk-forward evidence labels use the hypergeometric match-count variance and a Bonferroni correction across the 16 strategy/horizon comparisons per game; challenger validation is corrected across candidate weight profiles.",',
        "research methodology note",
    )
    path.write_text(text)


def patch_index() -> None:
    path = ROOT / "index.html"
    text = path.read_text()
    text = replace_once(
        text,
        "const games=['Daily Lotto','Lotto','PowerBall'];",
        "const evidence=v=>({early:'EARLY DATA',not_significant:'NOT SIGNIFICANT',interesting_above_chance:'INTERESTING +',interesting_below_chance:'INTERESTING −',strong_above_chance:'STRONG +',strong_below_chance:'STRONG −'})[v]||'—';\nconst games=['Daily Lotto','Lotto','PowerBall'];",
        "evidence formatter",
    )
    text = replace_once(text, '<span>≥2 RATE</span></div>${rows.length?', '<span>≥2 / EVIDENCE</span></div>${rows.length?', "hold evidence header")
    text = replace_once(
        text,
        '<span>${pct(x.ge2_rate)}</span></div>`).join(\'\')',
        '<span>${pct(x.ge2_rate)}<small style="display:block;color:var(--muted);margin-top:2px">${evidence(x.evidence)}</small></span></div>`).join(\'\')',
        "hold evidence cell",
    )
    text = replace_once(text, '<span>LIFT</span></div><div class="research-row"><strong>Champion v1</strong>', '<span>LIFT / EVIDENCE</span></div><div class="research-row"><strong>Champion v1</strong>', "challenger evidence header")
    text = replace_once(
        text,
        '<span>${pct(v1.lift_vs_expected_pct)}</span></div><div class="research-row"><strong>Challenger v2</strong>',
        '<span>${pct(v1.lift_vs_expected_pct)}<small style="display:block;color:var(--muted);margin-top:2px">${evidence(v1.evidence)}</small></span></div><div class="research-row"><strong>Challenger v2</strong>',
        "champion evidence cell",
    )
    text = replace_once(
        text,
        '<span>${pct(ch.lift_vs_expected_pct)}</span></div></div><div class="research-note"',
        '<span>${pct(ch.lift_vs_expected_pct)}<small style="display:block;color:var(--muted);margin-top:2px">${evidence(ch.evidence)}</small></span></div></div><div class="research-note"',
        "challenger evidence cell",
    )
    path.write_text(text)


def main() -> None:
    patch_research_engine()
    patch_index()
    print("Applied DrawLab Research v2 statistical evidence hardening")


if __name__ == "__main__":
    main()
