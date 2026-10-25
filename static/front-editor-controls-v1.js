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
  let scaleGesture=null;
  function mayAdjust(c,o,permission){
    if(!c||!allowed(o)||o.bfUserLocked||o.locked||o.selectable===false)return false;
    const policy=multi();
    return !(o.templateLayerId&&policy&&c.layer_contract_version===policy.VERSION&&!policy.allowed(c,o,permission));
  }
  function mayScale(c,o){return mayAdjust(c,o,'canScale')&&!o.lockScalingX&&!o.lockScalingY;}
  function finishScale(){
    const g=scaleGesture;scaleGesture=null;
    if(g&&g.c===current()&&g.c.getObjects().includes(g.o)&&(g.o.scaleX!==g.x||g.o.scaleY!==g.y)){
      g.o.setCoords();g.c.requestRenderAll();recordHistory();
    }
    syncAdjust();
  }
  function syncAdjust(){
    const c=current(),o=c?.getActiveObject(),range=by('object-scale-range');
    if(!range)return;
    range.disabled=!mayScale(c,o);
    if(!scaleGesture){
      const percent=Math.abs(o?.scaleX||1)*100;
      range.max=String(Math.max(400,Math.ceil(percent*2)));range.value=String(percent);
    }
    by('object-scale-value').textContent=o?`${Math.round(Math.abs(o.scaleX)*1000)/10}%`:'—';
    const shapes=by('bf-shape-tools'),shape=o&&['rect','circle','triangle','polygon','path','line'].includes(o.type);
    shapes.hidden=!shape;
    if(!shape)return;
    const editable=mayAdjust(c,o,'canEdit');
    shapes.querySelectorAll('input').forEach(input=>input.disabled=!editable);
    const color=v=>/^#[0-9a-f]{6}$/i.test(v||'')?v:'#000000';
    by('shape-fill').value=color(o.fill);by('shape-transparent').checked=!o.fill||o.fill==='transparent';
    by('shape-stroke').value=color(o.stroke);by('shape-stroke-width').value=o.strokeWidth||0;
    by('shape-radius-label').hidden=o.type!=='rect';by('shape-radius').value=o.rx||0;
  }
  function adjustUi(){
    const opacity=by('opacity-range');if(!opacity||by('object-scale-range'))return;
    const row=document.createElement('div');row.className='range-row';
    row.innerHTML='<div class="head"><label for="object-scale-range">放大／縮小</label><output id="object-scale-value" for="object-scale-range"></output></div><input id="object-scale-range" type="range" min="0.1" max="400" step="0.1">';
    opacity.closest('.range-row').before(row);
    const range=by('object-scale-range');
    range.addEventListener('input',()=>{
      const c=current(),o=c?.getActiveObject();
      if(!mayScale(c,o)){finishScale();return;}
      if(scaleGesture&&(scaleGesture.c!==c||scaleGesture.o!==o))finishScale();
      if(!scaleGesture)scaleGesture={c,o,x:o.scaleX,y:o.scaleY,center:o.getCenterPoint()};
      const g=scaleGesture,factor=Number(range.value)/100/Math.abs(g.x);
      if(!Number.isFinite(factor)||factor<=0)return;
      o.set({scaleX:g.x*factor,scaleY:g.y*factor});o.setPositionByOrigin(g.center,'center','center');
      // Keep existing template bounds and paired editable text authoritative.
      c.fire('object:scaling',{target:o});window.BenfuwanEditableSticker?.syncAll(c);
      o.setCoords();c.requestRenderAll();by('object-scale-value').textContent=`${Math.round(Math.abs(o.scaleX)*1000)/10}%`;
    });
    for(const event of ['change','pointerup','pointercancel','blur'])range.addEventListener(event,finishScale);
    const shapes=document.createElement('fieldset');shapes.id='bf-shape-tools';shapes.hidden=true;
    shapes.innerHTML='<legend>形狀樣式</legend><label>填色<input id="shape-fill" type="color"></label><label><input id="shape-transparent" type="checkbox">透明填色</label><label>描邊<input id="shape-stroke" type="color"></label><label>線條粗細<input id="shape-stroke-width" type="number" min="0" max="50" step="0.5"></label><label id="shape-radius-label">圓角<input id="shape-radius" type="number" min="0" max="1000" step="1"></label>';
    row.parentElement.append(shapes);
    shapes.addEventListener('change',event=>{
      const c=current(),o=c?.getActiveObject();if(!mayAdjust(c,o,'canEdit')){syncAdjust();return;}
      const center=o.getCenterPoint(),id=event.target.id;
      if(id==='shape-fill'||id==='shape-transparent')o.set('fill',by('shape-transparent').checked?'transparent':by('shape-fill').value);
      if(id==='shape-stroke')o.set('stroke',event.target.value);
      if(id==='shape-stroke-width'){
        const width=Number(event.target.value);if(!Number.isFinite(width))return;
        o.set({strokeWidth:Math.max(0,Math.min(50,width)),stroke:o.stroke||by('shape-stroke').value});
      }
      if(id==='shape-radius'&&o.type==='rect'){
        const value=Number(event.target.value);if(!Number.isFinite(value))return;
        const radius=Math.max(0,Math.min(value,o.width/2,o.height/2));o.set({rx:radius,ry:radius});
      }
      o.setPositionByOrigin(center,'center','center');o.setCoords();c.requestRenderAll();recordHistory();syncAdjust();
    });
    const open=window.openAdjustSheet;
    window.openAdjustSheet=function(){syncAdjust();return open.apply(this,arguments);};
    syncAdjust();
  }
  if(typeof CUSTOM_PROPS!=='undefined')for(const key of ['bfUserLocked','stickerId','originalPublicSrc','aiOutlineViewport'])if(!CUSTOM_PROPS.includes(key))CUSTOM_PROPS.push(key);

  function styles(){
    if(by('bf-editor-lock-css'))return;
    const s=document.createElement('style');s.id='bf-editor-lock-css';s.textContent=`
      #bf-object-lock{flex:0 0 auto!important;min-width:54px!important;color:#bb4771!important}
      #bf-object-lock[aria-pressed="true"]{background:#ffe8f0!important;color:#bf285d!important}
      #bf-front-slot-actions{position:absolute;top:10px;right:9px;z-index:65;display:flex;flex-wrap:wrap;justify-content:flex-end;gap:5px;max-width:75%}
      #bf-front-slot-actions[hidden]{display:none}
      .bf-front-slot-btn{min-height:38px;padding:7px 10px;border-radius:999px;border:1px solid #eeb7ca;background:rgba(255,255,255,.96);color:#ad3667;font-size:11px;font-weight:900;box-shadow:0 3px 12px rgba(90,40,65,.12)}
      .bf-front-slot-btn:disabled{opacity:.5;cursor:not-allowed}
      #object-scale-value{min-width:55px;text-align:right;font-variant-numeric:tabular-nums}
      #bf-shape-tools{border:1px solid #f3d9e3;border-radius:14px;margin:14px 0;padding:12px;display:flex;flex-wrap:wrap;gap:12px}
      #bf-shape-tools[hidden],#shape-radius-label[hidden]{display:none}
      #bf-shape-tools label{display:flex;align-items:center;gap:7px;min-height:44px;font-size:13px}
      #bf-shape-tools input[type=number]{width:68px;min-height:44px}#bf-shape-tools input[type=color]{width:44px;height:44px}
      #material-cats{display:flex;gap:8px;overflow-x:auto;margin-bottom:12px}.material-hint{font-size:12px;color:#776570}
      #material-grid button{min-height:96px;background:#fff;border:1px solid #f1dce5;border-radius:14px;color:#ad4770;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px}
      #material-grid svg{width:42px;height:42px}#material-grid button span{font-size:13px}
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
    syncAdjust();
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
  function boot(){styles();adjustUi();lockUi();bind(current());slots();}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
  window.BenfuwanEditorControls={bind,applyUserLock,refreshSlotActions:slots,openSlot};
})();
