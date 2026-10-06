(function(){
  'use strict';const multi=window.BenfuwanMultilayer,editable=window.BenfuwanEditableSticker;if(!multi||!editable)return;
  CUSTOM_PROPS.push(...multi.PROPS.filter(k=>!CUSTOM_PROPS.includes(k)));
  const get=()=>typeof canvas!=='undefined'?canvas:null,active=()=>get()?.getActiveObject(),enabled=c=>c?.layer_contract_version===multi.VERSION;
  const say=m=>window.toast?.(m);
  async function contract(id,application=''){
    const url='/api/template_contract/'+encodeURIComponent(id)+'?model_id='+encodeURIComponent(ctx.modelId)+'&style_id='+encodeURIComponent(ctx.styleId)+(application?'&application_id='+encodeURIComponent(application):'');
    const r=await fetch(url,{credentials:'same-origin',cache:'no-store'}),data=await r.json();if(!r.ok||data.status!=='success')throw Error(data.msg||'模板設定無法讀取');return data;
  }
  async function refresh(c){if(!enabled(c)||!c.templateState)return;
    const state=c.templateState,data=await contract(state.id,state.applicationId);
    if(state.binding.hash!==data.binding.hash)throw Error('此模板設定已更新，請重新套用模板');
    c.templateState=multi.freeze({...multi.clone(state),binding:data.binding});
  }
  const oldApply=window.applyTemplate;
  window.applyTemplate=function(tpl,done){if(tpl?.layer_contract_version!==multi.VERSION)return oldApply.apply(this,arguments);
    const c=get();if(!c)return;setBusy(true,'正在載入可編輯模板…');restoringHistory=true;
    return (async()=>{try{
      const approved=await contract(tpl.id);if(get()!==c)return;
      ctx.backgroundColor='transparent';ctx.backgroundOpacity=1;
      await multi.apply(c,approved.template,approved.binding);multi.bind(c);bindSlots(c);rehydrateCanvas();
      historyStack=[];historyIndex=-1;restoringHistory=false;recordHistory(true);renderLayerList();done?.();
    }catch(error){say(error.message);}finally{restoringHistory=false;setBusy(false);}})();
  };
  const init=window.initCanvas;window.initCanvas=function(){const result=init.apply(this,arguments);multi.bind(get());touch(get());return result;};
  const hydrate=window.rehydrateCanvas;window.rehydrateCanvas=function(){const result=hydrate.apply(this,arguments);const c=get();if(enabled(c)){multi.hydrate(c);bindSlots(c);touch(c);}return result;};
  const fontReady=window.ensureCanvasFonts;window.ensureCanvasFonts=async function(){await fontReady.apply(this,arguments);const c=get();if(enabled(c)){await refresh(c);multi.hydrate(c);multi.update(c);}};
  const history=window.recordHistory;window.recordHistory=function(){const c=get();if(enabled(c))multi.update(c);return history.apply(this,arguments);};
  const oldCart=window.confirmDesignToCart;window.confirmDesignToCart=async function(){const c=get();if(!enabled(c))return oldCart.apply(this,arguments);
    try{await ensureCanvasFonts();const data=await multi.serialize(c,ctx),before=cartItem;await oldCart.apply(this,arguments);
      if(cartItem&&cartItem!==before&&cartItem.printBase64===ctx.printBase64&&cartItem.modelId===ctx.modelId&&cartItem.styleId===ctx.styleId){cartItem.designJson=data;await idbSet('cart',cartItem);}
    }catch(error){say('模板無法保存：'+error.message);}
  };
  function guard(flag){const c=get(),o=active();if(!enabled(c)||!o)return true;if(!multi.allowed(c,o,flag)){say('此模板圖層未開放這項操作');return false;}return true;}
  const operations={nudgeActive:'canMove',centerActive:'canMove',changeAngle:'canRotate',changeOpacity:'canEdit',flipActive:'canEdit',deleteActive:'canDelete',bringForward:'canMove',sendBackward:'canMove',moveToTop:'canMove',moveToBottom:'canMove',applyTextSettings:'canEdit',openTextSheet:'canEdit',removeBackgroundForActive:'canEdit',openAiRemoveTools:'canEdit',openAiOutlineSheet:'canEdit'};
  for(const [name,flag] of Object.entries(operations)){const old=window[name];if(typeof old!=='function')continue;window[name]=function(){if(!guard(flag))return;return old.apply(this,arguments);};}
  const aiButton=document.getElementById('ai-remove-btn');if(aiButton)aiButton.onclick=window.openAiRemoveTools;
  const editableSelection=window.bfEditableSelection;
  window.bfEditableSelection=function(c,o){if(enabled(c)&&o?.templateLayerId&&!multi.allowed(c,o,'canEdit')){const dock=document.getElementById('editable-text-tools');if(dock)dock.hidden=true;return;}return editableSelection?.apply(this,arguments);};
  const duplicate=window.duplicateActive;
  window.duplicateActive=async function(){const c=get(),o=active();if(!enabled(c)||!o?.templateLayerId)return duplicate.apply(this,arguments);if(!guard('canDuplicate'))return;
    try{
      let copied=[];
      if(editable.isMember(o)){const pair=await editable.duplicate(c,o);copied=[pair.bg,pair.text];}
      else{const item=await new Promise(resolve=>o.clone(resolve,[...multi.PROPS,...editable.PROPS]));c.add(item);c.setActiveObject(item);copied=[item];item.set({left:o.left+8,top:o.top+8});}
      for(const item of copied){item.layerInstanceId=multi.uid();item.duplicateOf=c.templateState.applicationId+':'+item.templateLayerId;multi.constrain(item,c);multi.permissions(c,item);}
      recordHistory();renderLayerList();
    }catch(error){say(error.message);}
  };
  const oldLayers=window.renderLayerList;
  window.renderLayerList=function(){const c=get();if(!enabled(c))return oldLayers.apply(this,arguments);
    const box=document.getElementById('layer-list');if(!box)return;box.replaceChildren();
    const reset=document.createElement('button');reset.type='button';reset.className='secondary multi-reset';reset.textContent='恢復原模板';reset.onclick=resetTemplate;box.append(reset);
    for(const o of [...c.getObjects()].filter(o=>o.role!=='guide').reverse()){
      const row=document.createElement('div');row.className='layer-row multi-layer-row';row.dataset.layerInstanceId=o.layerInstanceId||'';
      const label=document.createElement('div');label.className='layer-name';label.textContent=multi.name(o)+(o.locked?' 🔒':'');row.append(label);
      for(const [title,flag,fn] of [['顯示／隱藏','canEdit',()=>{o.visible=o.visible===false;}],['上移','canMove',()=>c.bringForward(o)],['下移','canMove',()=>c.sendBackwards(o)]]){
        const b=document.createElement('button');b.type='button';b.title=title;b.setAttribute('aria-label',title);b.textContent=title==='上移'?'↑':title==='下移'?'↓':o.visible===false?'顯示':'隱藏';b.disabled=Boolean(o.templateLayerId&&!multi.allowed(c,o,flag));
        b.onclick=e=>{e.stopPropagation();fn();c.requestRenderAll();recordHistory();renderLayerList();};row.append(b);
      }
      row.onclick=()=>{if(o.selectable!==false){c.setActiveObject(o);c.requestRenderAll();syncSelection();closeSheets();}};box.append(row);
    }
  };
  async function resetTemplate(){const c=get();if(!enabled(c)||!confirm('恢復模板原始排版與文字？你另外加入的照片／素材會保留。'))return;
    try{restoringHistory=true;await refresh(c);await multi.reset(c);bindSlots(c);say('已恢復原模板');}catch(error){say(error.message);}finally{restoringHistory=false;recordHistory();renderLayerList();}
  }
  function bindSlots(c){for(const o of c.getObjects().filter(o=>o.role==='slot-guide'&&o.templateSlot)){
    o.off('mousedown');o.on('mousedown',()=>{if(!multi.allowed(c,o,'canEdit'))return;activeSlotGuide=o;document.getElementById('slot-input').click();});multi.permissions(c,o);
  }}
  const slotUpload=window.uploadSlotPhoto;
  window.uploadSlotPhoto=async function(event){const target=activeSlotGuide;
    if(!enabled(get())||!target?.templateLayerId)return slotUpload.apply(this,arguments);
    const file=event.target.files?.[0];event.target.value='';if(!file||!multi.allowed(get(),target,'canEdit'))return;
    const c=get();setBusy(true,'正在加入模板照片…');
    try{
      const data=await prepareImageDataURL(file),image=await new Promise((resolve,reject)=>fabric.Image.fromURL(data,o=>o?.width?resolve(o):reject(Error('照片讀取失敗'))));
      const g=target.normalizedGeometry||multi.geometry(target,c),w=g.width*c.width,h=g.height*c.height,scale=Math.max(w/image.width,h/image.height),width=w/scale,height=h/scale;
      const sourceSize={width:image.width,height:image.height};
      image.set({width,height,cropX:(image.width-width)/2,cropY:(image.height-height)/2,sourceSize,role:'slot-photo',templateSlot:true,isSlot:false,slotId:target.slotId,originalName:file.name,angle:target.angle,opacity:target.opacity,flipX:target.flipX,flipY:target.flipY,strokeWidth:0});
      for(const key of multi.PROPS)if(target[key]!==undefined&&!['sourceSize','isSlot','cropX','cropY','templateState','layer_contract_version'].includes(key))image[key]=multi.clone(target[key]);
      image.slotMeta={x:(g.x-g.width/2)*c.width,y:(g.y-g.height/2)*c.height,w,h,id:image.slotId};
      multi.map(image,g,c);styleEditableObject(image);multi.permissions(c,image);const index=c.getObjects().indexOf(target);
      c.remove(target);c.insertAt(image,index,false);c.setActiveObject(image);activeSlotGuide=null;c.requestRenderAll();recordHistory();renderLayerList();
    }catch(error){say(error.message);}finally{setBusy(false);}
  };
  const replace=window.replaceSelectedSlotPhoto;
  window.replaceSelectedSlotPhoto=function(){const o=active();if(enabled(get())&&o?.templateSlot){if(!guard('canEdit'))return;activeSlotGuide=o;document.getElementById('slot-input').click();return;}return replace.apply(this,arguments);};
  const touchBound=new WeakSet();
  function touch(c){if(!c||touchBound.has(c))return;touchBound.add(c);const el=c.upperCanvasEl;let state=null,blocked=false;
    function stop(e){e.preventDefault();e.stopImmediatePropagation();}
    function pair(e){const [a,b]=e.touches;return {distance:Math.hypot(b.clientX-a.clientX,b.clientY-a.clientY),angle:Math.atan2(b.clientY-a.clientY,b.clientX-a.clientX)*180/Math.PI};}
    el.addEventListener('touchstart',e=>{if(!enabled(c)||e.touches.length!==2)return;stop(e);blocked=true;const o=c.getActiveObject()||c.findTarget(e);if(!o||o.locked)return;const target=o.role==='editable-sticker-text'?editable.pair(c,o).bg:o;
      c.setActiveObject(target);c._currentTransform=null;state={object:target,...pair(e),scaleX:target.scaleX,scaleY:target.scaleY,objectAngle:target.angle||0};
    },{capture:true,passive:false});
    el.addEventListener('touchmove',e=>{if(!enabled(c)||!blocked)return;stop(e);if(!state||e.touches.length!==2)return;const now=pair(e),o=state.object,ratio=now.distance/Math.max(1,state.distance);
      if(multi.allowed(c,o,'canScale'))o.set({scaleX:state.scaleX*ratio,scaleY:state.scaleY*ratio});
      if(multi.allowed(c,o,'canRotate'))o.set('angle',state.objectAngle+now.angle-state.angle);
      multi.constrain(o,c);editable.syncAll(c);o.setCoords();c.requestRenderAll();
    },{capture:true,passive:false});
    function end(e){if(!blocked)return;stop(e);if(state&&e.touches.length<2){state=null;c._currentTransform=null;recordHistory();renderLayerList();}if(!e.touches.length)blocked=false;}
    el.addEventListener('touchend',end,{capture:true,passive:false});el.addEventListener('touchcancel',end,{capture:true,passive:false});
  }
  window.BenfuwanMultilayerFront={contract,refresh,resetTemplate};
})();
