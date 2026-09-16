/* 本福丸前台編輯器操作修正：選取物件時保留主工具列可直接使用，不必先點底圖取消選取。 */
(function(){
  'use strict';
  if(window.__bfFrontEditorAccessV1)return;window.__bfFrontEditorAccessV1=true;

  function addCss(){
    if(document.getElementById('bf-front-editor-access-css'))return;
    const s=document.createElement('style');s.id='bf-front-editor-access-css';s.textContent=`
      /* 物件快捷列浮在主工具列上方，兩條工具列同時可用。 */
      #page-editor>.object-bar.bf-docked-object-bar{
        display:none!important;position:absolute!important;left:8px!important;right:8px!important;
        bottom:78px!important;height:64px!important;z-index:74!important;border-radius:16px!important;
        border:1px solid var(--line)!important;background:rgba(255,255,255,.985)!important;
        box-shadow:0 7px 20px rgba(0,0,0,.10)!important;padding:5px 6px!important;
        grid-template-columns:none!important;gap:2px!important;overflow-x:auto!important;overflow-y:hidden!important;
        -webkit-overflow-scrolling:touch;scrollbar-width:none;white-space:nowrap;
      }
      #page-editor>.object-bar.bf-docked-object-bar::-webkit-scrollbar{display:none}
      #page-editor>.object-bar.bf-docked-object-bar.show{display:flex!important;align-items:stretch!important}
      #page-editor>.object-bar.bf-docked-object-bar button{flex:1 0 52px!important;min-width:52px!important;height:52px!important;padding:4px 2px!important;font-size:9px!important;line-height:1.1!important}
      #page-editor>.toolbar{position:relative!important;z-index:76!important;visibility:visible!important;pointer-events:auto!important}
    `;document.head.appendChild(s);
  }

  function clearSelectionForMainTool(){
    try{
      if(typeof canvas==='undefined'||!canvas||!canvas.getActiveObject?.())return;
      canvas.discardActiveObject();
      document.getElementById('object-bar')?.classList.remove('show');
      canvas.requestRenderAll?.();
    }catch(e){console.warn('[FRONT UX] selection release warning',e)}
  }

  function bind(){
    addCss();const toolbar=document.querySelector('#page-editor>.toolbar');if(!toolbar||toolbar.dataset.bfDirectAccess)return;
    toolbar.dataset.bfDirectAccess='1';
    // Capture 階段先取消目前物件選取，但不阻止原本按鈕事件；因此照片仍在畫布，功能按鈕會直接打開。
    toolbar.addEventListener('click',clearSelectionForMainTool,true);
  }

  function boot(){bind();const obs=new MutationObserver(bind);obs.observe(document.documentElement,{childList:true,subtree:true});setTimeout(()=>{try{obs.disconnect()}catch(e){}},30000);console.info('[FRONT] direct main-toolbar access while object selected enabled')}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
