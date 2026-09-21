(function(){
  'use strict';
  if(window.__benfuwanPrintCenterInstalled)return;
  window.__benfuwanPrintCenterInstalled=true;
  let rows=[],busy=false,query='',bindingEditing=null;
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
        <div class="pc-toolbar"><input id="pc-search" type="search" placeholder="搜尋訂單、客人、型號、殼款、taskid"><span class="pc-badge">送到銳印後，由店員在銳印人工確認</span></div>
        <div id="pc-grid" class="pc-grid"><div class="pc-empty">讀取列印任務中…</div></div>`;content.insertBefore(section,content.firstChild);
      section.querySelector('#pc-reload').onclick=()=>load(true);section.querySelector('#pc-search').oninput=e=>{query=e.target.value.trim().toLowerCase();render()};section.addEventListener('click',onAction);
    }
    if(!document.getElementById('pc-bind-modal')){
      const modal=document.createElement('div');modal.id='pc-bind-modal';modal.className='pc-modal';modal.innerHTML=`<div class="pc-dialog pc-bind-dialog"><div class="pc-dialog-head">補綁列印 SKU</div><div class="pc-form">
        <div id="pc-bind-order" class="pc-spec" style="grid-column:1/-1"></div>
        <div class="pc-suggestion suggested" style="grid-column:1/-1">此為舊訂單，先選擇列印用 SKU，不會修改營收／成本／庫存資料。系統建議只供預選，仍須由店員按下儲存確認。</div>
        <div class="pc-field" style="grid-column:1/-1"><label for="pc-bind-sku">列印用 SKU</label><select id="pc-bind-sku"></select></div>
      </div><div class="pc-dialog-actions"><button class="btn alt" id="pc-bind-close">取消</button><button class="btn" id="pc-bind-save">確認補綁</button></div></div>`;document.body.appendChild(modal);
      modal.querySelector('#pc-bind-close').onclick=()=>modal.classList.remove('show');modal.querySelector('#pc-bind-save').onclick=saveBinding;
    }
  }

  function card(row){
    const j=row.job||null,state=j?.state||'',isVoid=row.order_status==='作廢';
    const thumb=row.preview_url?`<img class="pc-thumb" loading="lazy" src="${esc(row.preview_url)}" alt="訂單預覽">`:'<div class="pc-thumb pc-thumb-empty">無預覽</div>';
    let actions='';
    if(row.binding_required&&!isVoid)actions+=`<button class="primary" data-pc="binding" data-order="${esc(row.order_id)}">補綁列印 SKU</button>`;
    if(!j&&!isVoid&&row.has_print&&row.sku_id&&row.profile_available)actions+=`<button class="primary" data-pc="prepare" data-order="${esc(row.order_id)}">準備任務</button>`;
    if(j?.state==='PREPARED'&&!j.profile_complete&&row.profile_available)actions+=`<button data-pc="snapshot" data-job="${esc(j.id)}">套用參數快照</button>`;
    if(j?.state==='PREPARED'&&j.profile_complete)actions+=`<button class="primary" data-pc="send" data-job="${esc(j.id)}" ${window.pcVendorReady?'':'disabled title="雲打印未啟用"'}>送到銳印</button>`;
    if(j?.state==='QUEUED')actions+=`<button class="danger" data-pc="cancel" data-job="${esc(j.id)}" ${window.pcVendorConnected?'':'disabled'}>取消等待</button>`;
    if(j?.state==='PREPARED')actions+=`<button class="danger" data-pc="cancel" data-job="${esc(j.id)}">取消任務</button>`;
    if(j&&['UNKNOWN','SENDING','QUEUED','STARTING','PRINTING','CANCELING'].includes(j.state))actions+=`<button data-pc="reconcile" data-job="${esc(j.id)}" ${window.pcVendorConnected?'':'disabled'}>查核雲端</button>`;
    const profile=row.profile?`${Number(row.profile.width_mm)} × ${Number(row.profile.height_mm)} mm / X ${Number(row.profile.left_mm)} / Y ${Number(row.profile.top_mm)}`:'請到「品牌及型號」設定列印參數';
    return `<article class="pc-card${isVoid?' void':''}">${thumb}<div><div class="pc-id">${esc(row.order_id)}</div><div class="pc-meta"><b>${esc(row.model)}</b>・${esc(row.style)}<br>${esc(row.customer_name)}｜${esc(row.order_status)}｜${date(row.time)}</div><div class="pc-badges">
      <span class="pc-badge ${row.has_print?'ok':'bad'}">${row.has_print?'有高清生產圖':'缺生產圖'}</span><span class="pc-badge ${row.profile_available?'ok':'bad'}">${row.profile_available?'參數已設定':'列印參數未設定'}</span>${j?`<span class="pc-badge pc-state ${stateClass(state)}">${esc(j.state_label)}</span>`:''}</div>
      <div class="pc-raw">列印參數：${esc(profile)}</div>${row.legacy_order?'<div class="pc-legacy-note">此為舊訂單，先選擇列印用 SKU，不會修改營收／成本／庫存資料。</div>':''}${j?.vendor_taskid?`<div class="pc-raw">taskid：${esc(j.vendor_taskid)}｜raw ${esc(j.vendor_raw_status||'—')} ${esc(j.vendor_raw_message||'')}</div>`:''}${j?.last_error?`<div class="pc-error">${esc(j.last_error)}</div>`:''}
      <div class="pc-actions">${actions||'<span class="pc-raw">目前沒有可執行操作</span>'}</div></div></article>`;
  }
  function filtered(){if(!query)return rows;return rows.filter(r=>[r.order_id,r.customer_name,r.model,r.style,r.order_status,r.job?.vendor_taskid,r.job?.state_label].join(' ').toLowerCase().includes(query))}
  function render(){const box=document.getElementById('pc-grid');if(!box)return;const data=filtered();box.innerHTML=data.length?data.map(card).join(''):'<div class="pc-empty">這個條件目前沒有訂單</div>'}
  async function json(url,opt={}){const r=await fetch(url,opt);let j={};try{j=await r.json()}catch(e){}if(!r.ok||j.status!=='success'){const err=new Error(j.msg||('HTTP '+r.status));err.code=j.code||'';throw err}return j}
  async function load(force=false){if(busy&&!force)return;busy=true;const box=document.getElementById('pc-grid');if(force&&box)box.innerHTML='<div class="pc-empty">重新整理中…</div>';try{const j=await json('/api/admin/print/jobs?ts='+Date.now(),{cache:'no-store'});rows=j.rows||[];window.pcVendorReady=!!j.vendor_ready;window.pcVendorConnected=!!j.vendor_connected;const cfg=document.getElementById('pc-config');cfg.className='pc-banner '+(j.vendor_ready?'':'warn');cfg.textContent=j.vendor_ready?`雲打印已接線（設備 ${j.device_id}）。送到銳印後，請由店員在銳印人工確認；網站不會啟動實體打印。`:'雲打印目前關閉，或憑證、HTTPS public URL、生產圖密鑰未完整設定；送到銳印會安全拒絕。';render()}catch(e){if(box)box.innerHTML=`<div class="pc-empty pc-error">${esc(e.message)}</div>`}finally{busy=false}}
  function opKey(name,id){const slot='pc:'+name+':'+id;let value=sessionStorage.getItem(slot);if(!value){value=crypto.randomUUID();sessionStorage.setItem(slot,value)}return {slot,value}}
  async function operate(name,id,field='job_id'){
    const k=opKey(name,id);try{await json('/api/admin/print/'+(name==='snapshot'?'profile-snapshot':name),{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':k.value},body:JSON.stringify({[field]:id,idempotency_key:k.value})});sessionStorage.removeItem(k.slot);await load(true)}catch(e){if(e.code!=='RECONCILE_REQUIRED')sessionStorage.removeItem(k.slot);alert(e.message)}
  }
  function onAction(event){const b=event.target.closest('[data-pc]');if(!b||b.disabled)return;const name=b.dataset.pc;if(name==='binding')return openBinding(b.dataset.order);if(name==='send'&&!confirm('確定把任務送到銳印？送出後仍需店員在銳印人工確認才會打印。'))return;if(name==='cancel'&&!confirm('只能安全取消尚未開始打印的等待任務，確定取消？'))return;operate(name,name==='prepare'?b.dataset.order:b.dataset.job,name==='prepare'?'order_id':'job_id')}
  function openBinding(orderId){const row=rows.find(x=>x.order_id===orderId);if(!row?.legacy_order)return alert('這筆訂單已有財務 SKU 快照，不需要補綁');bindingEditing=row;const select=document.getElementById('pc-bind-sku'),candidates=row.sku_candidates||[];document.getElementById('pc-bind-order').textContent=`訂單 ${row.order_id}｜${row.model}・${row.style}`;select.innerHTML='<option value="">請選擇型號、系列與顏色完全相符的 SKU</option>'+candidates.map(s=>`<option value="${esc(s.id)}">${esc(s.model)}｜${esc(s.style)}｜${esc(s.color||'無顏色')}</option>`).join('');select.value=row.suggested_sku_id||'';select.disabled=!candidates.length;if(!candidates.length)select.innerHTML='<option value="">目前找不到相符的 commerce SKU</option>';document.getElementById('pc-bind-save').disabled=!candidates.length;document.getElementById('pc-bind-modal').classList.add('show')}
  async function saveBinding(){if(!bindingEditing)return;const skuId=document.getElementById('pc-bind-sku').value;if(!skuId)return alert('請明確選擇列印用 SKU');try{await json('/api/admin/print/binding',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({order_id:bindingEditing.order_id,sku_id:skuId})});document.getElementById('pc-bind-modal').classList.remove('show');await load(true)}catch(e){alert(e.message)}}
  function boot(){install()}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
