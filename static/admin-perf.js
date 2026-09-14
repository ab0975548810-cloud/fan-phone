/* 本福丸後台效能補丁：減少首屏資料、DOM 與圖片解碼負擔 */
(function(){
  'use strict';
  if(window.__benfuwanAdminPerfInstalled)return;
  window.__benfuwanAdminPerfInstalled=true;

  if(typeof window.loadShop==='function'){
    const originalLoadShop=window.loadShop;
    window.loadShop=async function(force=false){
      const active=document.querySelector('.view.active')?.id||'';
      if(!force&&active==='view-orders')return;
      return originalLoadShop(force);
    };
  }

  // 訂單管理先讀最近 40 筆；避免舊版一次抓 200 筆並建立大量卡片。
  const originalFetch=window.fetch.bind(window);
  window.fetch=function(input,init){
    if(typeof input==='string'&&input.includes('/api/admin/get_orders')){
      input=input.replace(/limit=(50|200)/,'limit=40');
    }
    return originalFetch(input,init);
  };

  const style=document.createElement('style');
  style.textContent='.bf-order-day,.bf-order-card,.card{content-visibility:auto;contain-intrinsic-size:auto 260px}.bf-order-thumb{background:#f8f6f7}';
  document.head.appendChild(style);

  const optimize=()=>{
    document.querySelectorAll('img:not([data-bf-optimized])').forEach(img=>{
      if(img.closest('#bf-order-manager,#orders-body,#asset-grid,#template-grid')){
        img.dataset.bfOptimized='1';img.loading='lazy';img.decoding='async';img.fetchPriority='low';
      }
    });
  };
  optimize();
  const observer=new MutationObserver(()=>requestAnimationFrame(optimize));
  observer.observe(document.body,{childList:true,subtree:true});

  console.info('[PERF] admin lightweight mode enabled: 40 orders + lazy images');
})();
