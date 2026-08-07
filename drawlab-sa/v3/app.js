(() => {
'use strict';

const NAV = [
  ['overview','⌂','Overview'],['strategies','◈','Strategies'],['live','●','Live'],
  ['research','⌁','Research'],['history','▦','History'],['records','★','Records'],['methodology','≡','Method']
];
const GAME_ORDER = ['Daily Lotto','Lotto','PowerBall'];
const STRATEGIES = ['Hot 6M','Weighted Historical','Cold 6M','Diversified Coverage','Frozen Alpha'];
const STRATEGY_INFO = {
  'Hot 6M': {type:'Dynamic',refresh:'Every draw',hypothesis:'Tests whether recent high-frequency numbers persist over the next draw.',method:'Ranks fixed six-month, three-month and very-recent frequency windows with deterministic tie-breaking.'},
  'Weighted Historical': {type:'Dynamic',refresh:'Every draw',hypothesis:'Tests whether a locked blend of long-term, six-month, momentum and gap signals outperforms simpler rankings.',method:'Versioned weighted score with deterministic spread construction. v1.0 never changes retroactively.'},
  'Cold 6M': {type:'Dynamic',refresh:'Every draw',hypothesis:'Tests whether recently underrepresented numbers revert toward expected frequency.',method:'Low six-month frequency is primary, absence/gap is secondary, followed by deterministic spread constraints.'},
  'Diversified Coverage': {type:'Portfolio',refresh:'Every draw',hypothesis:'Tests whether deliberately reducing overlap across the strategy portfolio improves coverage outcomes.',method:'Constructs a deterministic low-overlap line across number zones after the other live lines are known.'},
  'Frozen Alpha': {type:'Frozen control',refresh:'Never in rule era',hypothesis:'Tests the simplest persistence policy: generate a legal deterministic line once and keep playing it.',method:'Weighted Historical v1.0 snapshot, locked for the compatible legal number space. It resets only if the lottery itself changes the ticket format.'}
};
const DB_URL = 'https://lnmgieielbqqqvboonzj.supabase.co/functions/v1/drawlab-state';
const inV3 = location.pathname.includes('/drawlab-sa/v3/');
const LOCAL_URL = inV3 ? 'data/v3-state.json' : 'v3/data/v3-state.json';
let S = {};
let sourceMode = 'local';

const $ = id => document.getElementById(id);
const fmt = n => new Intl.NumberFormat('en-ZA',{maximumFractionDigits:2}).format(Number(n || 0));
const money = n => `R${fmt(n)}`;
const pct = n => n == null ? '—' : `${Number(n).toFixed(2)}%`;
const cls = n => Number(n) > 0 ? 'good' : Number(n) < 0 ? 'bad' : 'muted';
const dateFmt = value => { try { return new Date(value).toLocaleDateString('en-ZA',{day:'2-digit',month:'short',year:'numeric'}); } catch { return value || '—'; } };
const timeFmt = value => { try { return new Date(value).toLocaleString('en-ZA',{dateStyle:'medium',timeStyle:'short'}); } catch { return value || '—'; } };
const esc = v => String(v ?? '').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const gameLabel = id => ({'daily-lotto':'Daily Lotto','lotto':'Lotto','powerball':'PowerBall'}[id] || id);
const holdLabel = h => h === 'never' ? 'Never' : String(h);

async function fetchJSON(url, timeout=5500){
  const ctl = new AbortController();
  const timer = setTimeout(()=>ctl.abort(),timeout);
  try{
    const r = await fetch(`${url}${url.includes('?')?'&':'?'}t=${Date.now()}`,{signal:ctl.signal,cache:'no-store'});
    if(!r.ok) throw new Error(String(r.status));
    return await r.json();
  } finally { clearTimeout(timer); }
}

function dbFrozenToLocal(rows){
  if(!Array.isArray(rows) || !rows.length) return null;
  const lines = {};
  for(const row of rows){
    lines[row.game] = {numbers:row.numbers||[],bonus:row.bonus,cost:null};
  }
  return {name:'Frozen Alpha',version:'1.0',locked:true,generated_at:rows[0]?.generated_on,generation_method:'Weighted Historical v1.0 snapshot',data_policy_version:'2.0-rule-aware',lines};
}

function dbRetroToLocal(rows, existing){
  if(!Array.isArray(rows) || !rows.length) return existing || {};
  const summary = {};
  for(const r of rows){
    (summary[r.game] ||= {})[r.strategy] = {
      tickets:Number(r.tickets||0),spend:Number(r.spend||0),won:Number(r.won||0),net:Number(r.net||0),roi_pct:r.roi_pct==null?null:Number(r.roi_pct),
      avg_matches:r.avg_matches==null?null:Number(r.avg_matches),ge2_rate:r.ge2_rate==null?null:Number(r.ge2_rate),ge3_rate:r.ge3_rate==null?null:Number(r.ge3_rate),
      best_matches:Number(r.best_matches||0),longest_losing_streak:Number(r.longest_losing_streak||0),evidence:r.evidence
    };
  }
  return {...(existing||{}),summary};
}

function mergeState(local, db){
  const out = {...(local||{})};
  out.db = db || null;
  if(db?.database_status === 'ok'){
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
    out.hall_of_records = db.hall_of_records || out.hall_of_records || [];
    out.recent_results = db.recent_results || out.recent_results || [];
    out.pending_tickets = db.pending_tickets || out.pending_tickets || [];
    out.experiment_queue = db.experiment_queue || [];
    out.database_history = db.history || [];
    const frozen = dbFrozenToLocal(db.frozen);
    if(frozen) out.frozen = {...(out.frozen||{}),...frozen};
    out.retrospective = dbRetroToLocal(db.retrospective,out.retrospective);
    out.portfolio = portfolioFromLeague(out.live_league, db.counts);
  } else {
    sourceMode = 'local';
  }
  return out;
}

function portfolioFromLeague(rows, counts){
  rows = rows || [];
  const spend = rows.reduce((a,r)=>a+Number(r.spend||0),0);
  const won = rows.reduce((a,r)=>a+Number(r.won||0),0);
  const settled = rows.reduce((a,r)=>a+Number(r.settled||0),0);
  const tickets = rows.reduce((a,r)=>a+Number(r.tickets||0),0);
  return {tickets:counts?.tickets??tickets,settled:counts?.settlements??settled,pending:Math.max(0,(counts?.tickets??tickets)-(counts?.settlements??settled)),spend,won,net:won-spend,roi_pct:spend?(won-spend)/spend*100:null,best_matches:Math.max(0,...rows.map(r=>Number(r.best_matches||0)))};
}

function setupNav(){
  for(const id of ['desktopNav','mobileNav']){
    const el=$(id);
    el.innerHTML = NAV.map(([key,ico,label])=>`<button data-view="${key}" class="${key==='overview'?'active':''}">${id==='desktopNav'?`<span class="nav-ico">${ico}</span>${label}`:`<b>${ico}</b>${label}`}</button>`).join('');
    el.addEventListener('click',e=>{const b=e.target.closest('button[data-view]');if(b) show(b.dataset.view);});
  }
  document.body.addEventListener('click',e=>{const b=e.target.closest('[data-goto]');if(b) show(b.dataset.goto);});
}

function show(id){
  if(!NAV.some(x=>x[0]===id)) id='overview';
  document.querySelectorAll('.view').forEach(v=>v.classList.toggle('active',v.id===id));
  document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===id));
  $('viewTitle').textContent = NAV.find(x=>x[0]===id)?.[2] || 'DrawLab';
  history.replaceState(null,'',`${location.pathname}${location.search}#${id}`);
  window.scrollTo({top:0,behavior:'smooth'});
}

