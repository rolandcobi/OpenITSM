/* Searchable user picker: enhance select.userpick with search across user details */
(()=>{
 const API='/api/users/search';
 const lab=u=>u.full_name+(u.duty?' — '+u.duty:(u.sector?' — '+u.sector:''));
 function enhance(sel){
  if(sel.dataset.up) return; sel.dataset.up='1';
  const empty=[...sel.options].find(o=>!o.value), quick=[...sel.options].filter(o=>o.value).map(o=>({id:o.value,full_name:o.textContent,quick:1}));
  const wrap=document.createElement('div'); wrap.className='up';
  const inp=document.createElement('input'); inp.type='text'; inp.className='up-input'; inp.autocomplete='off'; inp.placeholder=sel.dataset.placeholder||(empty?empty.textContent:'')||'Search users: name, department, email, position…'; inp.setAttribute('aria-label','Search users');
  const clr=document.createElement('button'); clr.type='button'; clr.className='up-clear'; clr.textContent='✕'; clr.title='Clear selection';
  const list=document.createElement('div'); list.className='up-list'; list.hidden=true;
  const hint=document.createElement('small'); hint.className='up-hint'; hint.textContent='Type part of a name, department, email, position or institution';
  sel.after(wrap); wrap.append(inp,clr,list,hint); sel.style.display='none';
  const req=sel.required; sel.required=false; let items=[],hi=-1,timer=null,seq=0;
  const sync=()=>{const o=sel.options[sel.selectedIndex]; inp.value=(sel.value&&o)?o.textContent:''; wrap.classList.toggle('has',!!sel.value)};
  const close=()=>{list.hidden=true; hi=-1};
  function render(){
   list.textContent=''; if(!items.length){const d=document.createElement('div'); d.className='up-none'; d.textContent='No users found'; list.appendChild(d); list.hidden=false; return}
   items.forEach((u,i)=>{const d=document.createElement('div'); d.className='up-item'+(i===hi?' on':''); d.dataset.i=i;
    const b=document.createElement('b'); b.textContent=u.quick?u.full_name:u.full_name; d.appendChild(b);
    if(!u.quick){const s1=document.createElement('small'); s1.textContent=[u.role,u.sector,u.structure,u.duty].filter(Boolean).join(' · '); const s2=document.createElement('small'); s2.textContent=[u.institution,u.email,u.phone].filter(Boolean).join(' · '); d.append(s1,s2)}
    d.addEventListener('mousedown',e=>{e.preventDefault(); pick(u)}); list.appendChild(d)}); list.hidden=false}
  function pick(u){let o=[...sel.options].find(x=>x.value==u.id); if(!o){o=new Option(u.quick?u.full_name:lab(u),u.id); sel.add(o)} sel.value=String(u.id); sync(); close(); inp.setCustomValidity(''); sel.dispatchEvent(new Event('change',{bubbles:true}))}
  async function search(q){const my=++seq; try{const r=await fetch(API+'?limit=12&q='+encodeURIComponent(q),{credentials:'same-origin'}); const j=await r.json(); if(my!==seq) return; items=(q.trim()?[]:quick).concat(j); render()}catch(e){}}
  inp.addEventListener('focus',()=>{document.querySelectorAll('.up-list').forEach(l=>{if(l!==list) l.hidden=true}); inp.select(); search(sel.value?'':inp.value)});
  inp.addEventListener('input',()=>{inp.setCustomValidity(''); clearTimeout(timer); timer=setTimeout(()=>search(inp.value),180)});
  inp.addEventListener('keydown',e=>{
   if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault(); if(list.hidden) search(inp.value); else {hi=Math.max(0,Math.min(items.length-1,hi+(e.key==='ArrowDown'?1:-1))); render()}}
   else if(e.key==='Enter'){if(!list.hidden&&items.length){e.preventDefault(); pick(items[hi>=0?hi:0])}}
   else if(e.key==='Escape'){close(); sync()}});
  inp.addEventListener('blur',()=>setTimeout(()=>{close(); sync()},120));
  clr.addEventListener('click',()=>{sel.value=''; sync(); sel.dispatchEvent(new Event('change',{bubbles:true})); inp.focus()});
  const f=sel.closest('form'); if(f&&req) f.addEventListener('submit',e=>{if(!sel.value){e.preventDefault(); inp.setCustomValidity('Select a user from the list'); inp.reportValidity(); inp.focus()}});
  sync();
 }
 const scan=r=>(r.querySelectorAll?r.querySelectorAll('select.userpick'):[]).forEach(enhance);
 scan(document); new MutationObserver(ms=>ms.forEach(m=>m.addedNodes.forEach(n=>{if(n.nodeType===1){if(n.matches&&n.matches('select.userpick')) enhance(n); scan(n)}}))).observe(document.body,{childList:true,subtree:true});
})();
