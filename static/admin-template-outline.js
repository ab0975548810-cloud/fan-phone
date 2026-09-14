/* 本福丸模板編輯器：圖片／AI 去背描邊（與前台樣式一致） */
(function(){
  'use strict';
  if(window.__benfuwanTemplateOutlineInstalled)return;
  window.__benfuwanTemplateOutlineInstalled=true;

  const by=id=>document.getElementById(id);
  const STYLE={
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
  let busy=false,applyTimer=null;

  function isImage(o){return !!o&&o.type==='image'&&!o.isTplBg&&!o.isSlot}
  function active(){return window.visualCanvas?.getActiveObject?.()||null}
  function status(msg){const e=by('bf-tpl-status');if(e)e.textContent=msg}
  function proxyUrl(url){url=String(url||'').trim();if(!url||url.startsWith('data:')||url.startsWith('blob:')||url.startsWith('/'))return url;try{const u=new URL(url,location.href);if(u.origin===location.origin)return u.href}catch(e){}return '/api/admin/template_asset_proxy?url='+encodeURIComponent(url)}
  function loadImage(src){return new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=()=>reject(new Error('圖片讀取失敗'));im.src=src})}
  function toBlob(c){return new Promise((resolve,reject)=>c.toBlob(b=>b?resolve(b):reject(new Error('描邊輸出失敗')),'image/webp',.94))}

  // 讓描邊來源資訊跟模板 JSON 一起保存，重新開模板後仍可改／關閉描邊。
  const oldToObject=fabric.Object.prototype.toObject;
  if(!fabric.Object.prototype.__bfOutlineSerializePatched){
    fabric.Object.prototype.toObject=function(props){
      const out=oldToObject.call(this,props);
      ['aiOutlineSourcePublic','aiOutlineStyle','aiOutlineWidth','aiOutlineColor','aiBackgroundRemoved'].forEach(k=>{if(this[k]!==undefined)out[k]=this[k]});
      return out;
    };
    fabric.Object.prototype.__bfOutlineSerializePatched=true;
  }

  function ensureCss(){if(by('bf-tpl-outline-css'))return;const s=document.createElement('style');s.id='bf-tpl-outline-css';s.textContent=`
    #bf-tpl-outline-panel{display:none;margin-top:8px;padding:11px;border:1px solid #efdfe5;background:#fff;border-radius:14px}#bf-tpl-outline-panel.show{display:block}
    .bf-ol-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:9px;color:#d95580;font-size:12px;font-weight:900}.bf-ol-head button{border:1px solid #efd3dc;background:#fff;border-radius:999px;color:#d95580;padding:5px 9px;font-size:10px;font-weight:800}
    .bf-ol-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:7px}.bf-ol-style{border:1px solid #efdee4;background:#fff;border-radius:11px;padding:8px 3px;font-size:10px;font-weight:900;color:#685e63}.bf-ol-style.active{border-color:#ff6f9a;background:#fff0f5;color:#f54f84}
    .bf-ol-row{display:flex;align-items:center;gap:9px;margin-top:11px}.bf-ol-row label{width:52px;font-size:10px;font-weight:900;color:#766970}.bf-ol-row input[type=range]{flex:1;accent-color:#ff6f9a}.bf-ol-value{width:30px;text-align:right;font-size:10px;color:#93868c}.bf-ol-colors{display:flex;gap:7px;align-items:center}.bf-ol-color{width:30px;height:30px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 0 1px #dfd2d7}.bf-ol-color.active{box-shadow:0 0 0 2px #ff6f9a}#bf-ol-custom{width:42px;height:34px;border:1px solid #eadce1;border-radius:9px;padding:2px;background:#fff}
    #bf-tpl-objectbar .bf-outline-admin-btn{display:none}#bf-tpl-objectbar.has-outline-image .bf-outline-admin-btn{display:inline-block}
    @media(max-width:760px){.bf-ol-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
  `;document.head.appendChild(s)}

  function ensureUi(){
    ensureCss();const tools=by('bf-tpl-tools');if(!tools)return;
    if(!by('bf-tpl-outline-panel')){
      const p=document.createElement('div');p.id='bf-tpl-outline-panel';
      p.innerHTML=`<div class="bf-ol-head"><span>圖片描邊</span><button data-close>收起</button></div><div class="bf-ol-grid">${Object.entries(STYLE).map(([k,v])=>`<button type="button" class="bf-ol-style" data-style="${k}">${v.label}</button>`).join('')}</div><div class="bf-ol-row"><label>粗細</label><input id="bf-ol-width" type="range" min="2" max="28" step="1" value="8"><span id="bf-ol-value" class="bf-ol-value">8</span></div><div class="bf-ol-row"><label>顏色</label><div class="bf-ol-colors"><button type="button" class="bf-ol-color" data-color="#ffffff" style="background:#fff"></button><button type="button" class="bf-ol-color" data-color="#111111" style="background:#111"></button><button type="button" class="bf-ol-color" data-color="#ff6f9a" style="background:#ff6f9a"></button><input id="bf-ol-custom" type="color" value="#ffffff"></div></div><div style="font-size:10px;color:#8e8288;line-height:1.5;margin-top:8px">圖片與 AI 去背圖都能用；效果會直接存進模板，前台套用模板與生產圖都會保留。</div>`;
      tools.appendChild(p);p.querySelector('[data-close]').onclick=()=>p.classList.remove('show');p.querySelectorAll('[data-style]').forEach(b=>b.onclick=()=>applyStyle(b.dataset.style));
      p.querySelectorAll('[data-color]').forEach(b=>b.onclick=()=>{const c=by('bf-ol-custom');if(c)c.value=b.dataset.color;const o=active();if(o){o.aiOutlineColor=b.dataset.color;o.aiOutlineStyle='custom'}sync();applyStyle('custom')});
      by('bf-ol-custom').onchange=()=>{const o=active();if(o){o.aiOutlineColor=by('bf-ol-custom').value;o.aiOutlineStyle='custom'}sync();applyStyle('custom')};
      by('bf-ol-width').oninput=()=>{by('bf-ol-value').textContent=by('bf-ol-width').value;clearTimeout(applyTimer);applyTimer=setTimeout(()=>{const o=active();if(isImage(o)&&(o.aiOutlineStyle||'none')!=='none')applyStyle(o.aiOutlineStyle)},180)};
    }
    const obj=by('bf-tpl-objectbar');if(obj&&!obj.querySelector('.bf-outline-admin-btn')){const b=document.createElement('button');b.className='bf-outline-admin-btn';b.textContent='描邊';b.onclick=()=>{by('bf-tpl-outline-panel')?.classList.add('show');sync()};obj.insertBefore(b,obj.querySelector('.danger')||obj.lastElementChild)}
  }

  function sourceUrl(o){return o.aiOutlineSourcePublic||o.publicSrc||o.getSrc?.()||o._element?.src||''}
  function widthPx(img,ui,extra=1){const base=Math.max(180,Math.min(img.naturalWidth||img.width||900,img.naturalHeight||img.height||900));return Math.max(2,Math.min(64,Math.round(base*(Number(ui||8)/700)*extra)))}
  function drawRing(g,img,pad,r,alpha=1,jitter=0){const steps=Math.max(28,Math.min(72,Math.round(r*2.7)));g.globalAlpha=alpha;for(let i=0;i<steps;i++){const a=Math.PI*2*i/steps,j=jitter?((Math.sin(i*2.71)+Math.cos(i*1.37))*jitter):0,rr=r+j;g.drawImage(img,pad+Math.cos(a)*rr,pad+Math.sin(a)*rr)}g.globalAlpha=1}
  function tint(g,c,color){g.globalCompositeOperation='source-in';g.fillStyle=color;g.fillRect(0,0,c.width,c.height);g.globalCompositeOperation='source-over'}
  async function build(src,style,color,ui){const img=await loadImage(proxyUrl(src));const iw=img.naturalWidth||img.width,ih=img.naturalHeight||img.height,w=widthPx(img,ui,style==='sticker'?1.8:1),pad=Math.max(w*3,style==='glow'?w*5:w*2)+5,c=document.createElement('canvas');c.width=Math.ceil(iw+pad*2);c.height=Math.ceil(ih+pad*2);const g=c.getContext('2d');if(style==='shadow'){g.save();g.shadowColor='rgba(0,0,0,.42)';g.shadowBlur=Math.max(8,w*2.6);g.shadowOffsetX=Math.max(2,w*.5);g.shadowOffsetY=Math.max(3,w*.75);g.drawImage(img,pad,pad);g.restore();g.drawImage(img,pad,pad);return c}if(style==='glow'){g.save();g.shadowColor=color||'#ff8fb2';g.shadowBlur=Math.max(12,w*3.2);for(let i=0;i<3;i++)g.drawImage(img,pad,pad);g.restore();g.drawImage(img,pad,pad);return c}if(style==='hand'){drawRing(g,img,pad,w,.78,Math.max(1,w*.16));drawRing(g,img,pad,w*.72,.5,Math.max(.6,w*.12));tint(g,c,color||'#fff');g.drawImage(img,pad,pad);return c}drawRing(g,img,pad,w,1,0);drawRing(g,img,pad,w*.58,1,0);if(style==='dashed'){tint(g,c,color||'#fff');g.globalCompositeOperation='destination-out';const cell=Math.max(7,Math.round(w*.95));for(let y=0;y<c.height;y+=cell*2){for(let x=(Math.floor(y/(cell*2))%2)*cell;x<c.width;x+=cell*2)g.clearRect(x,y,cell,cell)}g.globalCompositeOperation='source-over';g.drawImage(img,pad,pad);return c}tint(g,c,color||'#fff');g.drawImage(img,pad,pad);return c}

  async function replace(oldObj,blob,publicUrl,meta){const c=window.visualCanvas;if(!c)throw new Error('畫布尚未準備好');const idx=c.getObjects().indexOf(oldObj),center=oldObj.getCenterPoint(),oldW=Math.max(1,oldObj.getScaledWidth()),oldH=Math.max(1,oldObj.getScaledHeight()),src=URL.createObjectURL(blob);let el;try{el=await loadImage(src)}finally{URL.revokeObjectURL(src)}const neo=new fabric.Image(el,{left:center.x,top:center.y,originX:'center',originY:'center',angle:oldObj.angle||0,flipX:!!oldObj.flipX,flipY:!!oldObj.flipY,opacity:oldObj.opacity??1,objectCaching:true});const fit=Math.min(oldW/Math.max(1,neo.width),oldH/Math.max(1,neo.height));neo.set({scaleX:fit,scaleY:fit});neo.publicSrc=publicUrl;neo.originalName=oldObj.originalName||'圖片';neo.stickerId=oldObj.stickerId||'';neo.aiBackgroundRemoved=!!oldObj.aiBackgroundRemoved;neo.aiOutlineSourcePublic=meta.source;neo.aiOutlineStyle=meta.style;neo.aiOutlineWidth=meta.width;neo.aiOutlineColor=meta.color;['transparentCorners','cornerColor','cornerStrokeColor','borderColor','cornerSize','touchCornerSize','padding','centeredScaling','centeredRotation'].forEach(k=>{if(oldObj[k]!==undefined)neo[k]=oldObj[k]});c.remove(oldObj);c.insertAt(neo,Math.max(0,idx),false);c.setActiveObject(neo);neo.setCoords();c.requestRenderAll();return neo}

  async function applyStyle(style){if(busy)return;const o=active();if(!isImage(o)){alert('請先點選一張圖片');return}style=STYLE[style]?style:'none';busy=true;by('bf-tpl-outline-panel')?.classList.add('show');status(style==='none'?'正在移除描邊…':'正在套用描邊…');try{const source=sourceUrl(o);if(!source)throw new Error('找不到圖片來源');const width=Number(by('bf-ol-width')?.value||o.aiOutlineWidth||8),picked=by('bf-ol-custom')?.value||o.aiOutlineColor||'#ffffff',color=STYLE[style].color||picked;let blob,publicUrl;if(style==='none'){const img=await loadImage(proxyUrl(source));const c=document.createElement('canvas');c.width=img.naturalWidth||img.width;c.height=img.naturalHeight||img.height;c.getContext('2d').drawImage(img,0,0);blob=await toBlob(c);c.width=c.height=1}else{const c=await build(source,style,color,width);blob=await toBlob(c);c.width=c.height=1}publicUrl=await uploadAdminImage(new File([blob],style==='none'?'outline-source.webp':'outline-'+style+'.webp',{type:'image/webp'}),'template');await replace(o,blob,publicUrl,{source,style,width,color});status(style==='none'?'描邊已關閉':STYLE[style].label+'已套用');sync()}catch(e){console.error('[TPL OUTLINE]',e);alert(e.message||'描邊處理失敗')}finally{busy=false}}

  function sync(){ensureUi();const o=active(),ok=isImage(o),obj=by('bf-tpl-objectbar');obj?.classList.toggle('has-outline-image',ok);if(!ok)return;const style=o.aiOutlineStyle||'none',width=Math.max(2,Math.min(28,Number(o.aiOutlineWidth||8))),color=o.aiOutlineColor||'#ffffff';by('bf-ol-width').value=String(width);by('bf-ol-value').textContent=String(width);by('bf-ol-custom').value=color;document.querySelectorAll('#bf-tpl-outline-panel [data-style]').forEach(b=>b.classList.toggle('active',b.dataset.style===style));document.querySelectorAll('#bf-tpl-outline-panel [data-color]').forEach(b=>b.classList.toggle('active',String(b.dataset.color).toLowerCase()===String(color).toLowerCase()))}
  function hook(){ensureUi();const c=window.visualCanvas;if(!c||c.__bfOutlineHooked)return;c.__bfOutlineHooked=true;['selection:created','selection:updated','selection:cleared','object:modified'].forEach(ev=>c.on(ev,()=>setTimeout(sync,0)));sync()}
  function boot(){ensureUi();const timer=setInterval(()=>{hook();if(by('template-modal'))ensureUi()},500);setTimeout(()=>clearInterval(timer),30000);console.info('[ADMIN] template image outline enabled')}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();