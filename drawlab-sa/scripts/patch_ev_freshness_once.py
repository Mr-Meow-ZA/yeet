#!/usr/bin/env python3
from pathlib import Path

path=Path('drawlab-sa/scripts/ev_hunter.py')
text=path.read_text()
needle='''def refresh_history(max_workers: int = 6) -> dict[str, Any]:\n    existing = load_json(CACHE_PATH, {"schema_version": 1, "rows": []})\n    cached = {(r.get("date"), r.get("game")): r for r in existing.get("rows", []) if r.get("quality") == "exact_archive"}\n'''
replacement='''def refresh_history(max_workers: int = 6) -> dict[str, Any]:\n    existing = load_json(CACHE_PATH, {"schema_version": 1, "rows": []})\n    existing_coverage = existing.get("coverage") or {}\n    try:\n        refreshed_at = datetime.fromisoformat(str(existing.get("updated_at", "")).replace("Z", "+00:00"))\n        if refreshed_at.tzinfo is None:\n            refreshed_at = refreshed_at.replace(tzinfo=timezone.utc)\n    except Exception:\n        refreshed_at = None\n    cache_is_useful = (\n        existing_coverage.get("Daily Lotto", 0) >= 10\n        and existing_coverage.get("Lotto", 0) >= 5\n        and existing_coverage.get("PowerBall", 0) >= 5\n    )\n    if refreshed_at and cache_is_useful and datetime.now(timezone.utc) - refreshed_at < timedelta(hours=6):\n        # Repository pushes can fan out into several workflows. Do not recrawl\n        # the public archive repeatedly within the same deployment window.\n        existing["refresh"] = {\n            "requested": 0,\n            "fetched": 0,\n            "failed": 0,\n            "skipped": "fresh_cache",\n            "fresh_for_hours": 6,\n        }\n        return existing\n\n    cached = {(r.get("date"), r.get("game")): r for r in existing.get("rows", []) if r.get("quality") == "exact_archive"}\n'''
if needle not in text:
    if '"skipped": "fresh_cache"' in text:
        print('freshness guard already present')
    else:
        raise SystemExit('refresh_history anchor not found')
else:
    text=text.replace(needle,replacement,1)
    path.write_text(text)
    print('added EV cache freshness guard')
