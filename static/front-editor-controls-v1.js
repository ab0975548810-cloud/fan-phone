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
  let adjustment=null;
  const fields={scale:['object-scale-range','object-scale-number','canScale'],opacity:['opacity-range','opacity-number','canEdit'],angle:['angle-range','angle-number','canRotate'],x:[null,'position-x','canMove'],y:[null,'position-y','canMove']};
  function baseline(o){
    if(!allowed(o))return;
    if(!(o.bfScaleBaseX>0&&o.bfScaleBaseY>0)){o.bfScaleBaseX=Math.abs(o.scaleX)||1;o.bfScaleBaseY=Math.abs(o.scaleY)||1;}
  }
  function mayAdjust(c,o,permission){
    if(!c||!allowed(o)||o.bfUserLocked||o.locked||o.selectable===false)return false;
    const policy=multi();
    if(o.templateLayerId&&policy&&c.layer_contract_version===policy.VERSION&&!policy.allowed(c,o,permission))return false;
    if(permission==='canMove'&&(o.lockMovementX||o.lockMovementY))return false;
    if(permission==='canScale'&&(o.lockScalingX||o.lockScalingY))return false;
    if(permission==='canRotate'&&o.lockRotation)return false;
    return true;
  }
  const snapshot=o=>({left:o.left,top:o.top,scaleX:o.scaleX,scaleY:o.scaleY,angle:o.angle,opacity:o.opacity});
  const normalAngle=a=>((a+180)%360+360)%360-180;
  function values(o){baseline(o);const p=o.getCenterPoint();return {scale:Math.abs(o.scaleX)/o.bfScaleBaseX*100,opacity:(o.opacity??1)*100,angle:normalAngle(o.angle||0),x:p.x,y:p.y};}
  function limits(key,c,o){
    if(key==='scale'){
      let min=.1,max=300;
      if(o.templateLayerId&&c.layer_contract_version===multi()?.VERSION){
        const stroke=o.strokeUniform?(o.strokeWidth||0):0,v=values(o).scale;
        max=Math.min(max,v*(c.width-stroke)/Math.max(.001,o.getScaledWidth()-stroke),v*(c.height-stroke)/Math.max(.001,o.getScaledHeight()-stroke));
        min=Math.max(min,v*.001/Math.abs(o.scaleX),v*.001/Math.abs(o.scaleY));
      }
      return [min,max];
    }
    if(key==='opacity')return [0,100];if(key==='angle')return [-180,180];
    const extent=key==='x'?c.width:c.height;
    return o.templateLayerId&&c.layer_contract_version===multi()?.VERSION?[0,extent]:[-extent,extent*2];
  }
  function beginAdjustment(c,o){
    if(adjustment&&(adjustment.c!==c||adjustment.o!==o))finishAdjustment();
    if(!adjustment){clearTimeout(historyTimer);recordHistory();adjustment={c,o,before:snapshot(o)};}
    return adjustment;
  }
  function finishAdjustment(){
    const g=adjustment;adjustment=null;
    if(g&&g.c===current()&&g.c.getObjects().includes(g.o)&&JSON.stringify(snapshot(g.o))!==JSON.stringify(g.before)){
      g.o.setCoords();g.c.requestRenderAll();recordHistory();renderLayerList();
    }
    syncAdjust();
  }
  function updateObject(key,value,preview=false){
    const c=current(),o=c?.getActiveObject();if(!mayAdjust(c,o,fields[key][2])){syncAdjust();return false;}
    const [min,max]=limits(key,c,o);
    if(typeof value==='string'&&!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(value.trim())||!Number.isFinite(Number(value))||Number(value)<min-1e-7||Number(value)>max+1e-7){
      toast(`請輸入 ${Number(min.toFixed(2))}～${Number(max.toFixed(2))} 的有效數字`);syncAdjust();return false;
    }
    value=Number(value);beginAdjustment(c,o);const center=o.getCenterPoint();
    if(key==='scale'){const factor=value/values(o).scale;o.set({scaleX:o.scaleX*factor,scaleY:o.scaleY*factor});o.setPositionByOrigin(center,'center','center');}
    else if(key==='angle')o.rotate(value);
    else if(key==='opacity')o.set('opacity',value/100);
    else {center[key]=value;o.setPositionByOrigin(center,'center','center');}
    if(key!=='opacity')c.fire(key==='scale'?'object:scaling':key==='angle'?'object:rotating':'object:moving',{target:o});
    window.BenfuwanEditableSticker?.syncAll(c);o.setCoords();c.requestRenderAll();syncAdjust();
    if(!preview)finishAdjustment();return true;
  }
  function syncAdjust(){
    const c=current(),o=c?.getActiveObject();if(!by('object-scale-range'))return;
    const v=o?values(o):{};
    for(const [key,[slider,input,permission]] of Object.entries(fields)){
      const enabled=mayAdjust(c,o,permission),number=by(input),range=by(slider);
      if(number){number.disabled=!enabled;if(document.activeElement!==number||!number.dataset.editing)number.value=o?String(Number(v[key].toFixed(3))):'';}
      if(range){range.disabled=!enabled;if(o){const [min,max]=limits(key,c,o);range.min=min;range.max=max;range.value=v[key];}}
    }
    by('object-scale-value').textContent=o?`${Number(v.scale.toFixed(1))}%`:'—';
    by('opacity-label').textContent=o?`${Number(v.opacity.toFixed(1))}%`:'—';by('angle-label').textContent=o?`${Number(v.angle.toFixed(1))}°`:'—';
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
    row.innerHTML='<div class="head"><label for="object-scale-range">大小（初始 100%）</label><output id="object-scale-value"></output></div><input id="object-scale-range" type="range" min="0.1" max="300" step="any">';
    opacity.closest('.range-row').before(row);
    const body=row.parentElement;
    const position=document.createElement('div');position.className='bf-position-inputs';
    position.innerHTML='<p>畫布座標 px：左上角為原點，X 向右、Y 向下；數值為物件中心，非列印定位。</p><label>X <input id="position-x" aria-label="畫布中心 X" inputmode="decimal" type="text"></label><label>Y <input id="position-y" aria-label="畫布中心 Y" inputmode="decimal" type="text"></label>';
    body.querySelector('.position-title').before(position);
    for(const [key,[slider,input]] of Object.entries(fields)){
      const range=by(slider);
      if(range){
        range.removeAttribute('oninput');range.removeAttribute('onchange');range.step='any';
        const number=document.createElement('input');number.id=input;number.type='text';number.inputMode='decimal';number.setAttribute('aria-label',({scale:'大小百分比',opacity:'透明度百分比',angle:'旋轉角度'})[key]);
        range.before(number);
        range.addEventListener('input',()=>updateObject(key,range.value,true));
        for(const event of ['change','pointerup','pointercancel','blur'])range.addEventListener(event,finishAdjustment);
      }
      const number=by(input);let inputObject=null;
      number.addEventListener('focus',()=>inputObject=current()?.getActiveObject());
      number.addEventListener('input',()=>number.dataset.editing='1');
      number.addEventListener('change',()=>{delete number.dataset.editing;if(inputObject!==current()?.getActiveObject()){syncAdjust();return;}updateObject(key,number.value);});
      number.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();number.blur();}if(e.key==='Escape'){delete number.dataset.editing;syncAdjust();number.blur();}});
    }
    const more=document.createElement('details');more.id='bf-adjust-more';
    more.innerHTML='<summary>更多調整</summary>';
    for(const el of [...body.children])if(!el.classList.contains('range-row'))more.append(el);
    body.append(more);
    const header=by('sheet-adjust').querySelector('.sheet-header');
    const collapse=document.createElement('button');collapse.id='bf-adjust-collapse';collapse.type='button';collapse.textContent='收合';collapse.setAttribute('aria-expanded','true');
    collapse.onclick=()=>{const collapsed=by('sheet-adjust').classList.toggle('bf-collapsed');collapse.textContent=collapsed?'展開':'收合';collapse.setAttribute('aria-expanded',String(!collapsed));};header.insertBefore(collapse,header.lastElementChild);
    const confirm=document.createElement('button');confirm.id='bf-adjust-confirm';confirm.textContent='確認';confirm.type='button';confirm.onclick=()=>{document.activeElement?.blur();finishAdjustment();};header.insertBefore(confirm,header.lastElementChild);
    const shapes=document.createElement('fieldset');shapes.id='bf-shape-tools';shapes.hidden=true;
    shapes.innerHTML='<legend>形狀樣式</legend><label>填色<input id="shape-fill" type="color"></label><label><input id="shape-transparent" type="checkbox">透明填色</label><label>描邊<input id="shape-stroke" type="color"></label><label>線條粗細<input id="shape-stroke-width" type="number" min="0" max="50" step="0.5"></label><label id="shape-radius-label">圓角<input id="shape-radius" type="number" min="0" max="1000" step="1"></label>';
    more.append(shapes);
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
    window.openAdjustSheet=function(){finishAdjustment();syncAdjust();return open.apply(this,arguments);};
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
    const c=current(),locked=!!(o.bfUserLocked||o.locked),policy=multi();
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
  function bindGestures(c){
    const el=c.upperCanvasEl;let state=null,blocked=false;
    const stop=e=>{e.preventDefault();e.stopImmediatePropagation();};
    // A terminated segment commits its last preview once; remaining fingers must
    // lift before Fabric may begin another drag. Selection changes never resume it.
    const finish=()=>{state=null;c._currentTransform=null;finishAdjustment();};
    for(const event of ['selection:created','selection:updated','selection:cleared'])c.on(event,()=>{if(state)finish();});
    c.on('object:removed',e=>{if(state?.o===e.target)finish();});
    const pair=e=>{const [a,b]=e.touches;return {distance:Math.hypot(b.clientX-a.clientX,b.clientY-a.clientY),angle:Math.atan2(b.clientY-a.clientY,b.clientX-a.clientX)*180/Math.PI};};
    el.addEventListener('touchstart',e=>{
      if(blocked){stop(e);if(e.touches.length!==2)finish();return;}
      if(e.touches.length!==2)return;stop(e);blocked=true;finishAdjustment();
      const o=c.getActiveObject();if(!o)return;
      // Finish the single-finger segment before taking over Fabric's transform.
      c._currentTransform=null;
      if(!mayAdjust(c,o,'canScale')&&!mayAdjust(c,o,'canRotate'))return;
      const start=pair(e);if(start.distance<1)return;
      beginAdjustment(c,o);state={o,distance:start.distance,gestureStartAngle:start.angle,objectStartAngle:o.angle||0,scale:values(o).scale};
    },{capture:true,passive:false});
    el.addEventListener('touchmove',e=>{
      if(!blocked)return;stop(e);if(!state)return;
      if(e.touches.length!==2||c!==current()||c.getActiveObject()!==state.o||restoringHistory){finish();return;}
      const now=pair(e),o=state.o;
      if(mayAdjust(c,o,'canScale')){const [min,max]=limits('scale',c,o);updateObject('scale',Math.max(min,Math.min(max,state.scale*now.distance/Math.max(1,state.distance))),true);}
      const rotationDelta=normalAngle(now.angle-state.gestureStartAngle);
      if(mayAdjust(c,o,'canRotate'))updateObject('angle',normalAngle(state.objectStartAngle+rotationDelta),true);
    },{capture:true,passive:false});
    const end=e=>{if(!blocked)return;stop(e);if(e.type==='touchcancel'||e.touches.length<2)finish();if(!e.touches.length){blocked=false;if(c.mainTouchId!=null)c._onTouchEnd(e);}};
    el.addEventListener('touchend',end,{capture:true,passive:false});el.addEventListener('touchcancel',end,{capture:true,passive:false});
  }
  function bind(c){
    if(!c||bound.has(c))return;
    bound.add(c);c.__bfUnifiedAdjust=true;c.uniformScaling=true;c.uniScaleKey=null;lockUi();bindGestures(c);
    c.getObjects().forEach(o=>{baseline(o);applyUserLock(o);});
    c.on('object:added',e=>{baseline(e.target);applyUserLock(e.target);queueMicrotask(slots)});
    c.on('object:removed',()=>queueMicrotask(slots));
    c.on('object:modified',e=>{if(e.target?.bfUserLocked)applyUserLock(e.target);syncLockButton()});
    for(const e of ['selection:created','selection:updated','selection:cleared'])c.on(e,()=>{finishAdjustment();syncLockButton();});
    c.on('object:scaling',({target:o})=>{
      if(!mayAdjust(c,o,'canScale'))return;
      const value=values(o).scale,[min,max]=limits('scale',c,o),factor=Math.max(min,Math.min(max,value))/value;
      if(Math.abs(factor-1)>1e-10){const center=o.getCenterPoint();o.set({scaleX:o.scaleX*factor,scaleY:o.scaleY*factor});o.setPositionByOrigin(center,'center','center');window.BenfuwanEditableSticker?.syncAll(c);o.setCoords();}
    });
    for(const e of ['object:moving','object:scaling','object:rotating'])c.on(e,syncAdjust);
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
  window.changeOpacity=v=>updateObject('opacity',v,true);
  window.changeAngle=v=>updateObject('angle',v,true);
  window.commitObjectAdjustment=finishAdjustment;
  for(const name of ['undoCanvas','redoCanvas']){
    const previous=window[name];
    window[name]=function(){finishAdjustment();return previous.apply(this,arguments);};
  }
  window.nudgeActive=function(dx,dy){const o=current()?.getActiveObject();if(!o)return;const v=values(o);if(dx)updateObject('x',v.x+dx);if(dy)updateObject('y',v.y+dy);};
  for(const name of ['centerActive','flipActive','sendBackward','bringForward','moveToBottom','moveToTop','duplicateActive','deleteActive']){
    const previous=window[name];if(typeof previous!=='function')continue;
    const permission=name==='duplicateActive'?'canDuplicate':name==='deleteActive'?'canDelete':name==='flipActive'?'canEdit':'canMove';
    window[name]=function(){const c=current(),active=c?.getActiveObject(),target=active?.role==='editable-sticker-text'?window.BenfuwanEditableSticker?.pair(c,active)?.bg:active;if(!mayAdjust(c,target,permission))return;finishAdjustment();const result=previous.apply(this,arguments);syncAdjust();return result;};
  }
  const close=window.closeSheets;
  window.closeSheets=function(){finishAdjustment();return close.apply(this,arguments);};
  function boot(){if(window.fabric)fabric.Object.NUM_FRACTION_DIGITS=8;styles();adjustUi();lockUi();bind(current());slots();}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
  window.BenfuwanEditorControls={bind,applyUserLock,refreshSlotActions:slots,openSlot};
})();
