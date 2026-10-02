(function(){
  'use strict';
  if(window.__benfuwanStewardV1Installed)return;
  window.__benfuwanStewardV1Installed=true;

  const REFRESH_MS=60000;
  const WARNING_USAGE_RATIO=.8;
  const LEVELS={normal:'正常',attention:'注意',error:'異常'};
  let panelOpen=false;
  let refreshing=false;
  let timer=null;
  let snapshot=null;

  const byId=id=>document.getElementById(id);
  const finite=value=>typeof value==='number'&&Number.isFinite(value);
  const escapeHtml=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const checkedTime=()=>new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date());

  async function getJson(url){
    const response=await fetch(url,{method:'GET',cache:'no-store',credentials:'same-origin',headers:{Accept:'application/json'}});
    let data=null;
    try{data=await response.json()}catch(_error){}
    if(!response.ok||!data)throw new Error(`READ_FAILED_${response.status}`);
    return data;
  }

  function healthState(result){
    if(result.status!=='fulfilled')return {
      website:{level:'error',value:'無法取得狀態'},
      supabase:{level:'error',value:'無法取得狀態'}
    };
    const data=result.value||{};
    return {
      website:data.status==='success'?{level:'normal',value:'正常'}:{level:'error',value:'異常'},
      supabase:data.persistence==='supabase'?{level:'normal',value:'正常'}:{level:'error',value:'無法使用'}
    };
  }

  function aiState(result){
    if(result.status!=='fulfilled')return {
      runpod:{level:'error',value:'無法取得狀態'},
      quota:{level:'error',value:'無法取得狀態',used:null,limit:60,active:null,activeLimit:2}
    };
    const data=result.value||{};
    const quota=data.ai_quota||{};
    const used=quota.global_used_24h;
    const active=quota.active_now;
    const limit=finite(quota.global_limit_24h)?quota.global_limit_24h:60;
    const activeLimit=finite(quota.active_limit)?quota.active_limit:2;
    const quotaAvailable=finite(used)&&finite(active);
    let quotaLevel='normal';
    if(!quotaAvailable||used>=limit)quotaLevel='error';
    else if(used>=limit*WARNING_USAGE_RATIO||active>=activeLimit)quotaLevel='attention';
    return {
      runpod:data.status==='transport_ok'?{level:'normal',value:'正常'}:{level:'error',value:'異常'},
      quota:{
        level:quotaLevel,
        value:!quotaAvailable?'無法取得狀態':used>=limit?'額度已用完':active>=activeLimit?'目前需等待':quotaLevel==='attention'?'接近額度上限':'正常',
        used:quotaAvailable?used:null,
        limit,
        active:quotaAvailable?active:null,
        activeLimit
      }
    };
  }

  function orderState(result){
    const data=result.status==='fulfilled'&&result.value?.status==='success'?result.value.orders:null;
    return data?.available?{level:'normal',value:'正常',...data}:{level:'error',value:'無法取得狀態'};
  }

  function printState(result){
    const data=result.status==='fulfilled'&&result.value?.status==='success'?result.value.print:null;
    return data?.available?{level:data.unknown||data.failed?'attention':'normal',value:'正常',...data,
      pending:(data.prepared||0)+(data.queued||0)+(data.printing||0)}:{level:'error',value:'無法取得狀態'};
  }

  function overallState(data){
    const critical=[data.website,data.supabase,data.runpod,data.quota,data.orders,data.print];
    if(critical.some(item=>item.level==='error'))return 'error';
    if(data.quota.level==='attention'||data.print.level==='attention')return 'attention';
    return 'normal';
  }

  function actionableItems(data){
    const issues=[];
    for(const [key,label] of [['website','網站'],['supabase','Supabase'],['runpod','RunPod AI']]){
      if(data[key].level==='error')issues.push({priority:0,kind:'system',anchor:'bf-steward-'+key,text:`${label} 狀態異常，請查看系統狀態`});
    }
    if(data.orders.level==='error')issues.push({priority:0,kind:'system',anchor:'bf-steward-orders',text:'今日訂單摘要無法取得'});
    if(data.print.level==='error')issues.push({priority:0,kind:'system',anchor:'bf-steward-print',text:'列印摘要無法取得'});
    if(data.quota.level==='error'&&!finite(data.quota.used))issues.push({priority:0,kind:'system',anchor:'bf-steward-quota',text:'AI quota 無法取得'});
    for(const item of data.issues||[]){
      if((item.kind==='print'||item.kind==='order')&&item.order_id)issues.push(item);
    }
    if(finite(data.quota.used)&&finite(data.quota.limit)&&data.quota.used>=data.quota.limit)
      issues.push({priority:4,kind:'ai',anchor:'bf-steward-quota',text:`雲端 AI 額度已滿：${data.quota.used} / ${data.quota.limit}`});
    else if(finite(data.quota.used)&&finite(data.quota.limit)&&data.quota.used>=data.quota.limit*WARNING_USAGE_RATIO)
      issues.push({priority:4,kind:'ai',anchor:'bf-steward-quota',text:`雲端 AI 使用量偏高：${data.quota.used} / ${data.quota.limit}`});
    if(finite(data.quota.active)&&data.quota.active>=data.quota.activeLimit)
      issues.push({priority:4,kind:'ai',anchor:'bf-steward-quota',text:`雲端 AI 任務已滿：${data.quota.active} / ${data.quota.activeLimit}，目前需等待`});
    return issues.sort((a,b)=>a.priority-b.priority||Number(b.time||0)-Number(a.time||0)).slice(0,5);
  }
  function oneLine(data,items){
    if(!items.length)return '目前沒有需要立即處理的項目。';
    const parts=[];
    if(data.print.unknown)parts.push(`${data.print.unknown} 筆列印狀態待確認`);
    if(data.print.failed)parts.push(`${data.print.failed} 筆列印失敗`);
    if(data.print.attention)parts.push(`${data.print.attention} 筆需要人工處理`);
    if(data.quota.level==='attention'||data.quota.level==='error')parts.push('AI 額度或服務需要注意');
    return `${overallState(data)==='error'?'偵測到系統異常':'目前系統正常'}，但有 ${parts.length?parts.join('、'):'需要注意的項目'}。`;
  }

  function installUi(){
    if(byId('bf-steward-launch'))return;
    const launch=document.createElement('button');
    launch.id='bf-steward-launch';launch.type='button';launch.className='bf-steward-launch';
    launch.setAttribute('aria-controls','bf-steward-panel');launch.setAttribute('aria-expanded','false');
    launch.textContent='🐱 本福丸';
    const panel=document.createElement('aside');
    panel.id='bf-steward-panel';panel.className='bf-steward-panel';panel.setAttribute('aria-hidden','true');panel.inert=true;
    panel.innerHTML=`
      <header class="bf-steward-head"><div><strong>本福丸</strong><span>系統管家・只讀模式</span></div><button id="bf-steward-close" type="button" aria-label="關閉本福丸管家">×</button></header>
      <div class="bf-steward-scroll">
        <section class="bf-steward-card bf-steward-attention"><h3>現在需要注意</h3><div id="bf-steward-issues">正在檢查…</div></section>
        <section id="bf-steward-overall" class="bf-steward-overall" data-level="normal"><div class="bf-steward-overall-line"><span id="bf-steward-overall-badge" class="bf-steward-status">正常</span><span id="bf-steward-overall-text">系統目前正常 ฅ^•ﻌ•^ฅ</span></div><small id="bf-steward-checked">尚未檢查</small></section>
        <section class="bf-steward-card"><h3>系統狀態</h3><div class="bf-steward-row" id="bf-steward-website"><span>網站</span><b>等待檢查</b></div><div class="bf-steward-row" id="bf-steward-supabase"><span>Supabase</span><b>等待檢查</b></div></section>
        <section class="bf-steward-card"><h3>RunPod AI</h3><div class="bf-steward-row" id="bf-steward-runpod"><span>RunPod</span><b>等待檢查</b></div><div class="bf-steward-metrics"><div><span>今日雲端 AI</span><b id="bf-steward-ai-usage">— / 60</b></div><div><span>目前 AI 任務</span><b id="bf-steward-ai-active">— / 2</b></div></div><div class="bf-steward-inline" id="bf-steward-quota"><span>AI quota</span><b>等待檢查</b></div></section>
        <section class="bf-steward-card"><h3>今日營運摘要</h3><div class="bf-steward-metrics three"><div><span>今日訂單</span><b id="bf-steward-order-total">—</b></div><div><span>營業額</span><b id="bf-steward-order-revenue">—</b></div><div><span>待處理</span><b id="bf-steward-order-pending">—</b></div><div><span>製作中</span><b id="bf-steward-order-making">—</b></div><div><span>待列印／列印中</span><b id="bf-steward-order-print-flow">—</b></div><div><span>今日訂單已完成</span><b id="bf-steward-order-completed">—</b></div></div><div class="bf-steward-inline" id="bf-steward-orders"><span>訂單資料</span><b>等待檢查</b></div></section>
        <section class="bf-steward-card"><h3>列印中心</h3><div class="bf-steward-metrics three"><div><span>需人工處理</span><b id="bf-steward-print-manual">—</b></div><div><span>PREPARED</span><b id="bf-steward-print-prepared">—</b></div><div><span>QUEUED</span><b id="bf-steward-print-queued">—</b></div><div><span>PRINTING</span><b id="bf-steward-print-printing">—</b></div><div><span>UNKNOWN</span><b id="bf-steward-print-unknown">—</b></div><div><span>FAILED</span><b id="bf-steward-print-failed">—</b></div></div><div class="bf-steward-inline" id="bf-steward-print"><span>列印資料</span><b>等待檢查</b></div></section>
      </div>
      <footer class="bf-steward-actions"><button id="bf-steward-refresh" type="button">重新檢查</button><button id="bf-steward-orders-link" type="button">查看訂單</button><button id="bf-steward-print-link" type="button">查看列印</button></footer>`;
    document.body.append(launch,panel);
    launch.addEventListener('click',()=>panelOpen?closePanel():openPanel());
    byId('bf-steward-close').addEventListener('click',closePanel);
    byId('bf-steward-refresh').addEventListener('click',()=>refresh(true));
    byId('bf-steward-orders-link').addEventListener('click',()=>openExistingView('orders'));
    byId('bf-steward-print-link').addEventListener('click',()=>openExistingView('print-center'));
    byId('bf-steward-issues').addEventListener('click',event=>{
      const item=event.target.closest('[data-steward-kind]');if(!item)return;
      const kind=item.dataset.stewardKind,orderId=item.dataset.orderId;
      if(kind==='print'&&orderId){closePanel();window.BenfuwanPrintCenter?.openOrder(orderId)}
      else if(kind==='order'&&orderId){closePanel();window.BenfuwanOrdersV3?.openOrder(orderId)}
      else byId(item.dataset.anchor)?.scrollIntoView({block:'center',behavior:'smooth'});
    });
    document.addEventListener('keydown',event=>{if(event.key==='Escape'&&panelOpen)closePanel()});
    document.addEventListener('visibilitychange',()=>{if(panelOpen&&!document.hidden)refresh(false)});
  }

  function setStatus(id,state){
    const row=byId(id);if(!row)return;
    row.dataset.level=state.level;
    const value=row.querySelector('b');if(value)value.textContent=state.value;
  }

  function setText(id,value){const element=byId(id);if(element)element.textContent=value;}

  function render(data){
    snapshot=data;
    setStatus('bf-steward-website',data.website);setStatus('bf-steward-supabase',data.supabase);
    setStatus('bf-steward-runpod',data.runpod);setStatus('bf-steward-quota',data.quota);
    setStatus('bf-steward-orders',data.orders);setStatus('bf-steward-print',data.print);
    setText('bf-steward-ai-usage',`${data.quota.used??'—'} / ${data.quota.limit}`);
    setText('bf-steward-ai-active',`${data.quota.active??'—'} / ${data.quota.activeLimit}`);
    setText('bf-steward-order-total',data.orders.total??'—');setText('bf-steward-order-revenue',finite(data.orders.revenue)?`NT$ ${data.orders.revenue.toLocaleString('zh-TW')}`:'—');
    setText('bf-steward-order-pending',data.orders.pending??'—');setText('bf-steward-order-making',data.orders.making??'—');setText('bf-steward-order-print-flow',data.orders.print_flow??'—');setText('bf-steward-order-completed',data.orders.completed??'—');
    for(const key of ['manual','prepared','queued','printing','unknown','failed'])setText('bf-steward-print-'+key,data.print[key]??'—');
    const items=actionableItems(data);
    byId('bf-steward-issues').innerHTML=items.length?items.map(item=>`<button type="button" class="bf-steward-issue" data-steward-kind="${escapeHtml(item.kind)}" data-order-id="${escapeHtml(item.order_id||'')}" data-anchor="${escapeHtml(item.anchor||'')}"><span>${escapeHtml(item.text)}</span><b>查看 ›</b></button>`).join(''):'<p class="bf-steward-no-issues">目前沒有需要立即處理的項目。</p>';
    const level=overallState(data);
    const overall=byId('bf-steward-overall');overall.dataset.level=level;
    setText('bf-steward-overall-badge',LEVELS[level]);
    setText('bf-steward-overall-text',oneLine(data,items));
    setText('bf-steward-checked',`最後檢查：${checkedTime()}`);
    window.BenfuwanStewardV1.lastSnapshot=data;
    window.BenfuwanStewardV1.lastOverall=level;
  }

  async function refresh(force=false){
    if(refreshing||!panelOpen||document.hidden)return;
    refreshing=true;
    const button=byId('bf-steward-refresh');if(button){button.disabled=true;button.textContent='檢查中…'}
    try{
      const [health,ai,summary]=await Promise.allSettled([
        getJson('/api/health?ts='+Date.now()),
        getJson('/api/admin/ai_remove_diagnose?ts='+Date.now()),
        getJson('/api/admin/steward/summary?ts='+Date.now())
      ]);
      render({...healthState(health),...aiState(ai),orders:orderState(summary),print:printState(summary),
        issues:summary.status==='fulfilled'&&Array.isArray(summary.value?.issues)?summary.value.issues:[]});
    }finally{
      refreshing=false;
      if(button){button.disabled=false;button.textContent='重新檢查'}
    }
  }

  function openPanel(){
    panelOpen=true;byId('bf-steward-panel').inert=false;byId('bf-steward-panel').classList.add('open');byId('bf-steward-panel').setAttribute('aria-hidden','false');byId('bf-steward-launch').setAttribute('aria-expanded','true');
    refresh(true);clearInterval(timer);timer=setInterval(()=>{if(panelOpen&&!document.hidden)refresh(false)},REFRESH_MS);
  }
  function closePanel(){
    panelOpen=false;byId('bf-steward-panel')?.classList.remove('open');byId('bf-steward-panel')?.setAttribute('aria-hidden','true');byId('bf-steward-panel').inert=true;byId('bf-steward-launch')?.setAttribute('aria-expanded','false');clearInterval(timer);timer=null;
  }
  function openExistingView(view){
    const button=document.querySelector(`.nav button[data-view="${view}"]`);
    if(button){closePanel();button.click()}
  }

  window.BenfuwanStewardV1={version:'2.0.0',open:openPanel,close:closePanel,refresh:()=>refresh(true),overallState,healthState,aiState,orderState,printState,actionableItems,lastSnapshot:snapshot,lastOverall:null};
  function boot(){installUi();console.info('[ADMIN] 本福丸系統管家 V2 enabled: read-only operations')}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
