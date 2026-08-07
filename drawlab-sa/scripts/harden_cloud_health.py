#!/usr/bin/env python3
from pathlib import Path

path = Path(__file__).resolve().parent / "update_cloud.py"
text = path.read_text()
replacements = [
    ('    state["errors"] = []\n    state["strategy_catalog"] = STRATEGIES', '    state["errors"] = []\n    state["warnings"] = []\n    state["strategy_catalog"] = STRATEGIES'),
    ('        state["errors"].extend(errors)', '        state["warnings"].extend(errors)'),
    ('                state["errors"].append(f"{game} payout: {error}")', '                state["warnings"].append(f"{game} payout: {error}")'),
    ('            state["errors"].append(\n                f"{result.get(\'game\')} {result.get(\'date\')} payout: {error}"\n            )', '            state["warnings"].append(\n                f"{result.get(\'game\')} {result.get(\'date\')} payout: {error}"\n            )'),
]
for old, new in replacements:
    if old in text:
        text = text.replace(old, new, 1)
    elif new not in text:
        raise RuntimeError(f"Expected cloud health block not found: {old[:60]}")

old = '''    settle(state)
    state["status"] = "ok" if not state["errors"] else "partial"
'''
new = '''    settle(state)
    # Source timeouts are warnings while the draw is not overdue. The late
    # results run upgrades a genuinely missing same-day result to an error.
    if NOW.hour >= 22:
        for game in games_for_date(NOW.date()):
            if not any(row.get("date") == TODAY and row.get("game") == game for row in state.get("results", [])):
                state["errors"].append(f"{game}: result is overdue after the late results window")
    state["status"] = "ok" if not state["errors"] else "partial"
'''
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise RuntimeError("Expected settle/status block not found")

old = '                "errors": state["errors"][:8],\n'
new = '                "errors": state["errors"][:8],\n                "warnings": state.get("warnings", [])[:8],\n'
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise RuntimeError("Expected output error block not found")

path.write_text(text)
print("Hardened DrawLab cloud health reporting")
