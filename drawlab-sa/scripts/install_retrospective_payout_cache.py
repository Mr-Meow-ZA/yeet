#!/usr/bin/env python3
from pathlib import Path

P=Path(__file__).with_name('retrospective_v3.py')
s=P.read_text()

s=s.replace(
    'OUT_PATH = ROOT / "v3" / "data" / "retrospective.json"\n',
    'OUT_PATH = ROOT / "v3" / "data" / "retrospective.json"\nPAYOUT_CACHE_PATH = ROOT / "data" / "retrospective-payout-cache.json"\n'
)

marker='''def fetch_payouts(game, d, cache):
    key = f"{game}|{d.isoformat()}"
    if key in cache:
        return cache[key]
    url = payout_url(game, d)
'''
replacement='''def load_archival_payout_cache():
    try:
        payload = json.loads(PAYOUT_CACHE_PATH.read_text())
        entries = payload.get("entries", {})
        return entries if isinstance(entries, dict) else {}
    except Exception:
        return {}


ARCHIVAL_PAYOUT_CACHE = load_archival_payout_cache()


def fetch_payouts(game, d, cache):
    key = f"{game}|{d.isoformat()}"
    if key in cache:
        return cache[key]
    url = payout_url(game, d)
    archived = ARCHIVAL_PAYOUT_CACHE.get(key)
    if isinstance(archived, dict) and archived.get("status") == "exact" and isinstance(archived.get("payouts"), dict):
        payouts = {str(k): float(v) for k, v in archived["payouts"].items()}
        cache[key] = (payouts, "exact", archived.get("source") or url)
        return cache[key]
'''
if marker not in s:
    if 'ARCHIVAL_PAYOUT_CACHE = load_archival_payout_cache()' in s:
        print('Retrospective payout cache already installed')
        raise SystemExit(0)
    raise SystemExit('fetch_payouts marker not found')
s=s.replace(marker,replacement,1)
P.write_text(s)
print('Installed retrospective payout cache support')
