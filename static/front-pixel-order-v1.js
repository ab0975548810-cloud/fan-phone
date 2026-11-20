/* Pixel repair mode reuses the storefront canvas and tools, never its checkout. */
(function(){
  'use strict';
  if(!window.__bfOrderDesignMode||new URLSearchParams(location.search).get('pixel')!=='1')return;
  if(window.BenfuwanPixelEditor)return;
  window.BenfuwanPixelEditor=true;
  window.idbGet=async()=>null;window.idbSet=async()=>{};window.idbDel=async()=>{};
  const editorURL = new URL(location.href);
  const order=decodeURIComponent(location.pathname.split('/').pop()),root='/api/admin/order-design/'+encodeURIComponent(order)+'/pixel';
  let work,busy=false,dirty=false,generation=0,checkpointQueued=false,durableGeneration=-1;
  let checkpointWrite=Promise.resolve(), recoveryReady=false, recoveryUnavailable=false;
  const localImages=new Map();
  const props=()=>CUSTOM_PROPS.concat(['pixelErase','pixelExtractionMask','pixelExtractionBounds','pixelExtractionMaskKey']);
  const emit=(name,details={})=>window.dispatchEvent(new CustomEvent('pixel-editor-diagnostic',{detail:{name,...details}}));
  const reportRecovery=()=>{
    const el=document.getElementById('pixel-recovery');
    if(el)el.textContent=recoveryUnavailable?'本機草稿暫存失敗，請先儲存修改再離開。':dirty?(durableGeneration===generation?'已暫存至此裝置。重新載入後可繼續編輯。':'正在暫存本機草稿…'):'';
  };
  function checkpoint(){
    if(!recoveryReady||!dirty||checkpointQueued)return;
    checkpointQueued=true;reportRecovery();
    queueMicrotask(()=>{
      checkpointQueued=false;
      if(!dirty||restoringHistory||!canvas)return;
      const objects=canvas.getObjects().map(o=>o.toObject(props()));
      const serialized=JSON.stringify(objects);
      const assets=[...localImages].filter(([url])=>serialized.includes(url))
        .map(([url,asset])=>[url,asset.bytes]);
      const captured=generation,record={hash:work.hash,objects,assets};
      checkpointWrite=checkpointWrite.catch(()=>{}).then(async()=>{
        await BenfuwanPixelRecovery.write(order,record);
        durableGeneration=captured;recoveryUnavailable=false;reportRecovery();
      }).catch(error=>{
        recoveryUnavailable=true;reportRecovery();
        emit('checkpoint-error',{cause:error.name});
      });
    });
  }
  function reviveSources(value, urls){
    if(typeof value==='string')return urls.get(value)||value;
    if(Array.isArray(value))return value.map(item=>reviveSources(item,urls));
    if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,reviveSources(item,urls)]));
    return value;
  }
  async function restoreDraft(design){
    const draft=await BenfuwanPixelRecovery.read(order);
    if(!draft||draft.hash!==design.hash)return false;
    const urls=new Map();
    for(const [src,stored] of draft.assets){
      const bytes=stored instanceof Blob?await stored.arrayBuffer():stored;
      const blob=new Blob([bytes],{type:'image/png'});
      const url=URL.createObjectURL(blob);
      urls.set(src,url);localImages.set(url,{blob,bytes});
    }
    const objects=await enliven(reviveSources(draft.objects,urls));
    canvas.getObjects().slice().forEach(obj=>canvas.remove(obj));
    objects.forEach(obj=>canvas.add(obj));
    dirty=true;return true;
  }
  const enliven=objects=>new Promise((ok,no)=>fabric.util.enlivenObjects(objects,ready=>
    ready.length===objects.length?ok(ready):no(Error('部分素材無法復原，請重新開啟'))));
  function pruneImages(){
    for(const [url] of localImages){
      if(historyStack.some(scene=>scene.includes(url)))continue;
      URL.revokeObjectURL(url);localImages.delete(url);
    }
  }
  const api=async(path,data)=>{const binary=data instanceof FormData;const r=await fetch(root+path,{method:'POST',headers:binary?{'X-Order-Design':'1'}:{'Content-Type':'application/json','X-Order-Design':'1'},body:binary?data:JSON.stringify(data||{})});if(r.status===413)throw Error('修改內容超過上傳容量，請減少新增圖片後再儲存');const j=await r.json();if(!r.ok||j.status!=='success')throw Error(j.msg||'操作失敗，原圖未變更');return j;};
  const status=message=>{document.getElementById('pixel-status').textContent=message;};
  window.submitOrder=()=>toast('修補模式不建立銷售訂單');window.confirmDesignToCart=()=>save();
  window.openPreview=()=>compare();
  window.startNewDesign=()=>false;
  window.navBack=()=>document.getElementById('pixel-back')?.click();
  // Native bitmap repair has no catalog mask. The server enforces V1 alpha.
  window.applyCaseBoundaryClip=()=>{if(typeof canvas!=='undefined'&&canvas)canvas.clipPath=null;};
  window.addEventListener('beforeunload',e=>{if(dirty&&durableGeneration!==generation){e.preventDefault();e.returnValue='';}});
  const button=(text,id,fn)=>{const b=document.createElement('button');b.textContent=text;b.id=id;b.onclick=fn;return b;};
  let clearOriginal=false,selecting=false,manualSelecting=false,firstCorner=null,originalPreview=null,previewBitmap=null,previewBackground=null,originalBackground=null;
  const fabricImage=url=>new Promise((resolve,reject)=>fabric.Image.fromURL(url,im=>im?resolve(im):reject(Error('提取素材無法載入')),{crossOrigin:'anonymous'}));
  let contour=null;
  function updateSelectionMode(){
    canvas.skipTargetFind=Boolean(selecting||manualSelecting||contour);
    if(canvas.skipTargetFind)canvas.discardActiveObject();
    canvas.requestRenderAll();
  }
  function rebuildBackground(){
    if(!originalPreview||!canvas)return;
    const masks=canvas.getObjects().filter(obj=>obj.pixelExtractionMask&&obj.type==='image');
    const w=canvas.getWidth(),h=canvas.getHeight();
    if(!masks.length){
      canvas.setBackgroundImage(originalBackground,()=>canvas.requestRenderAll());
      return;
    }
    if(!previewBitmap){
      previewBitmap=document.createElement('canvas');
      previewBitmap.width=Math.ceil(w);previewBitmap.height=Math.ceil(h);
      previewBackground=new fabric.Image(previewBitmap,{
        scaleX:w/previewBitmap.width,scaleY:h/previewBitmap.height,
        selectable:false,evented:false,objectCaching:false
      });
    }
    const context=previewBitmap.getContext('2d');
    context.setTransform(previewBitmap.width/w,0,0,previewBitmap.height/h,0,0);
    context.clearRect(0,0,w,h);
    context.drawImage(originalPreview,0,0,w,h);
    context.globalCompositeOperation='destination-out';
    for(const obj of masks){
      const source=obj.getElement();
      if(source)context.drawImage(source,obj.left,obj.top,obj.width*obj.scaleX,obj.height*obj.scaleY);
    }
    context.globalCompositeOperation='source-over';
    canvas.setBackgroundImage(previewBackground,()=>canvas.requestRenderAll());
  }
  async function extractionImage(source){
    const prefix='data:image/png;base64,', parts=[];
    if(!source.startsWith(prefix))throw Error('提取素材格式錯誤');
    for(let i=prefix.length;i<source.length;i+=32768){
      const segment=atob(source.slice(i,i+32768));
      parts.push(Uint8Array.from(segment,ch=>ch.charCodeAt(0)));
    }
    const blob=new Blob(parts,{type:'image/png'});
    const url=URL.createObjectURL(blob);
    try{return {image:await fabricImage(url),url,blob,bytes:await blob.arrayBuffer()};}
    catch(error){URL.revokeObjectURL(url);throw error;}
  }
  async function extractAt(point,rectangle=null,polygon=null){
    if(busy||!work)return;
    busy=true;status('正在從原圖提取素材…');
    const loaded=[];
    try{
      const payload=polygon?{work:work.work,polygon}:rectangle?{work:work.work,rectangle}:{work:work.work,x:point.x,y:point.y};
      if(clearOriginal)payload.clear=true;
      const result=await api('/extract',payload);
      const bounds=result.bounds,factor=work.design.factor;
      const key=result.eraseHash+':'+bounds.join(',');
      const existing=canvas.getObjects().find(o=>o.pixelExtractionMaskKey===key);
      if(existing&&!clearOriginal&&!rectangle&&!polygon){status('原圖此處已清除，可點選移動後的圖層。');return;}
      if(clearOriginal&&existing){status('原圖選取區已清除；後加圖層可分開刪除。');return;}
      const pictureAsset=clearOriginal?null:await extractionImage(result.cutout);
      if(pictureAsset)loaded.push(pictureAsset);
      const maskAsset=existing?null:await extractionImage(result.erase);
      if(maskAsset)loaded.push(maskAsset);
      for(const {url,blob,bytes} of loaded)localImages.set(url,{blob,bytes});
      const placement={left:bounds[0]/factor,top:bounds[1]/factor,scaleX:1/factor,scaleY:1/factor};
      if(maskAsset){
        maskAsset.image.set({...placement,pixelErase:true,pixelExtractionMask:true,pixelExtractionMaskKey:key,
          visible:false,selectable:false,evented:false,objectCaching:false});
        canvas.add(maskAsset.image);
      }
      if(pictureAsset){
        pictureAsset.image.set({...placement,pixelExtractionBounds:bounds,objectCaching:false});
        canvas.add(pictureAsset.image);
        canvas.setActiveObject(pictureAsset.image);
      }
      rebuildBackground();canvas.requestRenderAll();mark();recordHistory();
      status(clearOriginal?'已清除原圖選取區；可用「上一步」復原。原始 V1 不變。':
        '已提取 '+result.pixels+' 個像素；可移動、縮放、旋轉或刪除提取圖層。原始 V1 不變。');
    }catch(error){status(error.message);}
    finally{
      for(const asset of loaded)if(!localImages.has(asset.url))URL.revokeObjectURL(asset.url);
      if(clearOriginal){
        clearOriginal=false;
        document.getElementById('pixel-clear-original').setAttribute('aria-pressed','false');
      }
      busy=false;pruneImages();
    }
  }
  function mark(){dirty=true;generation++;checkpoint();}
  async function rasterObject(o,form,uploads){
    const value=o.toObject(props());
    if(o.type==='image' && !/^data:image\/png;base64,/.test(value.src)){
      const src=new URL(value.src,location.href);
      const archived=root+'/assets/';
      const reference=src.pathname.slice(archived.length).match(/^\d+\/[a-f0-9]{64}$/);
      if(src.origin===location.origin&&src.pathname.startsWith(archived)&&reference){
        value.src=src.pathname;
      }else{
        let name=uploads.get(value.src);
        if(!name){
          name='layer-'+uploads.size;
          let blob=localImages.get(value.src)?.blob;
          if(!blob){
            const el=o.getElement(),bitmap=document.createElement('canvas');
            bitmap.width=el.naturalWidth||el.width;bitmap.height=el.naturalHeight||el.height;
            try{bitmap.getContext('2d').drawImage(el,0,0);blob=await pngBlob(bitmap);}
            finally{bitmap.width=bitmap.height=0;}
          }
          form.append(name,blob,name+'.png');
          uploads.set(value.src,name);
        }
        value.src=name;
      }
    }
    if(o._objects){
      value.objects=[];
      for(const child of o._objects)value.objects.push(await rasterObject(child,form,uploads));
    }
    if(o.clipPath)value.clipPath=await rasterObject(o.clipPath,form,uploads);
    return value;
  }
  const pngBlob=bitmap=>new Promise((ok,no)=>bitmap.toBlob(
    blob=>blob?.size?ok(blob):no(Error('圖片編碼失敗，請重試')),'image/png'));
  const tileEdge=1024;
  function renderTile(design,objects,name,x,y,width,height){
    const background=canvas.backgroundImage,view=canvas.viewportTransform.slice();
    const skip=canvas.skipOffscreen;
    const settings=objects.map(o=>[o,o.visible,o.objectCaching]);
    try{
      canvas.backgroundImage=null;
      canvas.skipOffscreen=false;
      canvas.setViewportTransform([1,0,0,1,0,0]);
      settings.forEach(([o,v])=>o.set({visible:name==='erase'?!!o.pixelErase&&v&&!o.pixelExtractionMask:v&&!o.pixelErase,objectCaching:false}));
      return canvas.toCanvasElement(design.factor,{
        left:x/design.factor,top:y/design.factor,
        width:(width+.001)/design.factor,height:(height+.001)/design.factor
      });
    }finally{
      canvas.backgroundImage=background;canvas.skipOffscreen=skip;canvas.setViewportTransform(view);
      settings.forEach(([o,v,c])=>o.set({visible:v,objectCaching:c}));canvas.requestRenderAll();
    }
  }
  function drawNativeErasure(bitmap, objects, factor, x, y){
    const context=bitmap.getContext('2d');
    for(const obj of objects){
      if(!obj.pixelExtractionMask)continue;
      const source=obj.getElement();
      if(!source)continue;
      const position=obj.pixelExtractionMaskKey?.split(':')[1]?.split(',').map(Number);
      const left=(position?.length===4?position[0]:Math.round(obj.left*factor))-x;
      const top=(position?.length===4?position[1]:Math.round(obj.top*factor))-y;
      // Extracted alpha is already binary at native pixel resolution.
      // Draw at integer coordinates without resampling the erase boundary.
      context.drawImage(source,left,top);
    }
  }
  async function save(){
    if(busy)return;busy=true;
    try{
      if(work.version>=2&&!dirty){status(await BenfuwanOrderWorkspace.finish(order,work));return;}
      await ensureCanvasFonts();canvas.discardActiveObject();
      clearTimeout(historyTimer);recordHistory();
      const submitted=generation, objects=canvas.getObjects().slice(), design=work.design;
      const form=new FormData();
      form.append('work',work.work);
      await Promise.resolve();await checkpointWrite;
      const uploads=new Map(), serial=[];
      for(const object of objects)serial.push(await rasterObject(object,form,uploads));
      form.append('objects',new Blob([JSON.stringify(serial)],{type:'application/json'}),'objects.json');
      form.append('tiles','1024');
      const [fullWidth,fullHeight]=design.size;
      const exportStart=performance.now();
      for(const name of ['overlay','erase']){
        status(name==='overlay'?'正在儲存圖層…':'正在儲存擦除範圍…');
        for(let y=0;y<fullHeight;y+=tileEdge){
          for(let x=0;x<fullWidth;x+=tileEdge){
            if(generation!==submitted||restoringHistory)throw Error('畫布已變更，請重新儲存');
            const width=Math.min(tileEdge,fullWidth-x),height=Math.min(tileEdge,fullHeight-y);
            const bitmap=renderTile(design,objects,name,x,y,width,height);
            try{
              if(bitmap.width!==width||bitmap.height!==height)throw Error('高解析度畫布尺寸不符，請重新開啟再試');
              if(name==='erase')drawNativeErasure(bitmap,objects,design.factor,x,y);
              form.append(name+'-'+x+'-'+y,await pngBlob(bitmap),name+'.png');
            }finally{bitmap.width=bitmap.height=0;}
          }
        }
      }
      emit('export',{ms:performance.now()-exportStart,pixels:tileEdge*tileEdge});
      if(generation!==submitted||restoringHistory)throw Error('畫布已變更，請重新儲存');
      const result=await api('/save',form);
      work=result;dirty=generation!==submitted;
      if(dirty){checkpoint();}
      else{
        try{await BenfuwanPixelRecovery.remove(order);}
        catch(e){emit('checkpoint-error');}
        reportRecovery();
      }
      if(dirty)status('V'+work.version+' 已保存；V1 原圖未變更'+(work.design.proof?.alphaExpansion?'；此版移至原透明區，僅可保存／比較，禁止送印':'；尚未送印')+(dirty?'；另有尚未保存的修改':''));
      if(!dirty)status(await BenfuwanOrderWorkspace.finish(order,work));
    }catch(e){status(e.message);}finally{busy=false;}
  }
  async function compare(){
    if(!work||busy)return;
    if(dirty){status('請先儲存修改，再比較實際保存的 V1／V2');return;}
    const layers=()=>JSON.stringify(canvas.getObjects().map(o=>o.toObject(CUSTOM_PROPS)));
    const reviewed=work,stamp=layers();
    try{await BenfuwanRevisionReview.open({orderId:order,work:reviewed,prefix:'pixel',valid:()=>!dirty&&work.hash===reviewed.hash&&layers()===stamp});}
    catch(e){status(e.message);}
  }
  async function boot(){
    const style=document.createElement('style');style.textContent='#pixel-tools{padding:8px;background:#fff3db;font-size:12px;flex:0 0 auto;max-height:34vh;overflow:auto}#pixel-tools button,#pixel-compare button{min-height:44px;margin:4px;max-width:100%}#pixel-compare{max-width:95vw;max-height:90vh;overflow:auto}#pixel-compare input{font-size:16px;min-height:44px;max-width:100%}.pixel-pair{display:flex;gap:8px}.pixel-pair a{width:50%;min-width:0;text-align:center}.pixel-pair img{display:block;width:100%;height:45vh;object-fit:contain;background:repeating-conic-gradient(#ddd 0% 25%,#fff 0% 50%) 0/12px 12px}';document.head.append(style);
    const tools=document.createElement('div');tools.id='pixel-tools';tools.innerHTML='<strong>原生產圖像素修補</strong><p>點選獨立圖案，或沿相連素材的邊緣圈選，再拖曳調整位置。</p><p id="pixel-status" role="status">正在讀取原生產圖…</p><p id="pixel-recovery" aria-live="polite"></p>';
    document.querySelector('#page-editor > .top').after(tools);
    style.textContent+='#page-editor #canvas-shell{border-radius:0!important}#page-editor #safe-guide,#page-editor #phone-mask{display:none!important}';
    tools.append(button('完成製作','pixel-save',save),button('版本紀錄','pixel-review',compare));
    document.querySelectorAll('button[onclick="deleteActive()"]').forEach(b=>{b.textContent='刪除選取圖層';});
    const extra=document.createElement('details');extra.id='pixel-extra';extra.innerHTML='<summary>更多操作／手動圈選</summary>';tools.append(extra);
    extra.append(button('手動框選素材（點兩個角落）','pixel-rectangle',()=>{if(!work||busy)return;contour=null;manualSelecting=!manualSelecting;selecting=false;firstCorner=null;updateSelectionMode();status(manualSelecting?'請依序點選圖案範圍的左上、右下兩角；可能會切到相鄰圖案，需人工檢查。':'已取消手動框選。');}));
    extra.append(button('沿輪廓點選','pixel-contour',()=>{
      if(!work||busy)return;
      selecting=manualSelecting=false;firstCorner=null;contour=contour?null:[];
      updateSelectionMode();status(contour?'沿素材邊緣依序點選，再按「完成圈選」。再次按此鍵可取消。':'已取消圈選');
    }),button('完成圈選','pixel-contour-done',()=>{
      if(busy)return;
      if(!contour||contour.length<3){status('請先沿素材邊緣選至少三點');return;}
      const polygon=contour;contour=null;updateSelectionMode();void extractAt(null,null,polygon);
    }),button('退回一點','pixel-contour-undo',()=>{
      if(!busy&&contour?.length){contour.pop();canvas.requestRenderAll();status('圈選已標記 '+contour.length+' 點');}
    }));
    const clearButton=button('清除原圖選取區','pixel-clear-original',()=>{
      if(!work||busy)return;
      clearOriginal=!clearOriginal;
      clearButton.setAttribute('aria-pressed',String(clearOriginal));
      contour=null;manualSelecting=false;firstCorner=null;selecting=clearOriginal;
      updateSelectionMode();
      status(clearOriginal?'清除模式：可點選原圖、手動框選或沿輪廓圈選。只清除原圖選取區。':'已離開原圖清除模式。');
    });
    clearButton.setAttribute('aria-pressed','false');
    extra.append(clearButton);
    extra.append(button('新增局部遮蓋','pixel-cover',()=>{canvas.add(new fabric.Rect({left:10,top:10,width:40,height:40,fill:'#ffffff'}));mark();}));
    extra.append(button('新增擦除區（可移動／縮放）','pixel-erase',()=>{const rect=new fabric.Rect({left:10,top:10,width:40,height:40,fill:'#ff00ff',opacity:1,pixelErase:true});canvas.add(rect);canvas.setActiveObject(rect);mark();}));
    tools.append(button('返回後台','pixel-back',async()=>{
      if(busy||restoringHistory)return;
      clearTimeout(historyTimer);recordHistory();
      await Promise.resolve();await checkpointWrite;
      if(recoveryUnavailable&&dirty&&!confirm('本機草稿尚未備妥，確定離開？'))return;
      location.href='/admin';
    }));
    try{
      work=await api('/open');const d=work.design;
      ctx={...ctx,modelId:'pixel-original',styleId:'pixel-original',modelName:'原生產 PNG',styleName:'像素修補',printW:d.size[0]/d.factor/3,printH:d.size[1]/d.factor/3,maskUrl:'',printLineUrl:'',backgroundColor:'transparent',backgroundOpacity:0};
      document.getElementById('editor-model').textContent=ctx.modelName;document.getElementById('editor-style').textContent=ctx.styleName;
      if(window.BenfuwanOrderWorkspace)BenfuwanOrderWorkspace.openEditor();
      else{editorURL.hash='editor';history.replaceState({page:'page-editor'},'',editorURL);showPage('page-editor');}
      initCanvas();editorHasSession=true;
      canvas.setDimensions({width:d.size[0]/d.factor,height:d.size[1]/d.factor});canvas.backgroundColor='transparent';canvas.clipPath=null;
      baseClip=new fabric.Rect({left:0,top:0,width:d.size[0]/d.factor,height:d.size[1]/d.factor,absolutePositioned:true});
      // BackgroundImage is outside the selectable object list and all layer controls.
      await new Promise((ok,no)=>fabric.Image.fromURL(d.previewPath||d.basePath,im=>{if(!im)return no(Error('V1 預覽圖載入失敗'));originalPreview=im.getElement();im.set({scaleX:canvas.getWidth()/im.width,scaleY:canvas.getHeight()/im.height,selectable:false,evented:false});originalBackground=im;im.objectCaching=false;canvas.setBackgroundImage(im,ok);},{crossOrigin:'anonymous'}));
      (await enliven(d.objects)).forEach(o=>canvas.add(o));
      let recovered=false;
      try{recovered=await restoreDraft(work);}
      catch(e){recoveryUnavailable=true;reportRecovery();emit('checkpoint-error',{cause:e.name});}
      for(const name of ['applyTemplate','applyTemplateById','setBackgroundColor'])if(typeof window[name]==='function')window[name]=()=>toast('像素修補不套用模板或整張背景，請新增局部遮蓋');
      window.openPreview=save;window.confirmDesignToCart=save;
      const rehydrate=window.rehydrateCanvas;
      window.rehydrateCanvas=function(){
        const result=rehydrate.apply(this,arguments);
        for(const obj of canvas.getObjects()){
          if(obj.pixelExtractionMask)obj.set({visible:false,selectable:false,evented:false});
          obj.objectCaching=false;
        }
        rebuildBackground();
        mark();
        return result;
      };
      const originalRecord=window.recordHistory;
      window.recordHistory=function(...args){
        const background=canvas.backgroundImage;
        canvas.backgroundImage=null;
        const previous=historyStack[historyIndex];
        try{return originalRecord.apply(this,args);}
        finally{
          canvas.backgroundImage=background;
          if(recoveryReady&&historyStack[historyIndex]!==previous)mark();
          pruneImages();
        }
      };
      for(const field of ['pixelErase','pixelExtractionMask','pixelExtractionBounds','pixelExtractionMaskKey'])if(!CUSTOM_PROPS.includes(field))CUSTOM_PROPS.push(field);
      historyStack=[];historyIndex=-1;
      window.rehydrateCanvas();dirty=recovered;recordHistory(true);recoveryReady=true;
      if(recovered)durableGeneration=generation;
      if(recovered||recoveryUnavailable)reportRecovery();
      for(const name of ['undoCanvas','redoCanvas']){
        const original=window[name];
        window[name]=function(){
          if(!busy&&!restoringHistory){
            clearTimeout(historyTimer);
            recordHistory();
            return original.apply(this,arguments);
          }
        };
      }
      const layerChanged=event=>{
        if(restoringHistory)return;
        if(event.target)event.target.objectCaching=false;
        mark();
        if(event.target?.pixelExtractionMask)rebuildBackground();
      };
      canvas.on('object:added',layerChanged);
      canvas.on('object:removed',layerChanged);
      canvas.on('object:modified',mark);
      let tap=null;
      const sample=document.createElement('canvas');sample.width=sample.height=1;
      const pixel=sample.getContext('2d',{willReadFrequently:true});
      canvas.on('mouse:down',event=>{
        tap=null;
        if(busy||event.target)return;
        const point=canvas.getPointer(event.e);
        if(contour){
          if(contour.length>=256){status('已達 256 點，請完成圈選或退回一點');return;}
          contour.push([point.x,point.y]);canvas.requestRenderAll();status('圈選已標記 '+contour.length+' 點');return;
        }
        if(manualSelecting){
          if(!firstCorner){firstCorner=point;status('已記錄第一個角落，請點第二個角落。');return;}
          const rectangle=[firstCorner.x,firstCorner.y,point.x,point.y];
          manualSelecting=false;firstCorner=null;updateSelectionMode();void extractAt(point,rectangle);return;
        }
        if(!selecting){tap=canvas.getPointer(event.e,true);return;}
        selecting=false;updateSelectionMode();void extractAt(point);
      });
      rebuildBackground();
      canvas.upperCanvasEl.addEventListener('touchstart',e=>{if(e.touches.length>1)tap=null;},{passive:true});
      canvas.upperCanvasEl.addEventListener('touchcancel',()=>{tap=null;});
      canvas.on('mouse:move',event=>{
        if(!tap)return;
        const p=canvas.getPointer(event.e,true);
        if(Math.hypot(tap.x-p.x,tap.y-p.y)>6)tap=null;
      });
      canvas.on('mouse:up',event=>{
        if(!tap)return;
        tap=null;
        if(busy||event.target||restoringHistory)return;
        const p=canvas.getPointer(event.e),bg=canvas.backgroundImage?.getElement();
        if(!bg)return;
        pixel.clearRect(0,0,1,1);
        pixel.drawImage(bg,Math.floor(p.x*bg.width/canvas.getWidth()),Math.floor(p.y*bg.height/canvas.getHeight()),1,1,0,0,1,1);
        if(pixel.getImageData(0,0,1,1).data[3])void extractAt(p);
      });
      canvas.on('after:render',({ctx})=>{
        canvas.backgroundColor='transparent';
        if(!contour?.length||ctx?.canvas!==canvas.lowerCanvasEl)return;
        ctx.save();ctx.transform(...canvas.viewportTransform);ctx.strokeStyle='#0671ba';ctx.fillStyle='#0671ba';
        ctx.beginPath();contour.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.closePath();ctx.stroke();
        for(const [x,y] of contour)ctx.fillRect(x-2,y-2,4,4);ctx.restore();
      });
      if(window.BenfuwanOrderWorkspace){
        fetch(root+'/alignment',{cache:'no-store'}).then(async response=>{
          if(!response.ok)throw Error();
          const guide=await response.json();
          if(guide.modelName)document.getElementById('editor-model').textContent=guide.modelName;
          if(guide.styleName)document.getElementById('editor-style').textContent=guide.styleName;
          window.BenfuwanOrderWorkspace.addGuide(guide.guide,guide.note,tools);
        }).catch(()=>window.BenfuwanOrderWorkspace.addGuide(null,'原始蒙版暫時無法讀取。',tools));
      }
      window.BenfuwanEditorAccess?.fitCanvas?.();canvas.renderAll();status('正在編輯 V'+work.version+'；已使用輕量預覽。原始 720 DPI 保留，提取後可單獨移動。若移入 V1 完全透明區，可保存與比較，但無法送印。'+(recovered?' 已復原此裝置的未儲存草稿。':''));
    }catch(e){window.BenfuwanOrderWorkspace?.openEditor();status(e.message);document.getElementById('pixel-save').disabled=true;}
  }
  window.addEventListener('pagehide',event=>{
    if(event.persisted)return;
    for(const [url] of localImages)URL.revokeObjectURL(url);
    localImages.clear();
    if(canvas){
      canvas.backgroundImage=null;
      canvas.dispose();
      canvas=null;
    }
    if(previewBitmap)previewBitmap.width=previewBitmap.height=0;
    previewBitmap=previewBackground=originalPreview=originalBackground=null;
  });
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
