(() => {
'use strict';

const DB_URL='https://lnmgieielbqqqvboonzj.supabase.co/functions/v1/drawlab-state';
const inV3=location.pathname.includes('/drawlab-sa/v3/');
const LOCAL_URL=inV3?'data/v3-state.json':'v3/data/v3-state.json';
const GAME_ORDER=['Daily Lotto','Lotto','PowerBall'];
const $=id=>document.getElementById(id);
const fmt=n=>new Intl.NumberFormat('en-ZA',{maximumFractionDigits:2}).format(Number(n||0));
const esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const tone=n=>Number(n)>0?'good':Number(n)<0?'bad':'muted';

async function fetchJSON(url,timeout=6000){
  const ctl=new AbortController();
  const timer=setTimeout(()=>ctl.abort(),timeout);
  try{
    const r=await fetch(`${url}${url.includes('?')?'&':'?'}t=${Date.now()}`,{signal:ctl.signal,cache:'no-store'});
    if(!r.ok) throw new Error(String(r.status));
    return await r.json();
  } finally { clearTimeout(timer); }
}

function shadowFor(game,shadow){
  const rows=Object.values(shadow?.summary||{});
  return rows.find(r=>r?.game===game&&r?.status==='shadow')||null;
}

function shadowNote(s){
  if(!s) return '';
  const settled=Number(s.settled||0), pending=Number(s.pending||0);
  const perf=settled?` · prospective avg <b>${s.avg_matches??'—'}</b> · ≥2 <b>${s.ge2_rate??'—'}%</b>`:'';
  return `<div class="notice subtle" style="margin-top:12px"><b>PROSPECTIVE SHADOW LOCK ACTIVE</b><br>${esc(s.name||'Challenger')} was frozen on ${esc(s.locked_on||'—')}. ${settled} future draw${settled===1?'':'s'} settled · ${pending} pending${perf}. Results can evaluate this lock but cannot retune it.</div>`;
}

function card(game,r,shadow){
  const s=shadowFor(game,shadow);
  if(!r || !Object.keys(r).length){
    return `<article class="card"><span class="pill amber">PREPARING</span><h3 style="margin-top:9px">${game}</h3><p class="sub">Discovery state has not been published for this game yet.</p>${shadowNote(s)}</article>`;
  }
  if(r.status==='insufficient_data'){
    return `<article class="card"><div class="card-head"><div><span class="pill amber">WAITING FOR DATA</span><h3 style="margin-top:9px">${game}</h3></div></div><p class="sub" style="margin-top:11px">${esc(r.reason||'Not enough compatible-rule draws yet.')}</p><div class="kpis"><div class="mini"><span>Compatible draws</span><strong>${fmt(r.draws||0)}</strong></div><div class="mini"><span>Minimum target</span><strong>${fmt(r.minimum_needed||0)}</strong></div></div>${shadowNote(s)}</article>`;
  }

  const c=r.selected||{};
  const test=r.held_out_test||{};
  const cm=test.candidate||{};
  const base=test.best_current_v1||{};
  const delta=Number(test.delta_avg_matches_vs_best_v1||0);
  const status=r.status==='promotion_candidate'?'PROMOTION CANDIDATE':r.status==='promising_unproven'?'PROMISING · UNPROVEN':r.status==='early_promising'?'EARLY SIGNAL':'NO IMPROVEMENT';
  const pill=r.status==='promotion_candidate'?'green':(r.status==='promising_unproven'||r.status==='early_promising'?'purple':'');
  const versus=base.strategy?`${base.strategy} · ${base.avg_matches}`:(base.avg_matches??'—');

  return `<article class="card"><div class="card-head"><div><span class="pill ${pill}">${status}</span><h3 style="margin-top:9px">${game}</h3><p class="sub">${esc(c.name||'No selected challenger')}</p></div><span class="pill">${esc(c.family||'research')}</span></div><div class="kpis"><div class="mini"><span>Held-out avg</span><strong>${cm.avg_matches??'—'}</strong></div><div class="mini"><span>Best current v1</span><strong>${esc(versus)}</strong></div><div class="mini"><span>Delta</span><strong class="${tone(delta)}">${delta>0?'+':''}${delta.toFixed(4)}</strong></div><div class="mini"><span>Test draws</span><strong>${fmt(cm.samples||0)}</strong></div></div><p class="sub" style="margin-top:11px">Chance expectation: <b>${cm.expected_matches??'—'}</b>. ≥2 matches: <b>${cm.ge2_rate??'—'}%</b>. Corrected evidence: <b>${esc(String(cm.evidence||'unknown').replaceAll('_',' '))}</b>.</p><p class="sub" style="margin-top:8px">Selected on earlier validation data, then tested once on later untouched draws. It does not enter the live league automatically.</p>${shadowNote(s)}</article>`;
}

function render(discovery,shadow){
  const el=$('discoveryCards');
  if(!el) return;
  const games=discovery?.games||{};
  el.innerHTML=GAME_ORDER.map(game=>card(game,games[game],shadow)).join('');
  const meta=$('discoveryMeta');
  if(meta){
    const families=(discovery?.candidate_families||[]).join(' · ');
    meta.innerHTML=discovery?.candidate_count?`Tested <b>${discovery.candidate_count}</b> pre-declared configurations across ${esc(families)}. Selection uses validation data; the held-out period stays untouched until the winner is fixed. Promising survivors must then earn evidence on genuinely future shadow draws.`:'Discovery engine is preparing its first candidate search.';
  }
}

async function boot(){
  const [dbRes,localRes]=await Promise.allSettled([fetchJSON(DB_URL),fetchJSON(LOCAL_URL,4500)]);
  const db=dbRes.status==='fulfilled'?dbRes.value:null;
  const local=localRes.status==='fulfilled'?localRes.value:null;
  const discovery=db?.research?.strategy_discovery||local?.research?.strategy_discovery||{};
  const shadow=db?.shadow_research||local?.shadow_research||{};
  render(discovery,shadow);
}

boot();
})();
