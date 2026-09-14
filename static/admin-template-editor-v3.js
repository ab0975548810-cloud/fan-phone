/* 本福丸模板編輯器 v3：把後台模板工作台做成接近前台 DIY 的操作方式 */
(function(){
  'use strict';
  if(window.__benfuwanTemplateEditorV3Installed)return;
  window.__benfuwanTemplateEditorV3Installed=true;

  let hookedCanvas=null;
  const by=id=>document.getElementById(id);

  function css(){
    if(by('bf-tpl-v3-css'))return;
    const s=document.createElement('style');s.id='bf-tpl-v3-css';s.textContent=`
      #template-modal .toolbar{display:none!important}
      #template-modal .editor{height:560px;background:linear-gradient(#f7f5f6,#efedef);border-radius:18px;position:relative}
      #template-modal .canvas-wrap{position:relative!important;overflow:hidden;background-color:#fff;background-image:linear-gradient(45deg,#eee 25%,transparent 25%),linear-gradient(-45deg,#eee 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#eee 75%),linear-gradient(-45deg,transparent 75%,#eee 75%);background-size:16px 16px;background-position:0 0,0 8px,8px -8px,-8px 0}
      #bf-tpl-model-mask{position:absolute;inset:0;width:100%;height:100%;object-fit:fill;pointer-events:none;z-index:40}
      #bf-tpl-safe-note{position:absolute;left:10px;top:10px;z-index:45;background:rgba(255,255,255,.9);border:1px solid #efdfe5;border-radius:999px;padding:5px 9px;font-size:10px;font-weight:850;color:#8c7c83;pointer-events:none}
      #bf-tpl-frontbar{display:grid;grid-template-columns:repeat(6,1fr);gap:6px;margin-top:10px;padding:8px;background:#fff;border:1px solid #f0dfe5;border-radius:18px;box-shadow:0 7px 22px rgba(180,80,115,.06)}
      .bf-tpl-main-tool{border:0;background:transparent;border-radius:12px;padding:7px 3px;font-size:10px;font-weight:900;color:#655b60;cursor:pointer}.bf-tpl-main-tool .ico{width:36px;height:36px;border-radius:12px;background:#fff0f5;color:#ff6f9a;display:grid;place-items:center;margin:0 auto 4px;font-size:15px}
      #bf-tpl-objectbar{display:none;gap:6px;flex-wrap:wrap;margin-top:8px;padding:8px;background:#fff8fb;border:1px solid #efdfe5;border-radius:14px;align-items:center}#bf-tpl-objectbar.show{display:flex}#bf-tpl-objectbar button{border:1px solid #efd3dc;background:#fff;color:#d95580;border-radius:999px;padding:6px 10px;font-size:11px;font-weight:850;cursor:pointer}#bf-tpl-objectbar button.danger{color:#d94d61}.bf-tpl-opacity-wrap{display:flex;align-items:center;gap:5px;font-size:10px;color:#8b7e84}.bf-tpl-opacity-wrap input{width:100px}
      #bf-tpl-bg-v3,#bf-tpl-layers-v3{display:none;margin-top:8px;padding:10px;border:1px solid #efdfe5;background:#fff;border-radius:14px}#bf-tpl-bg-v3.show,#bf-tpl-layers-v3.show{display:block}.bf-tpl-v3-head{display:flex;align-items:center;justify-content:space-between;font-size:12px;font-weight:900;color:#d95580;margin-bottom:8px}.bf-tpl-bg-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.bf-tpl-bg-row button{border:1px solid #efd3dc;background:#fff;color:#d95580;border-radius:999px;padding:7px 10px;font-size:11px;font-weight:850}.bf-tpl-bg-row input[type=color]{width:42px;height:34px;border:0;background:transparent}
      #bf-tpl-layer-list{display:flex;flex-direction:column;gap:5px;max-height:210px;overflow:auto}.bf-tpl-layer{display:grid;grid-template-columns:1fr auto auto;gap:5px;align-items:center;padding:7px 8px;border:1px solid #f0e3e7;border-radius:10px;background:#fffafb;font-size:11px}.bf-tpl-layer.active{border-color:#ff9ab7;background:#fff0f5}.bf-tpl-layer button{border:0;background:#fff;border-radius:8px;padding:5px 7px;color:#d95580}
      #bf-tpl-tools{margin-top:8px!important}
      @media(max-width:800px){#template-modal .editor{height:440px}#bf-tpl-frontbar{grid-template-columns:repeat(3,1fr)}.bf-tpl-main-tool{font-size:9px}#bf-tpl-model-mask{z-index:25}}
    `;document.head.appendChild(s);
  }

  function ensureUi(){
    css();const modal=by('template-modal');if(!modal)return;
    const editor=modal.querySelector('.editor');if(!editor)return;
    const wrap=by('canvas-wrap');if(wrap&&!by('bf-tpl-model-mask')){
      const img=document.createElement('img');img.id='bf-tpl-model-mask';img.alt='';wrap.appendChild(img);
      const note=document.createElement('div');note.id='bf-tpl-safe-note';note.textContent='手機殼 / 鏡頭遮罩僅供對位，不會存進模板';wrap.appendChild(note);
    }
    if(by('bf-tpl-frontbar'))return;
    const bar=document.createElement('div');bar.id='bf-tpl-frontbar';bar.innerHTML=`
      <button class="bf-tpl-main-tool" id="bf-tpl-upload-v3"><span class="ico"><i class="fa-regular fa-image"></i></span>上傳圖片</button>
      <button class="bf-tpl-main-tool" id="bf-tpl-slot-v3"><span class="ico"><i class="fa-regular fa-square-plus"></i></span>照片框</button>
      <button class="bf-tpl-main-tool" id="bf-tpl-sticker-v3"><span class="ico"><i class="fa-regular fa-face-smile"></i></span>貼紙</button>
      <button class="bf-tpl-main-tool" id="bf-tpl-text-v3"><span class="ico"><i class="fa-solid fa-font"></i></span>文字</button>
      <button class="bf-tpl-main-tool" id="bf-tpl-bg-btn-v3"><span class="ico"><i class="fa-solid fa-palette"></i></span>背景</button>
      <button class="bf-tpl-main-tool" id="bf-tpl-layers-btn-v3"><span class="ico"><i class="fa-solid fa-layer-group"></i></span>圖層</button>
      <input id="bf-tpl-image-file-v3" type="file" accept="image/png,image/jpeg,image/webp" hidden>`;
    editor.insertAdjacentElement('afterend',bar);
    const obj=document.createElement('div');obj.id='bf-tpl-objectbar';obj.innerHTML=`<button data-act="flipx">水平翻轉</button><button data-act="flipy">垂直翻轉</button><button data-act="clone">複製</button><button data-act="front">往前</button><button data-act="back">往後</button><button data-act="center">置中</button><span class="bf-tpl-opacity-wrap">透明度 <input id="bf-tpl-object-opacity-v3" type="range" min="10" max="100" value="100"></span><button class="danger" data-act="delete">刪除</button>`;bar.insertAdjacentElement('afterend',obj);
    const bg=document.createElement('div');bg.id='bf-tpl-bg-v3';bg.innerHTML=`<div class="bf-tpl-v3-head"><span>背景設定</span><button class="btn alt mini" id="bf-tpl-bg-close-v3">收起</button></div><div class="bf-tpl-bg-row"><span style="font-size:11px;font-weight:850">底色</span><input id="bf-tpl-bg-color-v3" type="color" value="#ffffff"><button id="bf-tpl-bg-white-v3">白色</button><button id="bf-tpl-bg-transparent-v3">透明</button><button id="bf-tpl-bg-upload-v3">上傳底圖</button><button id="bf-tpl-bg-remove-v3">移除底圖</button></div>`;obj.insertAdjacentElement('afterend',bg);
    const layers=document.createElement('div');layers.id='bf-tpl-layers-v3';layers.innerHTML=`<div class="bf-tpl-v3-head"><span>圖層管理</span><button class="btn alt mini" id="bf-tpl-layers-close-v3">收起</button></div><div id="bf-tpl-layer-list"></div>`;bg.insertAdjacentElement('afterend',layers);

    by('bf-tpl-upload-v3').onclick=()=>by('bf-tpl-image-file-v3').click();
    by('bf-tpl-image-file-v3').onchange=uploadFixedImage;
    by('bf-tpl-slot-v3').onclick=()=>{if(typeof addSlot==='function')addSlot();refreshLayers();syncSelection()};
    by('bf-tpl-sticker-v3').onclick=()=>{if(typeof window.pickSticker==='function')window.pickSticker()};
    by('bf-tpl-text-v3').onclick=()=>{if(typeof window.addText==='function')window.addText()};
    by('bf-tpl-bg-btn-v3').onclick=()=>togglePanel('bg');by('bf-tpl-layers-btn-v3').onclick=()=>togglePanel('layers');
    by('bf-tpl-bg-close-v3').onclick=()=>togglePanel('');by('bf-tpl-layers-close-v3').onclick=()=>togglePanel('');
    by('bf-tpl-bg-color-v3').oninput=ev=>setCanvasBackground(ev.target.value);by('bf-tpl-bg-white-v3').onclick=()=>setCanvasBackground('#ffffff');by('bf-tpl-bg-transparent-v3').onclick=()=>setCanvasBackground('rgba(0,0,0,0)');
    by('bf-tpl-bg-upload-v3').onclick=()=>by('tpl-bg-file')?.click();by('bf-tpl-bg-remove-v3').onclick=()=>{if(!visualCanvas)return;visualCanvas.getObjects().filter(o=>o.isTplBg).forEach(o=>visualCanvas.remove(o));visualCanvas.requestRenderAll();refreshLayers()};
    obj.querySelectorAll('[data-act]').forEach(b=>b.onclick=()=>objectAction(b.dataset.act));
    by('bf-tpl-object-opacity-v3').oninput=ev=>{const o=visualCanvas?.getActiveObject();if(!o)return;o.set('opacity',Number(ev.target.value)/100);visualCanvas.requestRenderAll()};
  }

  function togglePanel(which){by('bf-tpl-bg-v3')?.classList.toggle('show',which==='bg');by('bf-tpl-layers-v3')?.classList.toggle('show',which==='layers');if(which==='layers')refreshLayers()}
  function setCanvasBackground(color){if(!visualCanvas)return;visualCanvas.setBackgroundColor(color,()=>visualCanvas.requestRenderAll());if(by('bf-tpl-bg-color-v3')&&/^#[0-9a-f]{6}$/i.test(color))by('bf-tpl-bg-color-v3').value=color}

  function dataUrl(file){return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result||''));r.onerror=()=>reject(new Error('圖片讀取失敗'));r.readAsDataURL(file)})}
  function loadImg(src){return new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=()=>reject(new Error('圖片載入失敗'));im.src=src})}
  async function uploadFixedImage(ev){const f=ev.target.files?.[0];ev.target.value='';if(!f||!visualCanvas)return;try{const local=await dataUrl(f),publicUrl=await uploadAdminImage(f,'template'),el=await loadImg(local);const img=new fabric.Image(el,{left:tplW/2,top:tplH/2,originX:'center',originY:'center'});img.publicSrc=publicUrl;img.originalName=f.name||'圖片';img.scaleToWidth(Math.min(tplW*.65,180));visualCanvas.add(img);visualCanvas.setActiveObject(img);visualCanvas.requestRenderAll();refreshLayers();syncSelection()}catch(err){alert('圖片加入失敗：'+(err.message||err))}}

  function objectAction(act){const c=visualCanvas,o=c?.getActiveObject();if(!c||!o)return;
    if(act==='flipx')o.set('flipX',!o.flipX);if(act==='flipy')o.set('flipY',!o.flipY);
    if(act==='front')c.bringForward(o);if(act==='back')c.sendBackwards(o);
    if(act==='center')o.set({left:tplW/2,top:tplH/2,originX:'center',originY:'center'});
    if(act==='delete'){c.remove(o);c.discardActiveObject()}
    if(act==='clone')o.clone(cl=>{cl.set({left:(o.left||0)+14,top:(o.top||0)+14});['publicSrc','stickerId','originalName','isSlot','slotId'].forEach(k=>{if(o[k]!=null)cl[k]=o[k]});c.add(cl);c.setActiveObject(cl);c.requestRenderAll();refreshLayers();syncSelection()});
    o.setCoords?.();c.requestRenderAll();refreshLayers();syncSelection();
  }

  function labelFor(o,i){if(o.isTplBg)return '底圖';if(o.isSlot)return `照片框 ${i+1}`;if(['text','textbox','i-text'].includes(o.type))return `文字：${String(o.text||'').slice(0,12)}`;if(o.stickerId)return '貼紙';if(o.type==='image')return o.originalName?`圖片：${o.originalName}`:'圖片';return `物件 ${i+1}`}
  function refreshLayers(){const box=by('bf-tpl-layer-list');if(!box||!visualCanvas)return;const active=visualCanvas.getActiveObject();const arr=[...visualCanvas.getObjects()].reverse();box.innerHTML=arr.length?arr.map((o,i)=>{const realIndex=visualCanvas.getObjects().indexOf(o);return `<div class="bf-tpl-layer${o===active?' active':''}" data-layer-index="${realIndex}"><span>${labelFor(o,realIndex)}</span><button data-up="${realIndex}" title="往前">▲</button><button data-down="${realIndex}" title="往後">▼</button></div>`}).join(''):'<div style="padding:18px;text-align:center;color:#aaa;font-size:11px">目前沒有物件</div>';box.querySelectorAll('.bf-tpl-layer').forEach(row=>row.onclick=ev=>{if(ev.target.tagName==='BUTTON')return;const o=visualCanvas.getObjects()[Number(row.dataset.layerIndex)];if(o&&o.selectable!==false){visualCanvas.setActiveObject(o);visualCanvas.requestRenderAll();syncSelection();refreshLayers()}});box.querySelectorAll('[data-up]').forEach(b=>b.onclick=ev=>{ev.stopPropagation();const o=visualCanvas.getObjects()[Number(b.dataset.up)];if(o){visualCanvas.bringForward(o);refreshLayers();visualCanvas.requestRenderAll()}});box.querySelectorAll('[data-down]').forEach(b=>b.onclick=ev=>{ev.stopPropagation();const o=visualCanvas.getObjects()[Number(b.dataset.down)];if(o){visualCanvas.sendBackwards(o);refreshLayers();visualCanvas.requestRenderAll()}})}

  function syncSelection(){const o=visualCanvas?.getActiveObject();by('bf-tpl-objectbar')?.classList.toggle('show',!!o&&o.isTplBg!==true);if(o&&by('bf-tpl-object-opacity-v3'))by('bf-tpl-object-opacity-v3').value=Math.round((Number(o.opacity)||1)*100);refreshLayers()}
  function hook(){if(!visualCanvas||visualCanvas===hookedCanvas)return;hookedCanvas=visualCanvas;['selection:created','selection:updated','selection:cleared','object:added','object:removed','object:modified'].forEach(evt=>visualCanvas.on(evt,()=>setTimeout(()=>{syncSelection();},0)));syncSelection()}

  function updateModelMask(){const img=by('bf-tpl-model-mask');if(!img)return;const id=by('tpl-model')?.value,m=(shopData.models||[]).find(x=>x.id===id)||{};img.src=m.preview_mask_img||m.mask_img||'';img.style.display=img.src?'block':'none'}

  const oldInit=window.initEditor;
  if(typeof oldInit==='function')window.initEditor=function(...args){ensureUi();const out=oldInit.apply(this,args);setTimeout(()=>{ensureUi();updateModelMask();hook();refreshLayers()},60);return out};
  const oldOpen=window.openTemplateEditor;
  if(typeof oldOpen==='function')window.openTemplateEditor=async function(...args){ensureUi();const out=await oldOpen.apply(this,args);setTimeout(()=>{ensureUi();updateModelMask();hook();refreshLayers()},100);return out};

  function boot(){ensureUi();setTimeout(()=>{updateModelMask();hook()},80);console.info('[ADMIN] template editor v3 enabled: customer-like designer controls')}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
