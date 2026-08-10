(() => {
'use strict';

const DB_URL='https://lnmgieielbqqqvboonzj.supabase.co/functions/v1/drawlab-state';
const inV3=location.pathname.includes('/drawlab-sa/v3/');
const LOCAL_URL=inV3?'data/v3-state.json':'v3/data/v3-state.json';
const GAMES=['Daily Lotto','Lotto','PowerBall'];
const $=id=>document.getElementById(id);
const fmt=n=>new Intl.NumberFormat('en-ZA',{maximumFractionDigits:2}).format(Number(n||0));
const money=n=>n==null?'—':`R${fmt(n)}`;
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

function decisionPill(decision){
  const label=String(decision||'PREPARING').replaceAll('_',' ');
  const cls=decision==='ENTER_CANDIDATE'?'green':decision==='WATCH'?'amber':decision==='SKIP'?'':'purple';
  return `<span class="pill ${cls}">${esc(label)}</span>`;
}

function balls(line){
  if(!line?.numbers?.length) return '<span class="muted">—</span>';
  const main=line.numbers.map(n=>`<span class="ball">${n}</span>`).join('');
  const bonus=line.bonus!=null?`<span class="ball gold">${line.bonus}</span>`:'';
  return `<div class="balls" style="margin-top:9px">${main}${bonus}</div>`;
}

function currentCard(game,row,version){
  if(!row) return `<article class="card"><h3>${game}</h3><p class="sub">EV model is preparing.</p></article>`;
  const roi=row.expected_roi_pct;
  const conservative=row.conservative_roi_pct;
  const line=row.anti_crowd_line;
  const breakEven=game==='Daily Lotto'?'Not applicable':money(row.break_even_jackpot);
  const jackpot=game==='Daily Lotto'?(row.advertised_jackpot==null?'Sales-funded pool':money(row.advertised_jackpot)):money(row.advertised_jackpot);
  return `<article class="card">
    <div class="card-head"><div>${decisionPill(row.decision)}<h3 style="margin-top:9px">${game}</h3><p class="sub">Draw ${esc(row.draw_date||'—')}</p></div><span class="pill">${esc(version||'EV HUNTER v2.0')}</span></div>
    <div class="kpis">
      <div class="mini"><span>${game==='Daily Lotto'?'Displayed top pool':'Advertised jackpot'}</span><strong>${jackpot}</strong></div>
      <div class="mini"><span>Ticket cost</span><strong>${money(row.ticket_cost)}</strong></div>
      <div class="mini"><span>Central return</span><strong>${money(row.expected_return)}</strong></div>
      <div class="mini"><span>Central ROI</span><strong class="${tone(roi)}">${roi==null?'—':`${roi>0?'+':''}${fmt(roi)}%`}</strong></div>
      <div class="mini"><span>Conservative return</span><strong>${money(row.conservative_return)}</strong></div>
      <div class="mini"><span>Conservative ROI</span><strong class="${tone(conservative)}">${conservative==null?'—':`${conservative>0?'+':''}${fmt(conservative)}%`}</strong></div>
      <div class="mini"><span>Break-even jackpot</span><strong>${breakEven}</strong></div>
      <div class="mini"><span>Predicted / risk volume</span><strong>${row.predicted_line_volume?`${fmt(row.predicted_line_volume)} / ${fmt(row.risk_line_volume||row.predicted_line_volume)}`:'—'}</strong></div>
    </div>
    <div style="margin-top:14px"><span class="label">LOW-SHARING RESEARCH LINE</span>${balls(line)}<p class="sub">${esc(line?.crowd_model||'crowd model preparing')} · crowd score ${line?.crowding_score??'—'}. The EV gate credits this line with <b>zero</b> probability advantage and zero unverified crowding uplift.</p></div>
    <p class="sub" style="margin-top:10px">${esc(row.mechanic||'Structural prize accounting is preparing.')}</p>
  </article>`;
}

function backtestPanel(ev){
  const box=$('evBacktest');
  if(!box) return;
  const rows=ev?.historical_backtest||{};
  const body=GAMES.map(game=>{
    const r=rows[game]||{};
    const roi=r.roi_pct;
    const result=r.entries?`${money(r.won)} returned · ${money(r.net)} net`:'No historical draw crossed the conservative structural entry gate in the exact cached sample.';
    return `<div class="method-row"><b>${game==='Daily Lotto'?'DL':game==='PowerBall'?'PB':'L'}</b><div><h3>${game}</h3><p>${fmt(r.entries||0)} entries · ${money(r.spend||0)} spent · ${result}${roi==null?'':` · <span class="${tone(roi)}">${roi>0?'+':''}${fmt(roi)}% ROI</span>`}</p><p class="sub">${esc(r.interpretation||'Historical entry decisions use only information available before the target draw.')}</p></div></div>`;
  }).join('');
  box.classList.add('methods');
  box.innerHTML=body;
}

function shadowPanel(ev){
  const box=$('evShadow');
  if(!box) return;
  const s=ev?.shadow_summary||{};
  const recent=(ev?.shadow_tickets||[]).slice(0,3);
  const tickets=recent.length?recent.map(t=>`<div class="evidence-rule"><span>${esc(t.date)} · ${esc(t.game)} · v${esc(t.strategy_version||'2.0')}</span><b>${esc(t.status)} · ${t.status==='Settled'?`${t.matches||0} matches · ${money(t.won)}`:`EV ${fmt(t.ev_ratio_at_entry||0)}×`}</b></div>`).join(''):'<p class="sub">No qualifying prospective EV entry yet. That is a valid result: EV Hunter is designed to skip most draws.</p>';
  box.innerHTML=`<div class="kpis"><div class="mini"><span>Shadow entries</span><strong>${fmt(s.tickets||0)}</strong></div><div class="mini"><span>Settled</span><strong>${fmt(s.settled||0)}</strong></div><div class="mini"><span>Spend</span><strong>${money(s.spend||0)}</strong></div><div class="mini"><span>Won</span><strong>${money(s.won||0)}</strong></div></div><div style="margin-top:12px">${tickets}</div>`;
}

function render(ev){
  const cards=$('evCards');
  if(!cards) return;
  const current=ev?.current||{};
  cards.innerHTML=GAMES.map(game=>currentCard(game,current[game],ev?.model_version)).join('');
  const meta=$('evMeta');
  if(meta){
    const cov=ev?.cache_coverage||{},m=ev?.methodology||{};
    meta.innerHTML=ev?.model_version?`<b>${esc(ev.model_version)}</b> now uses structural prize mechanics rather than historical payout medians. <b>Daily Lotto has no independent rollover break-even jackpot</b>; its pool is sales-funded and rolls down. Current exact economics cache: Daily ${fmt(cov['Daily Lotto']||0)} · Lotto ${fmt(cov.Lotto||0)} · PowerBall ${fmt(cov.PowerBall||0)}.<br><br><b>Gate:</b> ${esc(m.gate||'Conservative structural expected value only.')}`:'EV Hunter v2 is building its structural economics state.';
  }
  backtestPanel(ev);
  shadowPanel(ev);
}

async function boot(){
  const [dbRes,localRes]=await Promise.allSettled([fetchJSON(DB_URL),fetchJSON(LOCAL_URL,4500)]);
  const db=dbRes.status==='fulfilled'?dbRes.value:null;
  const local=localRes.status==='fulfilled'?localRes.value:null;
  render(db?.ev_hunter||local?.ev_hunter||{});
}

boot();
})();
