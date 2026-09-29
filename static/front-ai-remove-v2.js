/* 本福丸前台通用去背 v3：保留所有分離圖案與原始解析度，壞結果不替換、不寫入快取。 */
(function(){
  'use strict';
  if(window.__bfFrontAiRemoveV2)return;window.__bfFrontAiRemoveV2=true;
  let busy=false;

  function cv(){try{return (typeof canvas!=='undefined'&&canvas)?canvas:null}catch(e){return null}}
  function active(){return cv()?.getActiveObject?.()||null}
  function isPhoto(o){return !!(o&&o.type==='image'&&(o.role==='photo'||o.role==='slot-photo'))}
  function say(msg){if(typeof toast==='function')toast(msg);else console.info(msg)}

  async function cacheGet(key){
    if(!key||typeof idbGet!=='function')return null;
    try{return await idbGet(key)}catch(e){return null}
  }
  async function cacheDelete(key){
    if(!key||typeof idbDel!=='function')return;
    try{await idbDel(key)}catch(e){}
  }
  async function cacheSet(key,blob){
    if(!key||typeof idbSet!=='function')return;
    try{
      await idbSet(key,blob);
      const idxKey='ai-cache-v2-index';let idx=await idbGet(idxKey);idx=Array.isArray(idx)?idx.filter(x=>x!==key):[];idx.unshift(key);
      for(const old of idx.slice(8)){try{await idbDel(old)}catch(e){}}
      await idbSet(idxKey,idx.slice(0,8));
    }catch(e){console.warn('[FRONT AI] cache skipped',e)}
  }

  async function replace(old,blob,fromCache,mode){
    const core=window.BenfuwanAiRemoveV2,c=cv();if(!core||!c)throw new Error('AI 摳圖工具尚未載入');
    if(!c.getObjects?.().includes(old))throw new Error('圖片狀態已改變，請重新選取後再試');
    const src=await core.blobToDataURL(blob),idx=c.getObjects().indexOf(old),center=old.getCenterPoint(),displayW=Math.max(1,old.getScaledWidth?.()||((old.width||1)*(old.scaleX||1))),displayH=Math.max(1,old.getScaledHeight?.()||((old.height||1)*(old.scaleY||1)));
    await new Promise((resolve,reject)=>fabric.Image.fromURL(src,img=>{
      try{
        img.set({
          left:center.x,top:center.y,originX:'center',originY:'center',angle:old.angle||0,
          flipX:!!old.flipX,flipY:!!old.flipY,skewX:old.skewX||0,skewY:old.skewY||0,
          scaleX:displayW/Math.max(1,img.width||1),scaleY:displayH/Math.max(1,img.height||1),opacity:old.opacity??1,
          role:old.role,slotId:old.slotId,slotMeta:old.slotMeta,clipPath:old.clipPath||undefined,
          originalName:old.originalName,materialType:old.materialType,aiBackgroundRemoved:true,aiCacheHit:!!fromCache,aiRemovalMode:mode||'cache',
          aiOutlineSource:src,aiOutlineStrength:'0',aiOutlineColor:old.aiOutlineColor||'#ffffff'
        });
        if(typeof styleEditableObject==='function')styleEditableObject(img);
        c.remove(old);c.insertAt(img,Math.max(0,idx),false);c.setActiveObject(img);img.setCoords?.();c.requestRenderAll?.();
        if(typeof recordHistory==='function')recordHistory();if(typeof renderLayerList==='function')renderLayerList();if(typeof window.syncSelection==='function')window.syncSelection();
        resolve(img);
      }catch(e){reject(e)}
    },{crossOrigin:'anonymous'}));
  }

  async function run(){
    if(busy)return;
    const old=active();if(!isPhoto(old)){say('請先選取一張照片');return}
    if(old.aiBackgroundRemoved){say('這張照片已經去背完成 ♡');return}
    const core=window.BenfuwanAiRemoveV2;if(!core){say('AI 摳圖工具尚未載入，請重新整理頁面');return}
    const el=old.getElement?.()||old._element;if(!el){say('讀不到這張圖片，請重新上傳後再試');return}
    const btn=document.getElementById('ai-remove-btn'),oldHtml=btn?.innerHTML;
    busy=true;if(btn){btn.disabled=true;btn.textContent='通用去背處理中…'}
    if(typeof setBusy==='function')setBusy(true,'正在保留全部圖案並移除外圍背景…');
    try{
      const fingerprintSource=await core.sourceBlobFromElement(el,{maxEdge:1200,maxBytes:5.5*1024*1024});
      const hash=await core.fingerprint(fingerprintSource),key=hash?('ai-cache-v3:'+hash):'';
      let out=await cacheGet(key),fromCache=false;
      if(out instanceof Blob&&out.size){
        try{await core.validate(out);fromCache=true}catch(e){console.warn('[FRONT AI] invalid cached result removed',e);await cacheDelete(key);out=null}
      }else out=null;
      let mode='cache';
      if(!out){
        const result=await core.universalRemoveFromElement(el,{filename:(old.originalName||'photo').replace(/\.[^.]+$/,'')+'.png',timeoutMs:195000});
        out=result.blob;mode=result.mode;await core.validate(out);
        await cacheSet(key,out);
      }
      await replace(old,out,fromCache,mode);
      if(typeof closeSheets==='function')closeSheets();
      say(fromCache?'通用去背完成（已驗證快取）♡':'通用去背完成，已保留原始解析度 ♡');
    }catch(e){
      console.error('[FRONT AI REMOVE V2]',e);say(e?.message||'AI 去背服務目前無法使用');
    }finally{
      busy=false;if(typeof setBusy==='function')setBusy(false);if(btn){btn.disabled=false;if(oldHtml!=null)btn.innerHTML=oldHtml;else btn.textContent='通用去背選取圖片'}
      setTimeout(()=>{try{window.syncSelection?.()}catch(e){}},0);
    }
  }

  window.removeBackgroundForActive=run;
  console.info('[FRONT] universal high-resolution background removal v3 enabled');
})();
