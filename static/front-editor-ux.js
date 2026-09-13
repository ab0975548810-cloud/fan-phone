/* 本福丸前台：手機版編輯器 UX 強化（貼紙庫 / 物件工具列 / AI 去背描邊） */
(function(){
  'use strict';
  if(window.__benfuwanEditorUxInstalled)return;
  window.__benfuwanEditorUxInstalled=true;

  function activeObject(){
    try{return (typeof canvas!=='undefined'&&canvas)?canvas.getActiveObject():null}catch(e){return null}
  }
  function isAiImage(o){return !!(o&&o.type==='image'&&o.aiBackgroundRemoved)}

  function ensureStyles(){
    if(document.getElementById('bf-editor-ux-style'))return;
    const s=document.createElement('style');s.id='bf-editor-ux-style';
    s.textContent=`
      /* 貼紙庫：只讓分類列橫向滑，不讓整個內容被撐寬 */
      #sheet-sticker,#sheet-sticker .sheet-body{min-width:0;max-width:100%;overflow-x:hidden}
      #sheet-sticker .sticker-tabs{display:flex;width:100%;max-width:100%;min-width:0;gap:7px;overflow-x:auto;overflow-y:hidden;padding:0 1px 10px;scrollbar-width:none;-webkit-overflow-scrolling:touch;overscroll-behavior-x:contain}
      #sheet-sticker .sticker-tabs::-webkit-scrollbar{display:none}
      #sheet-sticker .sticker-tabs .pill{flex:0 0 auto;min-width:max-content}
      #sheet-sticker .sticker-grid{width:100%;min-width:0;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px}
      #sheet-sticker .sticker-item{width:100%;min-width:0;overflow:hidden}
      #sheet-sticker .sticker-item img{width:100%;height:100%;max-width:100%;max-height:100%;object-fit:contain}

      /* 選取物件工具列改為覆蓋底部主工具列，不再壓住畫布 */
      #page-editor>.object-bar.bf-docked-object-bar{display:none!important;position:absolute!important;left:0!important;right:0!important;bottom:0!important;height:78px!important;z-index:75!important;border-radius:0!important;border-left:0!important;border-right:0!important;border-bottom:0!important;border-top:1px solid var(--line)!important;background:rgba(255,255,255,.99)!important;box-shadow:0 -5px 18px rgba(0,0,0,.06)!important;padding:7px 4px calc(7px + env(safe-area-inset-bottom))!important;grid-template-columns:repeat(auto-fit,minmax(44px,1fr))!important;gap:1px!important}
      #page-editor>.object-bar.bf-docked-object-bar.show{display:grid!important}
      #page-editor>.object-bar.bf-docked-object-bar button{min-width:0!important;padding:5px 1px!important;font-size:9px!important;line-height:1.15!important}
      #page-editor>.object-bar.bf-docked-object-bar button i{font-size:15px!important;margin-bottom:4px!important}
      #bf-ai-outline-btn{display:none}
      #bf-ai-outline-btn.show{display:block}

      /* AI 描邊面板 */
      .bf-outline-box{padding:4px 2px 8px}
      .bf-outline-tip{font-size:11px;color:#8e8288;line-height:1.55;margin-bottom:12px}
      .bf-outline-color-row{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:11px 12px;border:1px solid var(--line);border-radius:14px;background:#fff9fb;margin-bottom:12px;font-size:12px;font-weight:850}
      .bf-outline-color-row input{width:52px;height:36px;border:1px solid var(--line);border-radius:10px;background:#fff;padding:2px}
      .bf-outline-choices{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
      .bf-outline-choice{border:1px solid #f0dce3;background:#fff;border-radius:13px;padding:11px 4px;font-size:11px;font-weight:900;color:#685e63}
      .bf-outline-choice.active{border-color:var(--pink);background:var(--pink-soft);color:var(--pink-dark)}
      .bf-outline-preview{margin-top:11px;padding:10px 12px;border-radius:13px;background:#fff5f8;color:#8a7680;font-size:10px;line-height:1.5}
    `;
    document.head.appendChild(s);
  }

  function dockObjectBar(){
    const page=document.getElementById('page-editor'),bar=document.getElementById('object-bar');
    if(!page||!bar)return;
    if(bar.parentElement!==page)page.appendChild(bar);
    bar.classList.add('bf-docked-object-bar');
    if(!document.getElementById('bf-ai-outline-btn')){
      const b=document.createElement('button');
      b.id='bf-ai-outline-btn';b.type='button';b.title='AI 去背描邊';
      b.innerHTML='<i class="fa-solid fa-border-style"></i>描邊';
      b.onclick=()=>window.openAiOutlineSheet?.();
      const del=[...bar.querySelectorAll('button')].find(x=>/deleteActive/.test(x.getAttribute('onclick')||''));
      if(del)bar.insertBefore(b,del);else bar.appendChild(b);
    }
    updateOutlineButton();
  }

  function ensureOutlineSheet(){
    if(document.getElementById('sheet-outline'))return;
    const app=document.getElementById('app');if(!app)return;
    const sheet=document.createElement('div');sheet.className='sheet';sheet.id='sheet-outline';
    sheet.innerHTML=`<div class="sheet-header"><span>AI 去背描邊</span><button class="sheet-close" onclick="closeSheets()"><i class="fa-solid fa-xmark"></i></button></div><div class="sheet-body"><div class="bf-outline-box"><div class="bf-outline-tip">選取 AI 去背後的圖片，可以加上貼紙感描邊。描邊會跟著圖片一起縮放、旋轉，也會一起輸出到生產圖。</div><div class="bf-outline-color-row"><span>描邊顏色</span><input id="bf-outline-color" type="color" value="#ffffff"></div><div class="bf-outline-choices"><button class="bf-outline-choice" data-strength="0">無</button><button class="bf-outline-choice" data-strength="thin">細</button><button class="bf-outline-choice" data-strength="medium">中</button><button class="bf-outline-choice" data-strength="thick">粗</button></div><div class="bf-outline-preview">建議：照片人物或寵物用白色「中」描邊最像貼紙；深色背景可以改成粉色或其他顏色。</div></div></div>`;
    app.appendChild(sheet);
    sheet.querySelectorAll('.bf-outline-choice').forEach(b=>b.addEventListener('click',()=>applyOutline(b.dataset.strength)));
    document.getElementById('bf-outline-color')?.addEventListener('change',()=>{
      const o=activeObject();if(o?.aiOutlineStrength&&o.aiOutlineStrength!=='0')applyOutline(o.aiOutlineStrength);
    });
  }

  function updateOutlineButton(){
    const b=document.getElementById('bf-ai-outline-btn'),o=activeObject();
    if(!b)return;b.classList.toggle('show',isAiImage(o));
  }
  function updateOutlineSheet(){
    const o=activeObject(),color=document.getElementById('bf-outline-color');
    if(color&&o?.aiOutlineColor)color.value=o.aiOutlineColor;
    const strength=String(o?.aiOutlineStrength||'0');
    document.querySelectorAll('#sheet-outline .bf-outline-choice').forEach(b=>b.classList.toggle('active',b.dataset.strength===strength));
  }

  window.openAiOutlineSheet=function(){
    const o=activeObject();
    if(!isAiImage(o)){if(typeof toast==='function')toast('請先選取 AI 去背後的圖片');return}
    ensureOutlineSheet();updateOutlineSheet();
    if(typeof openSheet==='function')openSheet('sheet-outline');
  };

  function loadImage(src){
    return new Promise((resolve,reject)=>{
      const img=new Image();
      if(/^https?:/i.test(src))img.crossOrigin='anonymous';
      img.onload=()=>resolve(img);img.onerror=()=>reject(new Error('圖片讀取失敗'));img.src=src;
    });
  }
  function strengthWidth(img,strength){
    const base=Math.max(120,Math.min(img.naturalWidth||img.width||800,img.naturalHeight||img.height||800));
    const p=strength==='thin'?.0075:strength==='thick'?.025:.014;
    return Math.max(3,Math.min(48,Math.round(base*p)));
  }
  async function buildOutlined(src,color,strength){
    const img=await loadImage(src),w=strengthWidth(img,strength),pad=w+3;
    const c=document.createElement('canvas');c.width=(img.naturalWidth||img.width)+pad*2;c.height=(img.naturalHeight||img.height)+pad*2;
    const g=c.getContext('2d');
    const drawRing=(r,steps)=>{for(let i=0;i<steps;i++){const a=Math.PI*2*i/steps;g.drawImage(img,pad+Math.cos(a)*r,pad+Math.sin(a)*r)}};
    drawRing(w,Math.max(24,Math.min(48,w*2)));drawRing(w*.58,24);g.drawImage(img,pad,pad);
    g.globalCompositeOperation='source-in';g.fillStyle=color;g.fillRect(0,0,c.width,c.height);
    g.globalCompositeOperation='source-over';g.drawImage(img,pad,pad);
    return c.toDataURL('image/png');
  }

  function replaceFabricImage(oldObj,src,meta){
    return new Promise((resolve,reject)=>{
      const center=oldObj.getCenterPoint(),idx=canvas.getObjects().indexOf(oldObj);
      fabric.Image.fromURL(src,newObj=>{
        try{
          const props={
            left:center.x,top:center.y,originX:'center',originY:'center',angle:oldObj.angle||0,
            scaleX:oldObj.scaleX||1,scaleY:oldObj.scaleY||1,flipX:!!oldObj.flipX,flipY:!!oldObj.flipY,
            opacity:oldObj.opacity??1,visible:oldObj.visible!==false,selectable:oldObj.selectable!==false,evented:oldObj.evented!==false,
            role:oldObj.role,slotId:oldObj.slotId,slotMeta:oldObj.slotMeta,aiBackgroundRemoved:true,originalName:oldObj.originalName,
            materialType:oldObj.materialType,clipPath:oldObj.clipPath||undefined,
            aiOutlineSource:meta.source,aiOutlineStrength:meta.strength,aiOutlineColor:meta.color
          };
          newObj.set(props);if(typeof styleEditableObject==='function')styleEditableObject(newObj);
          canvas.remove(oldObj);canvas.insertAt(newObj,Math.max(0,idx),false);canvas.setActiveObject(newObj);newObj.setCoords();canvas.renderAll();
          if(typeof recordHistory==='function')recordHistory();if(typeof renderLayerList==='function')renderLayerList();
          updateOutlineButton();updateOutlineSheet();resolve(newObj);
        }catch(e){reject(e)}
      },{crossOrigin:'anonymous'});
    });
  }

  async function applyOutline(strength){
    const o=activeObject();if(!isAiImage(o)){if(typeof toast==='function')toast('請先選取 AI 去背後的圖片');return}
    const color=document.getElementById('bf-outline-color')?.value||o.aiOutlineColor||'#ffffff';
    const current=o.getSrc?.()||o._element?.src||'';if(!current)return;
    const source=o.aiOutlineSource||current;
    if(typeof setBusy==='function')setBusy(true,strength==='0'?'正在移除描邊...':'正在產生描邊...');
    try{
      const src=strength==='0'?source:await buildOutlined(source,color,strength);
      await replaceFabricImage(o,src,{source,strength,color});
      if(typeof toast==='function')toast(strength==='0'?'描邊已關閉':'描邊已套用');
    }catch(e){console.error(e);if(typeof toast==='function')toast('描邊處理失敗，請再試一次')}
    finally{if(typeof setBusy==='function')setBusy(false)}
  }

  function wrapSelectionSync(){
    const original=window.syncSelection;
    if(typeof original==='function'&&!original.__bfOutlineWrapped){
      const wrapped=function(){const r=original.apply(this,arguments);updateOutlineButton();updateOutlineSheet();return r};
      wrapped.__bfOutlineWrapped=true;window.syncSelection=wrapped;
    }
    const originalAi=window.removeBackgroundForActive;
    if(typeof originalAi==='function'&&!originalAi.__bfOutlineWrapped){
      const wrapped=async function(){const r=await originalAi.apply(this,arguments);setTimeout(()=>{const o=activeObject();if(isAiImage(o)&&!o.aiOutlineSource){try{o.aiOutlineSource=o.getSrc?.()||o._element?.src||''}catch(e){}}updateOutlineButton()},30);return r};
      wrapped.__bfOutlineWrapped=true;window.removeBackgroundForActive=wrapped;
    }
  }

  function boot(){ensureStyles();dockObjectBar();ensureOutlineSheet();wrapSelectionSync();console.info('[FRONT] editor UX patch enabled: sticker panel + docked object bar + AI outline')}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
