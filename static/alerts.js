(()=>{
 const meta=document.getElementById('faMeta'); const KEY='fa-sound';
 let ac=null,pending=null,hintEl=null;
 const on=()=>localStorage.getItem(KEY)!=='off';
 const getAC=()=>{try{ac=ac||new (window.AudioContext||window.webkitAudioContext)()}catch(e){}return ac};
 const SEQ={alert:[[880,0],[1175,.18],[880,.36],[1175,.54]],ding:[[740,0],[988,.14]],chat:[[1047,0],[1319,.1],[1568,.2],[2093,.32]],ok:[[660,0],[880,.12],[1320,.24]]};
 function tones(a,kind){const t=a.currentTime;(SEQ[kind]||SEQ.alert).forEach(([f,d])=>{const o=a.createOscillator(),g=a.createGain();o.type='sine';o.frequency.value=f;g.gain.setValueAtTime(0,t+d);g.gain.linearRampToValueAtTime(.35,t+d+.02);g.gain.exponentialRampToValueAtTime(.001,t+d+.16);o.connect(g);g.connect(a.destination);o.start(t+d);o.stop(t+d+.18)})}
 function hint(kind){pending=kind;const box=document.getElementById('faToasts');if(!box||hintEl)return;hintEl=document.createElement('a');hintEl.className='fa-toast';hintEl.href='#';hintEl.innerHTML='<b>🔔 Kliko për të aktivizuar zërin</b><span>Shfletuesi e bllokon zërin derisa të klikoni një herë në faqe.</span>';hintEl.onclick=e=>{e.preventDefault();unlock()};box.appendChild(hintEl)}
 function unlock(){if(hintEl){hintEl.remove();hintEl=null}const k=pending;pending=null;if(k)play(k,true);else play('ok',true)}
 function play(kind='alert',force){if(!force&&!on())return;const a=getAC();if(!a)return;if(a.state==='running'){tones(a,kind);return}a.resume().then(()=>{if(a.state==='running')tones(a,kind);else hint(kind)}).catch(()=>hint(kind))}
 ['click','keydown','touchstart'].forEach(e=>addEventListener(e,()=>{if(pending)unlock()},{passive:true,capture:true}));
 window.faSound={play,isOn:on};
 const btn=document.getElementById('soundBtn'),paint=()=>{if(btn){btn.textContent=on()?'🔊':'🔇';btn.style.opacity=on()?1:.55}};
 if(btn){paint();btn.addEventListener('click',()=>{localStorage.setItem(KEY,on()?'off':'on');paint();if(on())play('ok',true)})}
 if(!meta) return;
 // Popup në hyrje
 const modal=document.getElementById('faModal');
 if(modal){const close=()=>modal.remove();document.getElementById('faModalClose').onclick=close;modal.addEventListener('click',e=>{if(e.target===modal)close()});addEventListener('keydown',e=>{if(e.key==='Escape')close()});play('alert')}
 else{const f=document.querySelector('.flash.success'),d=document.querySelector('.flash.danger');if(d)play('ding');else if(f)play('ok')}
 // Notifications të reja në kohë reale (çdo 10 s): toast + zë
 let last=parseInt(meta.dataset.last||'0',10);const box=document.getElementById('faToasts'),badge=document.getElementById('navBadge');
 function toast(n){const a=document.createElement('a');a.className='fa-toast';a.href=n.link||meta.dataset.notif;const b=document.createElement('b');b.textContent=n.title;const p=document.createElement('span');p.textContent=(n.message||'').slice(0,140);a.append(b,p);box.appendChild(a);setTimeout(()=>a.remove(),15000)}
 async function poll(){try{const r=await fetch(meta.dataset.poll+'?since='+last,{credentials:'same-origin',headers:{'Accept':'application/json'}});if(!r.ok)return;const d=await r.json();if(badge)badge.textContent=d.unread;if(d.items&&d.items.length){d.items.forEach(toast);last=d.last;play('alert')}}catch(e){}}
 setInterval(()=>{if(!document.hidden)poll()},10000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll()});
})();
