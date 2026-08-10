(() => {
'use strict';

const DB_URL='https://lnmgieielbqqqvboonzj.supabase.co/functions/v1/drawlab-state';
const inV3=location.pathname.includes('/drawlab-sa/v3/');
const LOCAL_URL=inV3?'data/v3-state.json':'v3/data/v3-state.json';
const GAMES=['Daily Lotto','Lotto','PowerBall'];
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const fmt=n=>new Intl.NumberFormat('en-ZA',{maximumFractionDigits:2}).format(Number(n||0));
const tone=s=>String(s||'').includes('randomness')||String(s||'').includes('empirical_signal')?'good':String(s||'').includes('review')?'bad':String(s||'').includes('watch')?'warn':'muted';

async function json(url,timeout=6000){
  const c=new AbortController(),t=setTimeout(()=>c.abort(),timeout);
  try{const r=await fetch(`${url}${url.includes('?')?'&':'?'}t=${Date.now()}`,{cache:'no-store',signal:c.signal});if(!r.ok)throw new Error(String(r.status));return await r.json();}
  finally{clearTimeout(t);}
}

function inject(){
  const research=$('research');
  if(!research||$('structuralResearch'))return;
  const intro=research.querySelector('.page-intro');
  const wrap=document.createElement('div');
  wrap.id='structuralResearch';
  wrap.innerHTML=`
    <div class="section-head"><div><span class="kicker">RESEARCH ARCHITECTURE</span><h2>Three different questions. Never mix them.</h2><p>Prediction, player behaviour and prize economics are separate experiments with separate evidence standards.</p></div></div>
    <div class="cards cols-3" id="researchLayerCards"></div>

    <div class="split-xl research-v2-split">
      <section>
        <div class="section-head compact"><div><span class="kicker">PLAYER BEHAVIOUR</span><h2>Crowd Model v1</h2><p>Uses South African winner counts to estimate which line shapes other players disproportionately select.</p></div></div>
        <div class="cards" id="crowdV1Cards"></div>
      </section>
      <aside>
        <div class="section-head compact"><div><span class="kicker">RANDOMNESS AUDIT</span><h2>Draw Integrity</h2><p>Frequency, pair, overlap and duplicate diagnostics with multiple-testing correction.</p></div></div>
        <div class="cards" id="integrityCards"></div>
      </aside>
    </div>

    <div class="section-head"><div><span class="kicker">MODEL VERDICT</span><h2>What each strategy is actually for now</h2><p>The original five remain frozen research controls; newer layers focus on measurable economics and player behaviour.</p></div></div>
    <div class="panel table-panel"><div class="table" id="modelVerdictTable"></div></div>
  `;
  intro.insertAdjacentElement('afterend',wrap);
  const style=document.createElement('style');
  style.textContent=`
    #structuralResearch{margin-top:8px}
    #structuralResearch .layer-icon{width:38px;height:38px;border-radius:12px;display:grid;place-items:center;background:rgba(255,255,255,.06);font-size:19px;margin-bottom:12px}
    #structuralResearch .effect-list{display:grid;gap:7px;margin-top:10px}
    #structuralResearch .effect{display:flex;justify-content:space-between;gap:12px;font-size:12px;color:var(--muted,#8d98a8)}
    #structuralResearch .effect b{color:var(--text,#eef4ff);font-weight:650}
    #structuralResearch .audit-row{display:grid;grid-template-columns:1fr auto;gap:8px;padding:7px 0;border-bottom:1px solid rgba(255,255,255,.06);font-size:12px}
    #structuralResearch .audit-row:last-child{border-bottom:0}
    #structuralResearch .mechanic{font-size:12px;line-height:1.55;color:var(--muted,#8d98a8);margin-top:10px}
    @media(max-width:900px){#structuralResearch .research-v2-split{display:block}#structuralResearch .research-v2-split aside{margin-top:18px}}
  `;
  document.head.appendChild(style);
}

function renderLayers(state){
  const integrity=state.integrity_audit||{};
  const crowd=state.crowd_model||{};
  const ev=state.ev_hunter||{};
  $('researchLayerCards').innerHTML=[
    ['◎','Draw integrity',integrity.overall_status||'initialising','Tests whether the archive gives us a defensible reason to reject random, independent draws. It does not automatically create a prediction strategy.'],
    ['◌','Player crowding',crowd.model_version||'Crowd Model v1.0','Asks which equal-probability lines other people are more likely to choose, because sharing changes monetary value if a prize is won.'],
    ['↗','Prize economics',ev.model_version||'EV Hunter v2.0','Models prize mechanics, ticket demand and co-winner risk to decide whether a draw should be entered at all.']
  ].map(([ico,title,status,body])=>`<div class="card"><div class="layer-icon">${ico}</div><span class="pill ${tone(status)}">${esc(String(status).replaceAll('_',' ').toUpperCase())}</span><h3 style="margin-top:10px">${title}</h3><p class="sub">${body}</p></div>`).join('');
}

function renderCrowd(state){
  const crowd=state.crowd_model||{};
  const games=crowd.games||{};
  $('crowdV1Cards').innerHTML=GAMES.map(game=>{
    const g=games[game]||{};
    const effects=g.largest_effects||[];
    return `<div class="card"><div class="card-head"><div><span class="pill ${tone(g.status)}">${esc(String(g.status||'initialising').replaceAll('_',' ').toUpperCase())}</span><h3 style="margin-top:8px">${game}</h3></div><strong>${fmt(g.samples||0)} draws</strong></div>
      <div class="kpis"><div class="mini"><span>Holdout</span><strong>${fmt(g.holdout_samples||0)}</strong></div><div class="mini"><span>RMSE lift</span><strong class="${Number(g.holdout_improvement_pct)>0?'good':'bad'}">${g.holdout_improvement_pct==null?'—':`${Number(g.holdout_improvement_pct).toFixed(2)}%`}</strong></div></div>
      <div class="effect-list">${effects.length?effects.slice(0,4).map(e=>`<div class="effect"><span>${esc(String(e.feature).replaceAll('_',' '))}</span><b>${e.coefficient>0?'+':''}${Number(e.coefficient).toFixed(3)} · ${esc(String(e.direction).replaceAll('_',' '))}</b></div>`).join(''):'<div class="effect"><span>Not enough exact crowding data yet</span><b>Research only</b></div>'}</div>
      <p class="mechanic">${esc(g.interpretation||'The model remains exploratory until enough exact sales/winner observations support an out-of-sample signal.')}</p></div>`;
  }).join('');
}

function renderIntegrity(state){
  const audit=state.integrity_audit||{};
  const games=audit.games||{};
  $('integrityCards').innerHTML=GAMES.map(game=>{
    const g=games[game]||{};
    const f=g.frequency||{},p=g.pairs||{},o=g.serial_overlap||{};
    return `<div class="card"><div class="card-head"><div><span class="pill ${tone(g.status)}">${esc(String(g.status||'initialising').replaceAll('_',' ').toUpperCase())}</span><h3 style="margin-top:8px">${game}</h3></div><strong>n=${fmt(g.draws||0)}</strong></div>
      <div class="audit-row"><span>Most extreme number</span><b>${f.most_extreme_number??'—'} · pAdj ${f.p_adjusted??'—'}</b></div>
      <div class="audit-row"><span>Most extreme pair</span><b>${Array.isArray(p.most_extreme_pair)?p.most_extreme_pair.join(' · '):'—'} · pAdj ${p.p_adjusted??'—'}</b></div>
      <div class="audit-row"><span>Serial overlap</span><b>${o.observed_overlap??'—'} vs ${o.expected_overlap??'—'}</b></div>
      <div class="audit-row"><span>Minimum corrected p</span><b>${g.minimum_adjusted_p??'—'}</b></div>
      <p class="mechanic">${esc(g.interpretation||`Needs at least ${g.minimum||'more'} compatible draws before the audit is informative.`)}</p></div>`;
  }).join('');
}

function renderVerdicts(){
  const rows=[
    ['Hot 6M','Prediction control','Keep locked','No corrected evidence of persistent draw-prediction alpha. Recent frequency is more useful as a possible player-choice feature.'],
    ['Cold 6M','Prediction control','Keep locked','Some interesting raw Daily Lotto cells, but no multiple-testing-adjusted edge. Useful as falsification research.'],
    ['Weighted Historical','Prediction control','Do not promote','Its frequency/gap blend remains part of experiment history, not proven alpha.'],
    ['Diversified Coverage','Portfolio control','Keep / reinterpret','Useful for reducing overlap across multiple lines; coverage changes portfolio variance, not each line’s odds.'],
    ['Frozen Alpha','Persistence control','Keep permanently','The clean benchmark for never changing the numbers versus dynamic strategies.'],
    ['Crowd Model v1','Player behaviour','Research / calibrate','Predicts sharing pressure rather than the draw. Only out-of-sample crowding evidence can graduate it.'],
    ['EV Hunter v2','Prize economics','Primary new direction','Only enters a shadow ticket when conservative structural EV clears the locked threshold. Otherwise SKIP is the correct action.']
  ];
  $('modelVerdictTable').innerHTML='<div class="tr header"><div>Model</div><div>Role</div><div>Decision</div><div>Research interpretation</div></div>'+rows.map(r=>`<div class="tr"><strong>${r[0]}</strong><div>${r[1]}</div><div>${r[2]}</div><div>${r[3]}</div></div>`).join('');
}

async function load(){
  inject();
  let local={};
  try{local=await json(LOCAL_URL);}catch{}
  let db={};
  try{db=await json(DB_URL);}catch{}
  const state={...local};
  if(db&&db.database_status==='ok'){
    if(db.ev_hunter)state.ev_hunter=db.ev_hunter;
    if(db.crowd_model)state.crowd_model=db.crowd_model;
    if(db.integrity_audit)state.integrity_audit=db.integrity_audit;
  }
  renderLayers(state);renderCrowd(state);renderIntegrity(state);renderVerdicts();
}

document.addEventListener('DOMContentLoaded',load,{once:true});
})();
