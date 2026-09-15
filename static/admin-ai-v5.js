/* 本福丸後台模板 AI：只保留 AI 摳圖。AI 擴圖已下線。 */
(function(){
'use strict';
if(window.__bfAdminAiRemoveOnly)return;window.__bfAdminAiRemoveOnly=true;
const by=id=>document.getElementById(id),canvas=()=>window.visualCanvas||null,active=()=>canvas()?.getActiveObject?.()||null;
const isImage=o=>!!(o&&o.type==='image'&&!o.isTplBg&&!o.isSlot);
let busy=false;
function status(s){const e=by('bf-tpl-status');if(e)e.textContent=s}
function load(src){return new Promise((r,j)=>{const i=new Image();i.onload=()=>r(i);i.onerror=()=>j(new Error('圖片載入失敗'));i.src=src})}
function blob(c,q=.92){return new Promise((r,j)=>c.toBlob(b=>b?r(b):j(new Error('圖片處理失敗')),'image/webp',q))}
async function sourceBlob(o,max=1800){
  const el=o.getElement?.()||o._element;if(!el)throw new Error('找不到圖片來源');
  const iw=el.naturalWidth||el.width,ih=el.naturalHeight||el.height,r=Math.min(1,max/Math.max(iw,ih)),w=Math.max(1,Math.round(iw*r)),h=Math.max(1,Math.round(ih*r)),c=document.createElement('canvas');
  c.width=w;c.height=h;c.getContext('2d').drawImage(el,0,0,w,h);
  let q=.94,b=await blob(c,q);while(b.size>5.8*1024*1024&&q>.68){q-=.06;b=await blob(c,q)}c.width=c.height=1;return b;
}
async function replace(old,b){
  const c=canvas(),idx=c.getObjects().indexOf(old),center=old.getCenterPoint(),ow=old.getScaledWidth(),oh=old.getScaledHeight(),url=URL.createObjectURL(b),el=await load(url);URL.revokeObjectURL(url);
  const neo=new fabric.Image(el,{left:center.x,top:center.y,originX:'center',originY:'center',angle:old.angle||0,flipX:!!old.flipX,flipY:!!old.flipY,opacity:old.opacity??1,objectCaching:true,centeredScaling:true});
  const fit=Math.min(ow/Math.max(1,neo.width),oh/Math.max(1,neo.height));neo.scaleX=fit;neo.scaleY=fit;neo.originalName=old.originalName||'圖片';neo.stickerId=old.stickerId||'';neo.role=old.role;neo.aiBackgroundRemoved=true;
  const f=new File([b],'ai-cutout.png',{type:'image/png'});try{neo.publicSrc=await uploadAdminImage(f,'template')}catch(e){console.warn('[ADMIN AI] result upload warning',e)}
  c.remove(old);c.insertAt(neo,Math.max(0,idx),false);c.setActiveObject(neo);neo.setCoords();c.requestRenderAll();c.fire('object:modified',{target:neo});return neo;
}
async function runRemove(){
  if(busy)return;const old=active();if(!isImage(old))return alert('請先選取一張圖片');
  busy=true;status('AI 正在摳圖（冷啟動第一次可能較久）…');
  try{
    const b=await sourceBlob(old),fd=new FormData();fd.append('image',b,'image.webp');
    const r=await fetch('/api/ai/remove-background',{method:'POST',body:fd,cache:'no-store'});
    if(!r.ok){let m='AI 摳圖失敗';try{const j=await r.json();m=j.msg||m}catch(e){}throw new Error(m)}
    const out=await r.blob();if(!out.size)throw new Error('AI 沒有回傳圖片');await replace(old,out);status('AI 摳圖完成 ✓');
  }catch(e){console.error('[ADMIN AI REMOVE]',e);alert(e.message||'AI 摳圖失敗')}finally{busy=false}
}
window.bfAdminRemoveBackground=runRemove;
function removeExpandUi(){
  by('bf-admin-ai-v5-panel')?.remove();by('bf-tpl-ai-v5-panel')?.remove();
  const main=by('bf-tpl-expand-v4');if(main)main.style.display='none';
  document.querySelectorAll('#bf-tpl-objectbar .bf-expand-btn').forEach(b=>b.style.display='none');
}
function bind(){
  removeExpandUi();const bar=by('bf-tpl-objectbar');if(!bar)return;
  const ai=bar.querySelector('.bf-ai-btn');if(ai&&!ai.dataset.removeOnly){ai.dataset.removeOnly='1';ai.textContent='AI 摳圖';ai.onclick=e=>{e.preventDefault();e.stopPropagation();e.stopImmediatePropagation();runRemove()}}
  const top=by('bf-tpl-ai-v4');if(top&&!top.dataset.removeOnly){top.dataset.removeOnly='1';top.innerHTML='<span class="ico"><i class="fa-solid fa-wand-magic-sparkles"></i></span>AI 摳圖';top.onclick=e=>{e.preventDefault();e.stopPropagation();e.stopImmediatePropagation();runRemove()}}
}
function boot(){bind();let n=0;const t=setInterval(()=>{bind();if(++n>120)clearInterval(t)},500);console.info('[ADMIN] AI remove-background only enabled')}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
