#!/usr/bin/env python3
from pathlib import Path

path = Path(__file__).resolve().parent / "update_cloud.py"
text = path.read_text()
old = '''    state["data_policy"] = {
        "version": DATA_POLICY_VERSION,
        "rule_change_date": RULE_CHANGE_DATE.isoformat(),
        "Lotto": "current model uses 6/52 draws from 2026-06-01 onward",
        "PowerBall": "main model uses 5/50 history; special ball uses current 1-16 era",
        "Daily Lotto": "5/36 format unchanged",
    }

    if NOW.hour < ENTRY_OPEN_HOUR or NOW.hour >= ENTRY_CUTOFF_HOUR:
        return
'''
new = '''    state["data_policy"] = {
        "version": DATA_POLICY_VERSION,
        "rule_change_date": RULE_CHANGE_DATE.isoformat(),
        "Lotto": "current model uses 6/52 draws from 2026-06-01 onward",
        "PowerBall": "main model uses 5/50 history; special ball uses current 1-16 era",
        "Daily Lotto": "5/36 format unchanged",
    }
    # Keep current board prices current without rewriting historical ticket costs.
    for game, rule in RULES.items():
        costs[game] = rule["cost"]

    # If the methodology/data policy changes before today's draw, discard only
    # still-pending same-day entries from the superseded policy. They will be
    # recreated during the normal 17:00-20:00 entry window. Settled history is
    # never rewritten.
    if NOW.hour < ENTRY_CUTOFF_HOUR:
        tickets[:] = [
            ticket for ticket in tickets
            if not (
                ticket.get("date") == TODAY
                and ticket.get("status") == "Pending result"
                and ticket.get("data_policy_version") != DATA_POLICY_VERSION
            )
        ]

    if NOW.hour < ENTRY_OPEN_HOUR or NOW.hour >= ENTRY_CUTOFF_HOUR:
        return
'''
if new not in text:
    if old not in text:
        raise RuntimeError("Expected ensure_virtual_entries policy block not found")
    text = text.replace(old, new, 1)
path.write_text(text)
print("Hardened current-draw cohort handling")