function setHealth(){
  const dbOk = S.db?.database_status === 'ok';
  const cloudOk = String(S.cloud_status||'ok').toLowerCase()==='ok';
  $('sourceChip').textContent = dbOk ? 'SUPABASE PRIMARY' : 'REPOSITORY FALLBACK';
  const chip=$('healthChip');
  chip.classList.toggle('warn',!(dbOk&&cloudOk));
  chip.querySelector('span').textContent = dbOk&&cloudOk ? 'HEALTHY' : 'DEGRADED';
  $('railHealth').textContent = dbOk ? 'Database synchronized' : 'Fallback mode active';
  const sync = S.db?.sync?.synced_at || S.generated_at;
  $('railHealthSub').textContent = dbOk ? `${fmt(S.db?.counts?.draws)} draws · last DB sync ${timeFmt(sync)}` : 'The static validated read model is still available if the database endpoint cannot be reached.';
  $('updatedLabel').textContent = `${sourceMode==='database'?'Database read':'Validated fallback'} · ${timeFmt(S.db?.generated_at || S.generated_at)}`;
}

function renderOverview(){
  const live=S.live_league||[];
  const dbCounts=S.db?.counts||{};
  const researchRows=S.research?.walk_forward||[];
  const significant=researchRows.filter(x=>['strong_above_chance','interesting_above_chance'].includes(x.evidence));
  $('evidenceHero').textContent = significant.length ? 'Evidence worth reviewing' : 'No proven edge';
  $('evidenceSub').textContent = significant.length ? 'One or more research cells clear a corrected threshold; this still requires replication across periods.' : 'No tested live strategy has earned a durable predictive claim. That is a valid research outcome.';
  const modelDraws=Object.values(S.research?.data_quality||{}).reduce((a,x)=>a+Number(x.draws||0),0);
  $('overviewMetrics').innerHTML = [
    ['Database draws',dbCounts.draws??modelDraws,'Verified archive'],
    ['Live competitors',Math.max(5,live.length),'4 dynamic + Frozen Alpha'],
    ['Live tickets',dbCounts.tickets??S.portfolio?.tickets??0,'Pre-draw ledger'],
    ['Settlements',dbCounts.settlements??S.portfolio?.settled??0,'Officially scored'],
    ['Research runs',dbCounts.research_runs??15,'Versioned experiments']
  ].map(([l,v,s])=>`<div class="metric"><span>${l}</span><strong>${fmt(v)}</strong><small>${s}</small></div>`).join('');

  $('leagueCards').innerHTML = live.length ? live.slice(0,5).map((r,i)=>leagueCard(r,i)).join('') : '<div class="empty">Live league is waiting for its first database sync.</div>';
  renderPortfolio();
  const recent=(S.recent_results||[]).slice(0,4);
  $('recentOverview').innerHTML = recent.length ? recent.map(resultCard).join('') : '<div class="empty">No official results loaded yet.</div>';
  const cold=(S.research?.horizon1||[]).find(x=>x.game==='Daily Lotto'&&x.strategy==='Cold 6M');
  $('latestInsight').innerHTML = cold ? `<b>Cold 6M is a hypothesis, not a promise.</b><br><br>Its one-draw Daily Lotto walk-forward average is <b>${cold.avg_matches}</b> matches versus a chance expectation of <b>${cold.expected_matches}</b>. Observed lift: <b class="${cls(cold.lift_vs_expected_pct)}">${cold.lift_vs_expected_pct>0?'+':''}${cold.lift_vs_expected_pct}%</b>. Corrected evidence: <b>${esc(String(cold.evidence).replaceAll('_',' '))}</b>.` : '<b>Research state is preparing.</b> The platform will not manufacture an insight when the evidence is unavailable.';
}

