/* 本福丸前台：照片選取時提供通用去背；去背後同位置改成描邊。 */
(function(){
  'use strict';
  if(window.__benfuwanAiContextInstalled)return;
  window.__benfuwanAiContextInstalled=true;

  function activeObject(){
    try{return (typeof canvas!=='undefined'&&canvas)?canvas.getActiveObject():null}catch(e){return null}
  }
  function isPhoto(o){
    return !!(o&&o.type==='image'&&(o.role==='photo'||o.role==='slot-photo'));
  }
  function refreshAiContextButton(){
    const b=document.getElementById('bf-ai-outline-btn');
    if(!b)return;
    const o=activeObject();
    if(!isPhoto(o)){
      b.classList.remove('show');
      return;
    }
    b.classList.add('show');
    if(o.aiBackgroundRemoved){
      b.title='描邊';
      b.innerHTML='<i class="fa-solid fa-border-style"></i>描邊';
      b.onclick=()=>window.openAiOutlineSheet?.();
    }else{
      b.title='AI 摳圖工具';
      b.innerHTML='<i class="fa-solid fa-wand-magic-sparkles"></i>AI 摳圖';
      b.onclick=async()=>{
        if(typeof window.removeBackgroundForActive!=='function'){
          if(typeof toast==='function')toast('通用去背功能尚未載入');
          return;
        }
        try{
          await (window.openAiRemoveTools||window.removeBackgroundForActive)();
        }finally{
          setTimeout(refreshAiContextButton,80);
        }
      };
    }
  }

  function wrapSelection(){
    const original=window.syncSelection;
    if(typeof original==='function'&&!original.__bfAiContextWrapped){
      const wrapped=function(){
        const r=original.apply(this,arguments);
        setTimeout(refreshAiContextButton,0);
        return r;
      };
      wrapped.__bfAiContextWrapped=true;
      window.syncSelection=wrapped;
    }
  }

  function boot(){
    wrapSelection();
    setTimeout(refreshAiContextButton,0);
    console.info('[FRONT] contextual button enabled: universal remove -> outline');
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
