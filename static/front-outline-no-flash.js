/* 本福丸前台：描邊粗細滑動時不顯示 Busy 閃屏；放手後靜默重算一次 */
(function(){
  'use strict';
  if(window.__benfuwanOutlineNoFlashInstalled)return;
  window.__benfuwanOutlineNoFlashInstalled=true;

  let dragging=false;
  let silentUntil=0;
  let suppressedBusy=false;

  function isSliderTarget(target){
    return !!(target && (target.id==='bf-os-width' || target.closest?.('#bf-os-width')));
  }
  function begin(e){
    if(!isSliderTarget(e.target))return;
    dragging=true;
    silentUntil=Date.now()+1200;
  }
  function end(e){
    if(!dragging && !isSliderTarget(e.target))return;
    dragging=false;
    // front-outline-slider-fix 會在放手後送出 input，描邊約 180ms 後重算。
    // 這段期間不要顯示白色 Busy overlay，避免使用者看到畫面閃一下。
    silentUntil=Date.now()+1200;
  }

  document.addEventListener('touchstart',begin,{capture:true,passive:true});
  document.addEventListener('touchend',end,{capture:true,passive:true});
  document.addEventListener('touchcancel',end,{capture:true,passive:true});
  document.addEventListener('pointerdown',begin,true);
  document.addEventListener('pointerup',end,true);
  document.addEventListener('pointercancel',end,true);
  document.addEventListener('mousedown',begin,true);
  document.addEventListener('mouseup',end,true);

  function patchBusy(){
    const original=window.setBusy;
    if(typeof original!=='function' || original.__bfOutlineNoFlashWrapped)return false;
    const wrapped=function(show,message){
      const msg=String(message||'');
      const shouldSuppress=show && /描邊/.test(msg) && (dragging || Date.now()<silentUntil);
      if(shouldSuppress){
        suppressedBusy=true;
        return;
      }
      if(!show && suppressedBusy){
        suppressedBusy=false;
        return;
      }
      return original.apply(this,arguments);
    };
    wrapped.__bfOutlineNoFlashWrapped=true;
    wrapped.__bfOutlineNoFlashOriginal=original;
    window.setBusy=wrapped;
    return true;
  }

  if(!patchBusy()){
    let tries=0;
    const timer=setInterval(()=>{
      tries++;
      if(patchBusy()||tries>80)clearInterval(timer);
    },50);
  }
  console.info('[FRONT] outline slider no-flash enabled');
})();