function leagueCard(r,i){
  return `<article class="card clickable" data-strategy="${esc(r.strategy)}"><div class="card-head"><div><span class="pill ${r.strategy==='Frozen Alpha'?'purple':'green'}">#${i+1} · ${r.strategy==='Frozen Alpha'?'FROZEN':'LIVE'}</span><h3 style="margin-top:9px">${esc(r.strategy)}</h3><p class="sub">${esc(STRATEGY_INFO[r.strategy]?.type||'Strategy')}</p></div><strong class="${cls(r.net)}">${money(r.net)}</strong></div><div class="kpis"><div class="mini"><span>ROI</span><strong class="${cls(r.roi_pct)}">${pct(r.roi_pct)}</strong></div><div class="mini"><span>Best</span><strong>${Number(r.best_matches||0)} match</strong></div><div class="mini"><span>Settled</span><strong>${fmt(r.settled)}</strong></div><div class="mini"><span>Avg match</span><strong>${r.avg_matches??'—'}</strong></div></div></article>`;
}

function renderPortfolio(){
  const p=S.portfolio||portfolioFromLeague(S.live_league||[],S.db?.counts);
  const max=Math.max(Number(p.spend||0),Number(p.won||0),1);
  $('portfolioPanel').innerHTML = `<div class="portfolio-total"><div><span>NET RESEARCH P/L</span><strong class="${cls(p.net)}">${money(p.net)}</strong></div><span class="pill ${Number(p.roi_pct)>=0?'green':'red'}">ROI ${pct(p.roi_pct)}</span></div><div class="portfolio-bars"><div class="progress-row"><span>Spend</span><div class="track"><i style="width:${Math.max(3,Number(p.spend||0)/max*100)}%"></i></div><b>${money(p.spend)}</b></div><div class="progress-row"><span>Winnings</span><div class="track"><i style="width:${Math.max(3,Number(p.won||0)/max*100)}%"></i></div><b>${money(p.won)}</b></div></div><div class="kpis"><div class="mini"><span>Tickets</span><strong>${fmt(p.tickets)}</strong></div><div class="mini"><span>Settled</span><strong>${fmt(p.settled)}</strong></div><div class="mini"><span>Pending</span><strong>${fmt(p.pending)}</strong></div><div class="mini"><span>Best</span><strong>${p.best_matches||0} matches</strong></div></div>`;
}

