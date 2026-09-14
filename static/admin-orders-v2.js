/* 本福丸後台訂單 v2：日期/時段分組、搜尋、作廢、恢復、永久刪除 */
(function(){
  'use strict';
  if(window.__benfuwanOrdersV2Installed)return;
  window.__benfuwanOrdersV2Installed=true;

  let rows=[];
  let loading=false;
  let dateMode='today';
  let exactDate='';
  let query='';

  const e=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmtParts=(ts)=>{
    const d=new Date((Number(ts)||0)*1000);
    const parts=new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23',weekday:'short'}).formatToParts(d);
    const get=t=>parts.find(p=>p.type===t)?.value||'';
    const y=get('year'),m=get('month'),day=get('day'),hour=Number(get('hour')||0),minute=get('minute');
    return {key:`${y}-${m}-${day}`,label:`${y}/${m}/${day} ${get('weekday')}`,time:`${String(hour).padStart(2,'0')}:${minute}`,hour};
  };
  const todayKey=(offset=0)=>{
    const now=new Date(Date.now()+offset*86400000);
    const p=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(now);
    const get=t=>p.find(x=>x.type===t)?.value||'';
    return `${get('year')}-${get('month')}-${get('day')}`;
  };
  const period=h=>h<12?'上午':(h<18?'下午':'晚上');

  function installCss(){
    if(document.getElementById('bf-orders-v2-css'))return;
    const s=document.createElement('style');s.id='bf-orders-v2-css';s.textContent=`
      #bf-order-manager{display:flex;flex-direction:column;gap:12px}
      .bf-order-tools{display:flex;gap:8px;flex-wrap:wrap;align-items:center;background:#fff;border:1px solid var(--line);border-radius:16px;padding:10px;position:sticky;top:0;z-index:5}
      .bf-order-tools input[type=search]{flex:1;min-width:180px;border:1px solid #eadce1;border-radius:999px;padding:9px 13px}.bf-order-tools input[type=date]{border:1px solid #eadce1;border-radius:12px;padding:8px 10px}
      .bf-order-chip{border:1px solid #efd5de;background:#fff;color:#74676d;border-radius:999px;padding:7px 11px;font-size:12px;font-weight:850;cursor:pointer}.bf-order-chip.active{background:var(--pink);color:#fff;border-color:var(--pink)}
      .bf-order-summary{display:flex;gap:8px;flex-wrap:wrap;font-size:12px;color:#786c71}.bf-order-summary span{background:#fff;border:1px solid var(--line);border-radius:999px;padding:6px 10px}
      .bf-order-day{background:#fff;border:1px solid var(--line);border-radius:18px;overflow:hidden;box-shadow:var(--shadow)}.bf-order-day-head{padding:12px 14px;background:#fff2f6;color:#d95580;font-weight:950;display:flex;justify-content:space-between;align-items:center}.bf-order-period{padding:10px 12px 4px;font-size:12px;font-weight:900;color:#8e7d84}
      .bf-order-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px;padding:8px 12px 14px}.bf-order-card{border:1px solid #f0e3e7;border-radius:16px;padding:11px;background:#fffafb;display:grid;grid-template-columns:88px minmax(0,1fr);gap:10px}.bf-order-card.void{opacity:.62;background:#f6f3f4}.bf-order-thumb{width:88px;height:112px;object-fit:contain;border:1px solid #efe1e6;border-radius:12px;background:#f8f6f7}.bf-order-id{font-size:11px;font-weight:900;word-break:break-all}.bf-order-meta{font-size:12px;line-height:1.55;color:#51484c}.bf-order-time{font-size:11px;color:#9a8e93}.bf-order-actions{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}.bf-order-actions a,.bf-order-actions button{border:1px solid #edc4d0;background:#fff;color:#d95580;border-radius:999px;padding:6px 9px;font-size:11px;font-weight:850;text-decoration:none;cursor:pointer}.bf-order-actions .danger{color:#d94d61;border-color:#efc0c9}.bf-order-actions .voidbtn{color:#8a6c35;border-color:#ead8b7}.bf-order-status{display:inline-flex;border-radius:999px;padding:3px 7px;background:#fff0f4;color:#d95580;font-weight:900;font-size:10px;margin-left:4px}.bf-order-empty{padding:50px 20px;text-align:center;color:#aaa;background:#fff;border:1px solid var(--line);border-radius:18px}
      @media(max-width:700px){.bf-order-tools{position:static}.bf-order-grid{grid-template-columns:1fr}.bf-order-card{grid-template-columns:78px minmax(0,1fr)}.bf-order-thumb{width:78px;height:102px}}
    `;document.head.appendChild(s);
  }

  function ensureUi(){
    installCss();
    const view=document.getElementById('view-orders');if(!view)return null;
    const panel=view.querySelector('.panel');if(!panel)return null;
    if(document.getElementById('bf-order-manager'))return document.getElementById('bf-order-manager');
    panel.innerHTML=`<div id="bf-order-manager">
      <div class="bf-order-tools">
        <input id="bf-order-search" type="search" placeholder="搜尋訂單編號、客人、型號、殼款…">
        <button class="bf-order-chip active" data-range="today">今天</button><button class="bf-order-chip" data-range="yesterday">昨天</button><button class="bf-order-chip" data-range="7d">近 7 天</button><button class="bf-order-chip" data-range="all">全部</button>
        <input id="bf-order-date" type="date" title="指定日期">
        <button class="btn alt mini" id="bf-order-reload"><i class="fa-solid fa-rotate"></i> 重新整理</button>
      </div>
      <div class="bf-order-summary" id="bf-order-summary"></div>
      <div id="bf-order-list"><div class="bf-order-empty">讀取訂單中…</div></div>
    </div>`;
    document.getElementById('bf-order-search').addEventListener('input',ev=>{query=ev.target.value.trim().toLowerCase();render()});
    document.querySelectorAll('[data-range]').forEach(b=>b.onclick=()=>{dateMode=b.dataset.range;exactDate='';document.getElementById('bf-order-date').value='';document.querySelectorAll('[data-range]').forEach(x=>x.classList.toggle('active',x===b));render()});
    document.getElementById('bf-order-date').onchange=ev=>{exactDate=ev.target.value||'';if(exactDate){dateMode='exact';document.querySelectorAll('[data-range]').forEach(x=>x.classList.remove('active'));}render()};
    document.getElementById('bf-order-reload').onclick=()=>refreshOrders(true);
    return document.getElementById('bf-order-manager');
  }

  function passesDate(row){
    const key=fmtParts(row.time).key;
    if(dateMode==='all')return true;
    if(dateMode==='today')return key===todayKey(0);
    if(dateMode==='yesterday')return key===todayKey(-1);
    if(dateMode==='exact')return !exactDate||key===exactDate;
    if(dateMode==='7d'){
      const cutoff=new Date(todayKey(-6)+'T00:00:00+08:00').getTime()/1000;
      return Number(row.time||0)>=cutoff;
    }
    return true;
  }
  function filtered(){
    return rows.filter(r=>{
      if(!passesDate(r))return false;
      if(!query)return true;
      const hay=[r.order_id,r.customer_name,r.model,r.style,r.payment_method,r.status].join(' ').toLowerCase();
      return hay.includes(query);
    });
  }

  function render(){
    ensureUi();const list=document.getElementById('bf-order-list'),sum=document.getElementById('bf-order-summary');if(!list||!sum)return;
    const data=filtered();const voidCount=data.filter(x=>x.status==='作廢').length;const active=data.length-voidCount;
    sum.innerHTML=`<span>顯示 <b>${data.length}</b> 筆</span><span>有效 <b>${active}</b></span><span>作廢 <b>${voidCount}</b></span><span>資料已依「日期 → 上午/下午/晚上」整理</span>`;
    if(!data.length){list.innerHTML='<div class="bf-order-empty">這個條件目前沒有訂單</div>';return}
    const days=new Map();data.forEach(r=>{const f=fmtParts(r.time);if(!days.has(f.key))days.set(f.key,{label:f.label,rows:[]});days.get(f.key).rows.push({...r,_fmt:f})});
    list.innerHTML=[...days.entries()].sort((a,b)=>b[0].localeCompare(a[0])).map(([key,g])=>{
      const groups={上午:[],下午:[],晚上:[]};g.rows.sort((a,b)=>Number(b.time||0)-Number(a.time||0)).forEach(r=>groups[period(r._fmt.hour)].push(r));
      const sections=Object.entries(groups).filter(([,arr])=>arr.length).map(([p,arr])=>`<div class="bf-order-period">${p}・${arr.length} 筆</div><div class="bf-order-grid">${arr.map(cardHtml).join('')}</div>`).join('');
      return `<section class="bf-order-day"><div class="bf-order-day-head"><span>${e(g.label)}</span><small>${g.rows.length} 筆</small></div>${sections}</section>`;
    }).join('');
  }

  function cardHtml(o){
    const total=Number(o.total||((o.price||0)*(o.quantity||1)))||0,isVoid=o.status==='作廢';
    return `<article class="bf-order-card${isVoid?' void':''}">
      <div>${o.mockup_url?`<a href="${e(o.mockup_url)}" target="_blank" rel="noopener"><img class="bf-order-thumb" loading="lazy" decoding="async" src="${e(o.mockup_url)}" onerror="this.style.opacity=.15"></a>`:'<div class="bf-order-thumb" style="display:grid;place-items:center;color:#bbb;font-size:11px">無預覽</div>'}</div>
      <div><div class="bf-order-id">${e(o.order_id)} <span class="bf-order-status">${e(o.status||'待處理')}</span></div><div class="bf-order-time">${e(o._fmt?.time||fmtParts(o.time).time)}</div>
      <div class="bf-order-meta"><b>${e(o.model||'')}</b>・${e(o.style||'')}<br>${e(o.customer_name||'')}｜${e(o.payment_method||'')}｜${Number(o.quantity||1)} 件<br><b>NT$ ${total.toLocaleString()}</b></div>
      <div class="bf-order-actions">${o.print_url?`<a href="${e(o.print_url)}">下載生產圖</a>`:''}${isVoid?`<button onclick="bfOrderAction('${e(o.order_id)}','restore')">恢復</button>`:`<button class="voidbtn" onclick="bfOrderAction('${e(o.order_id)}','void')">作廢</button>`}<button class="danger" onclick="bfOrderAction('${e(o.order_id)}','delete')">刪除</button></div></div>
    </article>`;
  }

  window.bfOrderAction=async function(orderId,action){
    if(action==='void'&&!confirm('確定將這筆訂單標記為「作廢」？資料與生產圖會保留。'))return;
    if(action==='restore'&&!confirm('確定恢復這筆訂單為「待處理」？'))return;
    if(action==='delete'){
      if(!confirm('這會永久刪除訂單資料與生產/預覽圖片，確定刪除？'))return;
      if(!confirm('最後確認：永久刪除後無法復原。'))return;
    }
    try{
      const r=await fetch('/api/admin/order_action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({order_id:orderId,action})});let j={};try{j=await r.json()}catch(e){}
      if(!r.ok||j.status!=='success')throw new Error(j.msg||('HTTP '+r.status));
      await refreshOrders(true);
    }catch(err){alert(err.message||'訂單操作失敗')}
  };

  window.refreshOrders=async function(force=false){
    if(loading&&!force)return;loading=true;ensureUi();const list=document.getElementById('bf-order-list');if(force&&list)list.innerHTML='<div class="bf-order-empty">重新整理中…</div>';
    try{
      const r=await fetch('/api/admin/get_orders?limit=200&ts='+Date.now(),{cache:'no-store'});let j={};try{j=await r.json()}catch(e){}
      if(!r.ok||j.status!=='success')throw new Error(j.msg||('HTTP '+r.status));rows=Array.isArray(j.data)?j.data:[];render();
    }catch(err){if(list)list.innerHTML=`<div class="bf-order-empty" style="color:#d94d61">${e(err.message||'讀取失敗')}</div>`}
    finally{loading=false}
  };

  function boot(){ensureUi();refreshOrders(true);console.info('[ADMIN] orders v2 enabled: date/time groups + void/delete')}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
