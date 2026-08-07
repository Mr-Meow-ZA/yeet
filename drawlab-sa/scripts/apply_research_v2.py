#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"Could not patch {label}: expected text not found")
    return text.replace(old, new, 1)


def patch_python() -> None:
    cloud = ROOT / "scripts" / "update_cloud.py"
    text = cloud.read_text()
    text = text.replace('"bonus_max": 16', '"bonus_max": 20')
    if "ENTRY_OPEN_HOUR" not in text:
        text = replace_once(text, "ENTRY_CUTOFF_HOUR = 20", "ENTRY_OPEN_HOUR = 17\nENTRY_CUTOFF_HOUR = 20", "entry open hour")
    text = text.replace("if NOW.hour >= ENTRY_CUTOFF_HOUR:", "if NOW.hour < ENTRY_OPEN_HOUR or NOW.hour >= ENTRY_CUTOFF_HOUR:")
    cloud.write_text(text)

    importer = ROOT / "scripts" / "import_history.py"
    text = importer.read_text().replace('"bonus_max": 16', '"bonus_max": 20')
    importer.write_text(text)

    validator = ROOT / "scripts" / "validate_state.py"
    text = validator.read_text().replace('"PowerBall": {"count": 5, "max": 50, "bonus_max": 16}', '"PowerBall": {"count": 5, "max": 50, "bonus_max": 20}')
    text = text.replace('state.get("status") in {"initialising", "healthy", "partial", "degraded"}', 'state.get("status") in {"initialising", "healthy", "ok", "partial", "degraded"}')
    text = text.replace('require(history.get("schema_version") == 1, "Unsupported historical-results schema_version")', 'require(history.get("schema_version") in {1, 2}, "Unsupported historical-results schema_version")')
    validator.write_text(text)