function resultCard(r){
  const nums=(r.numbers||r.main_numbers||[]);
  const bonus=r.bonus ?? r.bonus_number;
  return `<div class="result-card"><div class="result-date"><span>${esc(r.game)}</span><strong>${dateFmt(r.date||r.draw_date)}</strong></div><div class="balls">${nums.map(n=>`<span class="ball">${n}</span>`).join('')}${bonus!=null?`<span class="ball gold">${bonus}</span>`:''}</div><div class="result-source"><span>${esc(r.verification_status||r.payout_type||'verified')}</span><b>${r.payout_divisions!=null?`${r.payout_divisions} payout divisions`:r.payout_type==='exact'?'exact payout':'official result'}</b></div></div>`;
}

function renderStrategies(){
  const liveMap=Object.fromEntries((S.live_league||[]).map(x=>[x.strategy,x]));
  $('strategyCards').innerHTML = STRATEGIES.map(name=>{
    const info=STRATEGY_INFO[name],r=liveMap[name]||{};
    return `<article class="card clickable" data-strategy="${esc(name)}"><div class="card-head"><div><span class="pill ${name==='Frozen Alpha'?'purple':'green'}">${esc(info.type)}</span><h3 style="margin-top:9px">${esc(name)} <span class="muted">v1.0</span></h3></div><span class="pill">LOCKED VERSION</span></div><p class="sub" style="margin-top:11px">${esc(info.hypothesis)}</p><div class="kpis"><div class="mini"><span>Refresh</span><strong>${esc(info.refresh)}</strong></div><div class="mini"><span>Settled</span><strong>${fmt(r.settled||0)}</strong></div><div class="mini"><span>Net</span><strong class="${cls(r.net)}">${r.net==null?'—':money(r.net)}</strong></div><div class="mini"><span>Best</span><strong>${r.best_matches||0} match</strong></div></div><button class="btn" style="margin-top:12px" data-strategy="${esc(name)}">Open research profile</button></article>`;
  }).join('');
}

