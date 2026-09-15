/* 本福丸後台模板編輯器：上一步/下一步歷史 + 空白取消選取 */
(function(){
  'use strict';
  if(window.__bfAdminTemplateHistoryV1)return;
  window.__bfAdminTemplateHistoryV1=true;

  const by=id=>document.getElementById(id);
  const CUSTOM_PROPS=['isSlot','isTplBg','slotId','publicSrc','stickerId','originalName','aiBackgroundRemoved','aiOutlineSource','aiOutlineStrength','aiOutlineColor','role','slotMeta','materialType'];
  let currentCanvas=null,history=[],historyIndex=-1,restoring=false,recordTimer=null,initTimer=null,initializing=false;

  function canvas(){return window.visualCanvas||null}
  function modalOpen(){return by('template-modal')?.classList.contains('show')}

  function addCss(){
    if(by('bf-admin-template-history-css'))return;
    const s=document.createElement('style');s.id='bf-admin-template-history-css';
    s.textContent=`
      #bf-tpl-historybar{display:flex;align-items:center;gap:8px;margin:0 0 10px;padding:9px 10px;border:1px solid #f0dfe5;border-radius:14px;background:#fff9fb;box-shadow:0 4px 14px rgba(180,80,115,.05)}
      #bf-tpl-historybar .bf-history-action{border:1px solid #efcad6;background:#fff;color:#d95580;border-radius:999px;padding:8px 13px;font-size:11px;font-weight:900;display:inline-flex;align-items:center;gap:6px;cursor:pointer}
      #bf-tpl-historybar .bf-history-action:disabled{opacity:.38;cursor:default;background:#f8f4f5;color:#a99da2}
      #bf-tpl-history-state{margin-left:auto;font-size:10px;color:#94878d;font-weight:800;white-space:nowrap}
      @media(max-width:560px){#bf-tpl-historybar{gap:6px;padding:8px}#bf-tpl-historybar .bf-history-action{flex:1;justify-content:center;padding:8px 9px}#bf-tpl-history-state{display:none}}
    `;
    document.head.appendChild(s);
  }

  function ensureUi(){
    addCss();
    if(by('bf-tpl-historybar'))return;
    const editor=by('template-modal')?.querySelector('.editor');if(!editor)return;
    const bar=document.createElement('div');bar.id='bf-tpl-historybar';
    bar.innerHTML=`<button type="button" class="bf-history-action" id="bf-tpl-undo"><i class="fa-solid fa-arrow-rotate-left"></i><span>上一步</span></button><button type="button" class="bf-history-action" id="bf-tpl-redo"><i class="fa-solid fa-arrow-rotate-right"></i><span>下一步</span></button><span id="bf-tpl-history-state">尚無編輯紀錄</span>`;
    editor.parentElement?.insertBefore(bar,editor);
    by('bf-tpl-undo').onclick=undo;
    by('bf-tpl-redo').onclick=redo;
    updateUi();
  }

  function snapshot(c=currentCanvas){
    if(!c)return '';
    const json=c.toDatalessJSON(CUSTOM_PROPS),live=c.getObjects();
    (json.objects||[]).forEach((o,i)=>{
      const src=live[i]?.publicSrc;
      if(src){o.src=src;delete o.crossOrigin}
    });
    return JSON.stringify(json);
  }

  function updateUi(){
    ensureUi();
    const u=by('bf-tpl-undo'),r=by('bf-tpl-redo'),st=by('bf-tpl-history-state');
    if(u)u.disabled=restoring||historyIndex<=0;
    if(r)r.disabled=restoring||historyIndex<0||historyIndex>=history.length-1;
    if(st)st.textContent=historyIndex<0?'尚無編輯紀錄':`步驟 ${historyIndex+1} / ${history.length}`;
  }

  function resetHistory(){
    if(!currentCanvas)return;
    clearTimeout(recordTimer);
    const s=snapshot();history=s?[s]:[];historyIndex=history.length?0:-1;
    updateUi();
  }

  function settleInitialization(){
    if(!initializing)return;
    clearTimeout(initTimer);
    initTimer=setTimeout(()=>{initializing=false;resetHistory()},380);
  }

  function beginInitialization(){
    initializing=true;
    clearTimeout(initTimer);
    settleInitialization();
  }

  function recordNow(){
    if(!currentCanvas||restoring||initializing)return;
    const s=snapshot();if(!s)return;
    if(historyIndex>=0&&history[historyIndex]===s){updateUi();return}
    history=history.slice(0,historyIndex+1);
    history.push(s);
    if(history.length>40)history.shift();
    historyIndex=history.length-1;
    updateUi();
  }

  function scheduleRecord(delay=180){
    if(restoring)return;
    if(initializing){settleInitialization();return}
    clearTimeout(recordTimer);recordTimer=setTimeout(recordNow,delay);
  }

  function styleRestoredObject(o){
    if(!o)return;
    if(o.isTplBg){o.set({selectable:false,evented:false});return}
    try{o.set({transparentCorners:false,cornerColor:'#ff6f9a',cornerStrokeColor:'#ffffff',borderColor:'#ff6f9a',cornerSize:13,touchCornerSize:28,padding:2,centeredScaling:true,centeredRotation:true});o.setCoords?.()}catch(e){}
  }

  function restoreAt(idx){
    const c=currentCanvas;if(!c||idx<0||idx>=history.length||restoring)return;
    restoring=true;historyIndex=idx;updateUi();
    let data;try{data=JSON.parse(history[idx])}catch(e){restoring=false;updateUi();return}
    c.loadFromJSON(data,()=>{
      try{
        c.getObjects().forEach(o=>{styleRestoredObject(o);if(o.isTplBg)c.sendToBack(o)});
        c.discardActiveObject();
        by('bf-tpl-objectbar')?.classList.remove('show');
        c.requestRenderAll();
      }finally{
        restoring=false;updateUi();
        const status=by('bf-tpl-status');if(status)status.textContent=idx===0?'已回到最初狀態':`已回到步驟 ${idx+1}`;
      }
    });
  }

  function undo(){if(historyIndex>0)restoreAt(historyIndex-1)}
  function redo(){if(historyIndex>=0&&historyIndex<history.length-1)restoreAt(historyIndex+1)}
  window.bfTemplateUndo=undo;window.bfTemplateRedo=redo;

  function clearSelectionFromBlank(opt,c){
    if(opt?.target||c.isDrawingMode)return;
    const native=opt?.e;if(native?.touches?.length>1)return;
    if(c.getActiveObject())c.discardActiveObject();
    by('bf-tpl-objectbar')?.classList.remove('show');
    c.requestRenderAll();
  }

  function hookCanvas(c){
    if(!c||c===currentCanvas)return;
    currentCanvas=c;history=[];historyIndex=-1;restoring=false;
    c.on('mouse:down',opt=>clearSelectionFromBlank(opt,c));
    c.on('object:added',()=>scheduleRecord());
    c.on('object:removed',()=>scheduleRecord());
    c.on('object:modified',()=>scheduleRecord());
    c.on('selection:cleared',()=>by('bf-tpl-objectbar')?.classList.remove('show'));
    beginInitialization();
    updateUi();
  }

  function relevantControlEvent(ev){
    if(!modalOpen()||!currentCanvas)return;
    const t=ev.target;if(!(t instanceof Element))return;
    if(!t.closest('#template-modal'))return;
    if(t.closest('#bf-tpl-historybar'))return;
    scheduleRecord(ev.type==='input'?260:120);
  }

  function boot(){
    ensureUi();
    window.addEventListener('benfuwan:template-canvas-ready',ev=>{const c=ev.detail?.canvas||canvas();if(c)hookCanvas(c)});
    document.addEventListener('click',relevantControlEvent,false);
    document.addEventListener('change',relevantControlEvent,false);
    document.addEventListener('input',relevantControlEvent,false);
    setInterval(()=>{ensureUi();const c=canvas();if(c&&c!==currentCanvas)hookCanvas(c)},350);
    console.info('[ADMIN] template undo/redo history enabled');
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
