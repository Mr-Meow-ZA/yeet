#!/usr/bin/env python3
from pathlib import Path

p=Path(__file__).with_name('retrospective_v3.py')
s=p.read_text()
old='''def bonus_number(rows, strategy, maximum):\n    eligible = [r for r in rows if isinstance(r.get("bonus"), int) and 1 <= r["bonus"] <= maximum]\n'''
new='''def bonus_number(rows, strategy, maximum, target):\n    # Special-ball ranking is isolated to the applicable PowerBall rule era.\n    change = date(2026, 6, 1)\n    if target >= change:\n        rows = [r for r in rows if r["_date"] >= change]\n    else:\n        rows = [r for r in rows if r["_date"] < change]\n    eligible = [r for r in rows if isinstance(r.get("bonus"), int) and 1 <= r["bonus"] <= maximum]\n'''
if old not in s and new not in s: raise SystemExit('bonus marker missing')
s=s.replace(old,new)
old='''def make_line(rows, game, strategy, target, avoid=None):\n    rule = rule_for(game, target)\n    nums = list(range(1, rule["max"] + 1))\n'''
new='''def model_rows(rows, game, target):\n    # Lotto changed its main number space from 6/58 to 6/52 on 1 June 2026.\n    # Never let a model score a current-era number using incompatible legacy rows.\n    if game == "Lotto":\n        change = date(2026, 6, 1)\n        return [r for r in rows if (r["_date"] >= change) == (target >= change)]\n    return rows\n\n\ndef make_line(rows, game, strategy, target, avoid=None):\n    rule = rule_for(game, target)\n    rows = model_rows(rows, game, target)\n    nums = list(range(1, rule["max"] + 1))\n'''
if old not in s and new not in s: raise SystemExit('make_line marker missing')
s=s.replace(old,new)
s=s.replace('bonus = bonus_number(rows, strategy, rule["bonus_max"]) if game == "PowerBall" else None','bonus = bonus_number(rows, strategy, rule["bonus_max"], target) if game == "PowerBall" else None')
s=s.replace('''        frozen = None\n        for draw in targets:\n            prior = [r for r in rows if r["_date"] < draw["_date"]]\n            if len(prior) < 60:\n                continue\n''','''        frozen_by_era = {}\n        for draw in targets:\n            prior = [r for r in rows if r["_date"] < draw["_date"]]\n            eligible_prior = model_rows(prior, game, draw["_date"])\n            if len(eligible_prior) < 60:\n                continue\n''')
s=s.replace('''            if frozen is None:\n                frozen = make_line(prior, game, "Weighted Historical", draw["_date"])\n            lines[FROZEN] = frozen\n''','''            rule = rule_for(game, draw["_date"])\n            era_key = (rule["max"], rule["bonus_max"], rule["cost"])\n            if era_key not in frozen_by_era:\n                frozen_by_era[era_key] = make_line(prior, game, "Weighted Historical", draw["_date"])\n            lines[FROZEN] = frozen_by_era[era_key]\n''')
s=s.replace('"frozen_policy": "generated once at first eligible simulated draw and never changed",','"frozen_policy": "generated once per legal rule era and never changed within that era; reset only when the lottery itself changes the ticket format",')
p.write_text(s)
print('Patched retrospective for rule-era isolation')
