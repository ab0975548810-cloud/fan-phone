/* Order recovery uses the existing storefront editor, in an isolated admin mode. */
(function(){
  'use strict';
  if(window.BenfuwanPixelEditor)return;
  const core=()=>window.BenfuwanEditableSticker;
  for(const key of ['aiOutlineSource','aiRemovalMode','aiOutlineStyle','aiOutlineStrength','aiOutlineWidth','aiOutlineColor'])if(!CUSTOM_PROPS.includes(key))CUSTOM_PROPS.push(key);
  // Match the isolated production renderer without changing interactive caching.
  const preview=window.openPreview;let previewWork=null;
  window.openPreview=function(){
    if(previewWork)return previewWork;
    const target=canvas;if(!target)return preview.apply(this,arguments);
    const objects=target.getObjects().map(o=>[o,o.objectCaching]);
    const args=arguments;
    previewWork=(async()=>{try{objects.forEach(([o])=>o.set('objectCaching',false));return await preview.apply(this,args);}
      finally{objects.forEach(([o,cached])=>o.set('objectCaching',cached));if(canvas===target)target.requestRenderAll();}})().finally(()=>{previewWork=null;});
    return previewWork;
  };
  async function serialize(){
    await ensureCanvasFonts();
    const data=canvas.layer_contract_version==='multilayer-v1'?await BenfuwanMultilayer.serialize(canvas,ctx):await core().serialize(canvas,ctx);
    data.orderDesignVersion=1;
    return data;
  }
  if(!window.__bfOrderDesignMode){
    // Capture before the cart's existing draft transaction, not after navigation.
    const confirm=window.confirmDesignToCart,set=window.idbSet;let pending=null,running=false;
    window.idbSet=function(key,value){if(key==='cart'&&pending&&value?.printBase64===pending.print&&value.modelId===pending.design.modelId&&value.styleId===pending.design.styleId)value.designJson=pending.design;return set.apply(this,arguments);};
    window.confirmDesignToCart=async function(){
      if(running)return;running=true;
      try{const design=await serialize();pending={design,print:ctx.printBase64};return await confirm.apply(this,arguments);}
      catch(error){toast('原始設計無法完整保存：'+error.message);}
      finally{pending=null;running=false;}
    };
    return;
  }
  let work=null,saving=false,ready=false,dirty=false,generation=0;
  const orderId=decodeURIComponent(location.pathname.split('/').pop());
  const root='/api/admin/order-design/'+encodeURIComponent(orderId);
  // This tab never reads or writes the customer's local cart/draft database.
  window.idbGet=async()=>null;window.idbSet=async()=>{};window.idbDel=async()=>{};
  window.submitOrder=()=>toast('此處只保存設計修改，不建立銷售訂單');
  window.confirmDesignToCart=save;
  window.startNewDesign=()=>false;
  window.navBack=()=>{if(document.querySelector('#page-preview.active'))navigate('page-editor');else location.href='/admin';};
  window.addEventListener('beforeunload',event=>{if(ready&&dirty){event.preventDefault();event.returnValue='';}});
  async function api(path,body){
    const r=await fetch(root+path,{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-Order-Design':'1'},body:JSON.stringify(body||{})});
    const data=await r.json();if(!r.ok||data.status!=='success')throw Error(data.msg||'設計服務暫時無法使用');return data;
  }
  async function save(){
    if(!work||saving||!ready)return;
    saving=true;
    let uploaded=null, message, notice;
    const button=document.getElementById('order-design-save');
    const review=document.getElementById('order-design-review');
    button.disabled=review.disabled=true;
    try{
      clearTimeout(historyTimer);
      recordHistory();
      const submitted=generation;
      if(work.version>=2&&!dirty){message=await BenfuwanOrderWorkspace.finish(orderId,work);return;}
      const design=await serialize();uploaded=await BenfuwanDesignSources.prepare(design);
      const result=await api('/save',{work:work.work,design:uploaded});
      message=`V${result.version} 草稿已保存；原生產圖未變更`;
      notice=result.msg;
      // The append response binds the next edit to exactly this saved version.
      work={...work,version:result.version,hash:result.hash,work:result.work};dirty=generation!==submitted;
      if(!dirty)message+='；'+await BenfuwanOrderWorkspace.finish(orderId,work);
    }catch(error){notice=error.message;message=[message,notice].filter(Boolean).join('；');}
    finally{
      try{if(uploaded)await BenfuwanDesignSources.release(uploaded);}
      finally{
        saving=false;button.disabled=review.disabled=false;
        document.getElementById('order-design-status').textContent=message;
        if(notice)toast(notice);
      }
    }
  }
  async function compare(){
    if(!work||saving||!ready)return;
    if(dirty){toast('請先儲存修改，再比較實際保存的 V1／V2');return;}
    const reviewed=work,stamp=JSON.stringify(canvas.toJSON(CUSTOM_PROPS));
    try{await BenfuwanRevisionReview.open({orderId,work:reviewed,valid:()=>!dirty&&work.hash===reviewed.hash&&JSON.stringify(canvas.toJSON(CUSTOM_PROPS))===stamp});}
    catch(error){toast(error.message);document.getElementById('order-design-status').textContent=error.message;}
  }
  async function preloadSceneFonts(objects){
    const tasks=[];
    function visit(item){
      if(['text','textbox','i-text'].includes(item.type)){
        tasks.push(item.role==='editable-sticker-text'
          ?core().font(item.fontFamily,item.text)
          :core().ordinaryFont(item.fontFamily,item.text));
      }
      (item.objects||[]).forEach(visit);
      if(item.clipPath)visit(item.clipPath);
    }
    objects.forEach(visit);
    await Promise.all(tasks);
  }
  async function boot(){
    const panel=document.createElement('div');panel.id='order-design-banner';
    panel.innerHTML='<strong>訂單設計修改</strong> <span id="order-design-status" role="status">正在驗證原始設計…</span><button id="order-design-save" disabled>完成製作</button><button id="order-design-review" disabled>版本紀錄</button>';
    const style=document.createElement('style');style.textContent='#order-design-banner{background:#fff3db;padding:8px;font-size:12px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}#order-design-save{margin-left:auto;min-height:40px;border:1px solid #ad4770;background:white;border-radius:12px;color:#ad4770;padding:6px 12px}#page-editor .topbar{flex-wrap:wrap}';document.head.append(style);
    document.querySelector('#page-editor > .top')?.after(panel);
    document.getElementById('order-design-save').onclick=save;
    document.getElementById('order-design-review').onclick=compare;
    try{
      work=await api('/open');const d=work.design,p=d.production,c=d.editorContext||{};
      const profile={preview_mask_img:c.previewPath||p.maskPath,print_line_img:p.maskPath,print_w:p.printW,print_h:p.printH,print_x:c.printX||0,print_y:c.printY||0,print_angle:c.printAngle||0};
      const model={id:d.modelId,name:c.modelName||d.modelId,status:true,brand:'訂單快照',product_type:c.productType||'phone_case',direct_style_id:d.styleId,case_profiles:{[d.styleId]:profile}};
      const style={id:d.styleId,name:c.styleName||d.styleId,status:true,product_type:model.product_type,price:1,colors:[]};
      shopData.models=[model];shopData.styles=[style];shopData.brands=['訂單快照'];
      ctx={...ctx,modelId:d.modelId,styleId:d.styleId,modelName:model.name,styleName:style.name,maskUrl:profile.preview_mask_img,printLineUrl:profile.print_line_img,printW:p.printW,printH:p.printH,printX:profile.print_x,printY:profile.print_y,printAngle:profile.print_angle,backgroundColor:d.background||'transparent',backgroundOpacity:1};
      window.BenfuwanOrderWorkspace?.openEditor();
      await startEditor(false);
      restoringHistory=true;
      canvas.setDimensions(d.logicalCanvas);
      const originalObjects=d.objects.concat(d.emptyTemplateSlots||[],d.editorGuides||[]);
      await preloadSceneFonts(originalObjects);
      await new Promise(resolve=>canvas.loadFromJSON({...d,objects:originalObjects,templateState:d.editorState},resolve));
      const intact=(expected,loaded)=>expected.length===loaded.length&&expected.every((item,i)=>{
        const object=loaded[i];
        if(!object||item.type!==object.type)return false;
        if(object.type==='image'&&!object.getElement()?.naturalWidth)return false;
        if(item.clipPath&&!intact([item.clipPath],[object.clipPath]))return false;
        return intact(item.objects||[],object._objects||[]);
      });
      if(!intact(originalObjects,canvas.getObjects()))throw Error('原始素材無法解碼，圖層未完整恢復');
      const restoreSources=(objects,assets)=>{for(const o of objects){if(o.orderOutlineSourceId){const a=assets?.find(a=>a.id===o.orderOutlineSourceId);if(!a)throw Error('描邊原始素材缺失');o.aiOutlineSource=a.src;}restoreSources(o._objects||o.objects||[],assets);}};restoreSources(canvas.getObjects(),d.sourceAssets);
      if(d.layer_contract_version){const state=structuredClone(d.editorState);restoreSources(state.initial,state.sourceAssets);canvas.layer_contract_version=d.layer_contract_version;canvas.templateState=BenfuwanMultilayer.freeze(state);}
      rehydrateCanvas();await core().textFonts(canvas);await core().rehydrate(canvas);
      await BenfuwanPrintMask.ensureClip(canvas,ctx.printLineUrl);
      restoringHistory=false;historyStack=[];historyIndex=-1;recordHistory(true);renderLayerList();canvas.renderAll();
      window.BenfuwanEditorAccess?.fitCanvas?.();
      ready=true;document.getElementById('order-design-save').disabled=false;
      document.getElementById('order-design-review').disabled=false;
      const changed=()=>{dirty=true;generation++;};
      const record=window.recordHistory;
      window.recordHistory=function(...args){
        const previous=historyStack[historyIndex];
        const result=record.apply(this,args);
        if(historyStack[historyIndex]!==previous)changed();
        return result;
      };
      if(window.BenfuwanOrderWorkspace){
        const hint=BenfuwanOrderWorkspace.addGuide(null,d.remakeNotice?'依已確認的重製設定顯示對位參考。':'使用設計版本封存的刀模與蒙版。',panel,true);
        if(!d.remakeNotice)fetch(root+'/alignment',{cache:'no-store'}).then(async response=>{
          if(!response.ok)return;
          const result=await response.json();
          if(result.note)hint.textContent=result.note;
        }).catch(()=>{});
      }
      for(const event of ['object:added','object:removed','object:modified','text:changed'])canvas.on(event,changed);
      document.getElementById('order-design-status').textContent=`訂單 ${orderId} · 正在編輯 V${work.version} 的獨立副本，尚未儲存${d.remakeNotice?' · '+d.remakeNotice:''}`;
      const previewSave=document.querySelector('.preview-buttons .primary');if(previewSave)previewSave.textContent='儲存修改（不送印）';
    }catch(error){
      console.error('Order design initialization failed',error);
      restoringHistory=false;ready=false;
      document.body.replaceChildren();const msg=document.createElement('p');msg.style.cssText='padding:24px;white-space:pre-wrap';msg.textContent='無法重新編輯此訂單\n'+error.message;
      const back=document.createElement('a');back.href='/admin';back.textContent='返回後台';document.body.append(msg,back);
      const pixel=document.createElement('a');pixel.href=location.pathname+'?pixel=1';pixel.textContent='以原始生產圖進行修改（保留排版）';pixel.style.cssText='display:block;padding:16px';document.body.append(pixel);
      const remake=document.createElement('button');remake.textContent='建立獨立重製草稿（不恢復舊圖層）';
      remake.onclick=async()=>{if(!confirm('將以目前商品設定建立空白 V2 草稿，不載入舊圖、不改原訂單、不送印。確定重新製作？'))return;remake.disabled=true;try{await api('/remake',{confirm:'new-design-current-profile'});location.reload();}catch(e){msg.textContent=e.message;remake.disabled=false;}};document.body.append(remake);
    }
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
