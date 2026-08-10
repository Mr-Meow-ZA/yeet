#!/usr/bin/env python3
"""DrawLab EV Hunter v2.0 — structural lottery economics.

This model does not predict balls. It models whether buying a ticket is
financially attractive after ticket price, prize mechanics, sales response and
jackpot-sharing risk. Equal-probability lines are then ranked for *sharing risk*
only. The conservative entry gate never credits the crowd model with a boost.

v2 changes:
* Daily Lotto is modelled as a 50%-of-sales pari-mutuel pool with jackpot
  rolldown, so it no longer has a fictitious independent break-even jackpot.
* Current Lotto and PowerBall fixed prizes are treated as rules, not medians.
* Variable pools are estimated structurally from exact historical pool totals.
* Sales use a log-demand model with calendar residuals and an upper-volume risk
  estimate for jackpot collision.
* Crowd Model v1 may rank lines, but cannot make an otherwise negative-EV draw
  pass the gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import ev_hunter as legacy
import crowd_model

ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT / "data" / "ev-history.json"
STATE_PATH = ROOT / "data" / "ev-state.json"
CROWD_PATH = ROOT / "data" / "crowd-state.json"
MODEL_VERSION = "EV Hunter v2.0"
TZ = ZoneInfo("Africa/Johannesburg")
NOW = datetime.now(TZ)
ENTRY_MARGIN = 1.02
WATCH_MARGIN = 0.90
MIN_ROWS = {"Daily Lotto": 18, "Lotto": 10, "PowerBall": 10}

FIXED_PRIZES = {
    "Lotto": {"4+B": 4000.0, "4": 200.0, "3+B": 200.0, "2+B": 30.0, "3": 20.0},
    "PowerBall": {"4": 2000.0, "3+PB": 500.0, "3": 100.0, "2+PB": 100.0, "1+PB": 20.0, "0+PB": 10.0},
}
VARIABLE_ALLOC = {
    "Lotto": {"6": 0.60, "5+B": 0.15, "5": 0.25},
    "PowerBall": {"5+PB": 0.91, "5": 0.06, "4+PB": 0.03},
}
DAILY_ALLOC = {"5": 0.35, "4": 0.10, "3": 0.15, "2": 0.40}
DAILY_PRIZE_POOL_RATE = 0.50


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text()) if path.exists() else default
    except Exception:
        return default


def save(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n")


def median(values: list[float], default: float = 0.0) -> float:
    vals = sorted(float(v) for v in values if v is not None and math.isfinite(float(v)))
    return float(statistics.median(vals)) if vals else default


def quantile(values: list[float], q: float, default: float = 0.0) -> float:
    vals = sorted(float(v) for v in values if v is not None and math.isfinite(float(v)))
    if not vals:
        return default
    if len(vals) == 1:
        return vals[0]
    pos = (len(vals) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return vals[lo]
    return vals[lo] * (hi - pos) + vals[hi] * (pos - lo)


def pool_amount(row: dict[str, Any], key: str) -> float:
    d = (row.get("divisions") or {}).get(key) or {}
    if d.get("pool") is not None:
        return float(d.get("pool") or 0.0)
    return float(d.get("payout") or 0.0) * int(d.get("winners") or 0)


def variable_pool_rates(game: str, prior: list[dict[str, Any]]) -> list[float]:
    rates = []
    for row in prior:
        sales = float(row.get("total_sales") or 0.0)
        if sales <= 0:
            continue
        if game == "Lotto":
            visible = pool_amount(row, "5+B") + pool_amount(row, "5")
            rate = visible / 0.40 / sales if visible > 0 else 0.0
        elif game == "PowerBall":
            visible = pool_amount(row, "5") + pool_amount(row, "4+PB")
            rate = visible / 0.09 / sales if visible > 0 else 0.0
        else:
            continue
        if 0.01 <= rate <= 0.80:
            rates.append(rate)
    return rates[-80:]


def month_end(d: date) -> bool:
    return d.day >= 25 or d.day <= 3


def fit_sales(prior: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [r for r in prior[-100:] if float(r.get("equivalent_lines") or 0) > 0]
    if not rows:
        return {"samples": 0, "median": 0.0, "a": 0.0, "b": 0.0, "resid_sd": 0.0, "weekday": {}, "month_end": 1.0}
    xs = [math.log1p(float(r.get("jackpot") or 0.0) / 1_000_000.0) for r in rows]
    ys = [math.log(float(r["equivalent_lines"])) for r in rows]
    xb, yb = sum(xs) / len(xs), sum(ys) / len(ys)
    denom = sum((x - xb) ** 2 for x in xs)
    b = sum((x - xb) * (y - yb) for x, y in zip(xs, ys)) / denom if denom else 0.0
    b = max(0.0, min(2.5, b))
    a = yb - b * xb
    residuals = [y - (a + b * x) for x, y in zip(xs, ys)]
    resid_sd = math.sqrt(sum(r * r for r in residuals) / max(1, len(residuals) - 2))
    weekday_buckets: dict[int, list[float]] = defaultdict(list)
    me, non = [], []
    for row, resid in zip(rows, residuals):
        d = datetime.fromisoformat(row["date"]).date()
        weekday_buckets[d.weekday()].append(resid)
        (me if month_end(d) else non).append(resid)
    weekday = {str(k): math.exp(median(v)) for k, v in weekday_buckets.items() if len(v) >= 3}
    me_factor = 1.0
    if len(me) >= 4 and len(non) >= 4:
        me_factor = math.exp(median(me) - median(non))
        me_factor = max(0.80, min(1.25, me_factor))
    return {
        "samples": len(rows), "median": median([float(r["equivalent_lines"]) for r in rows]),
        "a": a, "b": b, "resid_sd": resid_sd, "weekday": weekday, "month_end": me_factor,
    }


def predict_sales(model: dict[str, Any], jackpot: float, when: date) -> tuple[int, int]:
    med = max(1.0, float(model.get("median") or 1.0))
    raw = math.exp(float(model.get("a") or 0.0) + float(model.get("b") or 0.0) * math.log1p(max(0.0, jackpot) / 1_000_000.0))
    raw *= float((model.get("weekday") or {}).get(str(when.weekday()), 1.0))
    if month_end(when):
        raw *= float(model.get("month_end") or 1.0)
    central = min(max(raw, med * 0.55), med * 4.5)
    risk_factor = min(1.50, max(1.08, math.exp(0.75 * float(model.get("resid_sd") or 0.0))))
    upper = central * risk_factor
    return int(round(central)), int(round(upper))


def share_factor(lam: float) -> float:
    if lam <= 1e-12:
        return 1.0
    return (1.0 - math.exp(-lam)) / lam


def crowd_prior_score(game: str, nums: list[int], previous: list[int]) -> float:
    f = crowd_model.line_features(game, nums, previous)
    central_sum = 1.0 - min(1.0, abs(f["sum_norm"] - 0.5) * 2.0)
    # Positive = more crowding. Literature-informed prior: birthdays, lucky 7,
    # round numbers and representative central sums are popular; recent repeats,
    # parity imbalance and some obvious structure tend to be avoided. This prior
    # only ranks equal-probability lines and never enters the EV gate.
    return (
        2.2 * f["birthday_share"]
        + 0.45 * f["lucky7"]
        + 0.30 * f["round_share"]
        + 0.45 * central_sum
        - 0.35 * f["consecutive_rate"]
        - 0.18 * f["same_last_digit_rate"]
        - 0.25 * f["odd_imbalance"]
        - 0.18 * f["progression_rate"]
        - 0.35 * f["repeat_prev"]
    )


def score_empirical(game: str, nums: list[int], previous: list[int], crowd_state: dict[str, Any]) -> tuple[float, str, float | None]:
    g = (crowd_state.get("games") or {}).get(game) or {}
    if g.get("status") != "empirical_signal" or not g.get("model"):
        return crowd_prior_score(game, nums, previous), "behavioral_prior_v1", None
    model = g["model"]
    features = crowd_model.line_features(game, nums, previous)
    log_mult = crowd_model.predict(model, features)
    return log_mult, "empirical_crowd_v1", math.exp(log_mult)


def deterministic_candidate(game: str, key: str, iteration: int) -> tuple[list[int], int | None]:
    rule = legacy.RULES[game]
    seed = f"DrawLab-EV-v2|{game}|{key}|{iteration}".encode()
    stream = hashlib.sha256(seed).digest()
    pool = list(range(1, rule["max"] + 1))
    chosen = []
    i = 0
    while len(chosen) < rule["count"]:
        if i >= len(stream):
            stream += hashlib.sha256(stream).digest()
        chosen.append(pool.pop(stream[i] % len(pool)))
        i += 1
    bonus = None
    if game == "PowerBall":
        bonus = 1 + hashlib.sha256(seed + b"|PB").digest()[0] % 16
    return sorted(chosen), bonus


def previous_numbers(game: str, before: date) -> list[int]:
    rows = [r for r in legacy.combined_results() if r.get("game") == game and r.get("date") and datetime.fromisoformat(r["date"]).date() < before]
    if not rows:
        return []
    return list(max(rows, key=lambda r: r["date"]).get("numbers") or [])


def anti_crowd_line(game: str, key: str, when: date, crowd_state: dict[str, Any], empirical_allowed: bool = True) -> dict[str, Any]:
    prev = previous_numbers(game, when)
    best = None
    for i in range(2048):
        nums, bonus = deterministic_candidate(game, key, i)
        if empirical_allowed:
            score, model_name, multiplier = score_empirical(game, nums, prev, crowd_state)
        else:
            score, model_name, multiplier = crowd_prior_score(game, nums, prev), "behavioral_prior_v1", None
        tie = hashlib.sha256(f"{game}|{key}|{i}|anti-crowd-v2".encode()).hexdigest()
        item = (score, tie, nums, bonus, model_name, multiplier)
        if best is None or item[:2] < best[:2]:
            best = item
    assert best is not None
    return {
        "numbers": best[2], "bonus": best[3], "crowding_score": round(float(best[0]), 6),
        "crowd_model": best[4], "estimated_crowding_multiplier": round(best[5], 4) if best[5] is not None else None,
        "meaning": "Ranks equal-probability legal lines for expected sharing risk only. The EV gate gives this line zero predictive or crowd-uplift credit.",
    }


def daily_ev(prior: list[dict[str, Any]], when: date) -> dict[str, Any]:
    cost = legacy.ticket_cost_for("Daily Lotto", when)
    probs = legacy.match_probabilities("Daily Lotto", when)
    sales_model = fit_sales(prior)
    lines, upper_lines = predict_sales(sales_model, median([float(r.get("jackpot") or 0) for r in prior], 400_000.0), when)
    sales = lines * cost
    pool = sales * DAILY_PRIZE_POOL_RATE
    upper_sales = upper_lines * cost
    conservative_pool = upper_sales * DAILY_PRIZE_POOL_RATE  # pool grows with sales; sharing also worsens.
    central_parts = {}
    conservative_parts = {}
    for key in ("5", "4", "3", "2"):
        lam = lines * probs[key]
        clam = upper_lines * probs[key]
        central_pool = pool * DAILY_ALLOC[key]
        cons_pool = conservative_pool * DAILY_ALLOC[key]
        if key == "4":
            central_pool += pool * DAILY_ALLOC["5"] * math.exp(-lines * probs["5"])
            cons_pool += conservative_pool * DAILY_ALLOC["5"] * math.exp(-upper_lines * probs["5"])
        central_parts[key] = probs[key] * central_pool * share_factor(lam)
        conservative_parts[key] = probs[key] * cons_pool * share_factor(clam)
    central = sum(central_parts.values())
    conservative = sum(conservative_parts.values())
    ratio = conservative / cost
    return {
        "ticket_cost": cost,
        "advertised_jackpot": None,
        "jackpot_role": "not_an_independent_rollover_variable",
        "predicted_line_volume": lines,
        "risk_line_volume": upper_lines,
        "sales_model_samples": sales_model["samples"],
        "prize_pool_rate": DAILY_PRIZE_POOL_RATE,
        "prize_pool_estimate": round(pool, 2),
        "structural_components": {k: round(v, 4) for k, v in central_parts.items()},
        "expected_return": round(central, 4),
        "conservative_return": round(conservative, 4),
        "expected_roi_pct": round((central / cost - 1) * 100, 2),
        "conservative_roi_pct": round((ratio - 1) * 100, 2),
        "ev_ratio": round(ratio, 4),
        "break_even_jackpot": None,
        "decision": "ENTER_CANDIDATE" if len(prior) >= MIN_ROWS["Daily Lotto"] and ratio >= ENTRY_MARGIN else ("WATCH" if len(prior) >= MIN_ROWS["Daily Lotto"] and ratio >= WATCH_MARGIN else ("INSUFFICIENT_DATA" if len(prior) < MIN_ROWS["Daily Lotto"] else "SKIP")),
        "mechanic": "50% of sales funds four pari-mutuel divisions; if Match 5 has no winner its allocation rolls down to Match 4. Jackpot size is therefore not treated as an external rollover asset.",
    }


def variable_ev(game: str, jackpot: float, prior: list[dict[str, Any]], when: date) -> dict[str, Any]:
    cost = legacy.ticket_cost_for(game, when)
    probs = legacy.match_probabilities(game, when)
    sales_model = fit_sales(prior)
    lines, upper_lines = predict_sales(sales_model, jackpot, when)
    rates = variable_pool_rates(game, prior)
    rate_mid = median(rates, 0.0)
    rate_low = quantile(rates, 0.25, rate_mid)
    sales_mid, sales_risk = lines * cost, upper_lines * cost
    variable_mid, variable_low = sales_mid * rate_mid, sales_risk * rate_low
    top_key = "6" if game == "Lotto" else "5+PB"
    central_parts: dict[str, float] = {}
    conservative_parts: dict[str, float] = {}
    # Jackpot is the advertised accumulated/guaranteed top prize for this draw.
    central_parts[top_key] = probs[top_key] * jackpot * share_factor(lines * probs[top_key])
    conservative_parts[top_key] = probs[top_key] * jackpot * share_factor(upper_lines * probs[top_key])
    for key, amount in FIXED_PRIZES[game].items():
        central_parts[key] = probs.get(key, 0.0) * amount
        conservative_parts[key] = central_parts[key]
    for key, alloc in VARIABLE_ALLOC[game].items():
        if key == top_key:
            continue
        central_parts[key] = probs[key] * (variable_mid * alloc) * share_factor(lines * probs[key])
        conservative_parts[key] = probs[key] * (variable_low * alloc) * share_factor(upper_lines * probs[key])
    central = sum(central_parts.values())
    conservative = sum(conservative_parts.values())
    ratio = conservative / cost if cost else 0.0
    enough = len(prior) >= MIN_ROWS[game] and len(rates) >= 5
    decision = "INSUFFICIENT_DATA" if not enough else ("ENTER_CANDIDATE" if ratio >= ENTRY_MARGIN else ("WATCH" if ratio >= WATCH_MARGIN else "SKIP"))
    return {
        "ticket_cost": cost,
        "advertised_jackpot": round(jackpot, 2),
        "predicted_line_volume": lines,
        "risk_line_volume": upper_lines,
        "sales_model_samples": sales_model["samples"],
        "variable_pool_rate_median": round(rate_mid, 6),
        "variable_pool_rate_conservative": round(rate_low, 6),
        "variable_pool_rate_samples": len(rates),
        "fixed_prizes": FIXED_PRIZES[game],
        "variable_allocations": VARIABLE_ALLOC[game],
        "structural_components": {k: round(v, 4) for k, v in central_parts.items()},
        "expected_return": round(central, 4),
        "conservative_return": round(conservative, 4),
        "expected_roi_pct": round((central / cost - 1) * 100, 2),
        "conservative_roi_pct": round((ratio - 1) * 100, 2),
        "ev_ratio": round(ratio, 4),
        "decision": decision,
        "mechanic": "Fixed lower prizes are valued exactly from the current rules; top variable divisions use exact historical pool accounting. The jackpot is valued at the advertised draw amount with collision risk.",
    }


def evaluate(game: str, jackpot: float | None, prior: list[dict[str, Any]], when: date) -> dict[str, Any]:
    if game == "Daily Lotto":
        return daily_ev(prior, when)
    if jackpot is None:
        cost = legacy.ticket_cost_for(game, when)
        return {"ticket_cost": cost, "advertised_jackpot": None, "expected_return": None, "conservative_return": None, "expected_roi_pct": None, "conservative_roi_pct": None, "ev_ratio": None, "decision": "SOURCE_UNAVAILABLE", "break_even_jackpot": None}
    out = variable_ev(game, jackpot, prior, when)
    out["break_even_jackpot"] = break_even_jackpot(game, prior, when)
    return out


def break_even_jackpot(game: str, prior: list[dict[str, Any]], when: date) -> float | None:
    if game == "Daily Lotto" or len(prior) < MIN_ROWS[game] or len(variable_pool_rates(game, prior)) < 5:
        return None
    cost = legacy.ticket_cost_for(game, when)
    lo, hi = 0.0, 20_000_000.0
    while hi < 1_500_000_000:
        test = variable_ev(game, hi, prior, when)
        if float(test.get("conservative_return") or 0) >= cost:
            break
        lo, hi = hi, hi * 1.5
    if hi >= 1_500_000_000:
        return None
    for _ in range(42):
        mid = (lo + hi) / 2
        if float(variable_ev(game, mid, prior, when).get("conservative_return") or 0) >= cost:
            hi = mid
        else:
            lo = mid
    return round(hi, -3)


def backtest(cache_rows: list[dict[str, Any]]) -> dict[str, Any]:
    lookup = {(r["date"], r["game"]): r for r in legacy.combined_results() if r.get("date") and r.get("game")}
    output = {}
    empty_crowd: dict[str, Any] = {"games": {}}
    for game in legacy.RULES:
        econ = sorted([r for r in cache_rows if r.get("game") == game], key=lambda r: r["date"])
        entries = []
        spend = won = 0.0
        for idx, row in enumerate(econ):
            when = datetime.fromisoformat(row["date"]).date()
            prior = [p for p in econ[:idx] if p.get("era") == row.get("era")]
            ev = evaluate(game, float(row.get("jackpot") or 0) if game != "Daily Lotto" else None, prior, when)
            if ev.get("decision") != "ENTER_CANDIDATE":
                continue
            draw = lookup.get((row["date"], game))
            if not draw:
                continue
            # Historical settlement uses the fixed behavioural prior only. The
            # empirical crowd model is intentionally excluded to avoid future-data leakage.
            line = anti_crowd_line(game, row["date"], when, empty_crowd, empirical_allowed=False)
            key, matches, bonus_hit = legacy.prize_key(game, line["numbers"], line.get("bonus"), draw)
            payout = float(((row.get("divisions") or {}).get(key) or {}).get("payout") or 0.0)
            cost = float(ev["ticket_cost"])
            spend += cost
            won += payout
            entries.append({"date": row["date"], "decision_ev_ratio": ev.get("ev_ratio"), "numbers": line["numbers"], "bonus": line.get("bonus"), "prize_key": key, "matches": matches, "bonus_match": bonus_hit, "cost": cost, "won": payout})
        output[game] = {
            "entries": len(entries), "spend": round(spend, 2), "won": round(won, 2), "net": round(won - spend, 2),
            "roi_pct": round((won / spend - 1) * 100, 2) if spend else None, "decisions": entries,
            "interpretation": "Entry decisions use only earlier economics. Historical anti-crowd lines use a fixed literature-informed prior, not the empirical crowd model, preventing future-data leakage.",
        }
    return output


def settle_shadow(state: dict[str, Any], cache_rows: list[dict[str, Any]]) -> int:
    lookup = {(r["date"], r["game"]): r for r in legacy.combined_results() if r.get("date") and r.get("game")}
    econ = {(r["date"], r["game"]): r for r in cache_rows}
    changed = 0
    for t in state.setdefault("shadow_tickets", []):
        if t.get("status") == "Settled":
            continue
        key = (t.get("date"), t.get("game"))
        draw, row = lookup.get(key), econ.get(key)
        if not draw or not row:
            continue
        pkey, matches, bonus_hit = legacy.prize_key(t["game"], t["numbers"], t.get("bonus"), draw)
        payout = float(((row.get("divisions") or {}).get(pkey) or {}).get("payout") or 0.0)
        t.update({"status": "Settled", "matches": matches, "bonus_match": bonus_hit, "prize_key": pkey, "won": payout, "settled_at": datetime.now(timezone.utc).isoformat()})
        changed += 1
    return changed


def build_state(cache: dict[str, Any]) -> dict[str, Any]:
    rows = cache.get("rows", [])
    crowd_state = load(CROWD_PATH, {"games": {}})
    old = load(STATE_PATH, {"shadow_tickets": [], "decisions": []})
    old.setdefault("shadow_tickets", [])
    old.setdefault("decisions", [])
    jackpots, source = legacy.fetch_current_jackpots()
    current = {}
    for game in legacy.RULES:
        draw_date = legacy.upcoming_draw_date(game, NOW.date())
        prior = legacy.prior_rows(rows, game, before=draw_date + timedelta(days=1), target=draw_date)
        ev = evaluate(game, jackpots.get(game), prior, draw_date)
        ev["draw_date"] = draw_date.isoformat()
        ev["jackpot_source"] = source if jackpots.get(game) is not None else None
        if game == "Daily Lotto" and jackpots.get(game) is not None:
            ev["advertised_jackpot"] = round(float(jackpots[game]), 2)
            ev["jackpot_role"] = "display_only; Daily Lotto top pool is sales-funded and rolls down rather than rolling over"
        ev["anti_crowd_line"] = anti_crowd_line(game, draw_date.isoformat(), draw_date, crowd_state, empirical_allowed=True)
        ev["crowding_credit_in_gate"] = 0.0
        current[game] = ev

    existing_decisions = {(d.get("date"), d.get("game"), d.get("model_version")) for d in old["decisions"]}
    if NOW.hour < 20:
        for game, row in current.items():
            key = (row["draw_date"], game, MODEL_VERSION)
            if key not in existing_decisions:
                old["decisions"].append({"date": row["draw_date"], "game": game, "model_version": MODEL_VERSION, "recorded_at": NOW.isoformat(), "decision": row.get("decision"), "ev_ratio": row.get("ev_ratio"), "expected_roi_pct": row.get("expected_roi_pct"), "conservative_roi_pct": row.get("conservative_roi_pct"), "advertised_jackpot": row.get("advertised_jackpot"), "break_even_jackpot": row.get("break_even_jackpot"), "ticket_cost": row.get("ticket_cost"), "source": row.get("jackpot_source")})
    old["decisions"] = sorted(old["decisions"], key=lambda d: (d.get("date", ""), d.get("game", ""), d.get("recorded_at", "")), reverse=True)[:800]

    ticket_keys = {(t.get("date"), t.get("game"), t.get("strategy_version")) for t in old["shadow_tickets"]}
    created = 0
    if NOW.hour < 20:
        for game, row in current.items():
            key = (row["draw_date"], game, "2.0")
            if row.get("decision") != "ENTER_CANDIDATE" or key in ticket_keys:
                continue
            line = row["anti_crowd_line"]
            old["shadow_tickets"].append({
                "id": f"{row['draw_date']}|{game}|EV Hunter|v2.0", "date": row["draw_date"], "game": game,
                "strategy": "EV Hunter", "strategy_version": "2.0", "numbers": line["numbers"], "bonus": line.get("bonus"),
                "crowding_score": line["crowding_score"], "crowd_model": line["crowd_model"], "cost": row["ticket_cost"],
                "advertised_jackpot": row.get("advertised_jackpot"), "ev_ratio_at_entry": row.get("ev_ratio"),
                "expected_roi_pct_at_entry": row.get("expected_roi_pct"), "conservative_roi_pct_at_entry": row.get("conservative_roi_pct"),
                "status": "Pending result", "won": 0.0, "created_at": NOW.isoformat(), "research_only": True,
            })
            ticket_keys.add(key)
            created += 1
    settled_now = settle_shadow(old, rows)
    tickets = old["shadow_tickets"]
    settled = [t for t in tickets if t.get("status") == "Settled"]
    spend = sum(float(t.get("cost") or 0) for t in tickets)
    won = sum(float(t.get("won") or 0) for t in settled)
    payload = {
        "schema_version": 2,
        "model_version": MODEL_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Selective expected-value research based on prize mechanics, sales demand and sharing risk. It changes when to participate, not the probability of the draw.",
        "current": current,
        "historical_backtest": backtest(rows),
        "shadow_tickets": sorted(tickets, key=lambda t: (t.get("date", ""), t.get("game", "")), reverse=True)[:800],
        "shadow_summary": {"tickets": len(tickets), "settled": len(settled), "pending": len(tickets) - len(settled), "spend": round(spend, 2), "won": round(won, 2), "net": round(won - spend, 2), "roi_pct": round((won / spend - 1) * 100, 2) if spend else None, "created_now": created, "settled_now": settled_now},
        "decisions": old["decisions"],
        "methodology": {
            "gate": f"ENTER only when conservative structural expected return >= {ENTRY_MARGIN:.2f}x ticket cost. Crowd-model uplift is always zero in the gate.",
            "daily_lotto": "50% sales-funded pari-mutuel pool with explicit Match-5-to-Match-4 rolldown; no independent rollover jackpot threshold.",
            "lotto": "Current fixed lower prizes are exact rules. The top three divisions use 60/15/25 variable-pool allocations, with the advertised jackpot valued separately as the accumulated top prize.",
            "powerball": "Current fixed lower prizes are exact rules. The top three divisions use 91/6/3 variable-pool allocations, with the advertised jackpot valued separately as the accumulated top prize.",
            "sales": "Rule-era log-demand model with weekday and month-end residual factors. A higher-volume risk estimate is used for conservative prize-sharing calculations.",
            "crowding": "Crowd Model v1 may rank equal-probability lines. No estimated sharing advantage is monetized in the entry decision until prospective evidence supports it.",
            "historical_test": "Historical entries use only earlier economics and a fixed behavioural-prior anti-crowd line, preventing leakage from the empirical crowd model.",
        },
        "cache_coverage": cache.get("coverage", {}),
        "crowd_model_version": crowd_state.get("model_version"),
        "sources": [legacy.RESULTS_URL, f"{legacy.SOURCE_ROOT}/<game>/results/<date>"],
    }
    save(STATE_PATH, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-history", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    if args.refresh_history or not CACHE_PATH.exists():
        cache = legacy.refresh_history(args.workers)
    else:
        cache = load(CACHE_PATH, {"rows": [], "coverage": {}})
    state = build_state(cache)
    print(json.dumps({
        "model": state["model_version"],
        "cache_coverage": state["cache_coverage"],
        "current": {g: {k: v for k, v in r.items() if k in {"decision", "advertised_jackpot", "expected_return", "conservative_return", "expected_roi_pct", "conservative_roi_pct", "break_even_jackpot", "ticket_cost", "ev_ratio"}} for g, r in state["current"].items()},
        "shadow": state["shadow_summary"],
        "backtest": {g: {k: v for k, v in r.items() if k in {"entries", "spend", "won", "net", "roi_pct"}} for g, r in state["historical_backtest"].items()},
    }, indent=2))


if __name__ == "__main__":
    main()
