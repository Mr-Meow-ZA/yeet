#!/usr/bin/env python3
"""Prospective DrawLab challenger shadow tracker.

Creates research-only predictions from challenger definitions that were locked
before the target draw. It never creates historical tickets after a result is
known and never mutates the live five-strategy ledger.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_engine import game_history
from strategy_discovery import candidate_line

ROOT = Path(__file__).resolve().parents[1]
CLOUD_PATH = ROOT / "data" / "cloud-state.json"
LOCKS_PATH = ROOT / "data" / "challenger-locks.json"
STATE_PATH = ROOT / "data" / "shadow-state.json"


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text()) if path.exists() else default
    except Exception:
        return default


def save(payload: dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(payload, indent=2) + "\n")


def locked_candidate(lock: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": lock["id"],
        "name": lock["name"],
        "family": lock["family"],
        "params": lock.get("params", {}),
    }


def target_dates(cloud: dict[str, Any], lock: dict[str, Any]) -> list[str]:
    cutoff = str(lock.get("confirmation_after") or lock.get("locked_on") or "9999-12-31")
    game = lock["game"]
    dates = {
        str(t.get("date"))
        for t in cloud.get("virtual", {}).get("tickets", [])
        if t.get("game") == game
        and t.get("status") != "Settled"
        and str(t.get("date") or "") > cutoff
    }
    # Results already present are never eligible targets, even if a malformed
    # pending live ticket somehow survived settlement.
    known = {
        (str(r.get("date")), r.get("game"))
        for r in cloud.get("results", [])
    }
    return sorted(d for d in dates if (d, game) not in known)


def make_pending(lock: dict[str, Any], target: str) -> dict[str, Any]:
    game = lock["game"]
    rows = [r for r in game_history(game) if str(r.get("date")) < target]
    if not rows:
        raise RuntimeError(f"No pre-target history for {game} {target}")
    numbers = candidate_line(rows, game, locked_candidate(lock))
    return {
        "id": f"{target}|{game}|{lock['id']}",
        "date": target,
        "game": game,
        "challenger_id": lock["id"],
        "challenger": lock["name"],
        "challenger_version": lock.get("version", "0.1"),
        "numbers": numbers,
        "bonus": None,
        "refresh_policy_draws": lock.get("refresh_policy_draws", 1),
        "deterministic": True,
        "research_only": True,
        "locked_on": lock.get("locked_on"),
        "history_cutoff": rows[-1]["date"],
        "status": "Pending result",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def settle_ticket(ticket: dict[str, Any], result: dict[str, Any]) -> None:
    matches = len(set(ticket.get("numbers", [])) & set(result.get("numbers", [])))
    ticket.update({
        "matches": matches,
        "status": "Settled",
        "settled_at": datetime.now(timezone.utc).isoformat(),
        "result_numbers": result.get("numbers", []),
        "result_bonus": result.get("bonus"),
        "result_source": result.get("source") or result.get("payout_source"),
    })


def summary_for(lock: dict[str, Any], tickets: list[dict[str, Any]]) -> dict[str, Any]:
    own = [t for t in tickets if t.get("challenger_id") == lock["id"]]
    settled = [t for t in own if t.get("status") == "Settled"]
    hits = [int(t.get("matches", 0) or 0) for t in settled]
    dist = Counter(hits)
    return {
        "challenger_id": lock["id"],
        "name": lock["name"],
        "game": lock["game"],
        "status": lock.get("status", "shadow"),
        "locked_on": lock.get("locked_on"),
        "tickets": len(own),
        "settled": len(settled),
        "pending": len(own) - len(settled),
        "avg_matches": round(sum(hits) / len(hits), 4) if hits else None,
        "ge2_rate": round(sum(h >= 2 for h in hits) / len(hits) * 100, 2) if hits else None,
        "ge3_rate": round(sum(h >= 3 for h in hits) / len(hits) * 100, 2) if hits else None,
        "best_matches": max(hits, default=None),
        "distribution": {str(k): dist[k] for k in sorted(dist)},
        "confirmation_note": "Prospective only; no result in this sample was available when its shadow line was created.",
    }


def main() -> None:
    cloud = load(CLOUD_PATH, {"virtual": {"tickets": []}, "results": []})
    locks_payload = load(LOCKS_PATH, {"locks": []})
    state = load(STATE_PATH, {"schema_version": 1, "tickets": [], "summary": {}})
    tickets = state.setdefault("tickets", [])
    existing_ids = {t.get("id") for t in tickets}
    locks = [l for l in locks_payload.get("locks", []) if l.get("status") == "shadow"]

    created = 0
    for lock in locks:
        for target in target_dates(cloud, lock):
            ticket_id = f"{target}|{lock['game']}|{lock['id']}"
            if ticket_id in existing_ids:
                continue
            ticket = make_pending(lock, target)
            tickets.append(ticket)
            existing_ids.add(ticket_id)
            created += 1

    # Settle from the combined validated history, not from a guessed payout.
    result_maps: dict[str, dict[str, dict[str, Any]]] = {}
    for lock in locks:
        game = lock["game"]
        result_maps[game] = {str(r.get("date")): r for r in game_history(game)}
    settled_now = 0
    for ticket in tickets:
        if ticket.get("status") == "Settled":
            continue
        result = result_maps.get(ticket.get("game"), {}).get(str(ticket.get("date")))
        if not result:
            continue
        settle_ticket(ticket, result)
        settled_now += 1

    tickets.sort(key=lambda t: (str(t.get("date", "")), str(t.get("challenger_id", ""))), reverse=True)
    state["schema_version"] = 1
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    state["policy"] = "Prospective research only. Shadow tickets are created only from already-locked challengers before the target result exists."
    state["summary"] = {lock["id"]: summary_for(lock, tickets) for lock in locks}
    save(state)
    print(json.dumps({
        "locks": len(locks),
        "created": created,
        "settled_now": settled_now,
        "tickets": len(tickets),
        "summary": state["summary"],
    }, indent=2))


if __name__ == "__main__":
    main()
