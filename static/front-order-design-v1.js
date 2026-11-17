/* Order recovery uses the existing storefront editor, in an isolated admin mode. */
(function(){
  'use strict';
  const core=()=>window.BenfuwanEditableSticker;
  for(const key of ['aiOutlineSource','aiRemovalMode','aiOutlineStyle','aiOutlineStrength','aiOutlineWidth','aiOutlineColor'])if(!CUSTOM_PROPS.includes(key))CUSTOM_PROPS.push(key);
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
  let work=null,saving=false,ready=false;
  const orderId=decodeURIComponent(location.pathname.split('/').pop());
  const root='/api/admin/order-design/'+encodeURIComponent(orderId);
  // This tab never reads or writes the customer's local cart/draft database.
  window.idbGet=async()=>null;window.idbSet=async()=>{};window.idbDel=async()=>{};
  window.submitOrder=()=>toast('此處只保存設計修改，不建立銷售訂單');
  window.confirmDesignToCart=save;
  window.startNewDesign=()=>false;
  window.navBack=()=>{if(document.querySelector('#page-preview.active'))navigate('page-editor');else location.href='/admin';};
  window.addEventListener('beforeunload',event=>{if(ready){event.preventDefault();event.returnValue='';}});
  async function api(path,body){
    const r=await fetch(root+path,{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-Order-Design':'1'},body:JSON.stringify(body||{})});
    const data=await r.json();if(!r.ok||data.status!=='success')throw Error(data.msg||'設計服務暫時無法使用');return data;
  }
  async function save(){
    if(!work||saving||!ready)return;
    saving=true;let uploaded=null;
    const button=document.getElementById('order-design-save');button.disabled=true;
    try{
      const design=await serialize();uploaded=await BenfuwanDesignSources.prepare(design);
      const result=await api('/save',{work:work.work,design:uploaded});
      document.getElementById('order-design-status').textContent=`V${result.version} 草稿已保存；原生產圖未變更`;
      toast(result.msg);ready=false;
      // Renew the work token after a confirmed append, allowing the next explicit save.
      work=await api('/open');ready=true;
    }catch(error){toast(error.message);document.getElementById('order-design-status').textContent=error.message;}
    finally{if(uploaded)await BenfuwanDesignSources.release(uploaded);saving=false;button.disabled=false;}
  }
  async function boot(){
    const panel=document.createElement('div');panel.id='order-design-banner';
    panel.innerHTML='<strong>訂單設計修改</strong> <span id="order-design-status" role="status">正在驗證原始設計…</span><button id="order-design-save" disabled>儲存修改</button>';
    const style=document.createElement('style');style.textContent='#order-design-banner{background:#fff3db;padding:8px;font-size:12px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}#order-design-save{margin-left:auto;min-height:40px;border:1px solid #ad4770;background:white;border-radius:12px;color:#ad4770;padding:6px 12px}#page-editor .topbar{flex-wrap:wrap}';document.head.append(style);
    document.querySelector('#page-editor > .top')?.after(panel);
    document.getElementById('order-design-save').onclick=save;
    try{
      work=await api('/open');await loadAll();const d=work.design,p=d.production,c=d.editorContext||{};
      const profile={preview_mask_img:c.previewPath||p.maskPath,print_line_img:p.maskPath,print_w:p.printW,print_h:p.printH,print_x:c.printX||0,print_y:c.printY||0,print_angle:c.printAngle||0};
      const model={id:d.modelId,name:c.modelName||d.modelId,status:true,brand:'訂單快照',product_type:c.productType||'phone_case',direct_style_id:d.styleId,case_profiles:{[d.styleId]:profile}};
      const style={id:d.styleId,name:c.styleName||d.styleId,status:true,product_type:model.product_type,price:1,colors:[]};
      shopData.models=[model];shopData.styles=[style];shopData.brands=['訂單快照'];
      ctx={...ctx,modelId:d.modelId,styleId:d.styleId,modelName:model.name,styleName:style.name,maskUrl:profile.preview_mask_img,printLineUrl:profile.print_line_img,printW:p.printW,printH:p.printH,printX:profile.print_x,printY:profile.print_y,printAngle:profile.print_angle,backgroundColor:d.background||'transparent',backgroundOpacity:1};
      await startEditor(false);
      restoringHistory=true;
      canvas.setDimensions(d.logicalCanvas);
      // Preflight actual decoding so Fabric cannot silently drop missing images.
      const images=[];const scan=items=>{for(const o of items||[]){if(o.type==='image')images.push(o.src);scan(o.objects);if(o.clipPath)scan([o.clipPath]);}};scan(d.objects);
      await Promise.all([...new Set(images)].map(url=>new Promise((resolve,reject)=>{const im=new Image();im.onload=resolve;im.onerror=()=>reject(Error('原始素材無法解碼，設計尚未開啟'));im.src=url;})));
      await new Promise(resolve=>canvas.loadFromJSON({...d,objects:d.objects.concat(d.emptyTemplateSlots||[],d.editorGuides||[]),templateState:d.editorState},resolve));
      if(canvas.getObjects().length!==d.objects.length+(d.emptyTemplateSlots||[]).length+(d.editorGuides||[]).length)throw Error('圖層未完整恢復');
      const restoreSources=(objects,assets)=>{for(const o of objects){if(o.orderOutlineSourceId){const a=assets?.find(a=>a.id===o.orderOutlineSourceId);if(!a)throw Error('描邊原始素材缺失');o.aiOutlineSource=a.src;}restoreSources(o._objects||o.objects||[],assets);}};restoreSources(canvas.getObjects(),d.sourceAssets);
      if(d.layer_contract_version){const state=structuredClone(d.editorState);restoreSources(state.initial,state.sourceAssets);canvas.layer_contract_version=d.layer_contract_version;canvas.templateState=BenfuwanMultilayer.freeze(state);}
      rehydrateCanvas();await core().textFonts(canvas);await core().rehydrate(canvas);
      await BenfuwanPrintMask.ensureClip(canvas,ctx.printLineUrl);
      restoringHistory=false;historyStack=[];historyIndex=-1;recordHistory(true);renderLayerList();canvas.renderAll();
      window.BenfuwanEditorAccess?.fitCanvas?.();
      ready=true;document.getElementById('order-design-save').disabled=false;
      document.getElementById('order-design-status').textContent=`訂單 ${orderId} · 正在編輯 V${work.version} 的獨立副本，尚未儲存`;
      const previewSave=document.querySelector('.preview-buttons .primary');if(previewSave)previewSave.textContent='儲存修改（不送印）';
    }catch(error){
      restoringHistory=false;ready=false;
      document.body.replaceChildren();const msg=document.createElement('p');msg.style.cssText='padding:24px;white-space:pre-wrap';msg.textContent='無法重新編輯此訂單\n'+error.message;
      const back=document.createElement('a');back.href='/admin';back.textContent='返回後台';document.body.append(msg,back);
    }
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
