(function(){
  'use strict';
  if(window.__benfuwanPrintCenterInstalled)return;
  window.__benfuwanPrintCenterInstalled=true;
  let rows=[],busy=false,query='',editing=null;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const stateClass=s=>s==='UNKNOWN'?'unknown':(s==='FAILED'?'failed':'');
  const date=v=>{if(!v)return '—';const d=typeof v==='number'?new Date(v*1000):new Date(v);return isNaN(d)?'—':new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(d)};

  function install(){
    const nav=document.querySelector('.nav');
    if(nav&&!document.querySelector('[data-view="print-center"]')){
      const button=document.createElement('button');button.dataset.view='print-center';button.innerHTML='<i class="fa-solid fa-print"></i><span>列印中心</span>';
      button.addEventListener('click',()=>{document.querySelectorAll('.nav button').forEach(b=>b.classList.toggle('active',b===button));document.querySelectorAll('.view').forEach(v=>v.classList.toggle('active',v.id==='view-print-center'));load(true)});
      nav.insertBefore(button,nav.children[1]||null);
    }
    const content=document.querySelector('.content');
    if(content&&!document.getElementById('view-print-center')){
      const section=document.createElement('section');section.className='view';section.id='view-print-center';section.innerHTML=`
        <div class="pc-head"><h2>列印中心</h2><button class="btn alt" id="pc-reload"><i class="fa-solid fa-rotate"></i> 重新整理</button></div>
        <div id="pc-config" class="pc-banner">檢查雲打印設定中…</div>
        <div class="pc-toolbar"><input id="pc-search" type="search" placeholder="搜尋訂單、客人、型號、殼款、taskid"><span class="pc-badge">送到雲端不會自動出墨</span></div>
        <div id="pc-grid" class="pc-grid"><div class="pc-empty">讀取列印任務中…</div></div>`;content.insertBefore(section,content.firstChild);
      section.querySelector('#pc-reload').onclick=()=>load(true);section.querySelector('#pc-search').oninput=e=>{query=e.target.value.trim().toLowerCase();render()};section.addEventListener('click',onAction);
    }
    if(!document.getElementById('pc-modal')){
      const modal=document.createElement('div');modal.id='pc-modal';modal.className='pc-modal';modal.innerHTML=`<div class="pc-dialog"><div class="pc-dialog-head">設定 SKU 列印參數</div><div class="pc-form">
        <div class="pc-field" style="grid-column:1/-1"><label>SKU（由訂單財務快照帶入）</label><input id="pc-sku" readonly></div>
        <div class="pc-field"><label>寬度 mm</label><input id="pc-width" type="number" step="0.001" min="0.001"></div><div class="pc-field"><label>高度 mm</label><input id="pc-height" type="number" step="0.001" min="0.001"></div>
        <div class="pc-field"><label>左偏移 mm</label><input id="pc-left" type="number" step="0.001" value="0"></div><div class="pc-field"><label>上偏移 mm</label><input id="pc-top" type="number" step="0.001" value="0"></div>
        <div class="pc-field"><label>份數</label><input id="pc-copies" type="number" min="1" max="99" value="1"></div><div class="pc-field"><label>Channel</label><input id="pc-channel"></div>
        <div class="pc-field"><label>Spot color</label><input id="pc-spot"></div><div class="pc-field"><label>角度</label><input id="pc-angle" type="number" step="0.001" value="0"></div>
      </div><div class="pc-dialog-actions"><button class="btn alt" id="pc-close">取消</button><button class="btn" id="pc-save">儲存列印參數</button></div></div>`;document.body.appendChild(modal);
      modal.querySelector('#pc-close').onclick=()=>modal.classList.remove('show');modal.querySelector('#pc-save').onclick=saveProfile;
    }
  }

  function card(row){
    const j=row.job||null,state=j?.state||'',isVoid=row.order_status==='作廢';
    const thumb=row.preview_url?`<img class="pc-thumb" loading="lazy" src="${esc(row.preview_url)}" alt="訂單預覽">`:'<div class="pc-thumb pc-thumb-empty">無預覽</div>';
    let actions='';
    if(!j&&!isVoid&&row.has_print)actions+=`<button class="primary" data-pc="prepare" data-order="${esc(row.order_id)}">準備任務</button>`;
    if(row.sku_id)actions+=`<button data-pc="profile" data-order="${esc(row.order_id)}">設定列印參數</button>`;
    if(j?.state==='PREPARED'&&!j.profile_complete&&row.profile_available)actions+=`<button data-pc="snapshot" data-job="${esc(j.id)}">套用參數快照</button>`;
    if(j?.state==='PREPARED'&&j.profile_complete)actions+=`<button class="primary" data-pc="send" data-job="${esc(j.id)}" ${window.pcVendorReady?'':'disabled title="雲打印未啟用"'}>送到雲端</button>`;
    if(j?.state==='QUEUED')actions+=`<button class="primary" data-pc="start" data-job="${esc(j.id)}">開始列印</button><button class="danger" data-pc="cancel" data-job="${esc(j.id)}">取消等待</button>`;
    if(j?.state==='PREPARED')actions+=`<button class="danger" data-pc="cancel" data-job="${esc(j.id)}">取消任務</button>`;
    if(j&&['UNKNOWN','QUEUED','STARTING','PRINTING'].includes(j.state))actions+=`<button data-pc="reconcile" data-job="${esc(j.id)}" ${window.pcVendorReady?'':'disabled'}>查核雲端</button>`;
    return `<article class="pc-card${isVoid?' void':''}">${thumb}<div><div class="pc-id">${esc(row.order_id)}</div><div class="pc-meta"><b>${esc(row.model)}</b>・${esc(row.style)}<br>${esc(row.customer_name)}｜${esc(row.order_status)}｜${date(row.time)}</div><div class="pc-badges">
      <span class="pc-badge ${row.has_print?'ok':'bad'}">${row.has_print?'有高清生產圖':'缺生產圖'}</span><span class="pc-badge ${row.profile_available?'ok':'bad'}">${row.profile_available?'參數已設定':'列印參數未設定'}</span>${j?`<span class="pc-badge pc-state ${stateClass(state)}">${esc(j.state_label)}</span>`:''}</div>
      ${j?.vendor_taskid?`<div class="pc-raw">taskid：${esc(j.vendor_taskid)}｜raw ${esc(j.vendor_raw_status||'—')} ${esc(j.vendor_raw_message||'')}</div>`:''}${j?.last_error?`<div class="pc-error">${esc(j.last_error)}</div>`:''}
      <div class="pc-actions">${actions||'<span class="pc-raw">目前沒有可執行操作</span>'}</div></div></article>`;
  }
  function filtered(){if(!query)return rows;return rows.filter(r=>[r.order_id,r.customer_name,r.model,r.style,r.order_status,r.job?.vendor_taskid,r.job?.state_label].join(' ').toLowerCase().includes(query))}
  function render(){const box=document.getElementById('pc-grid');if(!box)return;const data=filtered();box.innerHTML=data.length?data.map(card).join(''):'<div class="pc-empty">這個條件目前沒有訂單</div>'}
  async function json(url,opt={}){const r=await fetch(url,opt);let j={};try{j=await r.json()}catch(e){}if(!r.ok||j.status!=='success'){const err=new Error(j.msg||('HTTP '+r.status));err.code=j.code||'';throw err}return j}
  async function load(force=false){if(busy&&!force)return;busy=true;const box=document.getElementById('pc-grid');if(force&&box)box.innerHTML='<div class="pc-empty">重新整理中…</div>';try{const j=await json('/api/admin/print/jobs?ts='+Date.now(),{cache:'no-store'});rows=j.rows||[];window.pcVendorReady=!!j.vendor_ready;const cfg=document.getElementById('pc-config');cfg.className='pc-banner '+(j.vendor_ready?'':'warn');cfg.textContent=j.vendor_ready?`雲打印已接線（設備 ${j.device_id}）。送到雲端後仍需人工二次確認才會開始實體列印。`:'雲打印目前關閉或憑證／安全網址未完整設定；可管理任務與列印參數，但送出和開始列印會安全拒絕。';render()}catch(e){if(box)box.innerHTML=`<div class="pc-empty pc-error">${esc(e.message)}</div>`}finally{busy=false}}
  function opKey(name,id){const slot='pc:'+name+':'+id;let value=sessionStorage.getItem(slot);if(!value){value=crypto.randomUUID();sessionStorage.setItem(slot,value)}return {slot,value}}
  async function operate(name,id,field='job_id'){
    const k=opKey(name,id);try{await json('/api/admin/print/'+(name==='snapshot'?'profile-snapshot':name),{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':k.value},body:JSON.stringify({[field]:id,idempotency_key:k.value})});sessionStorage.removeItem(k.slot);await load(true)}catch(e){if(e.code!=='RECONCILE_REQUIRED')sessionStorage.removeItem(k.slot);alert(e.message)}
  }
  function onAction(event){const b=event.target.closest('[data-pc]');if(!b||b.disabled)return;const name=b.dataset.pc;if(name==='profile')return openProfile(b.dataset.order);if(name==='start'&&!confirm('二次確認：按下後可能立即開始實體列印並出墨。已核對型號、殼款、生產圖與列印參數，確定開始？'))return;if(name==='send'&&!confirm('確定把任務送到雲打印等待佇列？這一步不會自動出墨。'))return;if(name==='cancel'&&!confirm('只能安全取消尚未開始列印的任務，確定取消？'))return;operate(name,name==='prepare'?b.dataset.order:b.dataset.job,name==='prepare'?'order_id':'job_id')}
  function openProfile(orderId){const row=rows.find(x=>x.order_id===orderId);if(!row?.sku_id)return alert('這筆訂單沒有可靠的 SKU 財務快照，不能猜列印參數');editing=row;const p=row.profile||{};document.getElementById('pc-sku').value=row.sku_id;document.getElementById('pc-width').value=p.width_mm??'';document.getElementById('pc-height').value=p.height_mm??'';document.getElementById('pc-left').value=p.left_mm??0;document.getElementById('pc-top').value=p.top_mm??0;document.getElementById('pc-copies').value=p.copies??1;document.getElementById('pc-channel').value=p.channel??'';document.getElementById('pc-spot').value=p.spot_color??'';document.getElementById('pc-angle').value=p.angle??0;document.getElementById('pc-modal').classList.add('show')}
  async function saveProfile(){if(!editing)return;const payload={sku_id:document.getElementById('pc-sku').value,width_mm:document.getElementById('pc-width').value,height_mm:document.getElementById('pc-height').value,left_mm:document.getElementById('pc-left').value,top_mm:document.getElementById('pc-top').value,copies:document.getElementById('pc-copies').value,channel:document.getElementById('pc-channel').value,spot_color:document.getElementById('pc-spot').value,angle:document.getElementById('pc-angle').value};try{await json('/api/admin/print/profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});document.getElementById('pc-modal').classList.remove('show');if(editing.job?.state==='PREPARED'&&!editing.job.profile_complete&&confirm('列印參數已儲存。要明確套用為這筆尚未送出任務的固定快照嗎？'))await operate('snapshot',editing.job.id);else await load(true)}catch(e){alert(e.message)}}
  function boot(){install()}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
