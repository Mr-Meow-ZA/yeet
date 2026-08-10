#!/usr/bin/env bash
set -euo pipefail

: "${DRAWLAB_SYNC_TOKEN:?DRAWLAB_SYNC_TOKEN must be configured as a protected GitHub Actions secret}"

DRAWLAB_SYNC_URL="${DRAWLAB_SYNC_URL:-https://lnmgieielbqqqvboonzj.supabase.co/functions/v1/drawlab-sync}"

response="$(curl --fail-with-body --silent --show-error --max-time 90 \
  --request POST \
  --header "x-drawlab-sync-token: ${DRAWLAB_SYNC_TOKEN}" \
  --header 'content-type: application/json' \
  --data '{}' \
  "${DRAWLAB_SYNC_URL}")"

echo "$response"
python - <<'PY' "$response"
import json,sys
payload=json.loads(sys.argv[1])
if not payload.get('ok'):
    raise SystemExit('DrawLab Supabase sync returned ok=false')
sync=payload.get('sync') or {}
for field in ('research_synced','retrospective_synced','shadow_synced','ev_synced'):
    if not sync.get(field):
        raise SystemExit(f'DrawLab Supabase sync missing required confirmation: {field}')
print('DrawLab authenticated Supabase sync validated; methodology',sync.get('research_methodology'))
PY
