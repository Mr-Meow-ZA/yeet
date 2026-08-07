#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'v3'/'app.js'
s=APP.read_text()
old="""  if(db?.database_status === 'ok'){
    sourceMode = 'database';
    out.live_league = db.live_league || out.live_league || [];
"""
new="""  if(db?.database_status === 'ok'){
    sourceMode = 'database';
    const rs = db.research;
    if(rs && typeof rs === 'object'){
      const walk = Array.isArray(rs.walk_forward) ? rs.walk_forward : (out.research?.walk_forward || []);
      out.research = {
        ...(out.research || {}),
        methodology_version: rs.methodology_version || out.research?.methodology_version,
        null_hypothesis: rs.null_hypothesis || out.research?.null_hypothesis,
        live_policy: rs.live_policy || out.research?.live_policy,
        feedback_policy: rs.feedback_policy || out.research?.feedback_policy,
        data_quality: rs.data_quality || out.research?.data_quality || {},
        chance_baselines: rs.chance_baselines || out.research?.chance_baselines || {},
        walk_forward: walk,
        horizon1: walk.filter(r => String(r.horizon) === '1'),
        best_hold: rs.best_hold || out.research?.best_hold || [],
        challengers: rs.challengers || out.research?.challengers || {},
        notes: rs.notes || out.research?.notes || []
      };
    }
    out.live_league = db.live_league || out.live_league || [];
"""
if old not in s:
    if 'const rs = db.research;' in s:
        print('Database research snapshot already wired')
        raise SystemExit(0)
    raise SystemExit('mergeState marker not found')
s=s.replace(old,new,1)
APP.write_text(s)
print('Wired v3 UI to Supabase research snapshot with repository fallback')
