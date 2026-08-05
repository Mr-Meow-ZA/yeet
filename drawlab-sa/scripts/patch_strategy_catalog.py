#!/usr/bin/env python3
from pathlib import Path

path = Path('drawlab-sa/index.html')
html = path.read_text(encoding='utf-8')
marker = 'STRATEGY_CATALOG_V1'
if marker in html:
    print('Strategy catalog already installed')
    raise SystemExit(0)

patch = r'''
<style>
/* STRATEGY_CATALOG_V1 */
.strategy-catalog-note{margin:0 0 12px;padding:13px 14px;border-radius:16px;border:1px solid #65a9ff2c;background:#65a9ff0b;color:#aebfd2;font-size:10px;line-height:1.55}.strategy-catalog-note strong{color:var(--text)}
.catalog-status{padding:5px 8px;border-radius:999px;border:1px solid #f7bd5538;background:#f7bd5510;color:#f8ce82;font-size:8px;font-weight:850;white-space:nowrap}
.catalog-version{color:var(--muted);font-size:8px;margin-top:3px}.catalog-hypothesis{margin-top:11px;padding:11px 12px;border-radius:13px;background:var(--surface2);border:1px solid var(--line);color:#aebfd2;font-size:9px;line-height:1.45}
</style>
<script>
(function(){
  const CATALOG=[
    {name:'Hot 6M',version:'1.0',hypothesis:'Tests whether recent high-frequency numbers continue appearing.'},
    {name:'Weighted Historical',version:'1.0',hypothesis:'Uses a fixed blend of long-term frequency, six-month frequency, momentum, recency gaps and pair signals.'},
    {name:'Cold 6M',version:'1.0',hypothesis:'Tests whether recently underrepresented numbers revert toward expected frequency.'},
    {name:'Diversified Coverage',version:'1.0',hypothesis:'Uses structured range coverage and low overlap to diversify the virtual portfolio.'}
  ];

  function existingNames(root){
    return [...root.querySelectorAll('.card h3,.strategy h3')].map(el=>el.textContent.trim().replace(/\s+v\d+(?:\.\d+)?$/i,''));
  }

  function addNote(root){
    if(root.previousElementSibling && root.previousElementSibling.classList.contains('strategy-catalog-note')) return;
    const note=document.createElement('div');
    note.className='strategy-catalog-note';
    note.innerHTML='<strong>Locked deterministic league:</strong> Hot 6M, Weighted Historical, Cold 6M and Diversified Coverage. New models begin only on an eligible draw before results are known.';
    root.parentNode.insertBefore(note,root);
  }

  function placeholderCard(item,rank){
    const card=document.createElement('article');
    card.className='card strategy-catalog-placeholder';
    card.dataset.catalogStrategy=item.name;
    card.innerHTML=`<div class="card-head"><div class="strategy"><span class="rank">${rank}</span><div><h3>${item.name}</h3><div class="catalog-version">DETERMINISTIC MODEL · v${item.version}</div></div></div><span class="catalog-status">AWAITING FIRST DRAW</span></div><div class="catalog-hypothesis">${item.hypothesis}</div><div class="meta"><span>No valid v${item.version} tickets settled yet</span><span>ROI —</span></div>`;
    return card;
  }

  function ensureCatalog(){
    const root=document.getElementById('strategyList');
    if(!root) return;
    addNote(root);
    const names=existingNames(root);
    CATALOG.forEach((item,index)=>{
      if(!names.includes(item.name) && !root.querySelector(`[data-catalog-strategy="${item.name}"]`)){
        root.appendChild(placeholderCard(item,index+1));
      }
    });
    [...root.querySelectorAll('.card')].forEach(card=>{
      const h=card.querySelector('h3'); if(!h) return;
      const item=CATALOG.find(x=>x.name===h.textContent.trim().replace(/\s+v\d+(?:\.\d+)?$/i,''));
      if(!item) return;
      if(!card.querySelector('.catalog-version')){
        const v=document.createElement('div'); v.className='catalog-version'; v.textContent=`DETERMINISTIC MODEL · v${item.version}`; h.insertAdjacentElement('afterend',v);
      }
    });
  }

  const observer=new MutationObserver(()=>ensureCatalog());
  window.addEventListener('DOMContentLoaded',()=>{
    const root=document.getElementById('strategyList');
    if(root) observer.observe(root,{childList:true,subtree:true});
    ensureCatalog();
    setTimeout(ensureCatalog,500);
    setTimeout(ensureCatalog,1800);
  });
})();
</script>
'''

html = html.replace('</body>', patch + '\n</body>')
path.write_text(html, encoding='utf-8')
print('Installed strategy catalog UI')
