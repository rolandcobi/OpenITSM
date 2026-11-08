(()=>{
 // Filtrim sipas kolonës (Direktoria)
 document.querySelectorAll('table[data-colfilter]').forEach(t=>{
  const inputs=[...t.querySelectorAll('input[data-col]')],rows=[...t.tBodies[0].rows],cnt=document.getElementById('dirCount');
  const run=()=>{const f=inputs.map(i=>[+i.dataset.col,i.value.trim().toLowerCase()]).filter(x=>x[1]);let n=0;rows.forEach(r=>{const ok=f.every(([c,v])=>(r.cells[c].textContent||'').toLowerCase().includes(v));r.hidden=!ok;if(ok)n++});if(cnt)cnt.textContent=n+' përdorues'};
  inputs.forEach(i=>i.addEventListener('input',run));
 });
 // Rreshta për hapat e rrjedhës (Create Ticket)
 const add=document.getElementById('addStep'),tpl=document.getElementById('stepTpl'),rows=document.getElementById('chainRows');
 if(add&&tpl&&rows){add.addEventListener('click',()=>rows.appendChild(tpl.content.cloneNode(true)));rows.addEventListener('click',e=>{const b=e.target.closest('.rmstep');if(b)b.closest('.chain-row').remove()})}
 document.querySelectorAll('select[data-autosubmit]').forEach(s=>s.addEventListener('change',()=>s.form.submit()));
})();

(()=>{ // dialogë (Edit / Add)
 document.addEventListener('click',e=>{
  const o=e.target.closest('[data-open]'); if(o){const d=document.getElementById(o.dataset.open); if(d&&d.showModal){d.showModal();window.faSound&&faSound.play('ding'); const f=d.querySelector('input:not([type=hidden]),select'); if(f&&!f.disabled)f.focus()} return}
  if(e.target.closest('[data-close]')){const d=e.target.closest('dialog'); if(d)d.close(); return}
  if(e.target.tagName==='DIALOG'){e.target.close()}
 });
 document.querySelectorAll('input[data-autosubmit]').forEach(i=>i.addEventListener('change',()=>i.form.submit()));
})();

(()=>{ // zgjedhës përdoruesish me kërkim
 document.querySelectorAll('[data-picker]').forEach(p=>{
  const s=p.querySelector('.up-search'),items=[...p.querySelectorAll('.up-item')],n=p.querySelector('.up-n'),none=p.querySelector('.up-none');
  const cnt=()=>{n.textContent=p.querySelectorAll('input:checked').length};
  s.addEventListener('input',()=>{const v=s.value.trim().toLowerCase();let shown=0;items.forEach(i=>{const ok=!v||i.dataset.text.includes(v);i.hidden=!ok;if(ok)shown++});if(none)none.hidden=shown>0});
  s.addEventListener('keydown',e=>{if(e.key==='Enter')e.preventDefault()});
  p.addEventListener('change',cnt);p.querySelector('.up-clear').addEventListener('click',()=>{p.querySelectorAll('input:checked').forEach(i=>i.checked=false);cnt()});
 });
 document.querySelectorAll('form[data-needpicker]').forEach(f=>f.addEventListener('submit',e=>{if(!f.querySelector('[data-picker] input:checked')){e.preventDefault();alert('Zgjidhni të paktën një përdorues nga lista.');f.querySelector('.up-search').focus()}}));
})();
(()=>{ // dritarja e përshkrimit të mbylljes
 const dlg=document.getElementById('faDone'); if(!dlg) return;
 const form=document.getElementById('faDoneForm'),fields=document.getElementById('faDoneFields'),txt=document.getElementById('faDoneText'),res=document.getElementById('faDoneRes'),ttl=document.getElementById('faDoneTitle');
 function open(cfg){form.action=cfg.action;fields.innerHTML='';Object.entries(cfg.fields||{}).forEach(([k,v])=>{const i=document.createElement('input');i.type='hidden';i.name=k;i.value=v;fields.appendChild(i)});ttl.textContent=cfg.title||'Complete';txt.value='';dlg.showModal();window.faSound&&faSound.play('ding');txt.focus()}
 document.addEventListener('click',e=>{const b=e.target.closest('[data-done]');if(!b)return;e.preventDefault();try{open(JSON.parse(b.dataset.done))}catch(x){}});
 form.addEventListener('submit',()=>{res.value=txt.value});
 document.querySelectorAll('form[data-statusform]').forEach(f=>f.addEventListener('submit',e=>{const sel=f.querySelector('select[name=status]');if(['Resolved','Closed'].includes(sel.value)&&sel.value!==sel.dataset.orig){e.preventDefault();open({action:f.getAttribute('action')||location.pathname,fields:{action:'status',status:sel.value},title:'Edit statusin në '+sel.value})}}));
})();
