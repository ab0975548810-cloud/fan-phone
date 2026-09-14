/* Robust template upload optimizer: keep print-ready detail while avoiding oversized browser uploads. */
(function(){
  'use strict';
  if(window.__benfuwanUploadOptimizerInstalled)return;
  window.__benfuwanUploadOptimizerInstalled=true;
  if(typeof window.uploadAdminImage!=='function')return;
  const original=window.uploadAdminImage;

  function blobFromCanvas(c,q){return new Promise((resolve,reject)=>c.toBlob(b=>b?resolve(b):reject(new Error('圖片最佳化失敗')),'image/webp',q))}
  async function decode(file){
    if(window.createImageBitmap){try{return await createImageBitmap(file,{imageOrientation:'from-image'})}catch(e){}}
    const url=URL.createObjectURL(file);return new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>{URL.revokeObjectURL(url);resolve(im)};im.onerror=()=>{URL.revokeObjectURL(url);reject(new Error('圖片讀取失敗'))};im.src=url})
  }
  async function optimize(file){
    if(!file||!/^image\/(png|jpeg|webp)$/i.test(file.type||''))return file;
    let im;try{im=await decode(file)}catch(e){return file}
    try{
      const iw=im.width||im.naturalWidth,ih=im.height||im.naturalHeight;
      if(!(iw>0&&ih>0))return file;
      if(file.size<=6*1024*1024&&Math.max(iw,ih)<=5200)return file;
      const scale=Math.min(1,5200/Math.max(iw,ih));
      const w=Math.max(1,Math.round(iw*scale)),h=Math.max(1,Math.round(ih*scale));
      const c=document.createElement('canvas');c.width=w;c.height=h;const g=c.getContext('2d',{alpha:true});g.imageSmoothingEnabled=true;g.imageSmoothingQuality='high';g.drawImage(im,0,0,w,h);
      let q=.95,b=await blobFromCanvas(c,q);while(b.size>12*1024*1024&&q>.84){q-=.03;b=await blobFromCanvas(c,q)}c.width=c.height=1;
      if(b.size>=file.size&&file.size<20*1024*1024)return file;
      return new File([b],(file.name||'template').replace(/\.[^.]+$/,'')+'.webp',{type:'image/webp'});
    }finally{try{im.close?.()}catch(e){}}
  }

  window.uploadAdminImage=async function(file,type='material'){
    if(type!=='template')return original(file,type);
    let send=file;
    try{send=await optimize(file);const s=document.getElementById('bf-tpl-status');if(s&&send!==file)s.textContent=`圖片已最佳化 ${(file.size/1048576).toFixed(1)}MB → ${(send.size/1048576).toFixed(1)}MB`;}catch(e){console.warn('[UPLOAD] browser optimize fallback to server',e)}
    return original(send,type);
  };
  console.info('[ADMIN] robust template upload optimizer enabled');
})();
