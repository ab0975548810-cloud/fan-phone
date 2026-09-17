/* 本福丸後台 POS / 成本 / 毛利 / 庫存管理 v1 */
(function(){
  'use strict';
  if(window.__bfAdminCommerceV1)return;window.__bfAdminCommerceV1=true;

  let state={version:1,style_defaults:{},skus:[]};
  let summary={};
  let loaded=false;
  const money=n=>'NT$ '+Math.round(Number(n)||0).toLocaleString('zh-TW');
  const num=(v,d=0)=>Number.isFinite(Number(v))?Number(v):d;
  const h=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const modelOf=id=>(shopData.models||[]).find(x=>String(x.id)===String(id));
  const styleOf=id=>(shopData.styles||[]).find(x=>String(x.id)===String(id));

  function css(){
    if(document.getElementById('bf-commerce-css'))return;
    const s=document.createElement('style');s.id='bf-commerce-css';s.textContent=`
      .commerce-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:14px}
      .commerce-kpi{background:#fff;border:1px solid var(--line);border-radius:16px;padding:13px;box-shadow:var(--shadow)}
      .commerce-kpi small{display:block;color:var(--muted);font-weight:800;font-size:11px}.commerce-kpi b{display:block;margin-top:5px;font-size:20px}.commerce-kpi em{display:block;margin-top:4px;color:#a09197;font-size:10px;font-style:normal}
      .commerce-toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px}.commerce-toolbar input,.commerce-toolbar select{border:1px solid #eadce1;border-radius:999px;padding:8px 11px;background:#fff;font-size:12px}
      .commerce-section-title{display:flex;justify-content:space-between;align-items:center;gap:8px;margin:8px 0 10px}.commerce-section-title b{font-size:14px}
      .commerce-price-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(245px,1fr));gap:10px;margin-bottom:16px}
      .commerce-price-card{border:1px solid var(--line);border-radius:16px;padding:12px;background:#fffafb}.commerce-price-card h4{margin:0 0 9px;font-size:13px}.commerce-mini-grid{display:grid;grid-template-columns:1fr 1fr;gap:7px}.commerce-mini-grid label{font-size:10px;color:var(--muted);font-weight:800}.commerce-mini-grid input{width:100%;margin-top:4px;border:1px solid #eadce1;border-radius:10px;padding:8px;background:#fff}.commerce-price-meta{font-size:11px;color:#7d7176;margin:8px 0}.commerce-actions{display:flex;gap:6px;flex-wrap:wrap}
      .commerce-table input[type=number]{width:82px;border:1px solid #eadce1;border-radius:9px;padding:7px}.commerce-table input[type=checkbox]{width:18px;height:18px;accent-color:var(--pink)}
      .commerce-profit{font-weight:900}.commerce-profit.positive{color:var(--green)}.commerce-profit.negative{color:var(--red)}.commerce-low{background:#fff2f3!important}.commerce-muted{color:var(--muted);font-size:11px}.commerce-warning{padding:10px 12px;border-radius:12px;background:#fff7e9;color:#8d682e;font-size:11px;margin-bottom:12px}
      @media(max-width:900px){.commerce-summary{grid-template-columns:1fr 1fr}.commerce-price-grid{grid-template-columns:1fr}.commerce-table{min-width:900px}}
    `;document.head.appendChild(s);
  }

  function ensureUi(){
    css();
    const nav=document.querySelector('.nav');
    if(nav&&!document.querySelector('.nav button[data-view="commerce"]')){
      const btn=document.createElement('button');btn.dataset.view='commerce';btn.innerHTML='<i class="fa-solid fa-cash-register"></i><span>商品・庫存 POS</span>';
      const orders=nav.querySelector('button[data-view="orders"]');
      if(orders)orders.insertAdjacentElement('afterend',btn);else nav.prepend(btn);
      btn.addEventListener('click',openView);
    }
    const content=document.querySelector('.content');
    if(content&&!document.getElementById('view-commerce')){
      const section=document.createElement('section');section.className='view';section.id='view-commerce';section.innerHTML=`
        <div class="titlebar"><h2>商品・庫存 POS</h2><div style="display:flex;gap:7px"><button class="btn alt" id="commerce-reload"><i class="fa-solid fa-rotate"></i> 重新整理</button><button class="btn" id="commerce-sync"><i class="fa-solid fa-arrows-rotate"></i> 同步商品 SKU</button></div></div>
        <div class="commerce-summary" id="commerce-summary"></div>
        <div class="commerce-warning" id="commerce-warning">售價會同步到客人前台；成本、庫存、毛利只存在店內後台，不會公開給客人。</div>
        <div class="panel" style="margin-bottom:14px">
          <div class="commerce-section-title"><b>材質售價與預設成本</b><span class="commerce-muted">售價＝前台售價；預設成本只套用到新 SKU，除非你按「套用到現有 SKU」</span></div>
          <div class="commerce-price-grid" id="commerce-price-grid"></div>
        </div>
        <div class="panel">
          <div class="commerce-section-title"><b>SKU 庫存明細</b><button class="btn" id="commerce-save"><i class="fa-solid fa-floppy-disk"></i> 儲存全部庫存</button></div>
          <div class="commerce-toolbar">
            <input id="commerce-search" placeholder="搜尋型號／材質／顏色">
            <select id="commerce-style-filter"><option value="">全部材質</option></select>
            <label style="font-size:12px;font-weight:800"><input id="commerce-low-only" type="checkbox"> 只看低庫存</label>
          </div>
          <div class="table-wrap"><table class="tbl commerce-table"><thead><tr><th>型號</th><th>材質</th><th>顏色</th><th>售價</th><th>成本</th><th>單件毛利</th><th>毛利率</th><th>庫存</th><th>警戒</th><th>追蹤庫存</th></tr></thead><tbody id="commerce-sku-body"></tbody></table></div>
        </div>`;
      const orders=document.getElementById('view-orders');if(orders)orders.insertAdjacentElement('afterend',section);else content.prepend(section);
      section.querySelector('#commerce-reload').addEventListener('click',()=>load(true));
      section.querySelector('#commerce-sync').addEventListener('click',syncSkus);
      section.querySelector('#commerce-save').addEventListener('click',saveAll);
      section.querySelector('#commerce-search').addEventListener('input',renderSkus);
      section.querySelector('#commerce-style-filter').addEventListener('change',renderSkus);
      section.querySelector('#commerce-low-only').addEventListener('change',renderSkus);
      section.querySelector('#commerce-sku-body').addEventListener('input',onSkuInput);
      section.querySelector('#commerce-sku-body').addEventListener('change',onSkuInput);
    }
  }

  async function openView(){
    document.querySelectorAll('.nav button').forEach(b=>b.classList.toggle('active',b.dataset.view==='commerce'));
    document.querySelectorAll('.view').forEach(v=>v.classList.toggle('active',v.id==='view-commerce'));
    try{currentView='commerce'}catch(e){}
    await load(false);
  }

  async function load(force=false){
    ensureUi();
    try{
      if(typeof loadShop==='function')await loadShop(force);
      if(loaded&&!force){renderAll();return}
      const j=await apiJson('/api/admin/commerce_data?ts='+Date.now(),{cache:'no-store'});
      state=j.data||{version:1,style_defaults:{},skus:[]};summary=j.summary||{};loaded=true;renderAll();
    }catch(e){alert('POS 資料載入失敗：'+e.message)}
  }

  function styleDefault(styleId){
    state.style_defaults=state.style_defaults||{};
    state.style_defaults[styleId]=state.style_defaults[styleId]||{cost_price:null,low_stock_threshold:2,track_stock:false};
    return state.style_defaults[styleId];
  }

  function inventoryStats(){
    let low=0,value=0,potential=0,potentialProfit=0,unknown=0;
    for(const sku of state.skus||[]){
      if(!sku.active)continue;
      const st=styleOf(sku.style_id),sale=num(st?.price,0),stock=Math.max(0,num(sku.stock_qty,0)),cost=sku.cost_price;
      if(sku.track_stock&&stock<=num(sku.low_stock_threshold,2))low++;
      potential+=sale*stock;
      if(cost===null||cost===undefined||cost==='')unknown++;else{value+=num(cost,0)*stock;potentialProfit+=(sale-num(cost,0))*stock}
    }
    return{low,value,potential,potentialProfit,unknown};
  }

  function renderSummary(){
    const inv=inventoryStats();
    const box=document.getElementById('commerce-summary');if(!box)return;
    const missing=num(summary.orders_missing_cost,0);
    box.innerHTML=`
      <div class="commerce-kpi"><small>今日營收</small><b>${money(summary.today_revenue)}</b><em>POS 啟用後的訂單</em></div>
      <div class="commerce-kpi"><small>今日毛利</small><b>${money(summary.today_gross_profit)}</b><em>${missing?'有 '+missing+' 筆訂單尚未設定成本':'已知成本訂單計算'}</em></div>
      <div class="commerce-kpi"><small>目前庫存成本</small><b>${money(inv.value)}</b><em>${inv.unknown?'有 '+inv.unknown+' 個 SKU 成本未設定':'全部 SKU 已有成本'}</em></div>
      <div class="commerce-kpi"><small>低庫存 SKU</small><b>${inv.low.toLocaleString('zh-TW')}</b><em>依各 SKU 警戒值判定</em></div>`;
  }

  function renderPriceCards(){
    const box=document.getElementById('commerce-price-grid');if(!box)return;
    const styles=(shopData.styles||[]).filter(s=>s.status!==false);
    box.innerHTML=styles.map(st=>{
      const d=styleDefault(String(st.id));const cost=d.cost_price;const sale=num(st.price,0);const profit=cost==null?null:sale-num(cost,0);const margin=cost==null||sale<=0?null:(profit/sale*100);
      return `<div class="commerce-price-card" data-style="${h(st.id)}"><h4>${h(st.name)}</h4>
        <div class="commerce-mini-grid">
          <label>前台售價<input class="commerce-style-price" type="number" min="1" step="1" value="${h(st.price||0)}"></label>
          <label>預設成本<input class="commerce-style-cost" type="number" min="0" step="1" value="${cost==null?'':h(cost)}" placeholder="未設定"></label>
          <label>預設低庫存警戒<input class="commerce-style-low" type="number" min="0" step="1" value="${h(d.low_stock_threshold??2)}"></label>
          <label style="display:flex;align-items:flex-end;gap:7px;padding-bottom:7px"><input class="commerce-style-track" type="checkbox" ${d.track_stock?'checked':''} style="width:18px;height:18px"> 追蹤庫存</label>
        </div>
        <div class="commerce-price-meta">單件毛利：<b>${profit==null?'尚未設定成本':money(profit)}</b>${margin==null?'':` ・ 毛利率 ${margin.toFixed(1)}%`}</div>
        <div class="commerce-actions"><button class="btn mini" onclick="BenfuwanCommerce.saveStyle('${h(st.id)}',false)">儲存材質設定</button><button class="btn alt mini" onclick="BenfuwanCommerce.saveStyle('${h(st.id)}',true)">套用成本到現有 SKU</button></div>
      </div>`;
    }).join('')||'<div class="empty">目前沒有啟用中的手機殼材質</div>';
  }

  function renderFilters(){
    const sel=document.getElementById('commerce-style-filter');if(!sel)return;const keep=sel.value;
    sel.innerHTML='<option value="">全部材質</option>'+(shopData.styles||[]).filter(s=>s.status!==false).map(s=>`<option value="${h(s.id)}">${h(s.name)}</option>`).join('');sel.value=keep;
  }

  function skuMatches(sku){
    const q=(document.getElementById('commerce-search')?.value||'').trim().toLowerCase();const styleFilter=document.getElementById('commerce-style-filter')?.value||'';const lowOnly=!!document.getElementById('commerce-low-only')?.checked;
    const m=modelOf(sku.model_id),st=styleOf(sku.style_id);const text=`${m?.name||sku.model_id} ${st?.name||sku.style_id} ${sku.color||''}`.toLowerCase();
    if(q&&!text.includes(q))return false;if(styleFilter&&String(sku.style_id)!==styleFilter)return false;if(lowOnly&&!(sku.track_stock&&num(sku.stock_qty)<=num(sku.low_stock_threshold,2)))return false;return true;
  }

  function renderSkus(){
    const body=document.getElementById('commerce-sku-body');if(!body)return;
    const list=(state.skus||[]).filter(skuMatches).sort((a,b)=>{const am=modelOf(a.model_id)?.name||a.model_id,bm=modelOf(b.model_id)?.name||b.model_id;return am.localeCompare(bm,'zh-Hant')||String(a.style_id).localeCompare(String(b.style_id))||String(a.color).localeCompare(String(b.color),'zh-Hant')});
    body.innerHTML=list.map(sku=>{
      const m=modelOf(sku.model_id),st=styleOf(sku.style_id),sale=num(st?.price,0),cost=sku.cost_price;const profit=cost==null?null:sale-num(cost,0),margin=profit==null||sale<=0?null:(profit/sale*100),low=sku.track_stock&&num(sku.stock_qty)<=num(sku.low_stock_threshold,2);
      return `<tr data-sku="${h(sku.id)}" class="${low?'commerce-low':''}"><td><b>${h(m?.name||sku.model_id)}</b></td><td>${h(st?.name||sku.style_id)}</td><td>${h(sku.color||'—')}</td><td>${money(sale)}</td><td><input data-field="cost_price" type="number" min="0" step="1" value="${cost==null?'':h(cost)}" placeholder="未設定"></td><td class="commerce-profit ${profit!=null&&profit>=0?'positive':'negative'}">${profit==null?'—':money(profit)}</td><td class="commerce-margin">${margin==null?'—':margin.toFixed(1)+'%'}</td><td><input data-field="stock_qty" type="number" min="0" step="1" value="${h(sku.stock_qty??0)}"></td><td><input data-field="low_stock_threshold" type="number" min="0" step="1" value="${h(sku.low_stock_threshold??2)}"></td><td style="text-align:center"><input data-field="track_stock" type="checkbox" ${sku.track_stock?'checked':''}></td></tr>`;
    }).join('')||'<tr><td colspan="10" class="empty">沒有符合條件的 SKU；第一次使用請按「同步商品 SKU」。</td></tr>';
  }

  function renderAll(){renderSummary();renderPriceCards();renderFilters();renderSkus()}

  function updateSkuFromRow(row){
    const sku=(state.skus||[]).find(x=>String(x.id)===String(row.dataset.sku));if(!sku)return;
    row.querySelectorAll('[data-field]').forEach(el=>{const f=el.dataset.field;if(f==='track_stock')sku[f]=el.checked;else if(f==='cost_price')sku[f]=el.value===''?null:Math.max(0,num(el.value,0));else sku[f]=Math.max(0,Math.floor(num(el.value,0))) });
  }

  function onSkuInput(e){const row=e.target.closest('tr[data-sku]');if(!row)return;updateSkuFromRow(row);const sku=(state.skus||[]).find(x=>String(x.id)===String(row.dataset.sku)),st=styleOf(sku?.style_id),sale=num(st?.price,0),cost=sku?.cost_price,profit=cost==null?null:sale-num(cost,0),margin=profit==null||sale<=0?null:profit/sale*100;const p=row.querySelector('.commerce-profit'),m=row.querySelector('.commerce-margin');if(p){p.textContent=profit==null?'—':money(profit);p.className='commerce-profit '+(profit!=null&&profit>=0?'positive':'negative')}if(m)m.textContent=margin==null?'—':margin.toFixed(1)+'%';row.classList.toggle('commerce-low',!!sku?.track_stock&&num(sku.stock_qty)<=num(sku.low_stock_threshold,2));renderSummary()}

  async function saveAll(silent=false){
    document.querySelectorAll('#commerce-sku-body tr[data-sku]').forEach(updateSkuFromRow);
    try{await apiJson('/api/admin/save_commerce_data',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({style_defaults:state.style_defaults||{},skus:state.skus||[]})});if(!silent)alert('成本與庫存已儲存');await load(true)}catch(e){if(!silent)alert('儲存失敗：'+e.message);throw e}
  }

  async function syncSkus(){
    try{const j=await apiJson('/api/admin/commerce_sync_skus',{method:'POST'});loaded=false;await load(true);alert(j.msg||'SKU 同步完成')}catch(e){alert('SKU 同步失敗：'+e.message)}
  }

  async function saveStyle(styleId,applyExisting){
    const card=document.querySelector(`.commerce-price-card[data-style="${CSS.escape(String(styleId))}"]`);if(!card)return;
    const price=Math.round(num(card.querySelector('.commerce-style-price')?.value,0));const rawCost=card.querySelector('.commerce-style-cost')?.value??'';const cost=rawCost===''?null:Math.max(0,num(rawCost,0));const low=Math.max(0,Math.floor(num(card.querySelector('.commerce-style-low')?.value,2)));const track=!!card.querySelector('.commerce-style-track')?.checked;
    if(price<=0)return alert('售價必須大於 0');
    const d=styleDefault(String(styleId));d.cost_price=cost;d.low_stock_threshold=low;d.track_stock=track;
    if(applyExisting){for(const sku of state.skus||[]){if(String(sku.style_id)===String(styleId)){sku.cost_price=cost;sku.low_stock_threshold=low;sku.track_stock=track}}}
    try{
      await apiJson('/api/admin/commerce_set_style_price',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({style_id:styleId,price})});
      const st=styleOf(styleId);if(st)st.price=price;
      await saveAll(true);renderAll();alert(applyExisting?'售價與預設已儲存，並套用到現有 SKU':'售價與預設已儲存');
    }catch(e){alert('材質設定儲存失敗：'+e.message)}
  }

  window.BenfuwanCommerce={version:'1.0-pos-inventory',open:openView,load,saveAll,syncSkus,saveStyle,get state(){return state}};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ensureUi,{once:true});else ensureUi();
  console.info('[COMMERCE] admin POS / cost / inventory UI enabled');
})();
