/* 本福丸後台訂單中心 v3：生產流程、狀態篩選、列印準備檢查 */
(function(){
  'use strict';
  if(window.__benfuwanOrdersV3Installed)return;
  window.__benfuwanOrdersV3Installed=true;

  const STATUSES=['待處理','製作中','待列印','列印中','已完成','作廢'];
  const PRINT_REQUIRED=new Set(['待列印','列印中','已完成']);
  let rows=[];
  let loading=false;
  let dateMode='today';
  let exactDate='';
  let query='';
  let statusFilter='全部';

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
  const statusClass=s=>({待處理:'pending',製作中:'making',待列印:'ready',列印中:'printing',已完成:'done',作廢:'void'}[s]||'pending');

  function installCss(){
    if(document.getElementById('bf-orders-v3-css'))return;
    const s=document.createElement('style');s.id='bf-orders-v3-css';s.textContent=`
      #bf-order-manager{display:flex;flex-direction:column;gap:12px}
      .bf-order-tools{display:flex;gap:8px;flex-wrap:wrap;align-items:center;background:#fff;border:1px solid var(--line);border-radius:16px;padding:10px;position:sticky;top:0;z-index:5}
      .bf-order-tools input[type=search]{flex:1;min-width:180px;border:1px solid #eadce1;border-radius:999px;padding:9px 13px}.bf-order-tools input[type=date],.bf-order-tools select{border:1px solid #eadce1;border-radius:12px;padding:8px 10px;background:#fff;color:#5f5358}
      .bf-order-chip{border:1px solid #efd5de;background:#fff;color:#74676d;border-radius:999px;padding:7px 11px;font-size:12px;font-weight:850;cursor:pointer}.bf-order-chip.active{background:var(--pink);color:#fff;border-color:var(--pink)}
      .bf-order-summary{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px}.bf-order-kpi{background:#fff;border:1px solid var(--line);border-radius:14px;padding:9px 10px;min-width:0}.bf-order-kpi b{display:block;font-size:17px}.bf-order-kpi small{font-size:10px;color:#897b81;white-space:nowrap}
      .bf-order-day{background:#fff;border:1px solid var(--line);border-radius:18px;overflow:hidden;box-shadow:var(--shadow)}.bf-order-day-head{padding:12px 14px;background:#fff2f6;color:#d95580;font-weight:950;display:flex;justify-content:space-between;align-items:center}.bf-order-period{padding:10px 12px 4px;font-size:12px;font-weight:900;color:#8e7d84}
      .bf-order-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:10px;padding:8px 12px 14px}.bf-order-card{border:1px solid #f0e3e7;border-radius:16px;padding:11px;background:#fffafb;display:grid;grid-template-columns:94px minmax(0,1fr);gap:11px}.bf-order-card.void{opacity:.64;background:#f6f3f4}.bf-order-thumb{width:94px;height:122px;object-fit:contain;border:1px solid #efe1e6;border-radius:12px;background:#f8f6f7}.bf-order-thumb.empty{display:grid;place-items:center;color:#aaa;font-size:11px}.bf-order-id{font-size:11px;font-weight:950;word-break:break-all}.bf-order-time{font-size:11px;color:#9a8e93;margin-top:2px}.bf-order-meta{font-size:12px;line-height:1.55;color:#51484c;margin-top:5px}.bf-order-price{font-size:14px;font-weight:950;color:#332c30}.bf-order-ready{display:flex;gap:5px;flex-wrap:wrap;margin-top:7px}.bf-ready-badge{font-size:10px;font-weight:900;padding:3px 7px;border-radius:999px;border:1px solid #e8dce0;background:#fff}.bf-ready-badge.ok{color:#22845a;border-color:#bfe4d1;background:#f3fff8}.bf-ready-badge.bad{color:#c24f62;border-color:#f0c5cd;background:#fff7f8}
      .bf-order-status-row{display:flex;gap:6px;align-items:center;margin-top:7px}.bf-order-status-row select{min-width:112px;max-width:150px;border:1px solid #eadce1;border-radius:10px;padding:6px 8px;background:#fff;font-size:11px;font-weight:850}.bf-order-status{display:inline-flex;border-radius:999px;padding:3px 7px;font-weight:900;font-size:10px}.bf-order-status.pending{background:#fff0f4;color:#d95580}.bf-order-status.making{background:#fff7e8;color:#a66a12}.bf-order-status.ready{background:#eef8ff;color:#337aa5}.bf-order-status.printing{background:#f0efff;color:#6458b6}.bf-order-status.done{background:#edf9f2;color:#278158}.bf-order-status.void{background:#f1eeee;color:#85797e}
      .bf-order-actions{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}.bf-order-actions a,.bf-order-actions button{border:1px solid #edc4d0;background:#fff;color:#d95580;border-radius:999px;padding:6px 9px;font-size:11px;font-weight:850;text-decoration:none;cursor:pointer}.bf-order-actions button:disabled,.bf-order-status-row select:disabled{opacity:.5;cursor:not-allowed}.bf-order-actions .danger{color:#d94d61;border-color:#efc0c9}.bf-order-actions .voidbtn{color:#8a6c35;border-color:#ead8b7}.bf-order-empty{padding:50px 20px;text-align:center;color:#aaa;background:#fff;border:1px solid var(--line);border-radius:18px}
      @media(max-width:800px){.bf-order-summary{grid-template-columns:repeat(3,minmax(0,1fr))}}
      @media(max-width:700px){.bf-order-tools{position:static}.bf-order-grid{grid-template-columns:1fr}.bf-order-card{grid-template-columns:82px minmax(0,1fr)}.bf-order-thumb{width:82px;height:108px}.bf-order-summary{grid-template-columns:repeat(2,minmax(0,1fr))}}
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
        <button class="bf-order-chip active" data-range="today">今天</button><button class="bf-order-chip" data-range="yesterday">昨天</button><button class="bf-order-chip" data-range="7d">近 7 天</button><button class="bf-order-chip" data-range="all">全部日期</button>
        <input id="bf-order-date" type="date" title="指定日期">
        <select id="bf-order-status-filter"><option value="全部">全部狀態</option>${STATUSES.map(x=>`<option value="${e(x)}">${e(x)}</option>`).join('')}</select>
        <button class="btn alt mini" id="bf-order-reload"><i class="fa-solid fa-rotate"></i> 重新整理</button>
      </div>
      <div class="bf-order-summary" id="bf-order-summary"></div>
      <div id="bf-order-list"><div class="bf-order-empty">讀取訂單中…</div></div>
    </div>`;
    document.getElementById('bf-order-search').addEventListener('input',ev=>{query=ev.target.value.trim().toLowerCase();render()});
    document.querySelectorAll('[data-range]').forEach(b=>b.onclick=()=>{dateMode=b.dataset.range;exactDate='';document.getElementById('bf-order-date').value='';document.querySelectorAll('[data-range]').forEach(x=>x.classList.toggle('active',x===b));render()});
    document.getElementById('bf-order-date').onchange=ev=>{exactDate=ev.target.value||'';if(exactDate){dateMode='exact';document.querySelectorAll('[data-range]').forEach(x=>x.classList.remove('active'));}render()};
    document.getElementById('bf-order-status-filter').onchange=ev=>{statusFilter=ev.target.value||'全部';render()};
    document.getElementById('bf-order-reload').onclick=()=>refreshOrders(true);
    document.getElementById('bf-order-manager').addEventListener('change',ev=>{
      const sel=ev.target.closest('[data-order-status]');if(!sel)return;
      const orderId=sel.dataset.orderStatus,newStatus=sel.value,oldStatus=sel.dataset.currentStatus||'待處理';
      sel.disabled=true;window.bfSetOrderStatus(orderId,newStatus).catch(()=>{sel.value=oldStatus}).finally(()=>{sel.disabled=false});
    });
    document.getElementById('bf-order-manager').addEventListener('click',ev=>{
      const btn=ev.target.closest('[data-order-action]');if(!btn)return;
      window.bfOrderAction(btn.dataset.orderId,btn.dataset.orderAction);
    });
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
      if(statusFilter!=='全部'&&(r.status||'待處理')!==statusFilter)return false;
      if(!query)return true;
      const hay=[r.order_id,r.customer_name,r.model,r.style,r.payment_method,r.status].join(' ').toLowerCase();
      return hay.includes(query);
    });
  }

  function renderSummary(data){
    const sum=document.getElementById('bf-order-summary');if(!sum)return;
    const live=data.filter(x=>(x.status||'待處理')!=='作廢');
    const count=s=>data.filter(x=>(x.status||'待處理')===s).length;
    const ready=live.filter(x=>x.has_print).length;
    sum.innerHTML=`
      <div class="bf-order-kpi"><b>${data.length}</b><small>目前顯示</small></div>
      <div class="bf-order-kpi"><b>${count('待處理')}</b><small>待處理</small></div>
      <div class="bf-order-kpi"><b>${count('製作中')}</b><small>製作中</small></div>
      <div class="bf-order-kpi"><b>${count('待列印')+count('列印中')}</b><small>列印流程</small></div>
      <div class="bf-order-kpi"><b>${count('已完成')}</b><small>已完成</small></div>
      <div class="bf-order-kpi"><b>${ready}/${live.length}</b><small>已有生產圖</small></div>`;
  }

  function render(){
    ensureUi();const list=document.getElementById('bf-order-list');if(!list)return;
    const data=filtered();renderSummary(data);
    if(!data.length){list.innerHTML='<div class="bf-order-empty">這個條件目前沒有訂單</div>';return}
    const days=new Map();data.forEach(r=>{const f=fmtParts(r.time);if(!days.has(f.key))days.set(f.key,{label:f.label,rows:[]});days.get(f.key).rows.push({...r,_fmt:f})});
    list.innerHTML=[...days.entries()].sort((a,b)=>b[0].localeCompare(a[0])).map(([key,g])=>{
      const groups={上午:[],下午:[],晚上:[]};g.rows.sort((a,b)=>Number(b.time||0)-Number(a.time||0)).forEach(r=>groups[period(r._fmt.hour)].push(r));
      const sections=Object.entries(groups).filter(([,arr])=>arr.length).map(([p,arr])=>`<div class="bf-order-period">${p}・${arr.length} 筆</div><div class="bf-order-grid">${arr.map(cardHtml).join('')}</div>`).join('');
      return `<section class="bf-order-day"><div class="bf-order-day-head"><span>${e(g.label)}</span><small>${g.rows.length} 筆</small></div>${sections}</section>`;
    }).join('');
  }

  function statusOptions(o){
    const current=o.status||'待處理';
    return STATUSES.filter(x=>x!=='作廢').map(s=>{
      const disabled=PRINT_REQUIRED.has(s)&&!o.has_print?' disabled':'';
      return `<option value="${e(s)}"${s===current?' selected':''}${disabled}>${e(s)}${disabled?'（需生產圖）':''}</option>`;
    }).join('');
  }

  function cardHtml(o){
    const total=Number(o.total||((o.price||0)*(o.quantity||1)))||0;
    const current=o.status||'待處理',isVoid=current==='作廢';
    const preview=o.mockup_url?`<a href="${e(o.mockup_url)}" target="_blank" rel="noopener"><img class="bf-order-thumb" loading="lazy" decoding="async" src="${e(o.mockup_url)}" onerror="this.style.opacity=.15"></a>`:'<div class="bf-order-thumb empty">無預覽</div>';
    return `<article class="bf-order-card${isVoid?' void':''}">
      <div>${preview}</div>
      <div>
        <div class="bf-order-id">${e(o.order_id)} <span class="bf-order-status ${statusClass(current)}">${e(current)}</span></div>
        <div class="bf-order-time">${e(o._fmt?.time||fmtParts(o.time).time)}</div>
        <div class="bf-order-meta"><b>${e(o.model||'')}</b>・${e(o.style||'')}<br>${e(o.customer_name||'')}｜${e(o.payment_method||'')}｜${Number(o.quantity||1)} 件<br><span class="bf-order-price">NT$ ${total.toLocaleString()}</span></div>
        <div class="bf-order-ready"><span class="bf-ready-badge ${o.has_mockup?'ok':'bad'}">${o.has_mockup?'✓ 預覽圖':'✕ 缺預覽圖'}</span><span class="bf-ready-badge ${o.has_print?'ok':'bad'}">${o.has_print?'✓ 高清生產圖':'✕ 缺生產圖'}</span></div>
        ${isVoid?'':`<div class="bf-order-status-row"><span style="font-size:10px;color:#887a80">生產狀態</span><select data-order-status="${e(o.order_id)}" data-current-status="${e(current)}">${statusOptions(o)}</select></div>`}
        <div class="bf-order-actions">
          ${o.print_url?`<a href="${e(o.print_url)}" target="_blank" rel="noopener"><i class="fa-solid fa-file-arrow-down"></i> 生產圖</a>`:''}
          ${isVoid?`<button data-order-action="restore" data-order-id="${e(o.order_id)}">恢復</button>`:`<button class="voidbtn" data-order-action="void" data-order-id="${e(o.order_id)}">作廢</button>`}
          <button class="danger" data-order-action="delete" data-order-id="${e(o.order_id)}">刪除</button>
        </div>
      </div>
    </article>`;
  }

  async function requestAction(orderId,action,newStatus=''){
    const payload={order_id:orderId,action};if(newStatus)payload.new_status=newStatus;
    const r=await fetch('/api/admin/order_action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});let j={};try{j=await r.json()}catch(e){}
    if(!r.ok||j.status!=='success')throw new Error(j.msg||('HTTP '+r.status));
    return j;
  }

  window.bfSetOrderStatus=async function(orderId,newStatus){
    try{await requestAction(orderId,'set_status',newStatus);await refreshOrders(true)}catch(err){alert(err.message||'更新訂單狀態失敗');throw err}
  };

  window.bfOrderAction=async function(orderId,action){
    if(action==='void'&&!confirm('確定將這筆訂單標記為「作廢」？資料與生產圖會保留。'))return;
    if(action==='restore'&&!confirm('確定恢復這筆訂單為「待處理」？'))return;
    if(action==='delete'){
      if(!confirm('這會永久刪除訂單資料與生產/預覽圖片，確定刪除？'))return;
      if(!confirm('最後確認：永久刪除後無法復原。'))return;
    }
    try{await requestAction(orderId,action);await refreshOrders(true)}catch(err){alert(err.message||'訂單操作失敗')}
  };

  window.refreshOrders=async function(force=false){
    if(loading&&!force)return;loading=true;ensureUi();const list=document.getElementById('bf-order-list');if(force&&list)list.innerHTML='<div class="bf-order-empty">重新整理中…</div>';
    try{
      const r=await fetch('/api/admin/get_orders?limit=200&ts='+Date.now(),{cache:'no-store'});let j={};try{j=await r.json()}catch(e){}
      if(!r.ok||j.status!=='success')throw new Error(j.msg||('HTTP '+r.status));rows=Array.isArray(j.data)?j.data:[];render();
    }catch(err){if(list)list.innerHTML=`<div class="bf-order-empty" style="color:#d94d61">${e(err.message||'讀取失敗')}</div>`}
    finally{loading=false}
  };

  function boot(){ensureUi();refreshOrders(true);console.info('[ADMIN] order center v3 enabled: production workflow + print readiness')}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