function renderLive(){
  const f=S.frozen||{};
  $('frozenCards').innerHTML = GAME_ORDER.map(game=>{
    const l=f.lines?.[game]; if(!l) return '';
    return `<div class="card"><div class="card-head"><div><span class="pill purple">LOCKED CONTROL</span><h3 style="margin-top:9px">${game}</h3></div><span class="pill">v${esc(f.version||'1.0')}</span></div><div class="balls" style="margin-top:13px">${(l.numbers||[]).map(n=>`<span class="ball">${n}</span>`).join('')}${l.bonus!=null?`<span class="ball gold">${l.bonus}</span>`:''}</div><p class="sub" style="margin-top:11px">Never re-ranked because of wins or losses. Reset only when the legal ticket format itself changes.</p></div>`;
  }).join('') || '<div class="empty">Frozen Alpha is initializing.</div>';

  const pending=S.pending_tickets||[];
  $('pendingTable').innerHTML = `<div class="tr header"><div>Strategy / game</div><div>Date</div><div>Numbers</div><div>Cost</div><div>Status</div><div>Version</div></div>` + (pending.length?pending.slice(0,24).map(t=>`<div class="tr"><strong>${esc(t.strategy)}<br><span class="muted">${esc(t.game)}</span></strong><div>${dateFmt(t.date)}</div><div>${esc((t.numbers||[]).join(' · '))}${t.bonus!=null?` + ${t.bonus}`:''}</div><div>${money(t.cost)}</div><div class="warn">${esc(t.status||'Pending')}</div><div>v${esc(t.version||t.strategy_version||'1.0')}</div></div>`).join(''):'<div class="empty">No pending tickets right now.</div>');

  const rows=S.live_league||[];
  $('liveTable').innerHTML = `<div class="tr header"><div>Strategy</div><div>Settled</div><div>Spend</div><div>Won</div><div>Net</div><div>ROI</div></div>` + rows.map(r=>`<div class="tr"><strong>${esc(r.strategy)}</strong><div>${fmt(r.settled)}</div><div>${money(r.spend)}</div><div>${money(r.won)}</div><div class="${cls(r.net)}">${money(r.net)}</div><div class="${cls(r.roi_pct)}">${pct(r.roi_pct)}</div></div>`).join('');
}

function renderResearch(){
  const retro=S.retrospective?.summary||{};
  const retroGames=GAME_ORDER.filter(g=>retro[g]);
  $('retroGame').innerHTML=(retroGames.length?retroGames:GAME_ORDER).map(g=>`<option>${g}</option>`).join('');
  $('retroGame').onchange=()=>renderRetro($('retroGame').value);
  renderRetro($('retroGame').value);

  const wf=S.research?.walk_forward||[];
  const holdGames=GAME_ORDER.filter(g=>wf.some(r=>r.game===g));
  $('holdGame').innerHTML=(holdGames.length?holdGames:GAME_ORDER).map(g=>`<option>${g}</option>`).join('');
  $('holdGame').onchange=()=>renderHoldMatrix($('holdGame').value);
  renderHoldMatrix($('holdGame').value);

  const ch=S.research?.challengers||{};
  $('challengerCards').innerHTML = Object.entries(ch).map(([game,c])=>{
    const test=c.held_out_test?.challenger,champ=c.held_out_test?.champion_v1;
    return `<div class="card"><div class="card-head"><div><span class="pill ${c.status==='candidate'?'purple':'amber'}">${esc(String(c.status||'unknown').toUpperCase())}</span><h3 style="margin-top:8px">${esc(game)}</h3></div></div><p class="sub">${esc(c.model||`Needs ${c.minimum_needed||'more'} compatible draws before challenger research.`)}</p>${test?`<div class="kpis"><div class="mini"><span>Challenger avg</span><strong>${test.avg_matches}</strong></div><div class="mini"><span>Champion avg</span><strong>${champ?.avg_matches??'—'}</strong></div><div class="mini"><span>Held-out n</span><strong>${test.samples}</strong></div><div class="mini"><span>Evidence</span><strong>${esc(String(test.evidence).replaceAll('_',' '))}</strong></div></div><p class="sub" style="margin-top:10px">Promotion remains disabled until a pre-declared evidence threshold is met across sufficient out-of-sample data.</p>`:''}</div>`;
  }).join('') || '<div class="empty">No challenger studies yet.</div>';

  const queue=S.experiment_queue||[];
  $('experimentQueue').innerHTML = queue.length ? queue.map(q=>`<div class="card queue-card"><div><h3>${esc(q.title)}</h3><p>${esc(q.hypothesis)}</p></div><span class="pill ${q.status==='candidate'?'purple':q.status==='running'?'green':'amber'}">${esc(String(q.status||'proposed').toUpperCase())}</span></div>`).join('') : `<div class="card queue-card"><div><h3>Multi-season retrospective</h3><p>Repeat the same locked methods across more non-overlapping historical periods before interpreting one good season.</p></div><span class="pill amber">PROPOSED</span></div>`;
}

