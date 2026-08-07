#!/usr/bin/env python3
from __future__ import annotations
import importlib.util, json
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ENGINE=ROOT/'scripts'/'update_cloud.py'
FROZEN=ROOT/'v3'/'data'/'frozen-alpha.json'

# Generate the frozen control before patching the live engine. This snapshot is immutable.
spec=importlib.util.spec_from_file_location('drawlab_update',ENGINE); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
state=mod.load_state(); lines={}
for game in mod.RULES:
    nums,bonus=mod.make_line(state,game,'Weighted Historical')
    lines[game]={"numbers":nums,"bonus":bonus,"cost":mod.RULES[game]['cost']}
FROZEN.parent.mkdir(parents=True,exist_ok=True)
if not FROZEN.exists():
    FROZEN.write_text(json.dumps({
      "schema_version":1,"name":"Frozen Alpha","version":"1.0","locked":True,
      "generated_at":datetime.now(timezone.utc).isoformat(),"generation_method":"Weighted Historical v1.0 snapshot",
      "data_policy_version":mod.DATA_POLICY_VERSION,"lines":lines,
      "policy":"These lines never change. A ticket is entered on every eligible draw using the era-correct board cost."
    },indent=2)+"\n")

text=ENGINE.read_text()
if 'FROZEN_PATH = ROOT / "v3" / "data" / "frozen-alpha.json"' not in text:
    text=text.replace('HISTORY_PATH = ROOT / "data" / "historical-results.json"','HISTORY_PATH = ROOT / "data" / "historical-results.json"\nFROZEN_PATH = ROOT / "v3" / "data" / "frozen-alpha.json"')
if '"Frozen Alpha": {' not in text:
    needle='    "Diversified Coverage": {\n        "version": "1.0",\n        "hypothesis": "Structured range coverage with low overlap diversifies the portfolio.",\n    },\n'
    repl=needle+'    "Frozen Alpha": {\n        "version": "1.0",\n        "hypothesis": "A fixed deterministic line provides a permanent control against dynamic refresh strategies.",\n    },\n'
    text=text.replace(needle,repl)
if 'def load_frozen_line(' not in text:
    marker='\ndef make_line(state, game, strategy, avoid=None):\n'
    helper='''\ndef load_frozen_line(game):\n    try:\n        payload = json.loads(FROZEN_PATH.read_text())\n        line = payload.get("lines", {}).get(game, {})\n        numbers = line.get("numbers", [])\n        bonus = line.get("bonus")\n        rule = RULES[game]\n        if len(numbers) == rule["count"] and len(set(numbers)) == len(numbers) and all(1 <= n <= rule["max"] for n in numbers):\n            if game != "PowerBall" or (isinstance(bonus, int) and 1 <= bonus <= rule["bonus_max"]):\n                return sorted(numbers), bonus\n    except Exception:\n        pass\n    raise RuntimeError(f"Frozen Alpha line unavailable or invalid for {game}")\n\n'''
    text=text.replace(marker,'\n'+helper+'def make_line(state, game, strategy, avoid=None):\n')
if 'if strategy == "Frozen Alpha":' not in text:
    text=text.replace('def make_line(state, game, strategy, avoid=None):\n    rule = RULES[game]','def make_line(state, game, strategy, avoid=None):\n    if strategy == "Frozen Alpha":\n        return load_frozen_line(game)\n    rule = RULES[game]')
text=text.replace('order = ("Hot 6M", "Weighted Historical", "Cold 6M", "Diversified Coverage")','order = ("Hot 6M", "Weighted Historical", "Cold 6M", "Diversified Coverage", "Frozen Alpha")')
ENGINE.write_text(text)
print(json.dumps({"frozen":json.loads(FROZEN.read_text()),"patched":True},indent=2))
