/* 本福丸模板編輯器 v4：順暢操作、自動壓縮、背景/文字、AI 摳圖、智慧補邊 */
(function(){
  'use strict';
  if(window.__benfuwanTemplateEditorV4Installed)return;
  window.__benfuwanTemplateEditorV4Installed=true;

  const by=id=>document.getElementById(id);
  let hookedCanvas=null;
  let busy=false;

  const status=msg=>{const e=by('bf-tpl-status');if(e)e.textContent=msg};
  const isImage=o=>!!o&&o.type==='image'&&!o.isTplBg;
  const isText=o=>!!o&&['text','textbox','i-text'].includes(o.type);

  function addCss(){
    if(by('bf-tpl-v4-css'))return;
    const s=document.createElement('style');s.id='bf-tpl-v4-css';s.textContent=`
      #template-modal .editor{touch-action:none}
      #template-modal .canvas-container{touch-action:none!important}
      #bf-tpl-frontbar{grid-template-columns:repeat(8,minmax(0,1fr))!important}
      .bf-v4-panel{display:none;margin-top:8px;padding:11px;border:1px solid #efdfe5;background:#fff;border-radius:14px}.bf-v4-panel.show{display:block}
      .bf-v4-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:9px;color:#d95580;font-size:12px;font-weight:900}.bf-v4-head button{border:1px solid #efd3dc;background:#fff;border-radius:999px;color:#d95580;padding:5px 9px;font-size:10px;font-weight:800}
      .bf-v4-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.bf-v4-field label{display:block;font-size:10px;color:#887b81;font-weight:850;margin-bottom:4px}.bf-v4-field input,.bf-v4-field select{width:100%;border:1px solid #eadde2;border-radius:10px;background:#fff;padding:8px}
      .bf-v4-swatches{display:flex;gap:7px;flex-wrap:wrap}.bf-v4-swatch{width:34px;height:34px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 0 1px #e6d7dc;cursor:pointer}.bf-v4-bg-card{height:52px;border:1px solid #eadde2;border-radius:12px;cursor:pointer;position:relative;overflow:hidden}.bf-v4-bg-card span{position:absolute;left:6px;bottom:5px;font-size:9px;font-weight:900;background:rgba(255,255,255,.88);padding:2px 5px;border-radius:999px}
      #bf-tpl-ai-panel-v4 .bf-v4-actions{display:flex;gap:8px;flex-wrap:wrap}.bf-v4-action{border:1px solid #f0cbd6;background:#fff7fa;color:#d95580;border-radius:999px;padding:8px 12px;font-size:11px;font-weight:900}.bf-v4-action.primary{background:#ff6f9a;color:#fff;border-color:#ff6f9a}.bf-v4-action:disabled{opacity:.45}
      .bf-v4-note{font-size:10px;line-height:1.6;color:#8e8288;margin-top:8px}.bf-v4-progress{display:none;margin-top:8px;padding:8px 10px;border-radius:10px;background:#fff3f7;color:#d95580;font-size:11px;font-weight:850}.bf-v4-progress.show{display:block}
      #bf-tpl-objectbar .bf-ai-btn,#bf-tpl-objectbar .bf-expand-btn{display:none}#bf-tpl-objectbar.has-image .bf-ai-btn,#bf-tpl-objectbar.has-image .bf-expand-btn{display:inline-block}
      @media(max-width:900px){#bf-tpl-frontbar{grid-template-columns:repeat(4,minmax(0,1fr))!important}.bf-v4-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
      @media(max-width:560px){#bf-tpl-frontbar{grid-template-columns:repeat(4,minmax(0,1fr))!important}.bf-v4-grid{grid-template-columns:1fr 1fr}}
    `;document.head.appendChild(s);
  }

  function ensureUi(){
    addCss();
    const bar=by('bf-tpl-frontbar');
    if(bar&&!by('bf-tpl-ai-v4')){
      const ai=document.createElement('button');ai.className='bf-tpl-main-tool';ai.id='bf-tpl-ai-v4';ai.innerHTML='<span class="ico"><i class="fa-solid fa-wand-magic-sparkles"></i></span>AI 摳圖';ai.onclick=()=>runRemoveBg();bar.appendChild(ai);
      const ex=document.createElement('button');ex.className='bf-tpl-main-tool';ex.id='bf-tpl-expand-v4';ex.innerHTML='<span class="ico"><i class="fa-solid fa-expand"></i></span>智慧補邊';ex.onclick=()=>runSmartExpand();bar.appendChild(ex);
    }
    const obj=by('bf-tpl-objectbar');
    if(obj&&!obj.querySelector('.bf-ai-btn')){
      const ai=document.createElement('button');ai.className='bf-ai-btn';ai.textContent='AI 摳圖';ai.onclick=()=>runRemoveBg();obj.insertBefore(ai,obj.lastElementChild);
      const ex=document.createElement('button');ex.className='bf-expand-btn';ex.textContent='智慧補邊';ex.onclick=()=>runSmartExpand();obj.insertBefore(ex,obj.lastElementChild);
    }
    const tools=by('bf-tpl-tools');
    if(tools&&!by('bf-tpl-bg-advanced-v4')){
      const bg=document.createElement('div');bg.id='bf-tpl-bg-advanced-v4';bg.className='bf-v4-panel';bg.innerHTML=`
        <div class="bf-v4-head"><span>進階背景</span><button data-close>收起</button></div>
        <div class="bf-v4-swatches" id="bf-v4-bg-swatches"></div>
        <div class="bf-v4-grid" style="margin-top:10px">
          <div class="bf-v4-bg-card" data-bg="pink" style="background:linear-gradient(135deg,#fff1f6,#ffc9da)"><span>粉色漸層</span></div>
          <div class="bf-v4-bg-card" data-bg="cream" style="background:linear-gradient(135deg,#fffaf1,#f4dfbd)"><span>奶油漸層</span></div>
          <div class="bf-v4-bg-card" data-bg="lavender" style="background:linear-gradient(135deg,#fff1fb,#d9d0ff)"><span>薰衣草</span></div>
          <div class="bf-v4-bg-card" data-bg="sky" style="background:linear-gradient(135deg,#f5fbff,#cde9ff)"><span>天空藍</span></div>
        </div>
        <div class="bf-v4-note">背景會完整跟著模板儲存；客人換手機型號時，系統再依該型號可印範圍裁切。</div>`;
      tools.appendChild(bg);
      bg.querySelector('[data-close]').onclick=()=>bg.classList.remove('show');
      bg.querySelectorAll('[data-bg]').forEach(x=>x.onclick=()=>applyGradientBg(x.dataset.bg));
      const colors=['#ffffff','#fff0f5','#ffd7e4','#f7e7ce','#e8dcff','#dcefff','#e4f6e9','#222222'];
      const sw=by('bf-v4-bg-swatches');colors.forEach(c=>{const b=document.createElement('button');b.className='bf-v4-swatch';b.style.background=c;b.title=c;b.onclick=()=>applySolidBg(c);sw.appendChild(b)});

      const ai=document.createElement('div');ai.id='bf-tpl-ai-panel-v4';ai.className='bf-v4-panel';ai.innerHTML=`
        <div class="bf-v4-head"><span>圖片 AI 工具</span><button data-close>收起</button></div>
        <div class="bf-v4-actions"><button class="bf-v4-action primary" data-remove>AI 自動摳圖</button><button class="bf-v4-action" data-expand>智慧補邊 140%</button></div>
        <div id="bf-v4-ai-progress" class="bf-v4-progress"></div>
        <div class="bf-v4-note">AI 摳圖使用目前前台同一套 BiRefNet。智慧補邊會先快速補足照片四周，適合人物太滿、版面不夠留白時使用；真正生成式 AI 擴圖會另外接模型，不會假裝成生成式結果。</div>`;
      tools.appendChild(ai);ai.querySelector('[data-close]').onclick=()=>ai.classList.remove('show');ai.querySelector('[data-remove]').onclick=()=>runRemoveBg();ai.querySelector('[data-expand]').onclick=()=>runSmartExpand();
    }

    // 延伸既有文字面板，避免另做一套文字編輯器。
    const textPanel=by('bf-tpl-text-panel');
    if(textPanel&&!by('bf-tpl-letter-spacing-v4')){
      const grid=textPanel.querySelector('.bf-tpl-grid');
      if(grid){
        grid.insertAdjacentHTML('beforeend',`
          <div class="bf-tpl-field"><label>字距</label><input id="bf-tpl-letter-spacing-v4" type="number" min="-200" max="1200" step="10" value="0"></div>
          <div class="bf-tpl-field"><label>行距</label><input id="bf-tpl-line-height-v4" type="number" min="0.6" max="3" step="0.1" value="1.16"></div>
          <div class="bf-tpl-field"><label>文字底色</label><input id="bf-tpl-text-bg-v4" type="color" value="#ffffff"></div>
          <div class="bf-tpl-field"><label>陰影顏色</label><input id="bf-tpl-shadow-color-v4" type="color" value="#000000"></div>`);
      }
      const applyBtn=by('bf-tpl-apply-text');if(applyBtn)applyBtn.onclick=applyTextV4;
      ['bf-tpl-text','bf-tpl-font','bf-tpl-size','bf-tpl-weight','bf-tpl-align','bf-tpl-color','bf-tpl-stroke','bf-tpl-stroke-width','bf-tpl-opacity','bf-tpl-shadow-blur','bf-tpl-shadow-x','bf-tpl-shadow-y','bf-tpl-letter-spacing-v4','bf-tpl-line-height-v4'].forEach(id=>{const e=by(id);if(e)e.addEventListener('change',()=>{if(isText(visualCanvas?.getActiveObject()))applyTextV4(false)})});
      ['bf-tpl-italic','bf-tpl-underline','bf-tpl-shadow'].forEach(id=>{const e=by(id);if(e)e.addEventListener('change',()=>{if(isText(visualCanvas?.getActiveObject()))applyTextV4(false)})});
    }

    // 背景按鈕打開進階背景，同時保留 v3 的快速背景。
    const bgBtn=by('bf-tpl-bg-btn-v3');if(bgBtn&&!bgBtn.dataset.v4){bgBtn.dataset.v4='1';const old=bgBtn.onclick;bgBtn.onclick=()=>{old?.();by('bf-tpl-bg-advanced-v4')?.classList.toggle('show')}}

    hookUploadCompression();
    hookCanvas();
  }

  function setProgress(msg,on=true){const e=by('bf-v4-ai-progress');if(!e)return;e.textContent=msg||'';e.classList.toggle('show',!!on)}

  function loadImage(src){return new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=()=>reject(new Error('圖片載入失敗'));im.src=src})}
  function fileUrl(file){return URL.createObjectURL(file)}
  function canvasBlob(c,type='image/webp',quality=.9){return new Promise((resolve,reject)=>c.toBlob(b=>b?resolve(b):reject(new Error('圖片壓縮失敗')),type,quality))}

  async function compressFile(file,maxEdge=3200,maxBytes=7.5*1024*1024){
    if(!file)throw new Error('沒有選擇圖片');
    if(!/^image\/(png|jpeg|webp)$/i.test(file.type||''))throw new Error('只支援 PNG / JPG / WEBP');
    const src=fileUrl(file);let im;
    try{im=await loadImage(src)}finally{URL.revokeObjectURL(src)}
    const ratio=Math.min(1,maxEdge/Math.max(im.naturalWidth||im.width,im.naturalHeight||im.height));
    const w=Math.max(1,Math.round((im.naturalWidth||im.width)*ratio)),h=Math.max(1,Math.round((im.naturalHeight||im.height)*ratio));
    const c=document.createElement('canvas');c.width=w;c.height=h;c.getContext('2d').drawImage(im,0,0,w,h);
    let q=.92,blob=await canvasBlob(c,'image/webp',q);
    while(blob.size>maxBytes&&q>.58){q-=.08;blob=await canvasBlob(c,'image/webp',q)}
    c.width=c.height=1;
    if(blob.size>maxBytes)throw new Error('圖片壓縮後仍過大，請換一張較小的圖片');
    const base=(file.name||'image').replace(/\.[^.]+$/,'');
    return new File([blob],base+'.webp',{type:'image/webp'});
  }

  async function addUploadedImage(file){
    if(!visualCanvas)return;
    status('正在最佳化圖片…');
    const optimized=await compressFile(file);
    const local=fileUrl(optimized);let el;
    try{el=await loadImage(local)}finally{URL.revokeObjectURL(local)}
    status(`圖片已最佳化 ${(file.size/1048576).toFixed(1)}MB → ${(optimized.size/1048576).toFixed(1)}MB，正在上傳…`);
    const publicUrl=await uploadAdminImage(optimized,'template');
    const img=new fabric.Image(el,{left:tplW/2,top:tplH/2,originX:'center',originY:'center',objectCaching:true,centeredScaling:true});
    img.publicSrc=publicUrl;img.originalName=file.name||'圖片';img.scaleToWidth(Math.min(tplW*.68,190));
    tuneObject(img);visualCanvas.add(img);visualCanvas.setActiveObject(img);visualCanvas.requestRenderAll();status('圖片已加入，可直接拖曳／縮放／旋轉');
  }

  function hookUploadCompression(){
    const input=by('bf-tpl-image-file-v3');
    if(input&&!input.dataset.v4){input.dataset.v4='1';input.onchange=async ev=>{const f=ev.target.files?.[0];ev.target.value='';if(!f)return;try{await addUploadedImage(f)}catch(e){console.error(e);alert('圖片加入失敗：'+(e.message||e))}}}
    // v2 底圖 input 仍透過全域 uploadTemplateBg 呼叫，直接覆寫即可。
    window.uploadTemplateBg=async function(ev){const f=ev.target.files?.[0];ev.target.value='';if(!f||!visualCanvas)return;try{status('正在最佳化底圖…');const opt=await compressFile(f);const url=await uploadAdminImage(opt,'template');const src=fileUrl(opt);let el;try{el=await loadImage(src)}finally{URL.revokeObjectURL(src)};removeBgObjects();const img=new fabric.Image(el,{left:tplW/2,top:tplH/2,originX:'center',originY:'center',selectable:false,evented:false,isTplBg:true,objectCaching:true});const sc=Math.max(tplW/(img.width||1),tplH/(img.height||1));img.set({scaleX:sc,scaleY:sc});img.publicSrc=url;visualCanvas.add(img);visualCanvas.sendToBack(img);visualCanvas.requestRenderAll();status('底圖已加入') }catch(e){console.error(e);alert('底圖加入失敗：'+(e.message||e))}};
  }

  function tuneObject(o){
    if(!o||o.isTplBg)return;
    o.set({transparentCorners:false,cornerColor:'#ff6f9a',cornerStrokeColor:'#ffffff',borderColor:'#ff6f9a',cornerSize:13,touchCornerSize:28,padding:2,objectCaching:true,centeredScaling:true,centeredRotation:true,perPixelTargetFind:false});
  }

  function hookCanvas(){
    if(!visualCanvas||hookedCanvas===visualCanvas)return;hookedCanvas=visualCanvas;
    visualCanvas.selection=true;visualCanvas.preserveObjectStacking=true;visualCanvas.perPixelTargetFind=false;visualCanvas.targetFindTolerance=8;
    visualCanvas.getObjects().forEach(tuneObject);
    visualCanvas.on('object:added',e=>tuneObject(e.target));
    visualCanvas.on('selection:created',syncObjectUi);visualCanvas.on('selection:updated',syncObjectUi);visualCanvas.on('selection:cleared',syncObjectUi);
    visualCanvas.on('object:modified',syncObjectUi);
    syncObjectUi();
  }

  function syncObjectUi(){const o=visualCanvas?.getActiveObject();const bar=by('bf-tpl-objectbar');if(bar)bar.classList.toggle('has-image',isImage(o));if(isImage(o))by('bf-tpl-ai-panel-v4')?.classList.remove('show');if(isText(o))syncTextExtra(o)}

  function syncTextExtra(o){if(!o)return;const set=(id,v)=>{const e=by(id);if(e)e.value=v};set('bf-tpl-letter-spacing-v4',Number(o.charSpacing)||0);set('bf-tpl-line-height-v4',Number(o.lineHeight)||1.16);if(/^#[0-9a-f]{6}$/i.test(o.backgroundColor||''))set('bf-tpl-text-bg-v4',o.backgroundColor);const sc=o.shadow?.color;if(typeof sc==='string'){const m=sc.match(/#[0-9a-f]{6}/i);if(m)set('bf-tpl-shadow-color-v4',m[0])}}

  function applyTextV4(create=true){
    if(!visualCanvas)return;let o=visualCanvas.getActiveObject();
    if(!isText(o)){if(!create)return;o=new fabric.Textbox('輸入文字',{left:tplW/2,top:tplH/2,originX:'center',originY:'center',width:Math.max(100,tplW*.68)});visualCanvas.add(o);visualCanvas.setActiveObject(o)}
    const val=id=>by(id)?.value;const chk=id=>!!by(id)?.checked;const sw=Number(val('bf-tpl-stroke-width'))||0;
    let shadow=null;if(chk('bf-tpl-shadow'))shadow=new fabric.Shadow({color:val('bf-tpl-shadow-color-v4')||'#000000',blur:Number(val('bf-tpl-shadow-blur'))||6,offsetX:Number(val('bf-tpl-shadow-x'))||0,offsetY:Number(val('bf-tpl-shadow-y'))||0});
    o.set({text:val('bf-tpl-text')||o.text||'文字',fontFamily:val('bf-tpl-font')||'PingFang TC',fontSize:Number(val('bf-tpl-size'))||28,fontWeight:val('bf-tpl-weight')||'400',textAlign:val('bf-tpl-align')||'center',fill:val('bf-tpl-color')||'#333333',stroke:sw>0?(val('bf-tpl-stroke')||'#ffffff'):null,strokeWidth:sw,opacity:Math.max(.1,Math.min(1,(Number(val('bf-tpl-opacity'))||100)/100)),fontStyle:chk('bf-tpl-italic')?'italic':'normal',underline:chk('bf-tpl-underline'),shadow,charSpacing:Number(val('bf-tpl-letter-spacing-v4'))||0,lineHeight:Number(val('bf-tpl-line-height-v4'))||1.16});
    tuneObject(o);o.setCoords();visualCanvas.requestRenderAll();status('文字設定已即時套用');
  }

  function removeBgObjects(){if(!visualCanvas)return;visualCanvas.getObjects().filter(o=>o.isTplBg).forEach(o=>visualCanvas.remove(o));visualCanvas.setBackgroundColor('rgba(0,0,0,0)',()=>{});}
  function applySolidBg(color){if(!visualCanvas)return;removeBgObjects();const r=new fabric.Rect({left:0,top:0,originX:'left',originY:'top',width:tplW,height:tplH,fill:color,selectable:false,evented:false,isTplBg:true,objectCaching:true});r.bgKind='solid';visualCanvas.add(r);visualCanvas.sendToBack(r);visualCanvas.requestRenderAll();status('背景已套用')}
  function applyGradientBg(kind){if(!visualCanvas)return;const map={pink:['#fff1f6','#ffc9da'],cream:['#fffaf1','#f1d7aa'],lavender:['#fff1fb','#d5c8ff'],sky:['#f7fcff','#cbe9ff']},pair=map[kind]||map.pink;removeBgObjects();const grad=new fabric.Gradient({type:'linear',coords:{x1:0,y1:0,x2:tplW,y2:tplH},colorStops:[{offset:0,color:pair[0]},{offset:1,color:pair[1]}]});const r=new fabric.Rect({left:0,top:0,originX:'left',originY:'top',width:tplW,height:tplH,fill:grad,selectable:false,evented:false,isTplBg:true,objectCaching:true});r.bgKind='gradient';r.bgPreset=kind;visualCanvas.add(r);visualCanvas.sendToBack(r);visualCanvas.requestRenderAll();status('漸層背景已套用')}

  async function fabricImageBlob(o,maxEdge=1800,quality=.9){
    const el=o?.getElement?.()||o?._element;if(!el)throw new Error('找不到圖片來源');const nw=el.naturalWidth||el.videoWidth||el.width,nh=el.naturalHeight||el.videoHeight||el.height;if(!nw||!nh)throw new Error('圖片尺寸讀取失敗');const ratio=Math.min(1,maxEdge/Math.max(nw,nh));const w=Math.max(1,Math.round(nw*ratio)),h=Math.max(1,Math.round(nh*ratio));const c=document.createElement('canvas');c.width=w;c.height=h;const g=c.getContext('2d');g.drawImage(el,0,0,w,h);const blob=await canvasBlob(c,'image/webp',quality);c.width=c.height=1;return blob;
  }

  async function replaceImage(oldObj,blob,publicUrl,extra={}){
    const src=URL.createObjectURL(blob);let el;try{el=await loadImage(src)}finally{URL.revokeObjectURL(src)}
    const c=visualCanvas,index=c.getObjects().indexOf(oldObj);const oldW=Math.max(1,oldObj.getScaledWidth()),oldH=Math.max(1,oldObj.getScaledHeight());
    const neo=new fabric.Image(el,{left:oldObj.left,top:oldObj.top,originX:oldObj.originX||'center',originY:oldObj.originY||'center',angle:oldObj.angle||0,flipX:!!oldObj.flipX,flipY:!!oldObj.flipY,opacity:oldObj.opacity??1,objectCaching:true});
    const fit=Math.min(oldW/(neo.width||1),oldH/(neo.height||1));neo.set({scaleX:fit,scaleY:fit});neo.publicSrc=publicUrl||'';neo.originalName=oldObj.originalName||'圖片';Object.assign(neo,extra);tuneObject(neo);c.remove(oldObj);c.insertAt(neo,Math.max(0,index),false);c.setActiveObject(neo);c.requestRenderAll();syncObjectUi();return neo;
  }

  async function runRemoveBg(){
    if(busy)return;const o=visualCanvas?.getActiveObject();if(!isImage(o)){alert('請先點選一張圖片');return}busy=true;by('bf-tpl-ai-panel-v4')?.classList.add('show');setProgress('正在準備圖片…');
    try{
      const inputBlob=await fabricImageBlob(o,1800,.9);if(inputBlob.size>6*1024*1024)throw new Error('圖片處理後仍超過 AI 限制');
      const fd=new FormData();fd.append('image',new File([inputBlob],'template-ai.webp',{type:'image/webp'}));setProgress('AI 正在摳圖，第一次啟動可能要等一下…');
      const r=await fetch('/api/ai/remove-background',{method:'POST',body:fd});if(!r.ok){let msg='AI 摳圖失敗';try{const j=await r.json();msg=j.msg||msg}catch(e){}throw new Error(msg)}
      const png=await r.blob();setProgress('摳圖完成，正在最佳化並儲存…');const opt=await compressBlob(png,3000,7.5*1024*1024,.94);const file=new File([opt],'ai-cutout.webp',{type:'image/webp'});const url=await uploadAdminImage(file,'template');await replaceImage(o,opt,url,{aiBackgroundRemoved:true});setProgress('AI 摳圖完成 ✓');status('AI 摳圖完成，可繼續排版');setTimeout(()=>setProgress('',false),1200);
    }catch(e){console.error(e);setProgress('',false);alert(e.message||'AI 摳圖失敗')}
    finally{busy=false}
  }

  async function compressBlob(blob,maxEdge=3000,maxBytes=7.5*1024*1024,quality=.92){const src=URL.createObjectURL(blob);let im;try{im=await loadImage(src)}finally{URL.revokeObjectURL(src)}const ratio=Math.min(1,maxEdge/Math.max(im.naturalWidth||im.width,im.naturalHeight||im.height));const w=Math.max(1,Math.round((im.naturalWidth||im.width)*ratio)),h=Math.max(1,Math.round((im.naturalHeight||im.height)*ratio));const c=document.createElement('canvas');c.width=w;c.height=h;c.getContext('2d').drawImage(im,0,0,w,h);let q=quality,out=await canvasBlob(c,'image/webp',q);while(out.size>maxBytes&&q>.6){q-=.08;out=await canvasBlob(c,'image/webp',q)}c.width=c.height=1;if(out.size>maxBytes)throw new Error('圖片最佳化後仍過大');return out}

  async function runSmartExpand(){
    if(busy)return;const o=visualCanvas?.getActiveObject();if(!isImage(o)){alert('請先點選一張圖片');return}busy=true;by('bf-tpl-ai-panel-v4')?.classList.add('show');setProgress('正在產生智慧補邊…');
    try{
      const el=o.getElement?.()||o._element,nw=el.naturalWidth||el.width,nh=el.naturalHeight||el.height;if(!nw||!nh)throw new Error('圖片尺寸讀取失敗');const max=2600,base=Math.min(1,max/Math.max(nw,nh)),iw=Math.round(nw*base),ih=Math.round(nh*base),w=Math.round(iw*1.4),h=Math.round(ih*1.4);const c=document.createElement('canvas');c.width=w;c.height=h;const g=c.getContext('2d');g.save();g.filter='blur(28px) brightness(.9)';const cover=Math.max(w/iw,h/ih);const cw=iw*cover,ch=ih*cover;g.drawImage(el,(w-cw)/2,(h-ch)/2,cw,ch);g.restore();g.fillStyle='rgba(255,255,255,.08)';g.fillRect(0,0,w,h);g.drawImage(el,(w-iw)/2,(h-ih)/2,iw,ih);const blob=await canvasBlob(c,'image/webp',.92);c.width=c.height=1;setProgress('補邊完成，正在儲存…');const url=await uploadAdminImage(new File([blob],'smart-expand.webp',{type:'image/webp'}),'template');await replaceImage(o,blob,url,{smartExpanded:true});setProgress('智慧補邊完成 ✓');status('已增加四周留白，可繼續調整位置');setTimeout(()=>setProgress('',false),1200);
    }catch(e){console.error(e);setProgress('',false);alert(e.message||'智慧補邊失敗')}
    finally{busy=false}
  }

  function installWhenReady(){ensureUi();hookCanvas();const t=setInterval(()=>{ensureUi();hookCanvas();if(by('template-modal')&&by('bf-tpl-frontbar'))clearInterval(t)},250);setTimeout(()=>clearInterval(t),10000)}

  const oldOpen=window.openTemplateEditor;
  if(typeof oldOpen==='function')window.openTemplateEditor=async function(...args){const r=await oldOpen.apply(this,args);setTimeout(()=>{ensureUi();hookCanvas()},80);setTimeout(()=>{ensureUi();hookCanvas()},350);return r};

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',installWhenReady,{once:true});else installWhenReady();
  console.info('[ADMIN] template editor v4 enabled: compression + richer background/text + AI remove-bg + smart expand');
})();
