/* 本福丸後台模板上傳修正 v1：先由伺服器標準化圖片，再載回 Fabric，避免 Safari 本機重複解碼失敗。 */
(function(){
  'use strict';
  if(window.__benfuwanTemplateUploadFixV1)return;
  window.__benfuwanTemplateUploadFixV1=true;

  const by=id=>document.getElementById(id);
  const getCanvas=()=>{try{return window.visualCanvas||null}catch(e){return null}};
  const status=msg=>{const el=by('bf-tpl-status');if(el)el.textContent=msg};
  const ACCEPTED=new Set(['image/png','image/jpeg','image/webp']);

  function normalizedFile(file){
    if(!file)throw new Error('沒有選擇圖片');
    if(!file.size)throw new Error('圖片內容是空的');
    if(file.size>75*1024*1024)throw new Error('單張圖片需小於 75MB');
    let type=String(file.type||'').toLowerCase();
    if(ACCEPTED.has(type))return file;
    const ext=String(file.name||'').split('.').pop()?.toLowerCase()||'';
    const guessed=ext==='png'?'image/png':((ext==='jpg'||ext==='jpeg')?'image/jpeg':(ext==='webp'?'image/webp':''));
    if(guessed)return new File([file],file.name||('upload.'+ext),{type:guessed,lastModified:file.lastModified||Date.now()});
    if(type.includes('heic')||type.includes('heif')||ext==='heic'||ext==='heif'){
      throw new Error('目前模板只支援 JPG／PNG／WEBP；這張是 HEIC/HEIF，請先在相簿轉成 JPG 再上傳');
    }
    throw new Error('圖片格式不支援，請使用 JPG／PNG／WEBP');
  }

  async function uploadTemplateFile(file){
    const f=normalizedFile(file);
    const fd=new FormData();fd.append('file',f);fd.append('type','template');
    const r=await fetch('/api/admin/upload_image',{method:'POST',body:fd,cache:'no-store'});
    let j={};try{j=await r.json()}catch(e){}
    if(r.status===401)throw new Error('登入已過期，請重新登入後再試');
    if(!r.ok||j.status!=='success')throw new Error(j.msg||('圖片上傳失敗（HTTP '+r.status+'）'));
    const url=String(j.url||'').trim();if(!url)throw new Error('圖片已上傳，但伺服器沒有回傳圖片網址');
    return url;
  }

  function proxyUrl(url){
    const raw=String(url||'').trim();
    if(!raw||raw.startsWith('/')||raw.startsWith('data:')||raw.startsWith('blob:'))return raw;
    try{const u=new URL(raw,location.href);if(u.origin===location.origin)return u.href}catch(e){}
    return '/api/admin/template_asset_proxy?url='+encodeURIComponent(raw);
  }

  function loadImage(src){
    return new Promise((resolve,reject)=>{
      const im=new Image();let done=false;
      const finish=(err)=>{if(done)return;done=true;clearTimeout(timer);err?reject(err):resolve(im)};
      const timer=setTimeout(()=>{try{im.src=''}catch(e){}finish(new Error('上傳成功，但標準化圖片載入逾時'))},20000);
      im.onload=()=>finish();
      im.onerror=()=>finish(new Error('上傳成功，但標準化圖片載入失敗'));
      im.decoding='async';im.src=src;
    });
  }

  function tune(img){
    try{img.set({transparentCorners:false,cornerColor:'#ff6f9a',cornerStrokeColor:'#fff',borderColor:'#ff6f9a',cornerSize:13,touchCornerSize:28,padding:2,objectCaching:true,centeredScaling:true,centeredRotation:true,perPixelTargetFind:false})}catch(e){}
  }

  async function addImage(file){
    const c=getCanvas();if(!c)throw new Error('模板畫布尚未準備好，請關閉模板後重新開啟');
    status('正在上傳原圖並最佳化…');
    const publicUrl=await uploadTemplateFile(file);
    status('圖片上傳完成，正在載入畫布…');
    const el=await loadImage(proxyUrl(publicUrl));
    const cw=Number(c.getWidth?.()||0),ch=Number(c.getHeight?.()||0);if(!cw||!ch)throw new Error('模板畫布尺寸讀取失敗');
    const img=new fabric.Image(el,{left:cw/2,top:ch/2,originX:'center',originY:'center',objectCaching:true,centeredScaling:true});
    img.publicSrc=publicUrl;img.originalName=file.name||'圖片';
    img.scaleToWidth(Math.max(40,Math.min(cw*.68,190)));
    tune(img);c.add(img);c.setActiveObject(img);img.setCoords?.();c.requestRenderAll();
    status('圖片已加入 ✓ 可直接拖曳／縮放／旋轉');
    try{window.dispatchEvent(new CustomEvent('benfuwan:template-uploaded',{detail:{kind:'image',url:publicUrl}}))}catch(e){}
  }

  async function addBackground(file){
    const c=getCanvas();if(!c)throw new Error('模板畫布尚未準備好，請關閉模板後重新開啟');
    status('正在上傳底圖並最佳化…');
    const publicUrl=await uploadTemplateFile(file);
    status('底圖上傳完成，正在載入畫布…');
    const el=await loadImage(proxyUrl(publicUrl));
    const cw=Number(c.getWidth?.()||0),ch=Number(c.getHeight?.()||0);if(!cw||!ch)throw new Error('模板畫布尺寸讀取失敗');
    c.getObjects().filter(o=>o.isTplBg).forEach(o=>c.remove(o));
    const img=new fabric.Image(el,{left:cw/2,top:ch/2,originX:'center',originY:'center',selectable:false,evented:false,isTplBg:true,objectCaching:true});
    const sc=Math.max(cw/Math.max(1,img.width||1),ch/Math.max(1,img.height||1));img.set({scaleX:sc,scaleY:sc});img.publicSrc=publicUrl;
    c.add(img);c.sendToBack(img);c.requestRenderAll();status('底圖已加入 ✓');
    try{window.dispatchEvent(new CustomEvent('benfuwan:template-uploaded',{detail:{kind:'background',url:publicUrl}}))}catch(e){}
  }

  function bindInput(id,kind){
    const input=by(id);if(!input||input.dataset.bfServerUploadFix)return;
    input.dataset.bfServerUploadFix='1';
    input.addEventListener('change',ev=>{
      const file=ev.target.files?.[0];ev.target.value='';if(!file)return;
      ev.preventDefault();ev.stopImmediatePropagation();
      const run=kind==='background'?addBackground:addImage;
      run(file).catch(err=>{console.error('[TEMPLATE UPLOAD FIX]',err);status('圖片上傳失敗');alert((kind==='background'?'底圖':'圖片')+'加入失敗：'+(err.message||err))});
    },true);
  }

  function bind(){bindInput('bf-tpl-image-file-v3','image');bindInput('tpl-bg-file','background')}
  bind();
  const observer=new MutationObserver(bind);observer.observe(document.documentElement,{childList:true,subtree:true});
  setTimeout(()=>{try{observer.disconnect()}catch(e){}},30000);
  window.addEventListener('benfuwan:template-canvas-ready',bind);
  console.info('[ADMIN] server-first template image upload fix enabled');
})();
