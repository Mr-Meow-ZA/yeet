#!/usr/bin/env python3
from pathlib import Path

path=Path('drawlab-sa/scripts/ev_hunter.py')
text=path.read_text()
if 'import time\n' not in text:
    text=text.replace('import statistics\n', 'import statistics\nimport time\n')

start=text.index('def fetch_economics(game: str, draw_date: str)')
end=text.index('\n\ndef combined_results()', start)
new_fetch='''def fetch_economics(game: str, draw_date: str) -> dict[str, Any] | None:\n    url = result_url(game, draw_date)\n    for attempt in range(3):\n        # The archive throttles bursty crawlers. A deliberate pause keeps the\n        # research cache polite and reproducible; normal cloud runs do not use\n        # this historical fetch path.\n        time.sleep(0.75)\n        try:\n            r = SESSION.get(url, timeout=HTTP_TIMEOUT)\n            if r.status_code in {403, 429, 500, 502, 503, 504}:\n                time.sleep(2.0 * (attempt + 1))\n                continue\n            r.raise_for_status()\n            parsed = parse_economics_page(game, draw_date, r.text, url)\n            if parsed:\n                return parsed\n        except Exception:\n            time.sleep(1.0 * (attempt + 1))\n    return None\n'''
text=text[:start]+new_fetch+text[end:]

start=text.index('def refresh_history(max_workers: int = 6)')
end=text.index('\n\ndef median(', start)
new_refresh='''def refresh_history(max_workers: int = 6) -> dict[str, Any]:\n    existing = load_json(CACHE_PATH, {"schema_version": 1, "rows": []})\n    cached = {(r.get("date"), r.get("game")): r for r in existing.get("rows", []) if r.get("quality") == "exact_archive"}\n    results = combined_results()\n    today = NOW.date()\n    candidates: dict[str, list[tuple[str, str]]] = defaultdict(list)\n\n    # Work newest-first so the current rule era becomes useful immediately.\n    # Limit each refresh to a small batch; future weekly runs gradually deepen\n    # the exact economics archive without hammering the source.\n    for row in reversed(results):\n        game, draw_date = row.get("game"), row.get("date")\n        if game not in RULES or not draw_date:\n            continue\n        d = datetime.fromisoformat(draw_date).date()\n        if game == "Lotto" and d < RULE_CHANGE_DATE:\n            continue\n        if game == "PowerBall" and d < date(2025, 1, 1):\n            continue\n        if game == "Daily Lotto" and d < today - timedelta(days=120):\n            continue\n        key = (draw_date, game)\n        if key not in cached:\n            candidates[game].append(key)\n\n    per_game_cap = 28\n    targets: list[tuple[str, str]] = []\n    for game in RULES:\n        targets.extend(candidates.get(game, [])[:per_game_cap])\n\n    fetched = 0\n    failed = 0\n    # A single worker is intentional. The source accepts ordinary sequential\n    # traffic but throttles aggressive parallel crawls.\n    worker_count = 1\n    if targets:\n        with ThreadPoolExecutor(max_workers=worker_count) as pool:\n            future_map = {pool.submit(fetch_economics, game, draw_date): (draw_date, game) for draw_date, game in targets}\n            for fut in as_completed(future_map):\n                key = future_map[fut]\n                try:\n                    row = fut.result()\n                except Exception:\n                    row = None\n                if row:\n                    cached[key] = row\n                    fetched += 1\n                else:\n                    failed += 1\n    rows = sorted(cached.values(), key=lambda r: (r["date"], r["game"]))\n    output = {\n        "schema_version": 1,\n        "updated_at": datetime.now(timezone.utc).isoformat(),\n        "source_policy": "Exact public result pages; newest-first paced cache. Ticket cost is rule-era configured and effective line volume is derived from Total Sales / ticket cost.",\n        "rows": rows,\n        "coverage": {game: sum(r.get("game") == game for r in rows) for game in RULES},\n        "refresh": {"requested": len(targets), "fetched": fetched, "failed": failed, "per_game_cap": per_game_cap, "workers": worker_count},\n    }\n    save_json(CACHE_PATH, output)\n    return output\n'''
text=text[:start]+new_refresh+text[end:]

start=text.index('def fetch_current_jackpots()')
end=text.index('\n\ndef prior_rows(', start)
new_current='''def fetch_current_jackpots() -> tuple[dict[str, float], str | None]:\n    for attempt in range(3):\n        try:\n            r = SESSION.get(RESULTS_URL, timeout=HTTP_TIMEOUT)\n            if r.status_code in {403, 429, 500, 502, 503, 504}:\n                time.sleep(2.0 * (attempt + 1))\n                continue\n            r.raise_for_status()\n            jackpots = parse_current_jackpots(r.text)\n            if jackpots:\n                return jackpots, RESULTS_URL\n        except Exception:\n            pass\n        time.sleep(1.5 * (attempt + 1))\n    return {}, None\n'''
text=text[:start]+new_current+text[end:]
path.write_text(text)

installer=Path('.github/workflows/install-drawlab-ev-hunter.yml')
yaml=installer.read_text().replace('--refresh-history --workers 8','--refresh-history --workers 1')
installer.write_text(yaml)
print('Patched EV cache pacing and installer')
