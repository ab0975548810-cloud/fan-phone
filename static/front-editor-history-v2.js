/* 本福丸前台編輯器：空白取消選取 + 明顯上一步/下一步 */
(function(){
  'use strict';
  if(window.__bfFrontEditorHistoryV2)return;
  window.__bfFrontEditorHistoryV2=true;

  const by=id=>document.getElementById(id);
  let hookedCanvas=null;

  function getCanvas(){
    try{return (typeof canvas!=='undefined'&&canvas)?canvas:null}catch(e){return null}
  }

  function addCss(){
    if(by('bf-front-history-v2-css'))return;
    const s=document.createElement('style');
    s.id='bf-front-history-v2-css';
    s.textContent=`
      #page-editor .editor-float.bf-history-float{gap:7px;align-items:center}
      #page-editor .editor-float.bf-history-float .bf-history-btn{width:auto!important;min-width:72px!important;height:40px!important;padding:0 11px!important;border-radius:999px!important;display:flex!important;align-items:center!important;justify-content:center!important;gap:6px!important;font-size:11px!important;font-weight:900!important;background:rgba(255,255,255,.98)!important}
      #page-editor .editor-float.bf-history-float .bf-history-btn i{font-size:13px;color:var(--pink)}
      #page-editor .editor-float.bf-history-float .bf-history-btn:disabled{opacity:.38;box-shadow:none;cursor:default}
      @media(max-width:350px){#page-editor .editor-float.bf-history-float .bf-history-btn{min-width:65px!important;padding:0 8px!important;font-size:10px!important}}
    `;
    document.head.appendChild(s);
  }

  function historyButtons(){
    const page=by('page-editor');
    if(!page)return {};
    const undo=[...page.querySelectorAll('button')].find(b=>/undoCanvas\s*\(/.test(b.getAttribute('onclick')||''));
    const redo=[...page.querySelectorAll('button')].find(b=>/redoCanvas\s*\(/.test(b.getAttribute('onclick')||''));
    return {undo,redo};
  }

  function ensureHistoryUi(){
    const {undo,redo}=historyButtons();
    if(undo){
      undo.parentElement?.classList.add('bf-history-float');
      undo.classList.add('bf-history-btn');
      undo.setAttribute('aria-label','上一步');undo.title='上一步（復原）';
      if(!undo.dataset.bfLabelled){undo.dataset.bfLabelled='1';undo.innerHTML='<i class="fa-solid fa-arrow-rotate-left"></i><span>上一步</span>'}
    }
    if(redo){
      redo.parentElement?.classList.add('bf-history-float');
      redo.classList.add('bf-history-btn');
      redo.setAttribute('aria-label','下一步');redo.title='下一步（重做）';
      if(!redo.dataset.bfLabelled){redo.dataset.bfLabelled='1';redo.innerHTML='<i class="fa-solid fa-arrow-rotate-right"></i><span>下一步</span>'}
    }
    updateHistoryUi();
  }

  function historyState(){
    try{
      if(typeof historyIndex!=='undefined'&&typeof historyStack!=='undefined'&&Array.isArray(historyStack)){
        return {known:true,undo:historyIndex>0,redo:historyIndex>=0&&historyIndex<historyStack.length-1};
      }
    }catch(e){}
    return {known:false,undo:true,redo:true};
  }

  function updateHistoryUi(){
    const {undo,redo}=historyButtons(),st=historyState();
    if(undo)undo.disabled=st.known&&!st.undo;
    if(redo)redo.disabled=st.known&&!st.redo;
  }

  function hideObjectToolbar(){
    by('object-bar')?.classList.remove('show');
  }

  function clearSelectionFromBlank(){
    const c=getCanvas();if(!c)return;
    try{if(c.getActiveObject())c.discardActiveObject();c.requestRenderAll?.()}catch(e){}
    hideObjectToolbar();
    try{if(typeof window.syncSelection==='function')window.syncSelection()}catch(e){}
  }

  function hookCanvas(){
    const c=getCanvas();
    if(!c||c===hookedCanvas)return;
    hookedCanvas=c;

    c.on('mouse:down',opt=>{
      const native=opt?.e;
      if(native?.touches?.length>1||c.isDrawingMode)return;
      if(opt?.target)return;
      clearSelectionFromBlank();
      setTimeout(updateHistoryUi,0);
    });
    c.on('selection:cleared',()=>{hideObjectToolbar();setTimeout(updateHistoryUi,0)});
    ['object:added','object:modified','object:removed'].forEach(evt=>c.on(evt,()=>setTimeout(updateHistoryUi,240)));
  }

  function wrapHistory(name){
    const original=window[name];
    if(typeof original!=='function'||original.__bfFrontHistoryWrapped)return;
    const wrapped=function(){
      const r=original.apply(this,arguments);
      setTimeout(updateHistoryUi,80);
      return r;
    };
    wrapped.__bfFrontHistoryWrapped=true;
    window[name]=wrapped;
  }

  function boot(){
    addCss();ensureHistoryUi();wrapHistory('undoCanvas');wrapHistory('redoCanvas');hookCanvas();
    document.addEventListener('click',ev=>{
      if(ev.target.closest('#page-editor'))setTimeout(()=>{ensureHistoryUi();hookCanvas();updateHistoryUi()},40);
    },true);
    setInterval(()=>{ensureHistoryUi();hookCanvas();updateHistoryUi()},800);
    console.info('[FRONT] blank deselect + labelled undo/redo enabled');
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
