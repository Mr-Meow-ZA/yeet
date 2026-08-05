#!/usr/bin/env python3
"""Validate DrawLab state without fetching data or modifying any files."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "data" / "cloud-state.json"
HISTORY_PATH = ROOT / "data" / "historical-results.json"

RULES = {
    "Daily Lotto": {"count": 5, "max": 36, "bonus_max": None},
    "Lotto": {"count": 6, "max": 52, "bonus_max": 52},
    "PowerBall": {"count": 5, "max": 50, "bonus_max": 16},
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_json(path: Path) -> dict[str, Any]:
    require(path.exists(), f"Missing required file: {path.relative_to(ROOT)}")
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    require(isinstance(value, dict), f"{path.name} must contain a JSON object")
    return value


def parse_iso_date(value: Any, context: str) -> date:
    require(isinstance(value, str), f"{context} must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{context} is not a valid ISO date: {value}") from exc


def parse_iso_datetime(value: Any, context: str) -> datetime:
    require(isinstance(value, str), f"{context} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{context} is not a valid ISO timestamp: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def validate_draw(draw: dict[str, Any], context: str) -> None:
    game = draw.get("game")
    require(game in RULES, f"{context} has unsupported game: {game}")
    rule = RULES[game]
    parse_iso_date(draw.get("date"), f"{context}.date")

    numbers = draw.get("numbers")
    require(isinstance(numbers, list), f"{context}.numbers must be a list")
    require(len(numbers) == rule["count"], f"{context} must contain exactly {rule['count']} numbers")
    require(all(isinstance(number, int) and not isinstance(number, bool) for number in numbers), f"{context}.numbers must contain integers")
    require(len(set(numbers)) == len(numbers), f"{context}.numbers contains duplicates")
    require(all(1 <= number <= rule["max"] for number in numbers), f"{context}.numbers contains an out-of-range value")

    bonus = draw.get("bonus")
    if bonus is not None:
        bonus_max = rule["bonus_max"]
        require(bonus_max is not None, f"{context} must not contain a bonus number")
        require(isinstance(bonus, int) and not isinstance(bonus, bool), f"{context}.bonus must be an integer or null")
        require(1 <= bonus <= bonus_max, f"{context}.bonus is out of range")


def validate_state(state: dict[str, Any]) -> None:
    require(state.get("status") in {"initialising", "healthy", "partial", "degraded"}, "cloud-state.json has an unsupported status")
    parse_iso_datetime(state.get("updated_at"), "cloud-state.updated_at")

    results = state.get("results", [])
    require(isinstance(results, list), "cloud-state.results must be a list")
    result_keys: set[tuple[str, str]] = set()
    for index, result in enumerate(results):
        require(isinstance(result, dict), f"cloud-state.results[{index}] must be an object")
        validate_draw(result, f"cloud-state.results[{index}]")
        key = (result["date"], result["game"])
        require(key not in result_keys, f"Duplicate cloud result for {key[0]} {key[1]}")
        result_keys.add(key)

    virtual = state.get("virtual")
    require(isinstance(virtual, dict), "cloud-state.virtual must be an object")
    tickets = virtual.get("tickets", [])
    require(isinstance(tickets, list), "cloud-state.virtual.tickets must be a list")
    ticket_ids: set[str] = set()
    for index, ticket in enumerate(tickets):
        require(isinstance(ticket, dict), f"ticket[{index}] must be an object")
        validate_draw(ticket, f"ticket[{index}]")
        ticket_id = ticket.get("id")
        require(isinstance(ticket_id, str) and ticket_id.strip(), f"ticket[{index}] has no id")
        require(ticket_id not in ticket_ids, f"Duplicate ticket id: {ticket_id}")
        ticket_ids.add(ticket_id)
        for field in ("cost", "won"):
            value = ticket.get(field, 0)
            require(isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0, f"ticket[{index}].{field} must be non-negative")


def validate_history(history: dict[str, Any]) -> None:
    require(history.get("schema_version") == 1, "Unsupported historical-results schema_version")
    parse_iso_datetime(history.get("updated_at"), "historical-results.updated_at")
    results = history.get("results")
    require(isinstance(results, list), "historical-results.results must be a list")

    result_keys: set[tuple[str, str]] = set()
    for index, result in enumerate(results):
        require(isinstance(result, dict), f"historical result[{index}] must be an object")
        validate_draw(result, f"historical result[{index}]")
        key = (result["date"], result["game"])
        require(key not in result_keys, f"Duplicate historical result for {key[0]} {key[1]}")
        result_keys.add(key)


def check_freshness(state: dict[str, Any], max_age_hours: int | None) -> None:
    if max_age_hours is None:
        return
    updated_at = parse_iso_datetime(state.get("updated_at"), "cloud-state.updated_at")
    age_hours = (datetime.now(timezone.utc) - updated_at.astimezone(timezone.utc)).total_seconds() / 3600
    require(age_hours <= max_age_hours, f"DrawLab cloud state is stale: {age_hours:.1f} hours old (limit {max_age_hours})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-age-hours", type=int, default=None)
    args = parser.parse_args()

    state = load_json(STATE_PATH)
    history = load_json(HISTORY_PATH)
    validate_state(state)
    validate_history(history)
    check_freshness(state, args.max_age_hours)

    print(
        "Validated DrawLab state: "
        f"{len(state.get('results', []))} cloud results, "
        f"{len(state.get('virtual', {}).get('tickets', []))} virtual tickets and "
        f"{len(history.get('results', []))} historical results."
    )


if __name__ == "__main__":
    main()
