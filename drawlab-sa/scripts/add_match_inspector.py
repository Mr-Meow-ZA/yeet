#!/usr/bin/env python3
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "index.html"
html = path.read_text(encoding="utf-8")

marker = "MATCH_INSPECTOR_V1"
if marker in html:
    print("Match inspector already installed")
    raise SystemExit(0)

css = r'''
/* MATCH_INSPECTOR_V1 */
.tag{cursor:pointer;transition:transform .16s ease,background .16s ease,border-color .16s ease}.tag:hover{transform:translateY(-1px);background:#65a9ff24;border-color:#65a9ff66}.tag:focus-visible{outline:2px solid var(--blue);outline-offset:3px}.match-modal{position:fixed;inset:0;z-index:100;display:none;align-items:flex-end;justify-content:center;background:#000a;backdrop-filter:blur(8px);padding:16px}.match-modal.open{display:flex}.match-sheet{width:min(560px,100%);max-height:min(82vh,720px);overflow:auto;border:1px solid #ffffff1c;border-radius:26px;background:linear-gradient(155deg,#111d29,#080e15);box-shadow:0 30px 100px #000;padding:20px;animation:sheetIn .2s ease}@keyframes sheetIn{from{transform:translateY(18px);opacity:.5}}.match-sheet-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.match-close{width:36px;height:36px;border-radius:12px;border:1px solid var(--line);background:var(--surface3);color:var(--text);font-size:20px;line-height:1;cursor:pointer}.match-section{margin-top:20px}.match-section-title{display:flex;justify-content:space-between;align-items:center;color:var(--muted);font-size:9px;font-weight:850;letter-spacing:.1em;text-transform:uppercase;margin-bottom:9px}.match-ball{width:42px;height:42px;border-radius:50%;display:grid;place-items:center;background:linear-gradient(145deg,#253f59,#132437);border:1px solid #ffffff20;font-weight:900}.match-ball.hit{background:linear-gradient(145deg,#65f0ad,#20bb70);border-color:#83f6c0;color:#03140c;box-shadow:0 0 24px #54e89c42}.match-ball.miss{opacity:.42}.match-ball.bonus-hit{background:linear-gradient(145deg,#ffe082,#d99a27);color:#241600;box-shadow:0 0 24px #f7bd5540}.match-summary{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:18px}.match-stat{padding:12px;border-radius:15px;background:var(--surface2);border:1px solid var(--line)}.match-stat span{display:block;color:var(--muted);font-size:8px}.match-stat strong{display:block;margin-top:4px;font-size:15px}.match-explainer{margin-top:16px;padding:13px;border-radius:15px;background:#65a9ff0d;border:1px solid #65a9ff26;color:#b8c9dc;font-size:10px;line-height:1.55}@media(min-width:620px){.match-modal{align-items:center}}@media(max-width:420px){.match-summary{grid-template-columns:1fr 1fr}.match-summary .match-stat:last-child{grid-column:1/-1}}
'''
html = html.replace("</style>", css + "\n</style>", 1)

modal = r'''
<div id="matchModal" class="match-modal" aria-hidden="true" role="dialog" aria-modal="true" aria-labelledby="matchModalTitle">
  <div class="match-sheet">
    <div class="match-sheet-head">
      <div><p class="ey">MATCH BREAKDOWN</p><h2 id="matchModalTitle">Ticket matches</h2><p id="matchModalSub" class="sub"></p></div>
      <button id="matchModalClose" class="match-close" aria-label="Close match breakdown">×</button>
    </div>
    <div id="matchModalBody"></div>
  </div>
</div>
'''
html = html.replace("</body>", modal + "\n</body>", 1)

