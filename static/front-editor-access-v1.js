/* 本福丸前台編輯器操作修正：物件工具列佔實際版面，不再浮蓋畫布；主工具列仍可直接使用。 */
(function(){
  'use strict';
  if(window.__bfFrontEditorAccessV1)return;window.__bfFrontEditorAccessV1=true;

  function addCss(){
    if(document.getElementById('bf-front-editor-access-css'))return;
    const s=document.createElement('style');s.id='bf-front-editor-access-css';s.textContent=`
      /* 物件快捷列是 page-editor 的正常 flex 子元素：顯示時縮小 workspace，不覆蓋畫布。 */
      #page-editor>.object-bar.bf-docked-object-bar{
        display:none!important;position:relative!important;left:auto!important;right:auto!important;top:auto!important;bottom:auto!important;
        flex:0 0 56px!important;width:calc(100% - 16px)!important;height:56px!important;margin:0 8px 6px!important;
        z-index:74!important;border-radius:16px!important;border:1px solid var(--line)!important;
        background:rgba(255,255,255,.99)!important;box-shadow:0 5px 16px rgba(0,0,0,.08)!important;padding:4px 6px!important;
        grid-template-columns:none!important;gap:2px!important;overflow-x:auto!important;overflow-y:hidden!important;
        -webkit-overflow-scrolling:touch;scrollbar-width:none;white-space:nowrap;pointer-events:auto!important;
      }
      #page-editor>.object-bar.bf-docked-object-bar::-webkit-scrollbar{display:none}
      #page-editor>.object-bar.bf-docked-object-bar.show{display:flex!important;align-items:center!important}
      #page-editor>.object-bar.bf-docked-object-bar button{flex:1 0 48px!important;min-width:48px!important;height:46px!important;padding:3px 2px!important;font-size:9px!important;line-height:1.1!important}
      #page-editor>.object-bar.bf-docked-object-bar button i{margin-bottom:3px!important}
      #page-editor>.workspace{min-height:0!important;flex:1 1 auto!important}
      #page-editor>.toolbar{position:relative!important;z-index:76!important;visibility:visible!important;pointer-events:auto!important;flex:0 0 78px!important}
    `;document.head.appendChild(s);
  }

  function fitCanvasToWorkspace(){
    try{
      const workspace=document.querySelector('#page-editor>.workspace'),shell=document.getElementById('canvas-shell');
      if(!workspace||!shell||typeof canvas==='undefined'||!canvas)return;
      const logicalW=Number(canvas.lowerCanvasEl?.width||canvas.width||0),logicalH=Number(canvas.lowerCanvasEl?.height||canvas.height||0);
      if(!(logicalW>0&&logicalH>0))return;
      const maxW=Math.max(120,workspace.clientWidth-20),maxH=Math.max(220,workspace.clientHeight-16);
      const ratio=Math.min(1,maxW/logicalW,maxH/logicalH);
      const displayW=Math.max(1,Math.floor(logicalW*ratio)),displayH=Math.max(1,Math.floor(logicalH*ratio));
      shell.style.width=displayW+'px';shell.style.height=displayH+'px';
      if(typeof canvas.setDimensions==='function')canvas.setDimensions({width:displayW,height:displayH},{cssOnly:true});
      canvas.calcOffset?.();canvas.requestRenderAll?.();
    }catch(e){console.warn('[FRONT UX] canvas fit warning',e)}
  }

  function clearSelectionForMainTool(){
    try{
      if(typeof canvas==='undefined'||!canvas||!canvas.getActiveObject?.())return;
      canvas.discardActiveObject();
      document.getElementById('object-bar')?.classList.remove('show');
      canvas.requestRenderAll?.();
      requestAnimationFrame(fitCanvasToWorkspace);
    }catch(e){console.warn('[FRONT UX] selection release warning',e)}
  }

  function dockInFlow(){
    const page=document.getElementById('page-editor'),bar=document.getElementById('object-bar'),toolbar=page?.querySelector(':scope>.toolbar');
    if(!page||!bar||!toolbar)return;
    if(bar.parentElement!==page||bar.nextElementSibling!==toolbar)page.insertBefore(bar,toolbar);
    bar.classList.add('bf-docked-object-bar');
    if(!bar.dataset.bfFlowObserver){
      bar.dataset.bfFlowObserver='1';
      new MutationObserver(()=>requestAnimationFrame(fitCanvasToWorkspace)).observe(bar,{attributes:true,attributeFilter:['class']});
    }
  }

  function bind(){
    addCss();dockInFlow();
    const toolbar=document.querySelector('#page-editor>.toolbar');if(!toolbar)return;
    if(!toolbar.dataset.bfDirectAccess){
      toolbar.dataset.bfDirectAccess='1';
      // Capture 階段先取消目前物件選取，但不阻止原本按鈕事件。
      toolbar.addEventListener('click',clearSelectionForMainTool,true);
    }
    requestAnimationFrame(fitCanvasToWorkspace);
  }

  function boot(){
    bind();
    const obs=new MutationObserver(bind);obs.observe(document.documentElement,{childList:true,subtree:true});setTimeout(()=>{try{obs.disconnect()}catch(e){}},30000);
    window.addEventListener('resize',()=>requestAnimationFrame(fitCanvasToWorkspace),{passive:true});
    window.addEventListener('orientationchange',()=>setTimeout(fitCanvasToWorkspace,80),{passive:true});
    window.BenfuwanEditorAccess={version:'2.0-flow-toolbar',fitCanvas:fitCanvasToWorkspace};
    console.info('[FRONT] selected-object toolbar uses real layout space; canvas auto-fits workspace');
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
