(function(){
  'use strict';
  if(window.__benfuwanStewardV1Installed)return;
  window.__benfuwanStewardV1Installed=true;

  const REFRESH_MS=60000;
  const WARNING_GLOBAL_USAGE=45;
  const ACTIVE_PRINT_STATES=new Set(['PREPARED','SENDING','QUEUED','STARTING','PRINTING','CANCELING']);
  const LEVELS={normal:'正常',attention:'注意',error:'異常'};
  let panelOpen=false;
  let refreshing=false;
  let timer=null;
  let snapshot=null;

  const byId=id=>document.getElementById(id);
  const finite=value=>typeof value==='number'&&Number.isFinite(value);
  const taipeiDay=value=>{
    const date=new Date(Number(value||0)*1000);
    if(Number.isNaN(date.getTime()))return '';
    const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(date);
    const get=type=>parts.find(part=>part.type===type)?.value||'';
    return `${get('year')}-${get('month')}-${get('day')}`;
  };
  const todayTaipei=()=>{
    const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
    const get=type=>parts.find(part=>part.type===type)?.value||'';
    return `${get('year')}-${get('month')}-${get('day')}`;
  };
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
    if(!quotaAvailable)quotaLevel='error';
    else if(used>=WARNING_GLOBAL_USAGE||active>=activeLimit)quotaLevel='attention';
    return {
      runpod:data.status==='transport_ok'?{level:'normal',value:'正常'}:{level:'error',value:'異常'},
      quota:{
        level:quotaLevel,
        value:quotaAvailable?'正常':'無法取得狀態',
        used:quotaAvailable?used:null,
        limit,
        active:quotaAvailable?active:null,
        activeLimit
      }
    };
  }

  function orderState(result){
    if(result.status!=='fulfilled'||result.value?.status!=='success')return {level:'error',value:'無法取得狀態',total:null,pending:null,completed:null};
    const today=todayTaipei();
    const rows=Array.isArray(result.value?.data)?result.value.data:[];
    const current=rows.filter(row=>taipeiDay(row.time)===today);
    return {
      level:'normal',value:'正常',total:current.length,
      pending:current.filter(row=>(row.status||'待處理')==='待處理').length,
      completed:current.filter(row=>row.status==='已完成').length
    };
  }

  function printState(result){
    if(result.status!=='fulfilled'||result.value?.status!=='success')return {level:'error',value:'無法取得狀態',pending:null,failed:null,unknown:null,completed:null};
    const rows=Array.isArray(result.value?.rows)?result.value.rows:[];
    const states=rows.map(row=>String(row?.job?.state||'')).filter(Boolean);
    const failed=states.filter(state=>state==='FAILED').length;
    const unknown=states.filter(state=>state==='UNKNOWN').length;
    return {
      level:failed>0||unknown>0?'attention':'normal',value:'正常',
      pending:states.filter(state=>ACTIVE_PRINT_STATES.has(state)).length,
      failed,unknown,completed:states.filter(state=>state==='COMPLETED').length
    };
  }

  function overallState(data){
    const critical=[data.website,data.supabase,data.runpod,data.quota,data.orders,data.print];
    if(critical.some(item=>item.level==='error'))return 'error';
    if(data.quota.level==='attention'||data.print.level==='attention')return 'attention';
    return 'normal';
  }

  function installUi(){
    if(byId('bf-steward-launch'))return;
    const launch=document.createElement('button');
    launch.id='bf-steward-launch';launch.type='button';launch.className='bf-steward-launch';
    launch.setAttribute('aria-controls','bf-steward-panel');launch.setAttribute('aria-expanded','false');
    launch.textContent='🐱 本福丸';
    const panel=document.createElement('aside');
    panel.id='bf-steward-panel';panel.className='bf-steward-panel';panel.setAttribute('aria-hidden','true');
    panel.innerHTML=`
      <header class="bf-steward-head"><div><strong>本福丸</strong><span>系統管家・只讀模式</span></div><button id="bf-steward-close" type="button" aria-label="關閉本福丸管家">×</button></header>
      <div class="bf-steward-scroll">
        <section id="bf-steward-overall" class="bf-steward-overall" data-level="normal"><div class="bf-steward-overall-line"><span id="bf-steward-overall-badge" class="bf-steward-status">正常</span><span id="bf-steward-overall-text">系統目前正常 ฅ^•ﻌ•^ฅ</span></div><small id="bf-steward-checked">尚未檢查</small></section>
        <section class="bf-steward-card"><h3>系統狀態</h3><div class="bf-steward-row" id="bf-steward-website"><span>網站</span><b>等待檢查</b></div><div class="bf-steward-row" id="bf-steward-supabase"><span>Supabase</span><b>等待檢查</b></div></section>
        <section class="bf-steward-card"><h3>RunPod AI</h3><div class="bf-steward-row" id="bf-steward-runpod"><span>RunPod</span><b>等待檢查</b></div><div class="bf-steward-metrics"><div><span>今日雲端 AI</span><b id="bf-steward-ai-usage">— / 60</b></div><div><span>目前 AI 任務</span><b id="bf-steward-ai-active">— / 2</b></div></div><div class="bf-steward-inline" id="bf-steward-quota"><span>AI quota</span><b>等待檢查</b></div></section>
        <section class="bf-steward-card"><h3>今日訂單</h3><div class="bf-steward-metrics three"><div><span>今日訂單</span><b id="bf-steward-order-total">—</b></div><div><span>待處理</span><b id="bf-steward-order-pending">—</b></div><div><span>已完成</span><b id="bf-steward-order-completed">—</b></div></div><div class="bf-steward-inline" id="bf-steward-orders"><span>訂單資料</span><b>等待檢查</b></div></section>
        <section class="bf-steward-card"><h3>列印中心</h3><div class="bf-steward-metrics three"><div><span>待處理</span><b id="bf-steward-print-pending">—</b></div><div><span>失敗</span><b id="bf-steward-print-failed">—</b></div><div><span>待確認</span><b id="bf-steward-print-unknown">—</b></div></div><div class="bf-steward-inline" id="bf-steward-print"><span>列印資料</span><b>等待檢查</b></div><small id="bf-steward-print-completed">完成：—</small></section>
      </div>
      <footer class="bf-steward-actions"><button id="bf-steward-refresh" type="button">重新檢查</button><button id="bf-steward-orders-link" type="button">查看訂單</button><button id="bf-steward-print-link" type="button">查看列印</button></footer>`;
    document.body.append(launch,panel);
    launch.addEventListener('click',()=>panelOpen?closePanel():openPanel());
    byId('bf-steward-close').addEventListener('click',closePanel);
    byId('bf-steward-refresh').addEventListener('click',()=>refresh(true));
    byId('bf-steward-orders-link').addEventListener('click',()=>openExistingView('orders'));
    byId('bf-steward-print-link').addEventListener('click',()=>openExistingView('print-center'));
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
    setText('bf-steward-order-total',data.orders.total??'—');setText('bf-steward-order-pending',data.orders.pending??'—');setText('bf-steward-order-completed',data.orders.completed??'—');
    setText('bf-steward-print-pending',data.print.pending??'—');setText('bf-steward-print-failed',data.print.failed??'—');setText('bf-steward-print-unknown',data.print.unknown??'—');setText('bf-steward-print-completed',`完成：${data.print.completed??'—'}`);
    const level=overallState(data);
    const overall=byId('bf-steward-overall');overall.dataset.level=level;
    setText('bf-steward-overall-badge',LEVELS[level]);
    setText('bf-steward-overall-text',level==='normal'?'系統目前正常 ฅ^•ﻌ•^ฅ':(level==='attention'?'有幾個項目需要注意，我已經幫你標出來。':'偵測到系統異常，請先查看紅色項目。'));
    setText('bf-steward-checked',`最後檢查：${checkedTime()}`);
    window.BenfuwanStewardV1.lastSnapshot=data;
    window.BenfuwanStewardV1.lastOverall=level;
  }

  async function refresh(force=false){
    if(refreshing||(!force&&(!panelOpen||document.hidden)))return;
    refreshing=true;
    const button=byId('bf-steward-refresh');if(button){button.disabled=true;button.textContent='檢查中…'}
    try{
      const [health,ai,orders,print]=await Promise.allSettled([
        getJson('/api/health?ts='+Date.now()),
        getJson('/api/admin/ai_remove_diagnose?ts='+Date.now()),
        getJson('/api/admin/get_orders?limit=200&ts='+Date.now()),
        getJson('/api/admin/print/jobs?ts='+Date.now())
      ]);
      render({...healthState(health),...aiState(ai),orders:orderState(orders),print:printState(print)});
    }finally{
      refreshing=false;
      if(button){button.disabled=false;button.textContent='重新檢查'}
    }
  }

  function openPanel(){
    panelOpen=true;byId('bf-steward-panel').classList.add('open');byId('bf-steward-panel').setAttribute('aria-hidden','false');byId('bf-steward-launch').setAttribute('aria-expanded','true');
    refresh(true);clearInterval(timer);timer=setInterval(()=>{if(panelOpen&&!document.hidden)refresh(false)},REFRESH_MS);
  }
  function closePanel(){
    panelOpen=false;byId('bf-steward-panel')?.classList.remove('open');byId('bf-steward-panel')?.setAttribute('aria-hidden','true');byId('bf-steward-launch')?.setAttribute('aria-expanded','false');clearInterval(timer);timer=null;
  }
  function openExistingView(view){
    const button=document.querySelector(`.nav button[data-view="${view}"]`);
    if(button){closePanel();button.click()}
  }

  window.BenfuwanStewardV1={version:'1.0.0',open:openPanel,close:closePanel,refresh:()=>refresh(true),overallState,healthState,aiState,orderState,printState,lastSnapshot:snapshot,lastOverall:null};
  function boot(){installUi();console.info('[ADMIN] 本福丸系統管家 V1 enabled: read-only dashboard')}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
