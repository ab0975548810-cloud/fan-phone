/* Existing POS, Phase 2: series workspace, receiving, reports and expenses. */
(function(){
  'use strict';
  if(window.__bfAdminCommerceV1)return;window.__bfAdminCommerceV1=true;
  let state={revision:0,style_defaults:{},skus:[]}, loaded=false, series='', tab='overview', dirty=false;
  let expenses=[], reportData=null, reportEpoch=0, busy=false, editingExpense=null;
  const h=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money=v=>v==null?'成本未知':'NT$ '+Number(v).toLocaleString('zh-TW',{maximumFractionDigits:2});
  const styles=()=>shopData.styles||[], models=()=>shopData.models||[];
  const styleOf=id=>styles().find(x=>String(x.id)===String(id));
  const modelOf=id=>models().find(x=>String(x.id)===String(id));
  const el=id=>document.getElementById(id);
  const labels={out:'缺貨',low:'低於警戒值',threshold:'剛好警戒值',normal:'正常',untracked:'未追蹤'};
  const categories=['房租','廣告','水電','耗材','運費','平台費','其他'];
  const status=s=>!s.track_stock?'untracked':s.stock_qty===0?'out':s.stock_qty<s.low_stock_threshold?'low':s.stock_qty===s.low_stock_threshold?'threshold':'normal';
  const needs=s=>['out','low','threshold'].includes(status(s));
  const active=s=>s.active&&!!styleOf(s.style_id)&&!!modelOf(s.model_id)&&styleOf(s.style_id)?.status!==false&&modelOf(s.model_id)?.status!==false;
  const today=()=>{const p=new Intl.DateTimeFormat('en-US',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());return ['year','month','day'].map(k=>p.find(x=>x.type===k).value).join('-')};
  function message(text,error=false){const box=el('pos-message');if(box){box.textContent=text;box.className='pos-message'+(error?' error':'');box.hidden=!text}}
  async function api(url,body){const r=await fetch(url,{cache:'no-store',...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});let j;try{j=await r.json()}catch{throw Error('回應中斷，請重試原操作')};if(!r.ok||j.status!=='success'){const e=Error(j.code==='STALE_DATA'?'資料已被其他分頁或裝置更新，請重新載入後再修改。':(j.msg||'操作失敗'));e.status=r.status;e.code=j.code;throw e}return j}
  const pendingSlot='bf-pos2-pending';
  // A single durable receipt shared by all tabs on this origin. Web Locks makes
  // check + save/clear atomic across tabs; unsupported storage fails closed.
  function pending(){
    const raw=localStorage.getItem(pendingSlot);if(!raw)return null;
    const p=JSON.parse(raw);
    if(!p||!['/api/admin/purchase_received','/api/admin/expense'].includes(p.url)||typeof p.body?.idempotency_key!=='string')throw Error('未確認操作資料異常，請保留網站資料並核對紀錄。');
    return p;
  }
  function receiptLock(fn){if(!navigator.locks)throw Error('瀏覽器不支援安全保存操作，請更新瀏覽器後再試。');return navigator.locks.request(pendingSlot,fn)}
  function pendingUi(){try{const p=pending();el('pos-pending').hidden=!p;if(p)el('pos-pending-text').textContent='有一筆尚未確認的'+p.label+'。請先重送查明結果，再登記下一筆。'}catch(e){message('無法讀取未確認操作：'+e.message,true)}}
  async function clearReceipt(saved){await receiptLock(()=>{if(pending()?.body.idempotency_key===saved.body.idempotency_key)localStorage.removeItem(pendingSlot)});pendingUi()}
  const terminalCodes=new Set(['IDEMPOTENCY_REQUIRED','IDEMPOTENCY_CONFLICT','BAD_DATA','BAD_ITEMS','BAD_NOTE','BAD_SKU','BAD_QUANTITY','BAD_ACTION','BAD_DATE','BAD_AMOUNT','BAD_EXPENSE','EXPENSE_NOT_FOUND','STALE_EXPENSE']);
  async function execute(saved){
    if(busy)return;busy=true;const buttons=[...document.querySelectorAll('#view-commerce .pos-write')].map(b=>[b,b.disabled]);buttons.forEach(([b])=>b.disabled=true);
    try{const result=await api(saved.url,saved.body);await clearReceipt(saved);message(result.msg||'已完成');el('pos-dialog').close();await load(true);return result}
    catch(e){if(e.status>=400&&e.status<500&&terminalCodes.has(e.code))await clearReceipt(saved);message(e.message,true);throw e}
    finally{busy=false;buttons.forEach(([b,disabled])=>b.disabled=disabled)}
  }
  async function command(url,body,label){
    let saved;
    try{saved=await receiptLock(()=>{
      if(pending())throw Error('請先按「重送原操作」確認上一筆結果，避免重複入帳。');
      const receipt={url,body:{...body,idempotency_key:crypto.randomUUID()},label};
      localStorage.setItem(pendingSlot,JSON.stringify(receipt));return receipt;
    })}catch(e){pendingUi();message('未送出：'+e.message,true);return}
    pendingUi();return execute(saved);
  }
  window.addEventListener('storage',e=>{if((e.key===pendingSlot||e.key===null)&&el('pos-pending'))pendingUi()});
  window.addEventListener('focus',()=>{if(el('pos-pending'))pendingUi()});
  function ensureUi(){
    const nav=document.querySelector('.nav'),content=document.querySelector('.content');if(!nav||!content||el('view-commerce'))return;
    const button=document.createElement('button');button.dataset.view='commerce';button.innerHTML='<i class="fa-solid fa-cash-register"></i><span>商品・營運 POS</span>';button.addEventListener('click',open);
    const orderNav=nav.querySelector('[data-view="orders"]');if(orderNav)orderNav.after(button);else nav.prepend(button);
    const section=document.createElement('section');section.id='view-commerce';section.className='view';section.innerHTML=`
      <div class="pos-heading"><div><p class="pos-eyebrow">本福丸 · 店務工作台</p><h2>商品與營運</h2><p>按系列管理商品，讓補貨與對帳更清楚。</p></div><button class="btn alt" id="commerce-reload">重新整理</button></div>
      <div id="pos-message" class="pos-message" role="status" aria-live="polite" hidden></div>
      <div id="pos-pending" class="pos-notice" hidden><span id="pos-pending-text"></span><button class="btn pos-write" id="pos-retry">重送原操作</button></div>
      <nav class="pos-tabs" aria-label="POS 工作區"><button data-tab="overview" class="selected">總覽</button><button data-tab="stock">系列商品</button><button data-tab="restock">補貨中心</button><button data-tab="reports">營運報表</button><button data-tab="expenses">支出管理</button></nav>
      <section id="pos-overview-panel">
        <div class="pos-row"><div><h3>老闆營運總覽</h3><p class="pos-muted">先看營運，再安排今天的店務。</p></div><label>總覽期間<select id="pos-overview-period"><option value="today">今日</option><option value="week">本週</option><option value="month" selected>本月</option><option value="year">今年</option></select></label></div>
        <div class="pos-overview-actions"><button class="btn alt" id="pos-overview-restock">前往補貨中心</button><button class="btn alt" id="pos-overview-report">查看完整報表</button><button class="btn" id="pos-overview-expense">新增支出</button></div>
        <p id="pos-overview-status" role="status" aria-live="polite"></p>
        <div id="pos-overview-content" hidden>
          <p id="pos-overview-range" class="pos-muted"></p><p id="pos-overview-cost-note" class="pos-notice" hidden></p>
          <div id="pos-overview-kpis" class="pos-metrics"></div><p id="pos-overview-empty" class="pos-muted" hidden>這段期間尚無有效訂單；營運支出仍依登記日期列計。</p>
          <div class="pos-overview-columns"><section class="pos-overview-box"><h3>補貨摘要</h3><p class="pos-muted">目前庫存 · 缺貨優先，其次低於／剛好警戒</p><div id="pos-overview-restock-summary"></div><ul id="pos-overview-restock-list" class="pos-overview-list"></ul></section><section class="pos-overview-box"><h3>熱銷系列</h3><p class="pos-muted">所選期間營業額前 5 名</p><ol id="pos-overview-series" class="pos-overview-list"></ol></section></div>
          <p id="pos-overview-recognition" class="pos-muted"></p>
        </div>
      </section>
      <div id="pos-stock-panel" hidden>
        <div id="commerce-summary" class="commerce-summary"></div>
        <div class="pos-row"><div><h3 id="pos-stock-title">依系列管理</h3><p class="pos-muted">選擇系列，再查看型號與顏色。售價為系列統一售價。</p></div><div class="pos-row-actions"><button id="commerce-sync" class="btn alt pos-write">同步商品</button><button id="pos-list" class="btn">產生補貨清單</button></div></div>
        <div class="pos-series" id="pos-series" aria-label="商品系列"></div>
        <div class="pos-series-detail"><div><h3 id="pos-series-name"></h3><span class="pos-muted" id="pos-series-caption"></span></div><form id="pos-price-form" class="pos-price-form"><label>系列售價<input id="pos-series-price" type="number" min="1" step="1" required></label><button class="btn alt pos-write" type="submit">更新售價</button></form></div>
        <div class="pos-filter"><label class="pos-search">搜尋型號或顏色<input id="commerce-search" type="search" placeholder="例如 iPhone 16、透明"></label><label>庫存狀態<select id="pos-status"><option value="">全部狀態</option>${Object.entries(labels).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label><label class="pos-check"><input type="checkbox" id="commerce-low-only">只看需要補貨</label></div>
        <div id="pos-skus" class="pos-skus"></div>
        <div class="pos-savebar"><span id="pos-save-hint">到貨請使用「到貨登記」，系統會保留庫存異動。</span><button id="commerce-save" class="btn pos-write">儲存商品設定</button></div>
      </div>
      <section id="pos-report-panel" hidden>
        <div class="pos-row"><div><h3>營運表現</h3><p class="pos-muted">Asia/Taipei · 每週由週一開始</p></div></div>
        <form id="pos-report-form" class="pos-filter"><label>統計區間<select id="pos-period"><option value="today">今日</option><option value="week">本週</option><option value="month">本月</option><option value="year">今年</option><option value="custom">自訂日期</option></select></label><label class="pos-custom" hidden>開始日期<input id="pos-start" type="date"></label><label class="pos-custom" hidden>結束日期<input id="pos-end" type="date"></label><button class="btn" type="submit">查詢</button></form>
        <p id="pos-report-range" class="pos-muted"></p><div id="pos-report-warning" class="pos-notice" hidden></div><div id="pos-metrics" class="pos-metrics"></div>
        <h3>系列銷售表現</h3><div id="pos-series-report" class="pos-report-series"></div>
        <details id="pos-unknown"><summary>成本未知訂單</summary><div id="pos-unknown-list"></div></details><p class="pos-muted" id="pos-recognition"></p>
      </section>
      <section id="pos-expense-panel" hidden>
        <div class="pos-row"><div><h3>營運支出</h3><p class="pos-muted">進貨成本由售出商品成本計算，請勿在此重複列為營運支出。</p></div></div>
        <form id="pos-expense-form" class="pos-expense-form"><label>日期<input id="pos-expense-date" type="date" required></label><label>分類<select id="pos-expense-category">${categories.map(c=>`<option>${c}</option>`).join('')}</select></label><label>金額（NT$）<input id="pos-expense-amount" type="number" min="0.01" max="10000000" step="0.01" required></label><label class="pos-note">備註<input id="pos-expense-note" maxlength="500" placeholder="例如：九月店面租金"></label><button id="pos-expense-save" type="submit" class="btn pos-write">新增支出</button><button id="pos-expense-cancel" type="button" class="btn alt" hidden>取消編輯</button></form>
        <div class="pos-filter"><label>篩選月份<input id="pos-expense-month" type="month"></label><label class="pos-check"><input id="pos-show-voided" type="checkbox">包含作廢紀錄</label></div><p id="pos-expense-total" class="pos-muted"></p><div id="pos-expenses" class="pos-expenses"></div>
      </section>
      <dialog id="pos-dialog"><form id="pos-dialog-form"><div class="pos-row"><h3 id="pos-dialog-title"></h3><button id="pos-close" type="button" class="btn alt" aria-label="關閉">關閉</button></div><div id="pos-dialog-body"></div><div class="pos-dialog-actions"><button id="pos-dialog-submit" class="btn pos-write" type="submit">確認</button></div></form></dialog>`;
    content.prepend(section);
    section.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>switchTab(b.dataset.tab)));
    el('commerce-reload').onclick=()=>{if(!dirty||confirm('有尚未儲存的商品設定，確定重新整理？')){dirty=false;load(true)}};
    el('commerce-sync').onclick=async()=>{if(dirty){message('請先儲存商品設定。',true);return}try{await api('/api/admin/commerce_sync_skus',{});await load(true);message('商品已同步')}catch(e){message(e.message,true)}};
    el('pos-overview-period').onchange=loadOverview;
    el('pos-overview-restock').onclick=()=>switchTab('restock');
    el('pos-overview-report').onclick=()=>{el('pos-period').value=el('pos-overview-period').value;el('pos-period').onchange();switchTab('reports')};
    el('pos-overview-expense').onclick=()=>{switchTab('expenses');resetExpense();el('pos-expense-form').scrollIntoView({block:'center'});el('pos-expense-date').focus()};
    el('commerce-save').onclick=saveAll;
    el('commerce-search').oninput=renderSkus;el('pos-status').onchange=renderSkus;el('commerce-low-only').onchange=renderSkus;
    el('pos-series').onclick=e=>{const b=e.target.closest('[data-series]');if(b){series=b.dataset.series;renderStock()}};
    el('pos-skus').oninput=onSkuInput;
    el('pos-skus').onclick=e=>{const b=e.target.closest('[data-receive],[data-adjust]');if(b)stockDialog(b.dataset.receive||b.dataset.adjust,!!b.dataset.adjust)};
    el('pos-price-form').onsubmit=async e=>{e.preventDefault();try{const j=await api('/api/admin/commerce_set_style_price',{style_id:series,price:Number(el('pos-series-price').value),expected_version:window.getShopVersion?.()||''});window.setShopVersion?.(j.version);styleOf(series).price=j.price;message('系列售價已更新');renderSkus()}catch(e){message(e.message,true)}};
    el('pos-list').onclick=exportList;el('pos-close').onclick=()=>el('pos-dialog').close();
    el('pos-period').onchange=()=>document.querySelectorAll('.pos-custom').forEach(x=>x.hidden=el('pos-period').value!=='custom');
    el('pos-start').value=el('pos-end').value=today();
    el('pos-report-form').onsubmit=e=>{e.preventDefault();loadReport()};
    el('pos-expense-date').value=today();el('pos-expense-month').value=today().slice(0,7);
    el('pos-expense-form').onsubmit=saveExpense;el('pos-expense-cancel').onclick=resetExpense;
    el('pos-expense-month').onchange=renderExpenses;el('pos-show-voided').onchange=renderExpenses;
    el('pos-expenses').onclick=e=>{const b=e.target.closest('[data-edit-expense],[data-void-expense]');if(b)expenseAction(b.dataset.editExpense||b.dataset.voidExpense,!!b.dataset.voidExpense)};
    el('pos-retry').onclick=()=>{try{const p=pending();if(p)execute(p).catch(()=>{})}catch(e){message(e.message,true)}};pendingUi();
  }
  async function open(){ensureUi();document.querySelectorAll('.nav button').forEach(b=>b.classList.toggle('active',b.dataset.view==='commerce'));document.querySelectorAll('.view').forEach(v=>v.classList.toggle('active',v.id==='view-commerce'));try{currentView='commerce'}catch{}await load(false)}
  async function load(force=false){
    ensureUi();try{if(typeof loadShop==='function')await loadShop(force);if(!loaded||force){const j=await api('/api/admin/commerce_data');state=j.data;loaded=true;dirty=false}
      if(!series||!styles().some(s=>String(s.id)===series))series=String(styles().find(s=>s.status!==false)?.id||'');renderStock();
      if(tab==='overview')await loadOverview();if(tab==='reports')await loadReport();if(tab==='expenses')await loadExpenses();
    }catch(e){message('資料載入失敗：'+e.message,true)}
  }
  function switchTab(value){tab=value;el('pos-overview-panel').hidden=tab!=='overview';document.querySelectorAll('.pos-tabs button').forEach(b=>b.classList.toggle('selected',b.dataset.tab===tab));el('pos-stock-panel').hidden=!['stock','restock'].includes(tab);el('pos-report-panel').hidden=tab!=='reports';el('pos-expense-panel').hidden=tab!=='expenses';if(tab==='restock'){el('commerce-low-only').checked=true;el('pos-status').value=''}else if(tab==='stock')el('commerce-low-only').checked=false;if(tab==='overview')loadOverview();else if(tab==='reports')loadReport();else if(tab==='expenses')loadExpenses();else renderStock()}
  let overviewEpoch=0;
  async function loadOverview(){
    const epoch=++overviewEpoch,period=el('pos-overview-period').value;
    el('pos-overview-panel').setAttribute('aria-busy','true');
    el('pos-overview-status').textContent='正在載入總覽…';
    el('pos-overview-content').hidden=true;
    try{
      const [financial,inventory]=await Promise.all([api('/api/admin/commerce_report?period='+encodeURIComponent(period)),api('/api/admin/replenishment')]);
      if(epoch!==overviewEpoch)return;
      renderOverview(financial.data,inventory.data);
      el('pos-overview-status').textContent='';el('pos-overview-content').hidden=false;
    }catch(e){if(epoch===overviewEpoch)el('pos-overview-status').textContent='總覽載入失敗：'+e.message+'。請按重新整理再試。'}
    finally{if(epoch===overviewEpoch)el('pos-overview-panel').removeAttribute('aria-busy')}
  }
  function renderOverview(report,stock){
    const s=report.summary,complete=s.cost_complete&&s.unknown_cost_orders===0;
    const cost=v=>complete&&v!=null?money(v):'成本資料不足';
    el('pos-overview-range').textContent=report.range.start+' ～ '+report.range.end+'（台灣時間）';
    el('pos-overview-cost-note').hidden=complete;
    el('pos-overview-cost-note').textContent=`${s.unknown_cost_orders} 筆成本未知 · 已知商品成本小計 ${money(s.known_cost)}。完整商品成本、毛利與淨利暫不計算。`;
    const values=[['revenue','營業額',money(s.revenue)],['orders','訂單數',s.orders+' 筆'],['units','銷售件數',s.units+' 件'],['average_order_value','平均客單價',money(s.average_order_value)],['product_cost','商品成本',cost(s.product_cost)],['gross_profit','毛利',cost(s.gross_profit)],['expenses','營運支出',money(s.expenses)],['net_profit','淨利',cost(s.net_profit)]];
    el('pos-overview-kpis').innerHTML=values.map(([key,label,value])=>`<article class="pos-metric" data-kpi="${key}"><small>${label}</small><b>${h(value)}</b></article>`).join('');
    el('pos-overview-empty').hidden=s.orders!==0;
    el('pos-overview-recognition').textContent=report.recognition;
    const needed=stock.counts.out+stock.counts.low+stock.counts.threshold;
    el('pos-overview-restock-summary').innerHTML=`<span>需要補貨 <b data-restock="needed">${needed}</b> 個規格</span><span>建議補貨 <b data-restock="suggested">${stock.total_suggested}</b> 件</span><span>未設定目標 <b data-restock="missing">${stock.missing_targets}</b> 個</span>`;
    const priority={out:0,low:1,threshold:2};
    const urgent=stock.groups.flatMap(g=>g.items.map(x=>({...x,series_name:g.series_name}))).sort((a,b)=>priority[a.status]-priority[b.status]||a.stock_qty-b.stock_qty||a.sku_id.localeCompare(b.sku_id)).slice(0,5);
    el('pos-overview-restock-list').innerHTML=urgent.map(x=>`<li><div><strong>${h(x.series_name)}</strong><p>${h(x.model_name)} · ${h(x.color||'無色別')}</p><span class="pos-badge ${h(x.status)}">${h(x.status_label)}</span></div><div>現有 ${x.stock_qty} 件<br><b>建議 ${x.suggested_quantity==null?'先設定目標':x.suggested_quantity+' 件'}</b></div></li>`).join('')||'<li class="pos-empty">目前沒有需要補貨的規格。</li>';
    const ranked=[...report.series].sort((a,b)=>b.revenue-a.revenue||a.series_id.localeCompare(b.series_id)).slice(0,5),max=Math.max(0,...ranked.map(x=>x.revenue));
    el('pos-overview-series').innerHTML=ranked.map((x,i)=>`<li><div class="pos-rank-heading"><strong>${i+1}. ${h(x.series_name)}</strong><b>${money(x.revenue)}</b></div><p>${x.orders} 筆訂單 · ${x.units} 件 · ${x.cost_complete&&x.gross_profit!=null?'毛利 '+money(x.gross_profit):'成本資料不足'}</p><div class="pos-rank-track" aria-hidden="true"><span style="width:${max?Math.max(0,Math.min(100,x.revenue/max*100)):0}%"></span></div></li>`).join('')||'<li class="pos-empty">這段期間尚無系列銷售。</li>';
  }
  function renderStock(){
    const counts={out:0,low:0,threshold:0,normal:0};state.skus.filter(active).forEach(s=>{if(status(s) in counts)counts[status(s)]++});
    el('commerce-summary').innerHTML=Object.entries(counts).map(([k,n])=>`<button class="commerce-kpi ${k}" data-stock-status="${k}"><small>${labels[k]}</small><b>${n}</b><span>個規格</span></button>`).join('');
    el('commerce-summary').querySelectorAll('[data-stock-status]').forEach(b=>b.onclick=()=>{el('pos-status').value=b.dataset.stockStatus;el('commerce-low-only').checked=false;renderSkus()});
    el('pos-stock-title').textContent=tab==='restock'?'今天需要補哪些貨？':'依系列管理';
    el('pos-series').innerHTML=styles().filter(s=>s.status!==false).map(s=>{const list=state.skus.filter(x=>x.style_id===String(s.id)&&active(x)),count=list.filter(needs).length;return `<button data-series="${h(s.id)}" class="${String(s.id)===series?'selected':''}" aria-pressed="${String(s.id)===series}"><strong>${h(s.name)}</strong><span>${list.length} 個規格${count?' · '+count+' 個待補貨':''}</span></button>`}).join('');
    const st=styleOf(series);el('pos-series-name').textContent=st?.name||'尚無系列';el('pos-series-price').value=st?.price||'';el('pos-price-form').hidden=!st;el('pos-series-caption').textContent='售價共用；成本與庫存依型號／顏色個別管理';renderSkus();
  }
  function renderSkus(){
    const q=el('commerce-search').value.trim().toLowerCase(),filter=el('pos-status').value,only=el('commerce-low-only').checked;
    const list=state.skus.filter(s=>s.style_id===series&&active(s)&&(!only||needs(s))&&(!filter||status(s)===filter)&&`${modelOf(s.model_id)?.name||s.model_id} ${s.color}`.toLowerCase().includes(q));
    el('pos-skus').innerHTML=list.map(s=>{const k=status(s),target=s.target_stock,suggest=tab==='stock'&&k==='normal'?'暫不需補貨':target==null?'先設定目標':Math.max(0,target-s.stock_qty)+' 件';return `<article class="pos-sku" data-sku="${h(s.id)}"><div class="pos-sku-heading"><div><h4>${h(modelOf(s.model_id)?.name||s.model_id)}</h4><p>${h(s.color||'無色別')}</p></div><span class="pos-badge ${k}">${labels[k]}</span></div><div class="pos-stock-number"><div><small>目前庫存</small><b>${s.stock_qty}<span> 件</span></b></div><div><small>建議補貨</small><strong>${s.track_stock?h(suggest):'未追蹤'}</strong></div></div><div class="pos-fields"><label>成本<input data-field="cost_price" aria-label="成本" type="number" step="0.01" min="0" max="10000000" value="${s.cost_price??''}" placeholder="成本未知"></label><label>警戒庫存<input data-field="low_stock_threshold" aria-label="警戒庫存" type="number" min="0" max="10000000" step="1" value="${s.low_stock_threshold}"></label><label>目標庫存<input data-field="target_stock" aria-label="目標庫存" type="number" min="0" max="10000000" step="1" value="${target??''}" placeholder="未設定"></label></div><div class="pos-sku-footer"><label class="pos-check"><input data-field="track_stock" type="checkbox" ${s.track_stock?'checked':''}>追蹤庫存</label><div><button class="pos-link" data-adjust="${h(s.id)}">盤點校正</button><button class="btn alt pos-write" data-receive="${h(s.id)}" ${!s.track_stock?'disabled':''}>到貨登記</button></div></div></article>`}).join('')||'<div class="pos-empty">沒有符合條件的規格。可切換系列／篩選，首次使用請按「同步商品」。</div>';
    el('pos-save-hint').textContent=dirty?'有尚未儲存的商品設定':'到貨請使用「到貨登記」，系統會保留庫存異動。';
  }
  function onSkuInput(e){const f=e.target.dataset.field,s=state.skus.find(x=>x.id===e.target.closest('[data-sku]')?.dataset.sku);if(!f||!s)return;s[f]=f==='track_stock'?e.target.checked:e.target.value===''&&['cost_price','target_stock'].includes(f)?null:Number(e.target.value);dirty=true;el('pos-save-hint').textContent='有尚未儲存的商品設定';}
  async function saveAll(){try{const fields=[...el('pos-skus').querySelectorAll('input')];if(fields.some(x=>!x.reportValidity()))return;await api('/api/admin/save_commerce_data',{revision:state.revision,style_defaults:state.style_defaults,skus:state.skus});await load(true);message('商品設定已儲存')}catch(e){message(e.message,true)}}
  function stockDialog(id,adjust=false){
    if(dirty){message('請先儲存商品設定，再登記到貨或盤點。',true);return}const s=state.skus.find(x=>x.id===id);if(!s)return;
    el('pos-dialog-title').textContent=adjust?'盤點校正':'到貨登記';el('pos-dialog-body').innerHTML=`<p>${h(styleOf(s.style_id)?.name)} · ${h(modelOf(s.model_id)?.name)} · ${h(s.color)}</p><p class="pos-muted">${adjust?'請輸入實際盤點數量；差額會記錄為盤點異動。':'輸入這次實際收到的數量，系統會加到最新庫存。'}</p><label>${adjust?'實際庫存':'本次到貨件數'}<input id="pos-receive-qty" type="number" min="${adjust?0:1}" max="10000000" step="1" required value="${adjust?s.stock_qty:Math.max(1,(s.target_stock??s.stock_qty+1)-s.stock_qty)}"></label>${adjust?'':'<label>備註<input id="pos-receive-note" maxlength="500" placeholder="例如：供應商／到貨單號"></label>'}`;
    el('pos-dialog-submit').textContent=adjust?'確認盤點校正':'確認到貨入庫';el('pos-dialog-submit').hidden=false;
    el('pos-dialog-form').onsubmit=async e=>{e.preventDefault();const quantity=Number(el('pos-receive-qty').value);try{if(adjust){const copy=structuredClone(s);copy.stock_qty=quantity;await api('/api/admin/save_commerce_data',{revision:state.revision,style_defaults:state.style_defaults,skus:[copy]});el('pos-dialog').close();await load(true);message('盤點校正已記錄')}else await command('/api/admin/purchase_received',{items:[{sku_id:id,quantity}],note:el('pos-receive-note').value},'到貨')}catch(e){message(e.message,true)}};el('pos-dialog').showModal();
  }
  async function exportList(){
    if(dirty){message('請先儲存目標與警戒庫存，再產生清單。',true);return}
    try{const j=await api('/api/admin/replenishment'),data=j.data;el('pos-dialog-title').textContent='補貨清單';el('pos-dialog-body').innerHTML=`<p>${data.groups.length} 個系列 · 建議 ${data.total_suggested} 件${data.missing_targets?' · '+data.missing_targets+' 個規格尚未設定目標':''}</p><p class="pos-muted">包含所有系列的缺貨、低於／剛好警戒品項。產生清單不會改動庫存。</p><textarea id="pos-export-text" readonly aria-label="補貨清單">${h(data.text)}</textarea><p id="pos-copy-status" role="status"></p>`;el('pos-dialog-submit').hidden=false;el('pos-dialog-submit').textContent='複製清單';el('pos-dialog-form').onsubmit=async e=>{e.preventDefault();try{await navigator.clipboard.writeText(data.text);el('pos-copy-status').textContent='已複製'}catch{el('pos-export-text').select();el('pos-copy-status').textContent='請長按或按 Ctrl+C 複製已選取文字'}};el('pos-dialog').showModal()}catch(e){message(e.message,true)}
  }
  async function loadReport(){const epoch=++reportEpoch;el('pos-metrics').setAttribute('aria-busy','true');try{const qs=new URLSearchParams({period:el('pos-period').value,start:el('pos-start').value,end:el('pos-end').value});const j=await api('/api/admin/commerce_report?'+qs);if(epoch!==reportEpoch)return;reportData=j.data;renderReport()}catch(e){if(epoch===reportEpoch){el('pos-metrics').innerHTML='';el('pos-series-report').innerHTML='';el('pos-report-warning').hidden=true;el('pos-unknown').hidden=true;el('pos-report-range').textContent='';message(e.message,true)}}finally{if(epoch===reportEpoch)el('pos-metrics').removeAttribute('aria-busy')}}
  function renderReport(){const r=reportData,s=r.summary;el('pos-report-range').textContent=r.range.start+' ～ '+r.range.end+'（台灣時間）';el('pos-report-warning').hidden=!s.unknown_cost_orders;el('pos-report-warning').textContent=`有 ${s.unknown_cost_orders} 筆訂單成本未知。已知商品成本 ${money(s.known_cost)}；完整成本、毛利與淨利暫不計算。`;
    const items=[['營業額',money(s.revenue)],['訂單數',s.orders+' 筆'],['銷售件數',s.units+' 件'],['商品成本',money(s.product_cost)],['毛利',money(s.gross_profit)],['毛利率',s.gross_margin==null?'—':s.gross_margin.toFixed(2)+'%'],['平均客單價',money(s.average_order_value)],['營運支出',money(s.expenses)],['淨利',money(s.net_profit)]];
    el('pos-metrics').innerHTML=items.map(([label,value])=>`<article class="pos-metric"><small>${label}</small><b>${value}</b></article>`).join('');
    el('pos-series-report').innerHTML=r.series.map(x=>`<article class="pos-report-card"><h4>${h(x.series_name)}</h4><p class="pos-muted">${x.orders} 筆訂單 · ${x.units} 件</p><dl><div><dt>營業額</dt><dd>${money(x.revenue)}</dd></div><div><dt>商品成本</dt><dd>${money(x.product_cost)}</dd></div><div><dt>毛利</dt><dd>${money(x.gross_profit)}</dd></div><div><dt>毛利率</dt><dd>${x.gross_margin==null?'—':x.gross_margin.toFixed(2)+'%'}</dd></div></dl>${x.unknown_cost_orders?`<p class="pos-muted">${x.unknown_cost_orders} 筆成本未知；已知成本 ${money(x.known_cost)}</p>`:''}</article>`).join('')||'<div class="pos-empty">這段期間還沒有有效訂單。</div>';
    el('pos-unknown').hidden=!r.unknown_cost_orders.length;el('pos-unknown-list').innerHTML=r.unknown_cost_orders.map(x=>`<p>${h(x.order_id)} · ${h(x.series_name)} · 成本未知</p>`).join('');el('pos-recognition').textContent=r.recognition;
  }
  async function loadExpenses(){try{expenses=(await api('/api/admin/expenses')).data;renderExpenses()}catch(e){message(e.message,true)}}
  function renderExpenses(){const month=el('pos-expense-month').value,show=el('pos-show-voided').checked,list=expenses.filter(x=>(!month||x.date.startsWith(month))&&(show||!x.voided));el('pos-expense-total').textContent=`${list.filter(x=>!x.voided).length} 筆有效支出 · 合計 ${money(list.filter(x=>!x.voided).reduce((n,x)=>n+x.amount,0))}`;el('pos-expenses').innerHTML=list.map(x=>`<article class="pos-expense ${x.voided?'voided':''}"><div><span class="pos-badge">${h(x.category)}</span><strong>${money(x.amount)}</strong><small>${h(x.date)}${x.voided?' · 已作廢':''}</small><p>${h(x.note||'無備註')}</p></div>${x.voided?'':`<div><button class="pos-link" data-edit-expense="${h(x.id)}">編輯</button><button class="pos-link danger" data-void-expense="${h(x.id)}">作廢</button></div>`}</article>`).join('')||'<div class="pos-empty">這個月份尚無支出紀錄。</div>'}
  function resetExpense(){editingExpense=null;el('pos-expense-form').reset();el('pos-expense-date').value=today();el('pos-expense-save').textContent='新增支出';el('pos-expense-cancel').hidden=true}
  async function expenseAction(id,voided){const row=expenses.find(x=>x.id===id);if(!row)return;if(voided){if(!confirm('作廢這筆支出？原始紀錄仍會保留。'))return;try{await command('/api/admin/expense',{action:'void',expense_id:id,expected_version:row.version},'支出作廢')}catch{}return}editingExpense=row;el('pos-expense-date').value=row.date;el('pos-expense-category').value=row.category;el('pos-expense-amount').value=row.amount;el('pos-expense-note').value=row.note;el('pos-expense-save').textContent='儲存修改';el('pos-expense-cancel').hidden=false;el('pos-expense-form').scrollIntoView({behavior:'smooth',block:'center'})}
  async function saveExpense(e){e.preventDefault();try{const result=await command('/api/admin/expense',{action:'save',date:el('pos-expense-date').value,category:el('pos-expense-category').value,amount:Number(el('pos-expense-amount').value),note:el('pos-expense-note').value,...(editingExpense?{expense_id:editingExpense.id,expected_version:editingExpense.version}:{})},'支出');if(result)resetExpense()}catch{}}
  window.BenfuwanCommerce={version:'2.0-series-operations',open,load,saveAll,get state(){return state}};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ensureUi,{once:true});else ensureUi();
})();
