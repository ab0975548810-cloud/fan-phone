/* Customer editor: a dedicated drag corner, position lock, and reachable template photo slots. */
(function(){
  'use strict';
  if(window.__bfEditorControls20261017)return;
  window.__bfEditorControls20261017=true;
  const by=id=>document.getElementById(id);
  const current=()=>{try{return typeof canvas!=='undefined'?canvas:null}catch(_){return null}};
  const allowed=o=>!!o&&o.role!=='guide'&&o.role!=='slot-guide'&&o.role!=='template-bg'&&o.role!=='editable-sticker-text';
  const multi=()=>window.BenfuwanMultilayer;
  const bound=new WeakSet();
  if(typeof CUSTOM_PROPS!=='undefined'&&!CUSTOM_PROPS.includes('bfUserLocked'))CUSTOM_PROPS.push('bfUserLocked');

  function styles(){
    if(by('bf-editor-lock-css'))return;
    const s=document.createElement('style');s.id='bf-editor-lock-css';s.textContent=`
      #bf-object-lock{flex:0 0 auto!important;min-width:54px!important;color:#bb4771!important}
      #bf-object-lock[aria-pressed="true"]{background:#ffe8f0!important;color:#bf285d!important}
      #bf-front-slot-actions{position:absolute;top:10px;right:9px;z-index:65;display:flex;flex-wrap:wrap;justify-content:flex-end;gap:5px;max-width:75%}
      #bf-front-slot-actions[hidden]{display:none}
      .bf-front-slot-btn{min-height:38px;padding:7px 10px;border-radius:999px;border:1px solid #eeb7ca;background:rgba(255,255,255,.96);color:#ad3667;font-size:11px;font-weight:900;box-shadow:0 3px 12px rgba(90,40,65,.12)}
      .bf-front-slot-btn:disabled{opacity:.5;cursor:not-allowed}
    `;document.head.appendChild(s);
  }
  function control(){
    if(!window.fabric?.Control||!fabric.controlsUtils?.dragHandler)return null;
    if(window.__bfMoveCorner)return window.__bfMoveCorner;
    const c=new fabric.Control({
      x:.5,y:.5,offsetX:7,offsetY:7,cursorStyle:'move',actionName:'drag',
      actionHandler:fabric.controlsUtils.dragHandler,
      render(ctx,left,top){
        ctx.save();ctx.translate(left,top);
        ctx.fillStyle='#ffffff';ctx.strokeStyle='#ed5e8f';ctx.lineWidth=2;
        ctx.beginPath();ctx.arc(0,0,12,0,Math.PI*2);ctx.fill();ctx.stroke();
        ctx.strokeStyle='#ce3c72';ctx.lineWidth=1.6;ctx.lineCap='round';
        ctx.beginPath();ctx.moveTo(-6,0);ctx.lineTo(6,0);ctx.moveTo(0,-6);ctx.lineTo(0,6);
        ctx.moveTo(-6,0);ctx.lineTo(-3,-3);ctx.moveTo(-6,0);ctx.lineTo(-3,3);
        ctx.moveTo(6,0);ctx.lineTo(3,-3);ctx.moveTo(6,0);ctx.lineTo(3,3);
        ctx.moveTo(0,-6);ctx.lineTo(-3,-3);ctx.moveTo(0,-6);ctx.lineTo(3,-3);
        ctx.moveTo(0,6);ctx.lineTo(-3,3);ctx.moveTo(0,6);ctx.lineTo(3,3);ctx.stroke();
        ctx.restore();
      }
    });
    c.cornerSize=25;c.touchCornerSize=42;
    window.__bfMoveCorner=c;return c;
  }
  function applyUserLock(o){
    if(!allowed(o))return;
    const c=current(),locked=!!o.bfUserLocked,policy=multi();
    if(o.templateLayerId&&policy&&c?.layer_contract_version===policy.VERSION){
      policy.permissions(c,o);
    }else{
      o.set({lockMovementX:false,lockMovementY:false,lockScalingX:false,lockScalingY:false,lockRotation:false,hasControls:true});
    }
    if(locked)o.set({lockMovementX:true,lockMovementY:true,lockScalingX:true,lockScalingY:true,lockRotation:true,hasControls:false});
    else {
      const handle=control();
      if(handle){o.controls={...o.controls,br:handle};o.setControlsVisibility?.({br:!o.lockMovementX&&!o.lockMovementY});}
      o.setControlsVisibility?.({ml:false,mr:false,mt:false,mb:false});
    }
    o.setCoords?.();
  }
  function lockUi(){
    styles();const bar=by('object-bar');if(!bar)return;
    let b=by('bf-object-lock');
    if(!b){
      b=document.createElement('button');b.type='button';b.id='bf-object-lock';
      b.addEventListener('click',()=>{
        const c=current(),o=c?.getActiveObject();if(!allowed(o))return;
        const policy=multi();
        if(o.templateLayerId&&policy&&c.layer_contract_version===policy.VERSION&&!policy.allowed(c,o,'canMove'))return;
        o.bfUserLocked=!o.bfUserLocked;applyUserLock(o);syncLockButton();c.requestRenderAll();
        if(typeof recordHistory==='function')recordHistory();
      });
      bar.prepend(b);
    }
    syncLockButton();
  }
  function syncLockButton(){
    const b=by('bf-object-lock'),o=current()?.getActiveObject();if(!b)return;
    b.hidden=!allowed(o);if(!allowed(o))return;
    const locked=!!o.bfUserLocked;
    b.setAttribute('aria-pressed',String(locked));b.title=locked?'解鎖選取物件':'鎖定選取物件位置';
    b.innerHTML=locked?'<i class="fa-solid fa-lock"></i>解鎖':'<i class="fa-solid fa-lock-open"></i>鎖定';
  }

  function slots(){
    styles();const space=by('page-editor')?.querySelector('.workspace');
    if(!space)return;
    let box=by('bf-front-slot-actions');
    if(!box){box=document.createElement('div');box.id='bf-front-slot-actions';space.append(box);}
    const c=current(),guides=c?.getObjects().filter(o=>o.role==='slot-guide')||[];
    box.replaceChildren();box.hidden=!guides.length;
    guides.forEach((o,index)=>{
      const b=document.createElement('button');b.type='button';b.className='bf-front-slot-btn';
      b.textContent=guides.length===1?'上傳照片到照片框':'照片框 '+(index+1)+'・上傳照片';
      const policy=multi(),canFill=!(o.templateLayerId&&policy&&c.layer_contract_version===policy.VERSION&&!policy.allowed(c,o,'canEdit'));
      b.disabled=!canFill;
      b.onclick=()=>openSlot(o);
      box.append(b);
    });
  }
  function openSlot(o){
    const c=current(),input=by('slot-input');if(!c||!input||!c.getObjects().includes(o)||o.role!=='slot-guide')return false;
    const policy=multi();
    if(o.templateLayerId&&policy&&c.layer_contract_version===policy.VERSION&&!policy.allowed(c,o,'canEdit'))return false;
    // activeSlotGuide is a top-level lexical binding owned by the base editor.
    activeSlotGuide=o;input.click();return true;
  }
  function bind(c){
    if(!c||bound.has(c))return;
    bound.add(c);lockUi();
    c.getObjects().forEach(applyUserLock);
    c.on('object:added',e=>{applyUserLock(e.target);queueMicrotask(slots)});
    c.on('object:removed',()=>queueMicrotask(slots));
    c.on('object:modified',e=>{if(e.target?.bfUserLocked)applyUserLock(e.target);syncLockButton()});
    for(const e of ['selection:created','selection:updated','selection:cleared'])c.on(e,()=>syncLockButton());
    queueMicrotask(slots);
  }
  const oldInit=window.initCanvas;
  if(typeof oldInit==='function')window.initCanvas=function(){const r=oldInit.apply(this,arguments);bind(current());return r;};
  const oldHydrate=window.rehydrateCanvas;
  if(typeof oldHydrate==='function')window.rehydrateCanvas=function(){const r=oldHydrate.apply(this,arguments);const c=current();bind(c);c?.getObjects().forEach(applyUserLock);queueMicrotask(slots);return r;};
  const oldSelect=window.syncSelection;
  if(typeof oldSelect==='function')window.syncSelection=function(){const r=oldSelect.apply(this,arguments);syncLockButton();return r;};
  const oldApply=window.applyTemplate;
  if(typeof oldApply==='function')window.applyTemplate=function(tpl,done){
    const r=oldApply.call(this,tpl,()=>{bind(current());slots();done?.();});
    if(r&&typeof r.finally==='function')r.finally(()=>slots());
    return r;
  };
  // Fabric locks do not guard toolbar methods that assign coordinates directly.
  for(const name of ['nudgeActive','centerActive','changeAngle']){
    const previous=window[name];if(typeof previous!=='function')continue;
    window[name]=function(){if(current()?.getActiveObject()?.bfUserLocked)return;return previous.apply(this,arguments);};
  }
  function boot(){styles();lockUi();bind(current());slots();}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
  window.BenfuwanEditorControls={bind,applyUserLock,refreshSlotActions:slots,openSlot};
})();