function renderRetro(game){
  const rows=S.retrospective?.summary?.[game]||{};
  $('retroTable').innerHTML = `<div class="tr header"><div>Strategy</div><div>Tickets</div><div>Spend</div><div>Won*</div><div>Net*</div><div>ROI*</div></div>` + Object.entries(rows).map(([name,r])=>`<div class="tr"><strong>${esc(name)}</strong><div>${fmt(r.tickets)}</div><div>${money(r.spend)}</div><div>${money(r.won)}</div><div class="${cls(r.net)}">${money(r.net)}</div><div class="${cls(r.roi_pct)}">${pct(r.roi_pct)}</div></div>`).join('');
  if(!Object.keys(rows).length) $('retroTable').innerHTML += '<div class="empty">Retrospective state is not available.</div>';
  const q=S.retrospective?.payout_quality||{};
  $('retroQuality').innerHTML = `<b>How to read this:</b> predictions and match counts are strict walk-forward results with no future leakage. Historical financial values marked * currently use payout-model estimates unless an archived exact table has been enriched. The live ledger never substitutes estimates when an exact settled payout is available. ${q.exact_draws!=null?`Archive enrichment status: <b>${q.exact_draws}</b> exact draw tables, <b>${q.estimated_draws||0}</b> estimated.`:''}`;
}

function renderHoldMatrix(game){
  const all=S.research?.walk_forward||[];
  const rows=all.filter(r=>r.game===game);
  const horizons=[1,2,4,8,20,'never'];
  if(!rows.length){$('holdMatrix').innerHTML='<div class="empty">Hold-policy state is rebuilding.</div>';return;}
  const bestMap=Object.fromEntries((S.research?.best_hold||[]).filter(r=>r.game===game).map(r=>[r.strategy,String(r.best_horizon)]));
  let html='<div class="hold-grid"><div class="hold-cell head">Strategy</div>'+horizons.map(h=>`<div class="hold-cell head">${holdLabel(h)}</div>`).join('');
  for(const strategy of STRATEGIES.filter(s=>s!=='Frozen Alpha')){
    html+=`<div class="hold-cell strategy">${esc(strategy)}</div>`;
    for(const h of horizons){
      const r=rows.find(x=>x.strategy===strategy&&String(x.horizon)===String(h));
      const best=bestMap[strategy]===String(h);
      html+=`<div class="hold-cell ${best?'best':''}">${r?`<b>${r.avg_matches}</b><span>${r.ge2_rate}% ≥2 · n=${r.samples}</span>`:'<b>—</b><span>not run</span>'}</div>`;
    }
  }
  html+='</div><div class="notice subtle" style="margin-top:13px"><b>Primary score:</b> average main-number matches, then ≥2-match rate. ROI is not used to select a hold policy because one rare payout can dominate a small financial sample. “Never” means generate once at the first eligible target and hold within the compatible rule era.</div>';
  $('holdMatrix').innerHTML=html;
}