js = r'''
<script>
(function(){
  const modal=document.getElementById('matchModal'),body=document.getElementById('matchModalBody'),title=document.getElementById('matchModalTitle'),sub=document.getElementById('matchModalSub'),close=document.getElementById('matchModalClose');
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money=n=>'R '+Number(n||0).toFixed(2).replace('.',',');
  function resultFor(t){return (state?.results||[]).find(r=>r.date===t.date&&r.game===t.game)}
  function locateTicket(card){
    const strategy=(card.querySelector('h3')?.textContent||'').trim();
    const game=(card.querySelector('.ey')?.textContent||'').trim();
    const date=(card.querySelector('.sub')?.textContent||'').match(/20\d{2}-\d{2}-\d{2}/)?.[0];
    const candidates=(state?.virtual?.tickets||[]).filter(t=>t.strategy===strategy&&(!game||t.game.toUpperCase()===game.toUpperCase())&&(!date||t.date===date));
    return candidates.sort((a,b)=>String(b.created_at||'').localeCompare(String(a.created_at||'')))[0];
  }
  function balls(values,hits,bonusValue,bonusHit){
    return '<div class="balls">'+(values||[]).map(n=>'<span class="match-ball '+(hits.has(n)?'hit':'miss')+'">'+esc(n)+'</span>').join('')+(bonusValue!=null?'<span class="match-ball '+(bonusHit?'bonus-hit':'miss')+'">'+esc(bonusValue)+'</span>':'')+'</div>';
  }
  function openTicket(t){
    const r=resultFor(t); if(!r)return;
    const hitSet=new Set((t.numbers||[]).filter(n=>(r.numbers||[]).includes(n)));
    const pb=t.game==='PowerBall'&&t.bonus!=null&&t.bonus===r.bonus;
    const lottoBonus=t.game==='Lotto'&&r.bonus!=null&&(t.numbers||[]).includes(r.bonus);
    title.textContent=t.strategy;
    sub.textContent=t.game+' · '+t.date;
    const prize=Number(t.won||0),cost=Number(t.cost||0);
    const bonusLabel=t.game==='PowerBall'?'PowerBall':t.game==='Lotto'?'Bonus ball':null;
    body.innerHTML=
      '<div class="match-section"><div class="match-section-title"><span>Your ticket</span><span>'+hitSet.size+' main match'+(hitSet.size===1?'':'es')+'</span></div>'+balls(t.numbers,hitSet,t.bonus,pb)+'</div>'+ 
      '<div class="match-section"><div class="match-section-title"><span>Official result</span><span>'+esc(r.payout_type==='exact'?'Verified payout':'Estimated payout')+'</span></div>'+balls(r.numbers,new Set(r.numbers||[]),r.bonus,true)+'</div>'+ 
      '<div class="match-summary"><div class="match-stat"><span>MAIN MATCHES</span><strong>'+hitSet.size+'</strong></div><div class="match-stat"><span>'+(bonusLabel||'RESULT')+'</span><strong>'+(bonusLabel?(pb||lottoBonus?'Matched':'Not matched'):'Settled')+'</strong></div><div class="match-stat"><span>NET RESULT</span><strong class="'+(prize-cost>=0?'positive':'negative')+'">'+money(prize-cost)+'</strong></div></div>'+ 
      '<div class="match-explainer">Matched ticket numbers are highlighted in green. '+(t.game==='PowerBall'?'The gold ball shows the separately drawn PowerBall.':t.game==='Lotto'?'The gold ball shows the separately drawn Lotto bonus ball.':'Daily Lotto has no bonus ball.')+'</div>';
    modal.classList.add('open');modal.setAttribute('aria-hidden','false');close.focus();
  }
  function shut(){modal.classList.remove('open');modal.setAttribute('aria-hidden','true')}
  document.addEventListener('click',e=>{
    const badge=e.target.closest('.tag');
    if(badge&&/^\d+\s+MATCH(?:ES)?$/i.test(badge.textContent.trim())){const t=locateTicket(badge.closest('.card'));if(t)openTicket(t);return}
    if(e.target===modal||e.target===close)shut();
  });
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&modal.classList.contains('open'))shut()});
  document.addEventListener('DOMContentLoaded',()=>{document.querySelectorAll('.tag').forEach(x=>{if(/^\d+\s+MATCH(?:ES)?$/i.test(x.textContent.trim())){x.tabIndex=0;x.setAttribute('role','button');x.setAttribute('aria-label',x.textContent.trim()+'. View matched numbers.')}})});
  document.addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&e.target.matches('.tag[role="button"]')){e.preventDefault();e.target.click()}});
  const observer=new MutationObserver(()=>document.querySelectorAll('.tag').forEach(x=>{if(/^\d+\s+MATCH(?:ES)?$/i.test(x.textContent.trim())&&!x.hasAttribute('role')){x.tabIndex=0;x.setAttribute('role','button');x.setAttribute('aria-label',x.textContent.trim()+'. View matched numbers.')}}));
  observer.observe(document.body,{childList:true,subtree:true});
})();
</script>
'''
html = html.replace("</body>", js + "\n</body>", 1)

path.write_text(html, encoding="utf-8")
print("Installed match inspector")
