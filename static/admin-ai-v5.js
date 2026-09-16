/* 本福丸後台模板 AI v2：只保留 AI 摳圖；前後台共用同一套驗證流程。AI 擴圖維持下線。 */
(function(){
'use strict';
if(window.__bfAdminAiRemoveOnlyV2)return;window.__bfAdminAiRemoveOnlyV2=true;
const by=id=>document.getElementById(id),canvas=()=>window.visualCanvas||null,active=()=>canvas()?.getActiveObject?.()||null;
const isImage=o=>!!(o&&o.type==='image'&&!o.isTplBg&&!o.isSlot);
let busy=false;
function status(s){const e=by('bf-tpl-status');if(e)e.textContent=s}
function proxyUrl(url){const raw=String(url||'').trim();if(!raw||raw.startsWith('/')||raw.startsWith('data:')||raw.startsWith('blob:'))return raw;try{const u=new URL(raw,location.href);if(u.origin===location.origin)return u.href}catch(e){}return '/api/admin/template_asset_proxy?url='+encodeURIComponent(raw)}
function load(src){return new Promise((r,j)=>{const i=new Image();let done=false;const finish=e=>{if(done)return;done=true;clearTimeout(tm);e?j(e):r(i)};const tm=setTimeout(()=>finish(new Error('圖片載入逾時')),18000);i.onload=()=>finish();i.onerror=()=>finish(new Error('圖片載入失敗'));i.src=src})}

async function sourceBlob(o){
  const core=window.BenfuwanAiRemoveV2;if(!core)throw new Error('AI 摳圖核心尚未載入，請重新整理後再試');
  const el=o.getElement?.()||o._element;if(!el)throw new Error('找不到圖片來源');
  try{return await core.sourceBlobFromElement(el,{maxEdge:1800,maxBytes:5.5*1024*1024})}
  catch(firstErr){
    // 舊模板可能直接引用雲端圖，Canvas 會遇到 CORS；改走登入中的同網域代理再處理。
    if(!o.publicSrc)throw firstErr;
    try{const safe=await load(proxyUrl(o.publicSrc));return await core.sourceBlobFromElement(safe,{maxEdge:1800,maxBytes:5.5*1024*1024})}
    catch(e){throw firstErr}
  }
}

async function uploadResult(blob){
  if(typeof window.uploadAdminImage!=='function')return '';
  const mime=/^image\/(png|jpeg|webp)$/i.test(blob.type||'')?blob.type:'image/png';
  const ext=mime==='image/webp'?'webp':(mime==='image/jpeg'?'jpg':'png');
  try{return await window.uploadAdminImage(new File([blob],'ai-cutout.'+ext,{type:mime}),'template')}
  catch(e){console.warn('[ADMIN AI] persistent result upload warning',e);return ''}
}

async function replace(old,blob,publicUrl){
  const core=window.BenfuwanAiRemoveV2,c=canvas();if(!core||!c)throw new Error('模板畫布尚未準備好');
  if(!c.getObjects?.().includes(old))throw new Error('圖片狀態已改變，請重新選取後再試');
  const src=await core.blobToDataURL(blob),el=await load(src),idx=c.getObjects().indexOf(old),center=old.getCenterPoint(),ow=Math.max(1,old.getScaledWidth?.()||((old.width||1)*(old.scaleX||1))),oh=Math.max(1,old.getScaledHeight?.()||((old.height||1)*(old.scaleY||1)));
  const neo=new fabric.Image(el,{
    left:center.x,top:center.y,originX:'center',originY:'center',angle:old.angle||0,
    flipX:!!old.flipX,flipY:!!old.flipY,skewX:old.skewX||0,skewY:old.skewY||0,
    opacity:old.opacity??1,visible:old.visible!==false,selectable:old.selectable!==false,evented:old.evented!==false,
    objectCaching:true,centeredScaling:true
  });
  neo.set({scaleX:ow/Math.max(1,neo.width||1),scaleY:oh/Math.max(1,neo.height||1)});
  neo.originalName=old.originalName||'圖片';neo.stickerId=old.stickerId||'';neo.role=old.role;neo.slotId=old.slotId;neo.slotMeta=old.slotMeta;neo.materialType=old.materialType;neo.clipPath=old.clipPath||undefined;neo.publicSrc=publicUrl||'';neo.aiBackgroundRemoved=true;
  try{neo.set({transparentCorners:false,cornerColor:'#ff6f9a',cornerStrokeColor:'#fff',borderColor:'#ff6f9a',cornerSize:13,touchCornerSize:28,padding:2,objectCaching:true,centeredScaling:true,centeredRotation:true})}catch(e){}
  c.remove(old);c.insertAt(neo,Math.max(0,idx),false);c.setActiveObject(neo);neo.setCoords?.();c.requestRenderAll?.();c.fire?.('object:modified',{target:neo});
  return neo;
}

async function runRemove(){
  if(busy)return;const old=active();if(!isImage(old)){alert('請先選取一張圖片');return}
  if(old.aiBackgroundRemoved){alert('這張圖片已經完成 AI 摳圖');return}
  const core=window.BenfuwanAiRemoveV2;if(!core){alert('AI 摳圖核心尚未載入，請重新整理後再試');return}
  busy=true;status('AI 正在準備圖片…');
  try{
    const input=await sourceBlob(old);status('AI 正在摳圖（第一次冷啟動可能較久）…');
    const out=await core.request(input,(old.originalName||'template')+'.jpg',{timeoutMs:195000});
    status('AI 已回傳，正在驗證透明背景…');await core.validate(out);
    status('AI 摳圖完成，正在儲存結果…');const publicUrl=await uploadResult(out);
    await replace(old,out,publicUrl);status(publicUrl?'AI 摳圖完成 ✓':'AI 摳圖完成 ✓（本次雲端備份未完成，儲存模板前請確認圖片仍正常）');
  }catch(e){console.error('[ADMIN AI REMOVE V2]',e);status('AI 摳圖失敗，原圖已保留');alert(e?.message||'AI 摳圖失敗')}
  finally{busy=false}
}
window.bfAdminRemoveBackground=runRemove;

function removeExpandUi(){
  by('bf-admin-ai-v5-panel')?.remove();by('bf-tpl-ai-v5-panel')?.remove();
  const main=by('bf-tpl-expand-v4');if(main)main.style.display='none';
  document.querySelectorAll('#bf-tpl-objectbar .bf-expand-btn,[data-expand]').forEach(b=>b.style.display='none');
}
function bind(){
  removeExpandUi();const bar=by('bf-tpl-objectbar');if(bar){bar.querySelectorAll('.bf-ai-btn').forEach(ai=>{ai.textContent='AI 摳圖';ai.title='AI 摳圖'})}
  const top=by('bf-tpl-ai-v4');if(top){top.innerHTML='<span class="ico"><i class="fa-solid fa-wand-magic-sparkles"></i></span>AI 摳圖';top.title='AI 摳圖'}
  const panel=document.querySelector('#bf-tpl-ai-panel-v4 [data-remove]');if(panel)panel.textContent='AI 自動摳圖';
}

// 舊版 v4 曾綁定匿名 capture listener；從 document capture 最前面攔截所有 AI 摳圖入口，確保只跑新版一次。
document.addEventListener('click',ev=>{
  const target=ev.target?.closest?.('#bf-tpl-ai-v4,#bf-tpl-objectbar .bf-ai-btn,#bf-tpl-ai-panel-v4 [data-remove]');
  if(!target)return;ev.preventDefault();ev.stopPropagation();ev.stopImmediatePropagation();runRemove();
},true);

function boot(){bind();let n=0;const t=setInterval(()=>{bind();if(++n>120)clearInterval(t)},500);console.info('[ADMIN] validated AI remove-background v2 enabled')}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