function renderHistory(){
  const dbHist=S.database_history||S.db?.history||[];
  const model=S.research?.data_quality||{};
  const map=Object.fromEntries(dbHist.map(x=>[x.game,x]));
  $('historyCards').innerHTML = GAME_ORDER.map(game=>{
    const total=Number(map[game]?.draws||0), eligible=Number(model[game]?.draws||0), ratio=total?eligible/total*100:0;
    return `<div class="card"><div class="history-stat"><div><span>TOTAL VERIFIED ARCHIVE</span><strong>${fmt(total||eligible)}</strong></div><span class="pill ${model[game]?.status==='usable'?'green':'amber'}">${esc(String(model[game]?.status||'unknown').toUpperCase())}</span></div><h3 style="margin-top:12px">${game}</h3><p class="sub">${esc(model[game]?.first_draw||map[game]?.first_draw||'—')} → ${esc(model[game]?.last_draw||map[game]?.last_draw||'—')}</p><div class="scope-bar"><i style="width:${Math.max(4,Math.min(100,ratio||100))}%"></i></div><p class="sub">Model-eligible scope: <b>${fmt(eligible)}</b>${total?` of ${fmt(total)} archived draws`:''}. ${esc(model[game]?.rule_scope||'')}</p></div>`;
  }).join('');
  const recent=(S.recent_results||[]).slice(0,12);
  $('historyResults').innerHTML = recent.length ? recent.map(resultCard).join('') : '<div class="empty">No draw tape available.</div>';
}

function renderRecords(){
  const rows=S.hall_of_records||[];
  $('recordsList').innerHTML = rows.length ? rows.map(r=>`<div class="record"><div class="rank">#${r.rank}</div><div><h3>${esc(r.strategy)} · ${esc(r.game)}</h3><p>${dateFmt(r.date)} · ${esc((r.numbers||[]).join(' · '))}${r.bonus!=null?` + ${r.bonus}`:''}</p></div><div class="record-score"><strong>${Number(r.matches||0)} match${Number(r.matches||0)===1?'':'es'}</strong><span>${money(r.won)} · ${esc(r.payout_type||'no payout')}</span></div></div>`).join('') : '<div class="empty">No settled live records yet.</div>';
}

function renderMethodology(){
  const descriptions=[
    'A historical target draw is never visible when its prediction is generated.',
    'Completed live tickets and research runs remain part of the audit trail.',
    'A formula change creates a new version rather than rewriting v1.0.',
    'Wins and losses evaluate strategies; they are not treated as magical feedback for individual numbers.',
    'Every valid lottery line starts with equal mathematical odds. Random independence is the default explanation.',
    'A rare prize can distort ROI, so match distributions and evidence thresholds matter too.',
    'Testing many ideas raises false-discovery risk, so corrected evidence is reported.',
    'Rule changes create explicit boundaries instead of silently mixing incompatible outcome spaces.',
    'Missing or questionable source data is withheld rather than fabricated.'
  ];
  $('principles').innerHTML=(S.principles||[]).map((p,i)=>`<div class="method-row"><b>${i+1}</b><div><h3>${esc(p)}</h3><p>${esc(descriptions[i]||'')}</p></div></div>`).join('');
  const db=S.db||{},sync=db.sync||{};
  $('architectureCards').innerHTML = [
    ['Supabase / Postgres',`${fmt(db.counts?.draws||0)} draws · ${fmt(db.counts?.tickets||0)} live tickets`,`Primary structured store for draws, tickets, settlements, strategies, frozen portfolios and research runs.`,'green'],
    ['GitHub audit snapshot','Automatic fallback','Validated JSON snapshots stay reproducible and keep the site usable if the database endpoint is temporarily unavailable.',''],
    ['Versioned research engine',`Methodology ${esc(S.research?.methodology_version||'—')}`,'Walk-forward simulations, hold-policy tests and challengers run separately from the live experiment.','purple']
  ].map(([t,b,p,c])=>`<div class="card"><span class="pill ${c}">${b}</span><h3 style="margin-top:10px">${t}</h3><p class="sub">${p}</p></div>`).join('');
  $('metadataPanel').innerHTML = `<div class="meta-grid"><div class="meta-item"><span>DATABASE SYNC</span><strong>${timeFmt(sync.synced_at)}</strong></div><div class="meta-item"><span>SOURCE UPDATED</span><strong>${timeFmt(sync.source_updated_at||S.cloud_updated_at)}</strong></div><div class="meta-item"><span>ROWS WRITTEN LAST SYNC</span><strong>${fmt(sync.rows_written||0)}</strong></div><div class="meta-item"><span>RESEARCH METHODOLOGY</span><strong>${esc(S.research?.methodology_version||'—')}</strong></div><div class="meta-item"><span>DATA POLICY</span><strong>${esc(S.data_policy?.version||S.frozen?.data_policy_version||'2.0-rule-aware')}</strong></div><div class="meta-item"><span>UI READ SOURCE</span><strong>${sourceMode==='database'?'Supabase primary':'Repository fallback'}</strong></div></div><div class="notice subtle" style="margin-top:13px">DrawLab is a private research project. It can generate lines and paper-track them, but it does not claim to alter the underlying probability of a valid lottery ticket.</div>`;
}

