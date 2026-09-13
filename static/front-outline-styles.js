/* 本福丸前台：AI 去背圖片進階描邊樣式（不含黃邊/藍邊/雙層/圓角貼紙邊） */
(function(){
  'use strict';
  if(window.__benfuwanOutlineStylesInstalled)return;
  window.__benfuwanOutlineStylesInstalled=true;

  const STYLE_META={
    none:{label:'無',color:null},
    white:{label:'白邊',color:'#ffffff'},
    black:{label:'黑邊',color:'#111111'},
    pink:{label:'粉邊',color:'#ff6f9a'},
    shadow:{label:'陰影',color:'#000000'},
    glow:{label:'發光',color:'#ff8fb2'},
    dashed:{label:'虛線',color:'#ffffff'},
    hand:{label:'手繪',color:'#ffffff'},
    sticker:{label:'厚貼紙',color:'#ffffff'},
    custom:{label:'自訂色',color:null}
  };
  let applyTimer=null;

  function activeObject(){
    try{return (typeof canvas!=='undefined'&&canvas)?canvas.getActiveObject():null}catch(e){return null}
  }
  function isAiImage(o){return !!(o&&o.type==='image'&&o.aiBackgroundRemoved)}
  function esc(s){return String(s||'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}

  function ensureStyles(){
    if(document.getElementById('bf-outline-style-v2-css'))return;
    const s=document.createElement('style');s.id='bf-outline-style-v2-css';
    s.textContent=`
      #sheet-outline-v2{height:min(61%,560px)}
      .bf-os-wrap{padding:2px 0 10px}
      .bf-os-tip{font-size:10px;line-height:1.55;color:#93868c;margin:0 2px 11px}
      .bf-os-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:7px;margin-bottom:14px}
      .bf-os-card{border:1px solid #efdee4;background:#fff;border-radius:13px;padding:9px 2px 8px;font-size:10px;font-weight:900;color:#685e63;min-width:0}
      .bf-os-card i{display:block;font-size:16px;color:#f06c94;margin-bottom:5px}
      .bf-os-card.active{border-color:var(--pink);background:var(--pink-soft);color:var(--pink-dark);box-shadow:0 0 0 2px rgba(255,111,154,.08)}
      .bf-os-section{border-top:1px solid #f4e9ed;padding-top:12px;margin-top:3px}
      .bf-os-row{display:flex;align-items:center;gap:10px;margin-bottom:11px}
      .bf-os-row label{width:62px;flex:0 0 62px;font-size:11px;font-weight:900;color:#766970}
      .bf-os-row input[type=range]{flex:1;accent-color:var(--pink)}
      .bf-os-value{width:34px;text-align:right;font-size:10px;color:#9a8d93}
      .bf-os-colors{display:flex;gap:8px;align-items:center;flex:1;flex-wrap:wrap}
      .bf-os-swatch{width:31px;height:31px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 0 1px #dfd2d7;padding:0}
      .bf-os-swatch.active{box-shadow:0 0 0 2px var(--pink)}
      #bf-os-custom-color{width:42px;height:34px;border:1px solid #eadce1;border-radius:10px;background:#fff;padding:2px}
      .bf-os-note{background:#fff5f8;border-radius:12px;padding:9px 11px;font-size:10px;line-height:1.45;color:#8b7881}
      @media(max-width:390px){.bf-os-grid{grid-template-columns:repeat(4,minmax(0,1fr))}}
    `;
    document.head.appendChild(s);
  }

  function iconFor(style){
    return ({none:'fa-ban',white:'fa-circle',black:'fa-circle',pink:'fa-circle',shadow:'fa-cloud',glow:'fa-sun',dashed:'fa-ellipsis',hand:'fa-pen-nib',sticker:'fa-certificate',custom:'fa-palette'})[style]||'fa-circle';
  }

  function ensureSheet(){
    ensureStyles();
    let old=document.getElementById('sheet-outline');if(old)old.remove();
    let sheet=document.getElementById('sheet-outline-v2');if(sheet)return sheet;
    const app=document.getElementById('app');if(!app)return null;
    sheet=document.createElement('div');sheet.className='sheet';sheet.id='sheet-outline-v2';
    const cards=Object.entries(STYLE_META).map(([key,m])=>`<button type="button" class="bf-os-card" data-style="${key}"><i class="fa-solid ${iconFor(key)}"></i>${esc(m.label)}</button>`).join('');
    sheet.innerHTML=`<div class="sheet-header"><span>描邊樣式</span><button class="sheet-close" onclick="closeSheets()"><i class="fa-solid fa-xmark"></i></button></div><div class="sheet-body"><div class="bf-os-wrap"><div class="bf-os-tip">AI 去背後可直接套用。描邊效果會一起進入預覽、購物車與生產 PNG。</div><div class="bf-os-grid">${cards}</div><div class="bf-os-section"><div class="bf-os-row"><label>粗細</label><input id="bf-os-width" type="range" min="2" max="28" step="1" value="8"><span id="bf-os-width-value" class="bf-os-value">8</span></div><div class="bf-os-row"><label>顏色</label><div class="bf-os-colors"><button type="button" class="bf-os-swatch" data-color="#ffffff" style="background:#fff"></button><button type="button" class="bf-os-swatch" data-color="#111111" style="background:#111"></button><button type="button" class="bf-os-swatch" data-color="#ff6f9a" style="background:#ff6f9a"></button><input id="bf-os-custom-color" type="color" value="#ffffff" title="自訂顏色"></div></div></div><div class="bf-os-note">人物／寵物：白邊、厚貼紙最好用；夢幻風可用發光；拼貼或手帳風可試虛線、手繪。</div></div></div>`;
    app.appendChild(sheet);
    sheet.querySelectorAll('.bf-os-card').forEach(b=>b.addEventListener('click',()=>applyStyle(b.dataset.style)));
    sheet.querySelectorAll('.bf-os-swatch').forEach(b=>b.addEventListener('click',()=>{
      const input=document.getElementById('bf-os-custom-color');if(input)input.value=b.dataset.color;
      const o=activeObject();if(o){o.aiOutlineColor=b.dataset.color;o.aiOutlineStyle='custom'}
      syncSheet();applyStyle('custom');
    }));
    const width=document.getElementById('bf-os-width');
    width?.addEventListener('input',()=>{const v=document.getElementById('bf-os-width-value');if(v)v.textContent=width.value;clearTimeout(applyTimer);applyTimer=setTimeout(()=>{const o=activeObject();if(o&&String(o.aiOutlineStyle||'none')!=='none')applyStyle(o.aiOutlineStyle)},180)});
    document.getElementById('bf-os-custom-color')?.addEventListener('change',()=>{const o=activeObject();if(o){o.aiOutlineColor=document.getElementById('bf-os-custom-color').value;o.aiOutlineStyle='custom'}syncSheet();applyStyle('custom')});
    return sheet;
  }

  function syncSheet(){
    ensureSheet();
    const o=activeObject();
    const style=String(o?.aiOutlineStyle||((o?.aiOutlineStrength&&o.aiOutlineStrength!=='0')?'custom':'none'));
    const width=Math.max(2,Math.min(28,Number(o?.aiOutlineWidth||8)));
    const color=o?.aiOutlineColor||'#ffffff';
    document.querySelectorAll('#sheet-outline-v2 .bf-os-card').forEach(b=>b.classList.toggle('active',b.dataset.style===style));
    const wr=document.getElementById('bf-os-width');if(wr)wr.value=String(width);
    const wv=document.getElementById('bf-os-width-value');if(wv)wv.textContent=String(width);
    const ci=document.getElementById('bf-os-custom-color');if(ci)ci.value=color;
    document.querySelectorAll('#sheet-outline-v2 .bf-os-swatch').forEach(b=>b.classList.toggle('active',b.dataset.color.toLowerCase()===String(color).toLowerCase()));
  }

  window.openAiOutlineSheet=function(){
    const o=activeObject();
    if(!isAiImage(o)){if(typeof toast==='function')toast('請先選取 AI 去背後的圖片');return}
    ensureSheet();syncSheet();
    if(typeof openSheet==='function')openSheet('sheet-outline-v2');
  };

  function loadImage(src){return new Promise((resolve,reject)=>{const img=new Image();if(/^https?:/i.test(src))img.crossOrigin='anonymous';img.onload=()=>resolve(img);img.onerror=()=>reject(new Error('圖片讀取失敗'));img.src=src})}
  function clampWidth(img,uiWidth,extra=1){const base=Math.max(180,Math.min(img.naturalWidth||img.width||900,img.naturalHeight||img.height||900));return Math.max(2,Math.min(64,Math.round(base*(Number(uiWidth||8)/700)*extra)))}
  function drawOffsetRing(g,img,pad,r,alpha=1,jitter=0){
    const steps=Math.max(28,Math.min(72,Math.round(r*2.7)));
    g.globalAlpha=alpha;
    for(let i=0;i<steps;i++){
      const a=Math.PI*2*i/steps;
      const jr=jitter?((Math.sin(i*2.71)+Math.cos(i*1.37))*jitter):0;
      const rr=r+jr;
      g.drawImage(img,pad+Math.cos(a)*rr,pad+Math.sin(a)*rr);
    }
    g.globalAlpha=1;
  }
  function tintCurrentAlpha(g,c,color){g.globalCompositeOperation='source-in';g.fillStyle=color;g.fillRect(0,0,c.width,c.height);g.globalCompositeOperation='source-over'}

  async function buildEffect(src,style,color,uiWidth){
    const img=await loadImage(src),iw=img.naturalWidth||img.width,ih=img.naturalHeight||img.height;
    const thick=style==='sticker'?1.8:1;
    const w=clampWidth(img,uiWidth,thick),pad=Math.max(w*3,style==='glow'?w*5:w*2)+5;
    const c=document.createElement('canvas');c.width=Math.ceil(iw+pad*2);c.height=Math.ceil(ih+pad*2);const g=c.getContext('2d');

    if(style==='shadow'){
      g.save();g.shadowColor='rgba(0,0,0,.42)';g.shadowBlur=Math.max(8,w*2.6);g.shadowOffsetX=Math.max(2,w*.5);g.shadowOffsetY=Math.max(3,w*.75);g.drawImage(img,pad,pad);g.restore();g.drawImage(img,pad,pad);return c.toDataURL('image/png');
    }
    if(style==='glow'){
      g.save();g.shadowColor=color||'#ff8fb2';g.shadowBlur=Math.max(12,w*3.2);for(let i=0;i<3;i++)g.drawImage(img,pad,pad);g.restore();g.drawImage(img,pad,pad);return c.toDataURL('image/png');
    }

    if(style==='hand'){
      drawOffsetRing(g,img,pad,w,0.78,Math.max(1,w*.16));
      drawOffsetRing(g,img,pad,w*.72,0.5,Math.max(.6,w*.12));
      tintCurrentAlpha(g,c,color||'#ffffff');g.drawImage(img,pad,pad);return c.toDataURL('image/png');
    }

    drawOffsetRing(g,img,pad,w,1,0);drawOffsetRing(g,img,pad,w*.58,1,0);
    if(style==='dashed'){
      tintCurrentAlpha(g,c,color||'#ffffff');
      g.globalCompositeOperation='destination-out';
      const cell=Math.max(7,Math.round(w*.95));
      for(let y=0;y<c.height;y+=cell*2){for(let x=(Math.floor(y/(cell*2))%2)*cell;x<c.width;x+=cell*2)g.clearRect(x,y,cell,cell)}
      g.globalCompositeOperation='source-over';g.drawImage(img,pad,pad);return c.toDataURL('image/png');
    }
    tintCurrentAlpha(g,c,color||'#ffffff');g.drawImage(img,pad,pad);return c.toDataURL('image/png');
  }

  function replaceFabricImage(oldObj,src,meta){
    return new Promise((resolve,reject)=>{
      const center=oldObj.getCenterPoint(),idx=canvas.getObjects().indexOf(oldObj);
      fabric.Image.fromURL(src,newObj=>{
        try{
          const props={left:center.x,top:center.y,originX:'center',originY:'center',angle:oldObj.angle||0,scaleX:oldObj.scaleX||1,scaleY:oldObj.scaleY||1,flipX:!!oldObj.flipX,flipY:!!oldObj.flipY,opacity:oldObj.opacity??1,visible:oldObj.visible!==false,selectable:oldObj.selectable!==false,evented:oldObj.evented!==false,role:oldObj.role,slotId:oldObj.slotId,slotMeta:oldObj.slotMeta,aiBackgroundRemoved:true,originalName:oldObj.originalName,materialType:oldObj.materialType,clipPath:oldObj.clipPath||undefined,aiOutlineSource:meta.source,aiOutlineStrength:meta.style==='none'?'0':'custom',aiOutlineStyle:meta.style,aiOutlineWidth:meta.width,aiOutlineColor:meta.color};
          newObj.set(props);if(typeof styleEditableObject==='function')styleEditableObject(newObj);
          canvas.remove(oldObj);canvas.insertAt(newObj,Math.max(0,idx),false);canvas.setActiveObject(newObj);newObj.setCoords();canvas.renderAll();
          if(typeof recordHistory==='function')recordHistory();if(typeof renderLayerList==='function')renderLayerList();syncSheet();resolve(newObj);
        }catch(e){reject(e)}
      },{crossOrigin:'anonymous'});
    });
  }

  async function applyStyle(style){
    const o=activeObject();if(!isAiImage(o)){if(typeof toast==='function')toast('請先選取 AI 去背後的圖片');return}
    style=STYLE_META[style]?style:'none';
    const current=o.getSrc?.()||o._element?.src||'';if(!current)return;
    const source=o.aiOutlineSource||current;
    const width=Number(document.getElementById('bf-os-width')?.value||o.aiOutlineWidth||8);
    const picked=document.getElementById('bf-os-custom-color')?.value||o.aiOutlineColor||'#ffffff';
    const color=STYLE_META[style].color||picked;
    if(typeof setBusy==='function')setBusy(true,style==='none'?'正在移除描邊...':'正在套用描邊...');
    try{
      const out=style==='none'?source:await buildEffect(source,style,color,width);
      await replaceFabricImage(o,out,{source,style,width,color});
      if(typeof toast==='function')toast(style==='none'?'描邊已關閉':STYLE_META[style].label+'已套用');
    }catch(e){console.error('[OUTLINE V2]',e);if(typeof toast==='function')toast('描邊處理失敗，請再試一次')}
    finally{if(typeof setBusy==='function')setBusy(false)}
  }

  function boot(){ensureStyles();ensureSheet();console.info('[FRONT] outline styles v2 enabled: white/black/pink/shadow/glow/dashed/hand/sticker/custom')}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else setTimeout(boot,0);
})();
