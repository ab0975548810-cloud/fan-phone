/* 本福丸後台效能補丁：日常開啟先只載訂單，其他資料點進去才載 */
(function(){
  'use strict';

  function install(){
    if(window.__benfuwanAdminPerfInstalled)return;
    window.__benfuwanAdminPerfInstalled=true;

    // 原本後台 DOMContentLoaded 會同時抓 shop_data + 訂單。
    // 訂單頁其實不需要品牌/型號/材質資料，所以先略過；點到對應頁面再載。
    if(typeof window.loadShop==='function'){
      const originalLoadShop=window.loadShop;
      window.loadShop=async function(force=false){
        const active=document.querySelector('.view.active')?.id||'';
        if(!force&&active==='view-orders')return;
        return originalLoadShop(force);
      };
    }

    // 正式後台日常只讀最近 20 筆，避免一次建立 50 張預覽圖請求。
    // 「快速訂單」頁仍保留 50 筆，真的要大量檢查時再使用。
    const originalFetch=window.fetch.bind(window);
    window.fetch=function(input,init){
      if(typeof input==='string'&&input.includes('/api/admin/get_orders?limit=50')){
        input=input.replace('limit=50','limit=20');
      }
      return originalFetch(input,init);
    };

    // 圖片交給瀏覽器延遲解碼，降低表格首次繪製時的卡頓。
    const observer=new MutationObserver(()=>{
      document.querySelectorAll('#orders-body img.order-thumb:not([data-bf-optimized])').forEach(img=>{
        img.dataset.bfOptimized='1';
        img.loading='lazy';
        img.decoding='async';
        img.fetchPriority='low';
      });
    });
    const body=document.getElementById('orders-body');
    if(body)observer.observe(body,{childList:true,subtree:true});

    console.info('[PERF] admin lazy-load patch enabled');
  }

  install();
})();
