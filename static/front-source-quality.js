/* 本福丸：保留較高解析度原圖，避免 720 DPI 生產圖只是把低解析素材放大。 */
(function(){
  'use strict';
  if(window.__benfuwanSourceQualityInstalled)return;
  window.__benfuwanSourceQualityInstalled=true;

  const MAX_EDITOR_EDGE=3600;

  function readFile(file){return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=()=>reject(r.error||new Error('圖片讀取失敗'));r.readAsDataURL(file)})}
  function loadImage(url){return new Promise((resolve,reject)=>{const i=new Image();i.onload=()=>resolve(i);i.onerror=()=>reject(new Error('圖片讀取失敗'));i.src=url})}

  // The old editor reduced every phone photo to 1800px before Fabric ever saw
  // it. 3600px is a safer print-quality compromise for mobile Safari memory.
  prepareImageDataURL=async function(file,maxDimension=MAX_EDITOR_EDGE){
    if(!file||!file.type.startsWith('image/'))throw new Error('不是圖片檔');
    if(file.size>20*1024*1024)throw new Error('圖片超過 20MB');
    maxDimension=Math.max(MAX_EDITOR_EDGE,Number(maxDimension)||0);
    const url=URL.createObjectURL(file);
    try{
      const img=await loadImage(url);
      const w=img.naturalWidth||img.width,h=img.naturalHeight||img.height;
      const ratio=Math.min(1,maxDimension/Math.max(w,h));
      if(ratio===1&&file.size<6*1024*1024)return await readFile(file);
      const c=document.createElement('canvas');
      c.width=Math.max(1,Math.round(w*ratio));c.height=Math.max(1,Math.round(h*ratio));
      const g=c.getContext('2d',{alpha:true});g.imageSmoothingEnabled=true;g.imageSmoothingQuality='high';g.drawImage(img,0,0,c.width,c.height);
      const keepPng=file.type==='image/png'&&file.size<10*1024*1024;
      return c.toDataURL(keepPng?'image/png':'image/jpeg',.95);
    }finally{URL.revokeObjectURL(url)}
  };

  // AI input also used to be hard-limited to 1600px on the browser side.
  // Keep more source detail while still staying below Runpod's 6MB request cap.
  fabricImageBlob=function(o,maxDimension=2600){
    return new Promise(async(resolve,reject)=>{
      try{
        const el=o.getElement?.()||o._element;if(!el)throw new Error('找不到圖片來源');
        const w=el.naturalWidth||el.videoWidth||el.width,h=el.naturalHeight||el.videoHeight||el.height;
        if(!w||!h)throw new Error('圖片尺寸錯誤');
        let edge=Math.min(Math.max(2400,Number(maxDimension)||0),2800,Math.max(w,h));
        let ratio=Math.min(1,edge/Math.max(w,h));
        let cw=Math.max(1,Math.round(w*ratio)),ch=Math.max(1,Math.round(h*ratio));

        async function encode(width,height,quality){
          const c=document.createElement('canvas');c.width=width;c.height=height;
          const g=c.getContext('2d',{alpha:false});g.imageSmoothingEnabled=true;g.imageSmoothingQuality='high';g.fillStyle='#fff';g.fillRect(0,0,width,height);g.drawImage(el,0,0,width,height);
          const blob=await new Promise((res,rej)=>c.toBlob(b=>b?res(b):rej(new Error('圖片轉換失敗')),'image/jpeg',quality));
          c.width=c.height=1;return blob;
        }

        let blob=await encode(cw,ch,.92);
        for(const q of [.86,.80]){if(blob.size<=5.7*1024*1024)break;blob=await encode(cw,ch,q)}
        if(blob.size>5.7*1024*1024){
          const shrink=Math.max(.72,Math.sqrt((5.4*1024*1024)/blob.size));
          cw=Math.max(1,Math.round(cw*shrink));ch=Math.max(1,Math.round(ch*shrink));
          blob=await encode(cw,ch,.82);
        }
        resolve(blob);
      }catch(e){reject(e)}
    });
  };

  // Tell the customer when a source image itself is too small. A 720-DPI PNG
  // cannot recreate detail that did not exist in the uploaded sticker/photo.
  const previousOpen=window.openPreview;
  window.openPreview=async function(){
    const r=typeof previousOpen==='function'?await previousOpen.apply(this,arguments):undefined;
    try{
      if(typeof canvas==='undefined'||!canvas||typeof ctx==='undefined'||!ctx)return r;
      const pw=Math.round(Number(ctx.printW||0)*28.3464567);
      const ph=Math.round(Number(ctx.printH||0)*28.3464567);
      if(!(pw>0&&ph>0))return r;
      const sx=pw/(canvas.width||1),sy=ph/(canvas.height||1);
      const low=[];
      canvas.getObjects().forEach(o=>{
        if(o.type!=='image'||o.visible===false||['guide','slot-guide'].includes(o.role))return;
        const el=o.getElement?.()||o._element;
        const sw=el?.naturalWidth||el?.width||o.width||0,sh=el?.naturalHeight||el?.height||o.height||0;
        const needW=Math.abs((o.width||0)*(o.scaleX||1)*sx),needH=Math.abs((o.height||0)*(o.scaleY||1)*sy);
        if(sw&&sh&&(needW>sw*1.25||needH>sh*1.25))low.push(o);
      });
      if(low.length)toast(`提醒：有 ${low.length} 張素材原始解析度偏低，放大列印仍可能模糊`);
    }catch(e){console.warn('[QUALITY] resolution check failed',e)}
    return r;
  };

  console.info('[QUALITY] 3600px source preservation + low-resolution warning enabled');
})();
