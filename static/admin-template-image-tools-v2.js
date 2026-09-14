/* 本福丸模板編輯器：圖片替換 / 裁切 / 調整 + 圖層拖曳排序 */
(function(){
  'use strict';
  if(window.__benfuwanTemplateImageToolsV2Installed)return;
  window.__benfuwanTemplateImageToolsV2Installed=true;

  const by=id=>document.getElementById(id);
  const canvas=()=>window.visualCanvas||null;
  const isImage=o=>!!o&&o.type==='image'&&!o.isTplBg&&!o.isSlot;
  let hooked=null,dragIndex=null,touchIndex=null;

  function status(msg){const e=by('bf-tpl-status');if(e)e.textContent=msg}
  function loadImage(src){return new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=()=>reject(new Error('圖片載入失敗'));im.src=src})}
  function toBlob(c,type='image/webp',q=.92){return new Promise((resolve,reject)=>c.toBlob(b=>b?resolve(b):reject(new Error('圖片處理失敗')),type,q))}

  function css(){
    if(by('bf-imgtools-css'))return;
    const s=document.createElement('style');s.id='bf-imgtools-css';s.textContent=`
      #bf-tpl-objectbar .bf-imgtool-btn{display:none}#bf-tpl-objectbar.bf-imgtools .bf-imgtool-btn{display:inline-block}
      #bf-imgtool-panel{display:none;margin-top:8px;padding:11px;border:1px solid #efdfe5;background:#fff;border-radius:14px}#bf-imgtool-panel.show{display:block}
      .bf-it-head{display:flex;justify-content:space-between;align-items:center;color:#d95580;font-size:12px;font-weight:900;margin-bottom:9px}.bf-it-head button{border:1px solid #efd3dc;background:#fff;border-radius:999px;color:#d95580;padding:5px 9px;font-size:10px}
      .bf-it-tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}.bf-it-tabs button,.bf-it-crop button{border:1px solid #efd3dc;background:#fff;color:#d95580;border-radius:999px;padding:7px 10px;font-size:10px;font-weight:850}.bf-it-tabs button.active{background:#fff0f5;border-color:#ff9ab7}
      .bf-it-section{display:none}.bf-it-section.show{display:block}.bf-it-row{display:grid;grid-template-columns:66px 1fr 38px;gap:8px;align-items:center;margin:9px 0;font-size:10px;color:#766970}.bf-it-row input[type=range]{width:100%;accent-color:#ff6f9a}.bf-it-crop{display:flex;gap:7px;flex-wrap:wrap}.bf-it-note{font-size:10px;color:#93868c;line-height:1.55;margin-top:8px}
      #bf-tpl-layer-list .bf-tpl-layer{cursor:grab;touch-action:pan-y}#bf-tpl-layer-list .bf-tpl-layer.bf-dragging{opacity:.45}#bf-tpl-layer-list .bf-tpl-layer.bf-drop{box-shadow:inset 0 0 0 2px #ff8faf}
    `;document.head.appendChild(s);
  }

  function ensureUi(){
    css();const obj=by('bf-tpl-objectbar'),tools=by('bf-tpl-tools');if(!obj||!tools)return;
    if(!by('bf-it-replace-file')){const inp=document.createElement('input');inp.id='bf-it-replace-file';inp.type='file';inp.accept='image/png,image/jpeg,image/webp';inp.hidden=true;inp.onchange=replaceFromFile;document.body.appendChild(inp)}
    if(!obj.querySelector('[data-bf-imgtool="replace"]')){
      const before=obj.querySelector('.danger')||obj.lastElementChild;
      [['replace','替換'],['crop','裁切'],['adjust','調整']].forEach(([k,label])=>{const b=document.createElement('button');b.type='button';b.className='bf-imgtool-btn';b.dataset.bfImgtool=k;b.textContent=label;b.onclick=()=>openTool(k);obj.insertBefore(b,before)});
    }
    if(!by('bf-imgtool-panel')){
      const p=document.createElement('div');p.id='bf-imgtool-panel';p.innerHTML=`
        <div class="bf-it-head"><span>圖片工具</span><button type="button" data-close>收起</button></div>
        <div class="bf-it-tabs"><button data-tab="crop">裁切</button><button data-tab="adjust">亮度／色彩</button></div>
        <div class="bf-it-section" data-sec="crop"><div class="bf-it-crop"><button data-ratio="1">1:1</button><button data-ratio="0.8">4:5</button><button data-ratio="0.75">3:4</button><button data-ratio="1.333333">4:3</button><button data-ratio="1.777778">16:9</button></div><div class="bf-it-note">目前採中央裁切，會直接存成新的模板圖片，前台套版最穩定。</div></div>
        <div class="bf-it-section" data-sec="adjust">
          <div class="bf-it-row"><label>亮度</label><input id="bf-it-bright" type="range" min="-100" max="100" value="0"><span id="bf-it-bright-v">0</span></div>
          <div class="bf-it-row"><label>對比</label><input id="bf-it-contrast" type="range" min="-100" max="100" value="0"><span id="bf-it-contrast-v">0</span></div>
          <div class="bf-it-row"><label>飽和度</label><input id="bf-it-sat" type="range" min="-100" max="100" value="0"><span id="bf-it-sat-v">0</span></div>
          <div class="bf-it-row"><label>模糊</label><input id="bf-it-blur" type="range" min="0" max="20" value="0"><span id="bf-it-blur-v">0</span></div>
          <div class="bf-it-crop"><button id="bf-it-reset">重設調整</button></div>
          <div class="bf-it-note">調整會即時預覽並跟模板一起儲存。</div>
        </div>`;
      tools.appendChild(p);p.querySelector('[data-close]').onclick=()=>p.classList.remove('show');p.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>showSection(b.dataset.tab));p.querySelectorAll('[data-ratio]').forEach(b=>b.onclick=()=>cropActive(Number(b.dataset.ratio)));['bright','contrast','sat','blur'].forEach(k=>{const e=by('bf-it-'+k);e.oninput=()=>{by('bf-it-'+k+'-v').textContent=e.value;applyAdjustments()}});by('bf-it-reset').onclick=resetAdjustments;
    }
  }

  function openTool(kind){
    ensureUi();const o=canvas()?.getActiveObject();if(!isImage(o)){alert('請先點選一張圖片');return}
    if(kind==='replace'){by('bf-it-replace-file')?.click();return}
    by('bf-imgtool-panel')?.classList.add('show');showSection(kind);syncAdjustmentUi(o);
  }
  function showSection(kind){document.querySelectorAll('#bf-imgtool-panel [data-sec]').forEach(e=>e.classList.toggle('show',e.dataset.sec===kind));document.querySelectorAll('#bf-imgtool-panel [data-tab]').forEach(e=>e.classList.toggle('active',e.dataset.tab===kind))}

  async function optimize(file,maxEdge=3000,maxBytes=7.5*1024*1024){
    const url=URL.createObjectURL(file);let im;try{im=await loadImage(url)}finally{URL.revokeObjectURL(url)}
    const r=Math.min(1,maxEdge/Math.max(im.naturalWidth||im.width,im.naturalHeight||im.height)),w=Math.max(1,Math.round((im.naturalWidth||im.width)*r)),h=Math.max(1,Math.round((im.naturalHeight||im.height)*r));const c=document.createElement('canvas');c.width=w;c.height=h;c.getContext('2d').drawImage(im,0,0,w,h);let q=.92,b=await toBlob(c,'image/webp',q);while(b.size>maxBytes&&q>.6){q-=.08;b=await toBlob(c,'image/webp',q)}c.width=c.height=1;if(b.size>maxBytes)throw new Error('圖片最佳化後仍過大');return new File([b],(file.name||'image').replace(/\.[^.]+$/,'')+'.webp',{type:'image/webp'})
  }

  async function replaceObject(oldObj,file,extra={}){
    const c=canvas();if(!c||!oldObj)throw new Error('畫布尚未準備好');const oldW=Math.max(1,oldObj.getScaledWidth()),oldH=Math.max(1,oldObj.getScaledHeight()),center=oldObj.getCenterPoint(),idx=c.getObjects().indexOf(oldObj),local=URL.createObjectURL(file);let el;try{el=await loadImage(local)}finally{URL.revokeObjectURL(local)}
    const neo=new fabric.Image(el,{left:center.x,top:center.y,originX:'center',originY:'center',angle:oldObj.angle||0,flipX:!!oldObj.flipX,flipY:!!oldObj.flipY,opacity:oldObj.opacity??1,objectCaching:true,centeredScaling:true});const fit=Math.min(oldW/Math.max(1,neo.width),oldH/Math.max(1,neo.height));neo.scaleX=fit;neo.scaleY=fit;neo.publicSrc=extra.publicSrc||'';neo.originalName=extra.originalName||oldObj.originalName||'圖片';neo.stickerId=oldObj.stickerId||'';neo.aiBackgroundRemoved=!!oldObj.aiBackgroundRemoved;neo.aiOutlineStyle=oldObj.aiOutlineStyle;neo.aiOutlineWidth=oldObj.aiOutlineWidth;neo.aiOutlineColor=oldObj.aiOutlineColor;neo.aiOutlineSourcePublic=oldObj.aiOutlineSourcePublic;neo.filters=oldObj.filters||[];c.remove(oldObj);c.insertAt(neo,Math.max(0,idx),false);c.setActiveObject(neo);neo.setCoords();c.requestRenderAll();c.fire('object:modified',{target:neo});return neo;
  }

  async function replaceFromFile(ev){const f=ev.target.files?.[0];ev.target.value='';const old=canvas()?.getActiveObject();if(!f||!isImage(old))return;try{status('正在最佳化替換圖片…');const opt=await optimize(f);const url=await uploadAdminImage(opt,'template');await replaceObject(old,opt,{publicSrc:url,originalName:f.name});status('圖片已替換 ✓')}catch(e){console.error(e);alert('替換失敗：'+(e.message||e))}}

  async function cropActive(ratio){const old=canvas()?.getActiveObject();if(!isImage(old))return alert('請先點選圖片');try{status('正在裁切圖片…');const el=old.getElement?.()||old._element,nw=el?.naturalWidth||el?.width,nh=el?.naturalHeight||el?.height;if(!nw||!nh)throw new Error('圖片尺寸讀取失敗');let sw=nw,sh=nh;if(nw/nh>ratio)sw=nh*ratio;else sh=nw/ratio;const sx=(nw-sw)/2,sy=(nh-sh)/2,max=2600,scale=Math.min(1,max/Math.max(sw,sh)),ow=Math.max(1,Math.round(sw*scale)),oh=Math.max(1,Math.round(sh*scale)),cc=document.createElement('canvas');cc.width=ow;cc.height=oh;cc.getContext('2d').drawImage(el,sx,sy,sw,sh,0,0,ow,oh);const b=await toBlob(cc,'image/webp',.94);cc.width=cc.height=1;const file=new File([b],'crop.webp',{type:'image/webp'}),url=await uploadAdminImage(file,'template');await replaceObject(old,file,{publicSrc:url,originalName:old.originalName||'裁切圖片'});status('裁切完成 ✓')}catch(e){console.error(e);alert('裁切失敗：'+(e.message||e))}}

  function upsertFilter(o,klass,value){if(!klass)return;o.filters=o.filters||[];o.filters=o.filters.filter(f=>!(f instanceof klass));if(Math.abs(value)>0.0001)o.filters.push(new klass(value));}
  function applyAdjustments(){const o=canvas()?.getActiveObject();if(!isImage(o)||!window.fabric?.Image?.filters)return;const F=fabric.Image.filters,b=Number(by('bf-it-bright')?.value||0)/100,c=Number(by('bf-it-contrast')?.value||0)/100,s=Number(by('bf-it-sat')?.value||0)/100,bl=Number(by('bf-it-blur')?.value||0)/100;upsertFilter(o,F.Brightness,b);upsertFilter(o,F.Contrast,c);upsertFilter(o,F.Saturation,s);upsertFilter(o,F.Blur,bl);o.__bfAdjust={brightness:b,contrast:c,saturation:s,blur:bl};o.applyFilters();canvas().requestRenderAll()}
  function resetAdjustments(){['bright','contrast','sat','blur'].forEach(k=>{by('bf-it-'+k).value='0';by('bf-it-'+k+'-v').textContent='0'});const o=canvas()?.getActiveObject();if(!isImage(o))return;o.filters=[];o.__bfAdjust={brightness:0,contrast:0,saturation:0,blur:0};o.applyFilters();canvas().requestRenderAll();status('圖片調整已重設')}
  function syncAdjustmentUi(o){const a=o?.__bfAdjust||{brightness:0,contrast:0,saturation:0,blur:0},map={bright:a.brightness,contrast:a.contrast,sat:a.saturation,blur:a.blur};Object.entries(map).forEach(([k,v])=>{const n=Math.round(Number(v||0)*100);if(by('bf-it-'+k))by('bf-it-'+k).value=String(n);if(by('bf-it-'+k+'-v'))by('bf-it-'+k+'-v').textContent=String(n)})}

  function syncSelection(){ensureUi();const o=canvas()?.getActiveObject(),ok=isImage(o),bar=by('bf-tpl-objectbar');bar?.classList.toggle('bf-imgtools',ok);if(!ok)by('bf-imgtool-panel')?.classList.remove('show')}

  function moveLayer(from,to){const c=canvas();if(!c||from==null||to==null||from===to)return;const o=c.getObjects()[from];if(!o)return;c.moveTo(o,to);c.setActiveObject(o);c.requestRenderAll();c.fire('object:modified',{target:o})}
  function enhanceLayerRows(){const list=by('bf-tpl-layer-list');if(!list)return;list.querySelectorAll('.bf-tpl-layer').forEach(row=>{if(row.dataset.bfDrag)return;row.dataset.bfDrag='1';row.draggable=true;row.addEventListener('dragstart',()=>{dragIndex=Number(row.dataset.layerIndex);row.classList.add('bf-dragging')});row.addEventListener('dragend',()=>{dragIndex=null;row.classList.remove('bf-dragging');list.querySelectorAll('.bf-drop').forEach(x=>x.classList.remove('bf-drop'))});row.addEventListener('dragover',e=>{e.preventDefault();row.classList.add('bf-drop')});row.addEventListener('dragleave',()=>row.classList.remove('bf-drop'));row.addEventListener('drop',e=>{e.preventDefault();row.classList.remove('bf-drop');moveLayer(dragIndex,Number(row.dataset.layerIndex))});row.addEventListener('touchstart',()=>{touchIndex=Number(row.dataset.layerIndex)},{passive:true});row.addEventListener('touchend',e=>{const t=e.changedTouches?.[0],el=t?document.elementFromPoint(t.clientX,t.clientY)?.closest('.bf-tpl-layer'):null;if(el)moveLayer(touchIndex,Number(el.dataset.layerIndex));touchIndex=null},{passive:true})})}

  function hook(){const c=canvas();ensureUi();syncSelection();enhanceLayerRows();if(!c||c===hooked)return;hooked=c;['selection:created','selection:updated','selection:cleared','object:added','object:removed','object:modified'].forEach(ev=>c.on(ev,()=>setTimeout(()=>{syncSelection();enhanceLayerRows()},0)))}
  function boot(){setInterval(()=>{hook();enhanceLayerRows()},450);console.info('[ADMIN] template image tools v2 enabled: replace/crop/adjust/layer drag')}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();