#!/usr/bin/env python3
from pathlib import Path
p=Path(__file__).with_name('retrospective_v3.py')
s=p.read_text()
if 'import os\n' not in s:
    s=s.replace('import json\n','import json\nimport os\n')
old='''def fetch_payouts(game, d, cache):\n    key = f"{game}|{d.isoformat()}"\n    if key in cache:\n        return cache[key]\n    url = payout_url(game, d)\n    try:\n'''
new='''def fetch_payouts(game, d, cache):\n    key = f"{game}|{d.isoformat()}"\n    if key in cache:\n        return cache[key]\n    url = payout_url(game, d)\n    # Fast deterministic rebuilds use the explicit payout model. Exact archival\n    # enrichment is opt-in so source latency cannot block the research platform.\n    if os.getenv("DRAWLAB_RETRO_EXACT", "0") != "1":\n        cache[key] = (FALLBACK[game], "estimated", url)\n        return cache[key]\n    try:\n'''
if old not in s and new not in s: raise SystemExit('fetch_payouts marker missing')
s=s.replace(old,new)
p.write_text(s)
print('Enabled fast retrospective mode; set DRAWLAB_RETRO_EXACT=1 for archival enrichment')
