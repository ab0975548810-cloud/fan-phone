/* 本福丸後台效能補丁：減少首屏資料、DOM、圖片解碼與高頻輪詢負擔 */
(function(){
  'use strict';
  if(window.__benfuwanAdminPerfInstalled)return;
  window.__benfuwanAdminPerfInstalled=true;

  // 後台幾個補丁原本每 250~500ms 輪詢，長時間開著會讓低階電腦/iPad 卡頓。
  // 僅在 admin 頁把過密 interval 拉到 1000ms；功能仍會正常更新。
  const nativeSetInterval=window.setInterval.bind(window);
  window.setInterval=function(fn,ms,...args){
    const delay=(Number(ms)>0&&Number(ms)<800)?1000:ms;
    return nativeSetInterval(fn,delay,...args);
  };

  if(typeof window.loadShop==='function'){
    const originalLoadShop=window.loadShop;
    window.loadShop=async function(force=false){
      const active=document.querySelector('.view.active')?.id||'';
      if(!force&&active==='view-orders')return;
      return originalLoadShop(force);
    };
  }

  // 訂單管理先讀最近 40 筆；搜尋舊單時再由使用者切條件/重新整理即可。
  const originalFetch=window.fetch.bind(window);
  window.fetch=function(input,init){
    if(typeof input==='string'&&input.includes('/api/admin/get_orders')){
      input=input.replace(/limit=(50|200)/,'limit=40');
    }
    return originalFetch(input,init);
  };

  const style=document.createElement('style');
  style.textContent='.bf-order-day,.bf-order-card,.card{content-visibility:auto;contain-intrinsic-size:auto 260px}.bf-order-thumb{background:#f8f6f7}#bf-order-list{contain:layout style paint}';
  document.head.appendChild(style);

  let raf=0;
  const optimize=()=>{
    raf=0;
    document.querySelectorAll('img:not([data-bf-optimized])').forEach(img=>{
      if(img.closest('#bf-order-manager,#orders-body,#asset-grid,#template-grid')){
        img.dataset.bfOptimized='1';img.loading='lazy';img.decoding='async';img.fetchPriority='low';
      }
    });
  };
  const schedule=()=>{if(!raf)raf=requestAnimationFrame(optimize)};
  schedule();
  const observer=new MutationObserver(schedule);
  observer.observe(document.body,{childList:true,subtree:true});

  console.info('[PERF] admin lightweight mode enabled: slower polling + 40 orders + lazy images');
})();