def patch_index() -> None:
    path = ROOT / "index.html"
    text = path.read_text()
    if "RESEARCH_V2_UI" in text:
        return

    css = r'''
/* RESEARCH_V2_UI */
.research-hero{padding:18px;background:radial-gradient(circle at 100% 0,#a97cff22,transparent 46%),linear-gradient(145deg,#111b29,#091019);border:1px solid var(--line);border-radius:var(--radius)}
.research-hero h2{font-size:24px;letter-spacing:-.04em}.research-hero p{margin-top:8px;color:var(--muted);font-size:10px;line-height:1.55}.research-pill{display:inline-flex;margin-top:12px;padding:6px 9px;border:1px solid #a97cff44;background:#a97cff12;color:#c9afff;border-radius:999px;font-size:8px;font-weight:900;letter-spacing:.06em}
.research-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}.research-card{padding:14px;background:linear-gradient(145deg,#0d1721,#091018);border:1px solid var(--line);border-radius:18px}.research-card h3{font-size:13px}.research-card p{color:var(--muted);font-size:9px;line-height:1.45;margin-top:5px}.research-big{font-size:24px;font-weight:900;letter-spacing:-.04em;margin-top:9px}.research-table{display:grid;gap:7px}.research-row{display:grid;grid-template-columns:minmax(110px,1.35fr) repeat(3,minmax(62px,.65fr));align-items:center;gap:7px;padding:10px 11px;border-radius:13px;background:#ffffff05;border:1px solid var(--line);font-size:9px}.research-row.header{background:transparent;border:0;color:var(--muted);padding:2px 11px;font-size:8px;font-weight:850}.research-row strong{font-size:10px}.research-status{display:inline-flex;padding:4px 7px;border-radius:999px;font-size:7px;font-weight:900;border:1px solid var(--line);background:#ffffff08}.research-status.good{color:var(--green);border-color:#54e89c36;background:#54e89c10}.research-status.warn{color:var(--amber);border-color:#f7bd5540;background:#f7bd5510}.research-status.lab{color:#c9afff;border-color:#a97cff44;background:#a97cff12}.research-note{padding:13px 14px;border-radius:15px;background:#65a9ff0b;border:1px solid #65a9ff22;color:#b9cadc;font-size:9px;line-height:1.55}.weight-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin-top:10px}.weight-grid div{padding:8px 4px;border-radius:10px;text-align:center;background:var(--surface2);border:1px solid var(--line)}.weight-grid span{display:block;color:var(--muted);font-size:7px}.weight-grid strong{display:block;margin-top:2px;font-size:10px}.research-live{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.research-live .metric{min-width:0}.research-live .metric strong{font-size:15px}@media(max-width:620px){.research-grid{grid-template-columns:1fr}.research-row{grid-template-columns:1.2fr repeat(3,.6fr);font-size:8px}.research-live{grid-template-columns:1fr 1fr}.weight-grid{grid-template-columns:repeat(3,1fr)}}
'''
    text = replace_once(text, "</style>", css + "\n</style>", "research CSS")
    text = text.replace("grid-template-columns:repeat(6,1fr)", "grid-template-columns:repeat(7,1fr)", 1)

    section = r'''
<section id="research" class="view">
  <div class="intro"><p>Walk-forward model laboratory</p><h1>Research engine</h1></div>
  <article class="research-hero"><p class="ey">DRAWS FIRST, CLAIMS SECOND</p><h2>Champion vs challenger research</h2><p>DrawLab treats random, independent draws as the null hypothesis. Live v1.0 strategies stay frozen while challengers are tested strictly out-of-sample. Played-ticket outcomes evaluate a model; they do not directly boost or punish individual numbers.</p><span class="research-pill">RESEARCH ENGINE v2.0</span></article>
  <div class="section"><div><p class="ey">DATA FOUNDATION</p><h2>Historical coverage</h2><p>Only validated draws are admitted to model research</p></div></div><div id="researchCoverage" class="research-grid"></div>
  <div class="section"><div><p class="ey">CONTROL GROUP</p><h2>Theoretical chance baseline</h2><p>No random tickets are played; chance is used only as the statistical control</p></div></div><div id="researchBaseline" class="research-grid"></div>
  <div class="section"><div><p class="ey">PERSISTENCE</p><h2>Hold-period experiment</h2><p>Which strategies benefit from refreshing every draw versus holding the same line?</p></div></div><div id="researchHold" class="stack"></div>
  <div class="section"><div><p class="ey">CHALLENGER LAB</p><h2>Weighted Historical v2</h2><p>Centre-of-range bias removed; candidate weights are selected on validation data and judged on a later held-out period</p></div></div><div id="researchChallenger" class="stack"></div>
  <div class="section"><div><p class="ey">LIVE EXPERIMENT</p><h2>v1.0 evidence so far</h2><p>Real virtual tickets are evaluation data only</p></div></div><div id="researchLive" class="stack"></div>
  <div class="section"><div><p class="ey">METHOD</p><h2>Research rules</h2></div></div><div id="researchNotes" class="stack"></div>
</section>
'''
    text = replace_once(text, "</main>", section + "\n</main>", "research section")

    nav = r'''<button class="nav" data-view="research" aria-label="Research"><svg viewBox="0 0 24 24"><path d="M9 3h6M10 3v5l-5 9a2 2 0 0 0 1.7 3h10.6A2 2 0 0 0 19 17l-5-9V3M8 14h8"/></svg><small>Research</small></button>'''
    text = replace_once(text, "</nav>", nav + "</nav>", "research navigation")

    script = r'''
<script id="researchV2Script">
(()=>{
const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct=v=>Number.isFinite(+v)?`${(+v).toFixed(2)}%`:'—';
const num=(v,d=3)=>Number.isFinite(+v)?(+v).toFixed(d):'—';
const games=['Daily Lotto','Lotto','PowerBall'];
async function fetchJSON(path){const r=await fetch(`${path}?v=${Date.now()}`,{cache:'no-store'});if(!r.ok)throw new Error(`${path}: ${r.status}`);return r.json()}
function liveStats(cloud){const rows=(cloud?.virtual?.tickets||[]).filter(t=>t.status==='Settled'&&t.strategy_version==='1.0');return ['Hot 6M','Weighted Historical','Cold 6M','Diversified Coverage'].map(strategy=>{const a=rows.filter(t=>t.strategy===strategy),spent=a.reduce((s,t)=>s+(+t.cost||0),0),won=a.reduce((s,t)=>s+(+t.won||0),0),avg=a.length?a.reduce((s,t)=>s+(+t.matches||0),0)/a.length:0;return{strategy,samples:a.length,avg,ge2:a.length?a.filter(t=>(+t.matches||0)>=2).length/a.length*100:0,roi:spent?(won-spent)/spent*100:0}})}
function renderCoverage(r){const el=document.getElementById('researchCoverage');if(!el)return;el.innerHTML=games.map(g=>{const q=r.data_quality?.[g]||{},good=q.status==='usable';return `<div class="research-card"><div class="row"><h3>${esc(g)}</h3><span class="research-status ${good?'good':'warn'}">${good?'USABLE':'INSUFFICIENT'}</span></div><div class="research-big">${esc(q.draws||0)}</div><p>validated draws · minimum ${esc(q.minimum_training_draws||'—')}</p><p>${esc(q.first_draw||'No history')} → ${esc(q.last_draw||'—')}</p></div>`}).join('')}
function renderBaseline(r){const el=document.getElementById('researchBaseline');if(!el)return;el.innerHTML=games.map(g=>{const b=r.chance_baselines?.[g]||{};return `<div class="research-card"><h3>${esc(g)}</h3><div class="research-big">${num(b.expected_matches,3)}</div><p>expected main-number matches per legal line</p><p>≥2: <strong>${pct(b.ge2_pct)}</strong> · ≥3: <strong>${pct(b.ge3_pct)}</strong></p></div>`}).join('')}
function renderHold(r){const el=document.getElementById('researchHold');if(!el)return;el.innerHTML=games.map(g=>{const rows=(r.best_hold||[]).filter(x=>x.game===g);return `<div class="panel"><div class="row"><div><h3>${esc(g)}</h3><p class="sub">Best observed deterministic hold horizon in walk-forward testing</p></div><span class="research-status lab">RESEARCH ONLY</span></div><div class="research-table" style="margin-top:12px"><div class="research-row header"><span>STRATEGY</span><span>HOLD</span><span>AVG MATCH</span><span>≥2 RATE</span></div>${rows.length?rows.map(x=>`<div class="research-row"><strong>${esc(x.strategy)}</strong><span>${esc(x.best_horizon)} draw${x.best_horizon===1?'':'s'}</span><span>${num(x.avg_matches,3)}</span><span>${pct(x.ge2_rate)}</span></div>`).join(''):`<div class="notice">Not enough validated history yet.</div>`}</div></div>`}).join('')}
function renderChallenger(r){const el=document.getElementById('researchChallenger');if(!el)return;el.innerHTML=games.map(g=>{const c=r.challengers?.[g]||{};if(c.status!=='candidate')return `<div class="panel"><div class="row"><h3>${esc(g)}</h3><span class="research-status warn">WAITING FOR DATA</span></div><p class="sub">${esc(c.draws||0)} draws available; ${esc(c.minimum_needed||'more')} required for a separated validation/test experiment.</p></div>`;const t=c.held_out_test||{},ch=t.challenger||{},v1=t.champion_v1||{},w=c.weights||{};return `<div class="panel"><div class="row"><div><h3>${esc(g)} · Weighted Historical v2.0</h3><p class="sub">Held-out test ${esc(t.from)} → ${esc(t.to)}</p></div><span class="research-status lab">CHALLENGER</span></div><div class="weight-grid">${['long','six','recent','gap','pair'].map(k=>`<div><span>${k.toUpperCase()}</span><strong>${pct((w[k]||0)*100)}</strong></div>`).join('')}</div><div class="research-table" style="margin-top:12px"><div class="research-row header"><span>MODEL</span><span>SAMPLES</span><span>AVG MATCH</span><span>LIFT</span></div><div class="research-row"><strong>Champion v1</strong><span>${esc(v1.samples||0)}</span><span>${num(v1.avg_matches,3)}</span><span>${pct(v1.lift_vs_expected_pct)}</span></div><div class="research-row"><strong>Challenger v2</strong><span>${esc(ch.samples||0)}</span><span>${num(ch.avg_matches,3)}</span><span>${pct(ch.lift_vs_expected_pct)}</span></div></div><div class="research-note" style="margin-top:11px">Not auto-promoted. A challenger must earn promotion under a pre-defined out-of-sample evidence threshold rather than a lucky short run.</div></div>`}).join('')}
function renderLive(cloud){const el=document.getElementById('researchLive');if(!el)return;const rows=liveStats(cloud);el.innerHTML=`<div class="panel"><div class="research-live">${rows.map(x=>`<div class="metric"><span>${esc(x.strategy)}</span><strong>${x.samples?num(x.avg,2):'—'} avg</strong><small>${x.samples} settled · ≥2 ${pct(x.ge2)} · ROI ${pct(x.roi)}</small></div>`).join('')}</div><div class="research-note" style="margin-top:12px">These outcomes evaluate the strategies. A number is not rewarded because one of our tickets won, or punished because one lost; the official draw itself is already the new historical evidence.</div></div>`}
function renderNotes(r){const el=document.getElementById('researchNotes');if(!el)return;el.innerHTML=[r.null_hypothesis,r.live_policy,r.feedback_policy,...(r.notes||[])].filter(Boolean).map(x=>`<div class="research-note">${esc(x)}</div>`).join('')}
async function load(){try{const [r,c]=await Promise.all([fetchJSON('data/research-state.json'),fetchJSON('data/cloud-state.json')]);renderCoverage(r);renderBaseline(r);renderHold(r);renderChallenger(r);renderLive(c);renderNotes(r)}catch(e){['researchCoverage','researchBaseline','researchHold','researchChallenger','researchLive','researchNotes'].forEach(id=>{const el=document.getElementById(id);if(el&&!el.innerHTML)el.innerHTML=`<div class="notice">Research data is being generated. ${esc(e.message)}</div>`})}}
document.querySelectorAll('.nav[data-view="research"]').forEach(b=>b.addEventListener('click',()=>{const t=document.getElementById('pageTitle');if(t)t.textContent='DrawLab Research'}));
load();setInterval(load,10*60*1000);
})();
</script>
'''
    text = replace_once(text, "</body>", script + "\n</body>", "research script")
    path.write_text(text)


def main() -> None:
    patch_python()
    patch_index()
    print("Applied DrawLab Research Engine v2 integration")


if __name__ == "__main__":
    main()
