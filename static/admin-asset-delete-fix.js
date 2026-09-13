/* 本福丸後台：修正貼紙分類刪除後卡住 / 刪不掉 */
(function(){
  'use strict';
  if(window.__benfuwanAssetDeleteFixInstalled)return;
  window.__benfuwanAssetDeleteFixInstalled=true;

  function bind(){
    const wrap=document.getElementById('bf-asset-cat-actions');
    if(!wrap)return false;
    const btn=[...wrap.querySelectorAll('button')].find(b=>b.textContent.includes('刪除分類'));
    if(!btn||btn.dataset.bfDeleteFixed==='1')return false;
    btn.dataset.bfDeleteFixed='1';
    btn.onclick=async()=>{
      const old=(typeof currentAsset!=='undefined'?currentAsset:'全部');
      if(!old||old==='全部'){alert('「全部」是系統分類，不能刪除');return}
      const list=(typeof assetsData!=='undefined'&&Array.isArray(assetsData.stickers))?assetsData.stickers:[];
      const count=list.filter(s=>(s.category||'全部')===old).length;
      if(!confirm(`刪除分類「${old}」？\n\n${count} 張貼紙不會被刪除，會移回「全部」。`))return;

      const oldHtml=btn.innerHTML;
      btn.disabled=true;
      btn.innerHTML='<i class="fa-solid fa-spinner fa-spin"></i> 刪除中';
      try{
        await apiJson('/api/admin/sticker_category',{
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({action:'delete',name:old})
        });
        currentAsset='全部';
        // 分類刪除屬低頻操作，這裡直接重新跟伺服器同步一次，避免前後端狀態不同步。
        await loadAssets(true);
        currentAsset='全部';
        renderAssetTabs();
        renderAssets();
        alert(`分類「${old}」已刪除`);
      }catch(e){
        console.error('[ASSET DELETE]',e);
        alert(e.message||'刪除分類失敗');
      }finally{
        btn.disabled=false;
        btn.innerHTML=oldHtml;
      }
    };
    console.info('[ADMIN] sticker category delete refresh fix enabled');
    return true;
  }

  function boot(){
    if(bind())return;
    const obs=new MutationObserver(()=>{if(bind())obs.disconnect()});
    obs.observe(document.body,{childList:true,subtree:true});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
