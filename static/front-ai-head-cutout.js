/* 本福丸前台：AI 大頭摳圖。先沿用 AI 去背，再用裝置端臉部 AI 自動裁成大頭。 */
(function(){
  'use strict';
  if(window.__bfFrontAiHeadCutout)return;window.__bfFrontAiHeadCutout=true;

  const by=id=>document.getElementById(id);
  let hookedCanvas=null,busy=false;
  function c(){try{return (typeof canvas!=='undefined'&&canvas)?canvas:null}catch(e){return null}}
  function active(){return c()?.getActiveObject?.()||null}
  function isPhoto(o){return !!(o&&o.type==='image'&&(o.role==='photo'||o.role==='slot-photo'))}

  function addCss(){
    if(by('bf-ai-head-front-css'))return;
    const s=document.createElement('style');s.id='bf-ai-head-front-css';s.textContent=`
      #bf-ai-head-btn{display:none}#bf-ai-head-btn.show{display:block}
      #bf-ai-head-btn i{color:#ff6f9a}
      #bf-ai-head-sheet-wrap{margin-top:10px;padding-top:10px;border-top:1px dashed rgba(161,87,195,.28)}
      #bf-ai-head-sheet-wrap .bf-ai-head-note{font-size:10px;color:#806e77;line-height:1.55;margin:5px 1px 1px}
      #bf-ai-head-sheet-btn{background:linear-gradient(135deg,#fff,#fff6fb);border-color:#e9b5f2;color:#9a48ba}
      #bf-ai-head-sheet-btn i{margin-right:6px}
    `;document.head.appendChild(s);
  }

  function ensureButton(){
    addCss();const bar=by('object-bar');if(!bar)return;
    let b=by('bf-ai-head-btn');
    if(!b){
      b=document.createElement('button');b.id='bf-ai-head-btn';b.type='button';b.title='AI 大頭摳圖';b.innerHTML='<i class="fa-solid fa-user-large"></i>AI大頭';b.onclick=e=>{e.preventDefault();e.stopPropagation();run()};
      const outline=by('bf-ai-outline-btn'),del=[...bar.querySelectorAll('button')].find(x=>/deleteActive/.test(x.getAttribute('onclick')||''));
      if(outline)bar.insertBefore(b,outline);else if(del)bar.insertBefore(b,del);else bar.appendChild(b);
    }
    refresh();
  }

  function ensureSheetButton(){
    addCss();const box=document.querySelector('#sheet-upload .ai-box');if(!box||by('bf-ai-head-sheet-wrap'))return;
    const wrap=document.createElement('div');wrap.id='bf-ai-head-sheet-wrap';
    wrap.innerHTML='<b><i class="fa-solid fa-user-large"></i> AI 大頭摳圖 <span style="font-size:9px;padding:2px 6px;border-radius:999px;background:#fff;color:#a157c3">NEW</span></b><div class="bf-ai-head-note">先在畫布上選取人物或寵物照片，再按下方按鈕；系統會先去背，再自動裁成適合手機殼排版的大頭素材。</div><button id="bf-ai-head-sheet-btn" class="secondary wide" type="button"><i class="fa-solid fa-user-large"></i>AI 大頭摳圖選取圖片</button>';
    box.appendChild(wrap);
    by('bf-ai-head-sheet-btn').onclick=e=>{e.preventDefault();run()};
    refresh();
  }

  function refresh(){
    const o=active(),ok=isPhoto(o),b=by('bf-ai-head-btn'),sheet=by('bf-ai-head-sheet-btn');
    if(b){b.classList.toggle('show',ok);b.disabled=busy||!ok;b.title=o?.aiHeadCutout?'這張已做過 AI 大頭摳圖':'AI 大頭摳圖'}
    if(sheet){sheet.disabled=busy;sheet.innerHTML=busy?'<i class="fa-solid fa-spinner fa-spin"></i>AI 大頭處理中…':'<i class="fa-solid fa-user-large"></i>AI 大頭摳圖選取圖片';sheet.title=ok?'AI 大頭摳圖':'請先選取畫布上的照片'}
  }

  function loadImage(src){return new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=()=>reject(new Error('大頭圖片載入失敗'));im.src=src})}
  function dataUrl(ca){return ca.toDataURL('image/png')}

  async function replaceObject(old,cut){
    const cv=c();if(!cv)return null;
    const center=old.getCenterPoint(),idx=cv.getObjects().indexOf(old),displayW=Math.max(1,old.getScaledWidth?.()||((old.width||1)*(old.scaleX||1))),src=dataUrl(cut.canvas),el=await loadImage(src);
    const neo=new fabric.Image(el,{left:center.x,top:center.y,originX:'center',originY:'center',angle:old.angle||0,flipX:!!old.flipX,flipY:!!old.flipY,opacity:old.opacity??1,objectCaching:true});
    const scale=displayW/Math.max(1,neo.width);neo.set({scaleX:scale,scaleY:scale,role:old.role,slotId:old.slotId,slotMeta:old.slotMeta,clipPath:old.clipPath||undefined,originalName:old.originalName,materialType:old.materialType,aiBackgroundRemoved:true,aiHeadCutout:true,aiHeadMode:cut.mode,aiOutlineSource:old.aiOutlineSource,aiOutlineStrength:old.aiOutlineStrength,aiOutlineColor:old.aiOutlineColor});
    if(typeof styleEditableObject==='function')styleEditableObject(neo);
    cv.remove(old);cv.insertAt(neo,Math.max(0,idx),false);cv.setActiveObject(neo);neo.setCoords();cv.requestRenderAll?.();
    if(typeof recordHistory==='function')recordHistory();if(typeof renderLayerList==='function')renderLayerList();if(typeof syncSelection==='function')syncSelection();
    return neo;
  }

  async function run(){
    if(busy)return;let old=active();if(!isPhoto(old)){if(typeof toast==='function')toast('請先在畫布上選取一張人物或寵物照片');return}
    if(old.aiHeadCutout){if(typeof toast==='function')toast('這張照片已經是 AI 大頭摳圖 ♡');return}
    const core=window.BenfuwanHeadCutout;if(!core){if(typeof toast==='function')toast('AI 大頭工具尚未載入，請重新整理頁面');return}
    busy=true;refresh();let face=null;
    try{
      if(typeof closeSheets==='function')closeSheets();
      if(typeof setBusy==='function')setBusy(true,'AI 正在辨識主要臉部...');
      try{face=await core.detectFace(old.getElement?.()||old._element)}catch(faceErr){console.warn('[FRONT AI HEAD] face detect fallback',faceErr)}
      if(typeof setBusy==='function')setBusy(false);

      if(!old.aiBackgroundRemoved){
        if(typeof window.removeBackgroundForActive!=='function')throw new Error('AI 去背功能尚未載入');
        await window.removeBackgroundForActive();
        old=active();
        if(!isPhoto(old)||!old.aiBackgroundRemoved)throw new Error('AI 去背未完成，請再試一次');
      }

      if(typeof setBusy==='function')setBusy(true,face?'正在保留頭髮與臉部輪廓...':'找不到正臉，正在用透明輪廓智慧裁切...');
      const cut=core.cropTransparent(old.getElement?.()||old._element,face);
      await replaceObject(old,cut);
      if(typeof toast==='function'){
        if(face?.count>1)toast('AI 大頭完成 ♡ 偵測到多人，已取最主要的一張臉');
        else if(face)toast('AI 大頭摳圖完成 ♡');
        else toast('AI 大頭完成 ♡ 已用輪廓智慧裁切');
      }
    }catch(e){console.error('[FRONT AI HEAD]',e);if(typeof toast==='function')toast(e.message||'AI 大頭摳圖失敗，請再試一次')}
    finally{busy=false;if(typeof setBusy==='function')setBusy(false);refresh()}
  }

  window.makeAiHeadCutout=run;

  function hook(){
    const cv=c();if(!cv||cv===hookedCanvas)return;hookedCanvas=cv;
    ['selection:created','selection:updated','selection:cleared','object:added','object:removed','object:modified'].forEach(evt=>cv.on(evt,()=>setTimeout(refresh,0)));
  }
  function boot(){ensureButton();ensureSheetButton();hook();setInterval(()=>{ensureButton();ensureSheetButton();hook();refresh()},700);console.info('[FRONT] AI head cutout enabled + visible upload entry')}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
