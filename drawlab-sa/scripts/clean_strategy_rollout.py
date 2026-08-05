from pathlib import Path
import json

script = Path('drawlab-sa/scripts/update_cloud.py')
text = script.read_text()
old = '''    for game in games_for_date(NOW.date()):
        costs.setdefault(game, RULES[game]["cost"])
        generated = []
'''
new = '''    for game in games_for_date(NOW.date()):
        # Never create a virtual ticket after that game's result is already known.
        if any(r.get("date") == TODAY and r.get("game") == game for r in state.get("results", [])):
            continue
        costs.setdefault(game, RULES[game]["cost"])
        generated = []
'''
if old not in text:
    raise SystemExit('ensure_virtual_entries marker not found')
script.write_text(text.replace(old, new, 1))

state_path = Path('drawlab-sa/data/cloud-state.json')
state = json.loads(state_path.read_text())
# Remove v1.0 tickets created during the post-result migration. Historical pre-v1 tickets remain untouched.
state['virtual']['tickets'] = [t for t in state.get('virtual', {}).get('tickets', []) if not (t.get('date') == '2026-08-05' and t.get('strategy_version') == '1.0')]
state_path.write_text(json.dumps(state, indent=2) + '\n')
print('Removed retroactive v1.0 tickets and installed post-result creation guard')
