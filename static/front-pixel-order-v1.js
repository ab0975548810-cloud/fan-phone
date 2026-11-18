/* Pixel repair mode reuses the storefront canvas and tools, never its checkout. */
(function(){
  'use strict';
  if(!window.__bfOrderDesignMode||new URLSearchParams(location.search).get('pixel')!=='1')return;
  window.BenfuwanPixelEditor=true;
  window.idbGet=async()=>null;window.idbSet=async()=>{};window.idbDel=async()=>{};
  const order=decodeURIComponent(location.pathname.split('/').pop()),root='/api/admin/order-design/'+encodeURIComponent(order)+'/pixel';
  let work,busy=false,dirty=false,comparison,generation=0;
  const api=async(path,data)=>{const r=await fetch(root+path,{method:'POST',headers:{'Content-Type':'application/json','X-Order-Design':'1'},body:JSON.stringify(data||{})});const j=await r.json();if(!r.ok||j.status!=='success')throw Error(j.msg||'操作失敗，原圖未變更');return j;};
  const status=message=>{document.getElementById('pixel-status').textContent=message;};
  window.submitOrder=()=>toast('修補模式不建立銷售訂單');window.confirmDesignToCart=()=>save();
  window.openPreview=()=>compare();
  window.startNewDesign=()=>false;
  // Native bitmap repair has no catalog mask. The server enforces V1 alpha.
  window.applyCaseBoundaryClip=()=>{if(typeof canvas!=='undefined'&&canvas)canvas.clipPath=null;};
  window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
  const button=(text,id,fn)=>{const b=document.createElement('button');b.textContent=text;b.id=id;b.onclick=fn;return b;};
  function mark(){dirty=true;comparison=null;generation++;}
  function rasterObject(o){
    const value=o.toObject(CUSTOM_PROPS.concat(['pixelErase']));
    if(o.type==='image'){const el=o.getElement(),c=document.createElement('canvas');c.width=el.naturalWidth||el.width;c.height=el.naturalHeight||el.height;c.getContext('2d').drawImage(el,0,0);value.src=c.toDataURL('image/png');}
    if(o._objects)value.objects=o._objects.map(rasterObject);
    if(o.clipPath)value.clipPath=rasterObject(o.clipPath);
    return value;
  }
  async function save(){
    if(busy)return;busy=true;
    try{
      await ensureCanvasFonts();canvas.discardActiveObject();
      const objects=canvas.getObjects(),originalBackground=canvas.backgroundImage,view=canvas.viewportTransform.slice();
      const settings=objects.map(o=>[o,o.visible,o.objectCaching]);
      const exportOptions={format:'png',multiplier:work.design.factor,enableRetinaScaling:false,width:work.design.size[0]/work.design.factor,height:work.design.size[1]/work.design.factor};
      let overlay,erase;
      try{
        canvas.backgroundImage=null;canvas.backgroundColor='transparent';canvas.clipPath=null;canvas.setViewportTransform([1,0,0,1,0,0]);
        settings.forEach(([o,v])=>o.set({visible:v&&!o.pixelErase,objectCaching:false}));overlay=canvas.toDataURL(exportOptions);
        settings.forEach(([o,v])=>o.set('visible',v&&!!o.pixelErase));erase=canvas.toDataURL(exportOptions);
      }finally{canvas.backgroundImage=originalBackground;canvas.setViewportTransform(view);settings.forEach(([o,v,c])=>o.set({visible:v,objectCaching:c}));canvas.requestRenderAll();}
      const submitted=generation;
      const result=await api('/save',{work:work.work,overlay,erase,objects:objects.map(rasterObject)});
      work=result;dirty=generation!==submitted;comparison=null;status('V'+work.version+' 已保存；V1 原圖未變更，尚未送印'+(dirty?'；另有尚未保存的修改':''));
    }catch(e){status(e.message);}finally{busy=false;}
  }
  async function compare(){
    if(!work||busy)return;
    if(dirty){status('請先儲存修改，再比較實際保存的 V1／V2');return;}
    const reviewed=work,stamp=JSON.stringify(canvas.toJSON(CUSTOM_PROPS));
    try{await BenfuwanRevisionReview.open({orderId:order,work:reviewed,prefix:'pixel',valid:()=>!dirty&&work.hash===reviewed.hash&&JSON.stringify(canvas.toJSON(CUSTOM_PROPS))===stamp});}
    catch(e){status(e.message);}
  }
  async function boot(){
    const style=document.createElement('style');style.textContent='#pixel-tools{padding:8px;background:#fff3db;font-size:12px;flex:0 0 auto;max-height:34vh;overflow:auto}#pixel-tools button,#pixel-compare button{min-height:44px;margin:4px;max-width:100%}#pixel-compare{max-width:95vw;max-height:90vh;overflow:auto}#pixel-compare input{font-size:16px;min-height:44px;max-width:100%}.pixel-pair{display:flex;gap:8px}.pixel-pair a{width:50%;min-width:0;text-align:center}.pixel-pair img{display:block;width:100%;height:45vh;object-fit:contain;background:repeating-conic-gradient(#ddd 0% 25%,#fff 0% 50%) 0/12px 12px}';document.head.append(style);
    const tools=document.createElement('div');tools.id='pixel-tools';tools.innerHTML='<strong>原生產圖像素修補</strong><p>底圖已鎖定；合成照片／文字不能拆開編輯。透明區不擴張，不套用現行刀模。</p><p id="pixel-status" role="status">正在讀取原生產圖…</p>';
    document.querySelector('#page-editor > .top').after(tools);
    style.textContent+='#page-editor #canvas-shell{border-radius:0!important}#page-editor #safe-guide,#page-editor #phone-mask{display:none!important}';
    tools.append(button('儲存修改','pixel-save',save),button('V1／V2 比較與確認','pixel-review',compare));
    tools.append(button('新增局部遮蓋','pixel-cover',()=>{canvas.add(new fabric.Rect({left:10,top:10,width:40,height:40,fill:'#ffffff'}));mark();}));
    tools.append(button('新增擦除區（可移動／縮放）','pixel-erase',()=>{const rect=new fabric.Rect({left:10,top:10,width:40,height:40,fill:'#ff00ff',opacity:1,pixelErase:true});canvas.add(rect);canvas.setActiveObject(rect);mark();}));
    tools.append(button('返回後台','pixel-back',()=>{location.href='/admin';}));
    try{
      work=await api('/open');await loadAll();const d=work.design;
      ctx={...ctx,modelId:'pixel-original',styleId:'pixel-original',modelName:'原生產 PNG',styleName:'像素修補',printW:d.size[0]/d.factor/3,printH:d.size[1]/d.factor/3,maskUrl:'',printLineUrl:'',backgroundColor:'transparent',backgroundOpacity:0};
      document.getElementById('editor-model').textContent=ctx.modelName;document.getElementById('editor-style').textContent=ctx.styleName;
      navigate('page-editor');initCanvas();editorHasSession=true;
      canvas.setDimensions({width:d.size[0]/d.factor,height:d.size[1]/d.factor});canvas.backgroundColor='transparent';canvas.clipPath=null;
      baseClip=new fabric.Rect({left:0,top:0,width:d.size[0]/d.factor,height:d.size[1]/d.factor,absolutePositioned:true});
      // BackgroundImage is outside the selectable object list and all layer controls.
      await new Promise((ok,no)=>fabric.Image.fromURL(d.basePath,im=>{if(!im)return no(Error('V1 圖片載入失敗'));im.set({scaleX:1/d.factor,scaleY:1/d.factor,selectable:false,evented:false});canvas.setBackgroundImage(im,ok);},{crossOrigin:'anonymous'}));
      await new Promise(ok=>fabric.util.enlivenObjects(d.objects,objects=>{objects.forEach(o=>canvas.add(o));ok();}));
      for(const name of ['applyTemplate','applyTemplateById','setBackgroundColor'])if(typeof window[name]==='function')window[name]=()=>toast('像素修補不套用模板或整張背景，請新增局部遮蓋');
      window.openPreview=compare;window.confirmDesignToCart=save;
      const rehydrate=window.rehydrateCanvas;
      window.rehydrateCanvas=function(){const result=rehydrate.apply(this,arguments);canvas.backgroundImage?.set({selectable:false,evented:false});return result;};
      CUSTOM_PROPS.push('pixelErase');historyStack=[];historyIndex=-1;recordHistory(true);dirty=false;
      canvas.on('object:added',mark);canvas.on('object:removed',mark);canvas.on('object:modified',mark);
      canvas.on('after:render',()=>{canvas.backgroundColor='transparent';});
      window.BenfuwanEditorAccess?.fitCanvas?.();canvas.renderAll();status('正在編輯 V'+work.version+'；原像素 '+d.size.join(' × ')+'，720 DPI。粉紅區表示待擦除範圍，請儲存後核對實際結果。');
    }catch(e){navigate('page-editor');status(e.message);document.getElementById('pixel-save').disabled=true;}
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
