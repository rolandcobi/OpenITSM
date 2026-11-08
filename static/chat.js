/* Chat i brendshëm: buton poshtë djathtas, kërkim përdoruesish, bisedë 1-me-1, popup dhe tingull për mesazhe të reja */
(()=>{
 const root=document.getElementById('chatRoot'); if(!root) return;
 const csrf=(document.querySelector('meta[name=csrf]')||{}).content||''; const ME=+root.dataset.me;
 const api=async(u,o={})=>{const r=await fetch(u,{method:o.m||'GET',headers:{'Content-Type':'application/json','X-CSRF':csrf},body:o.b?JSON.stringify(o.b):undefined,credentials:'same-origin'});const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.error||r.status);return j};
 const el=(t,c,x)=>{const e=document.createElement(t); if(c) e.className=c; if(x!=null) e.textContent=x; return e};
 root.innerHTML='';
 const btn=el('button','chat-btn'); btn.type='button'; btn.title='Chat i brendshëm'; btn.setAttribute('aria-label','Chat i brendshëm'); btn.append(el('span','chat-ico','💬')); const badge=el('span','chat-badge'); badge.hidden=true; btn.appendChild(badge);
 const panel=el('div','chat-panel'); panel.hidden=true; const toasts=el('div','chat-toasts');
 const head=el('div','chat-head'); const back=el('button','chat-back','←'); back.type='button'; back.hidden=true; const title=el('div','chat-title','Chat i brendshëm'); const sub=el('small','chat-sub',''); const tw=el('div','chat-tw'); tw.append(title,sub); const close=el('button','chat-x','✕'); close.type='button'; head.append(back,tw,close);
 const sbox=el('div','chat-search'); const sin=el('input'); sin.type='text'; sin.placeholder='Search person: emër, sektor, email, detyrë…'; sin.autocomplete='off'; sbox.appendChild(sin);
 const body=el('div','chat-body'); const form=el('form','chat-form'); const ta=el('textarea'); ta.rows=1; ta.placeholder='Shkruani një mesazh…'; ta.maxLength=2000; const send=el('button','chat-send','➤'); send.type='submit'; form.append(ta,send); form.hidden=true;
 panel.append(head,sbox,body,form); root.append(panel,toasts,btn);
 let cur=null,lastIn=0,unread=0,lastThread=0,convs=[],timer=null,baseTitle=document.title;
 const setBadge=n=>{unread=n; badge.hidden=!n; badge.textContent=n>99?'99+':n; btn.classList.toggle('alert',n>0); document.title=(n?'('+n+') ':'')+baseTitle.replace(/^\(\d+\)\s*/,'')};
 const bubble=m=>{const b=el('div','chat-msg '+(m.from_id===ME?'me':'them')); b.dataset.id=m.id; b.appendChild(el('div','chat-text',m.body)); b.appendChild(el('small','',m.at.slice(5).replace('-','.'))); return b};
 const scrollEnd=()=>{body.scrollTop=body.scrollHeight};
 function showList(){cur=null; back.hidden=true; form.hidden=true; title.textContent='Chat i brendshëm'; sub.textContent=''; sbox.hidden=false; renderList()}
 function renderList(){body.textContent=''; body.className='chat-body';
  if(!convs.length){body.appendChild(el('div','chat-empty','Nuk keni biseda ende. Searchni një person më sipër për të nisur një bisedë.'));return}
  body.appendChild(el('div','chat-h','Bisedat e fundit'));
  convs.forEach(c=>{const r=el('button','chat-conv'); r.type='button'; const l=el('div','chat-conv-t'); l.append(el('b','',c.name),el('small','',(c.mine?'Ju: ':'')+c.last)); r.appendChild(l); const rt=el('div','chat-conv-r'); rt.appendChild(el('small','',c.at.slice(5,16).replace('-','.'))); if(c.unread){const u=el('span','chat-n',c.unread); rt.appendChild(u)} r.appendChild(rt); r.onclick=()=>openThread(c.id); body.appendChild(r)})}
 async function refreshState(){try{const s=await api('/api/chat/state'); convs=s.convs; if(!lastIn) lastIn=s.last_in; setBadge(s.unread); if(!panel.hidden&&!cur&&!sin.value.trim()) renderList()}catch(e){}}
 async function openThread(id){try{const d=await api('/api/chat/thread?with='+id); await api('/api/chat/read',{m:'POST',b:{with:id}}); cur=d.user; back.hidden=false; form.hidden=false; sbox.hidden=true; sin.value=''; title.textContent=d.user.name; sub.textContent=d.user.sub; body.textContent=''; body.className='chat-body thread'; lastThread=0;
   if(!d.messages.length) body.appendChild(el('div','chat-empty','Shkruani mesazhin e parë.')); d.messages.forEach(m=>{body.appendChild(bubble(m)); lastThread=Math.max(lastThread,m.id)}); scrollEnd(); panel.hidden=false; ta.focus(); refreshState()}catch(e){}}
 function toast(m){const t=el('div','chat-toast'); const ic=el('div','chat-toast-ic','💬'); const tx=el('div','chat-toast-t'); tx.append(el('b','','Mesazh i ri · '+m.name),el('span','',m.body.length>90?m.body.slice(0,90)+'…':m.body)); const x=el('button','chat-toast-x','✕'); x.type='button'; t.append(ic,tx,x);
  const rm=()=>{t.classList.add('out'); setTimeout(()=>t.remove(),250)}; t.onclick=e=>{if(e.target===x){rm();return} rm(); panel.hidden=false; toasts.classList.add('beside'); openThread(m.from_id)}; toasts.appendChild(t); while(toasts.children.length>3) toasts.firstChild.remove(); setTimeout(rm,10000)}
 async function poll(){try{const p=await api('/api/chat/poll?after='+lastIn); let fresh=[];
   p.new.forEach(m=>{lastIn=Math.max(lastIn,m.id); if(!panel.hidden&&cur&&cur.id===m.from_id){body.querySelector('.chat-empty')&&body.querySelector('.chat-empty').remove(); body.appendChild(bubble(m)); lastThread=Math.max(lastThread,m.id); scrollEnd()} else fresh.push(m)});
   if(p.new.length&&!panel.hidden&&cur&&p.new.some(m=>m.from_id===cur.id)) api('/api/chat/read',{m:'POST',b:{with:cur.id}}).catch(()=>{});
   if(p.new.length&&window.faSound) faSound.play('chat');   // tingull për çdo mesazh të ri
   if(fresh.length){toast(fresh[fresh.length-1]); btn.classList.add('pulse'); setTimeout(()=>btn.classList.remove('pulse'),4000)}
   if(p.new.length) refreshState(); else setBadge(p.unread)}catch(e){}}
 const loop=()=>{clearTimeout(timer); timer=setTimeout(async()=>{await poll(); loop()},document.hidden?15000:4000)}; document.addEventListener('visibilitychange',()=>{if(!document.hidden){poll(); loop()}});
 btn.onclick=()=>{panel.hidden=!panel.hidden; toasts.classList.toggle('beside',!panel.hidden); if(!panel.hidden){toasts.textContent=''; cur?openThread(cur.id):(showList(),refreshState()); if(!cur) sin.focus()}};
 close.onclick=()=>{panel.hidden=true; toasts.classList.remove('beside')}; back.onclick=()=>{showList(); refreshState()};
 let st=null; sin.addEventListener('input',()=>{clearTimeout(st); const q=sin.value.trim(); if(!q){renderList(); return} st=setTimeout(async()=>{try{const r=await api('/api/users/search?self=0&limit=15&q='+encodeURIComponent(q)); body.textContent=''; body.className='chat-body'; body.appendChild(el('div','chat-h','Rezultatet'));
   if(!r.length) body.appendChild(el('div','chat-empty','Asnjë person nuk u gjet.')); r.forEach(u=>{const row=el('button','chat-conv'); row.type='button'; const l=el('div','chat-conv-t'); l.append(el('b','',u.full_name),el('small','',[u.role,u.sector,u.duty,u.institution].filter(Boolean).join(' · ')),el('small','',[u.email,u.phone].filter(Boolean).join(' · '))); row.appendChild(l); row.onclick=()=>openThread(u.id); body.appendChild(row)})}catch(e){}},200)});
 form.addEventListener('submit',async e=>{e.preventDefault(); const t=ta.value.trim(); if(!t||!cur) return; ta.value=''; ta.style.height=''; try{const r=await api('/api/chat/send',{m:'POST',b:{to:cur.id,body:t}}); body.querySelector('.chat-empty')&&body.querySelector('.chat-empty').remove(); body.appendChild(bubble(r.message)); lastThread=Math.max(lastThread,r.message.id); scrollEnd(); refreshState()}catch(er){ta.value=t; alert(er.message)}});
 ta.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault(); form.requestSubmit()}}); ta.addEventListener('input',()=>{ta.style.height='auto'; ta.style.height=Math.min(ta.scrollHeight,110)+'px'});
 refreshState().then(()=>{loop()});
})();