function openStrategy(name){
  const info=STRATEGY_INFO[name]; if(!info) return;
  const live=(S.live_league||[]).find(x=>x.strategy===name)||{};
  const retro=S.retrospective?.summary||{};
  const best=S.research?.best_hold||[];
  const profiles=GAME_ORDER.map(game=>{
    const rr=retro[game]?.[name];
    const h=best.find(x=>x.game===game&&x.strategy===name);
    return `<div class="profile-game"><div class="row"><b>${game}</b><span class="${cls(rr?.roi_pct)}">${rr?`1Y ROI* ${pct(rr.roi_pct)}`:'No 1Y run'}</span></div><div class="row"><span>Retrospective best match</span><b>${rr?.best_matches??'—'}</b></div><div class="row"><span>Best tested hold policy</span><b>${h?holdLabel(h.best_horizon):name==='Frozen Alpha'?'Never':'—'}</b></div></div>`;
  }).join('');
  $('drawerBody').innerHTML=`<span class="pill ${name==='Frozen Alpha'?'purple':'green'}">${esc(info.type)} · v1.0</span><h2>${esc(name)}</h2><p class="drawer-lede">${esc(info.hypothesis)}</p><div class="drawer-section"><h3>Method</h3><p class="drawer-lede">${esc(info.method)}</p></div><div class="drawer-section"><h3>Live record</h3><div class="kpis"><div class="mini"><span>Refresh</span><strong>${esc(info.refresh)}</strong></div><div class="mini"><span>Settled</span><strong>${fmt(live.settled||0)}</strong></div><div class="mini"><span>Live ROI</span><strong class="${cls(live.roi_pct)}">${pct(live.roi_pct)}</strong></div><div class="mini"><span>Best live</span><strong>${live.best_matches||0}</strong></div></div></div><div class="drawer-section"><h3>Historical research profile</h3>${profiles}<p class="sub" style="margin-top:10px">* Retrospective financial values may include labelled payout estimates. Match results are generated from historical official draws.</p></div>`;
  $('drawerBackdrop').hidden=false;
  $('strategyDrawer').classList.add('open');$('strategyDrawer').setAttribute('aria-hidden','false');
}
function closeDrawer(){ $('strategyDrawer').classList.remove('open');$('strategyDrawer').setAttribute('aria-hidden','true');setTimeout(()=>$('drawerBackdrop').hidden=true,180); }

function bindInteractive(){
  document.body.addEventListener('click',e=>{const target=e.target.closest('[data-strategy]');if(target) openStrategy(target.dataset.strategy);});
  $('drawerClose').onclick=closeDrawer;$('drawerBackdrop').onclick=closeDrawer;
  document.addEventListener('keydown',e=>{if(e.key==='Escape') closeDrawer();});
}

function render(){
  setHealth();renderOverview();renderStrategies();renderLive();renderResearch();renderHistory();renderRecords();renderMethodology();
}

async function boot(){
  setupNav();bindInteractive();
  let local={},db=null;
  const results=await Promise.allSettled([fetchJSON(LOCAL_URL,4500),fetchJSON(DB_URL,6000)]);
  if(results[0].status==='fulfilled') local=results[0].value;
  if(results[1].status==='fulfilled') db=results[1].value;
  S=mergeState(local,db);
  if(!Object.keys(S).length){S={cloud_status:'degraded',research:{},principles:[]};}
  render();
  const hash=location.hash.slice(1); if(hash) show(hash);
  if('serviceWorker' in navigator){ navigator.serviceWorker.register(inV3?'../sw.js':'sw.js').catch(()=>{}); }
}

boot();
})();
