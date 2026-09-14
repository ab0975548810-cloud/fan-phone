/* 本福丸：預覽維持快速，生產圖另外重算 720 DPI，避免後台下載模糊。 */
(function(){
  'use strict';
  if(window.__benfuwanProductionHQInstalled)return;
  window.__benfuwanProductionHQInstalled=true;
  const oldOpen=window.openPreview;
  const PPM=28.3464567; // 720 DPI / 25.4

  function safe(url){
    url=String(url||'').trim();
    if(!url||url.startsWith('data:')||url.startsWith('blob:')||url.startsWith('/'))return url;
    try{const u=new URL(url,location.href);if(u.origin===location.origin)return u.href}catch(e){}
    return '/api/public/asset_proxy?url='+encodeURIComponent(url);
  }
  function load(url){return new Promise((res,rej)=>{const i=new Image();const t=setTimeout(()=>{i.src='';rej(new Error('mask timeout'))},10000);i.onload=()=>{clearTimeout(t);res(i)};i.onerror=()=>{clearTimeout(t);rej(new Error('mask load failed'))};i.src=safe(url)})}
  function pngDensity(dataUrl){
    const binary=atob(dataUrl.split(',')[1]);
    const input=Uint8Array.from(binary,c=>c.charCodeAt(0));
    const chunk=new Uint8Array(21),v=new DataView(chunk.buffer);v.setUint32(0,9);chunk.set([112,72,89,115],4);v.setUint32(8,Math.round(PPM*1000));v.setUint32(12,Math.round(PPM*1000));chunk[16]=1;
    let crc=0xffffffff;for(const byte of chunk.subarray(4,17)){crc^=byte;for(let bit=0;bit<8;bit++)crc=(crc>>>1)^((crc&1)?0xedb88320:0)}v.setUint32(17,(crc^0xffffffff)>>>0);
    const parts=[input.subarray(0,33),chunk],src=new DataView(input.buffer);for(let p=33;p<input.length;){const end=p+src.getUint32(p)+12;if(!(input[p+4]===112&&input[p+5]===72&&input[p+6]===89&&input[p+7]===115))parts.push(input.subarray(p,end));p=end}
    const out=new Uint8Array(parts.reduce((s,a)=>s+a.length,0));let off=0;for(const a of parts){out.set(a,off);off+=a.length}const ss=[];for(let p=0;p<out.length;p+=32768)ss.push(String.fromCharCode(...out.subarray(p,p+32768)));return 'data:image/png;base64,'+btoa(ss.join(''));
  }
  async function rebuildHQ(){
    if(typeof canvas==='undefined'||!canvas||typeof ctx==='undefined'||!ctx)return;
    const w=Math.round(Number(ctx.printW||0)*PPM),h=Math.round(Number(ctx.printH||0)*PPM);
    if(!(w>0&&h>0)||w*h>18000000)return;
    const maskUrl=ctx.printLineUrl||'';if(!maskUrl)return;
    const mask=await load(maskUrl);
    const hidden=canvas.getObjects().filter(o=>['guide','slot-guide'].includes(o.role));
    const vis=hidden.map(o=>o.visible),clip=canvas.clipPath;let source;
    try{
      hidden.forEach(o=>o.visible=false);canvas.clipPath=null;
      source=canvas.toCanvasElement(Math.max(w/canvas.width,h/canvas.height));
    }finally{
      canvas.clipPath=clip;hidden.forEach((o,i)=>o.visible=vis[i]);canvas.requestRenderAll();
    }
    const out=document.createElement('canvas');out.width=w;out.height=h;const g=out.getContext('2d');g.imageSmoothingEnabled=true;g.imageSmoothingQuality='high';g.drawImage(source,0,0,w,h);g.globalCompositeOperation='destination-in';g.drawImage(mask,0,0,w,h);g.globalCompositeOperation='source-over';source.width=source.height=1;
    ctx.printBase64=pngDensity(out.toDataURL('image/png'));out.width=out.height=1;
    console.info('[PRINT] 720 DPI production PNG ready',w,h);
  }
  window.openPreview=async function(){
    const r=typeof oldOpen==='function'?await oldOpen.apply(this,arguments):undefined;
    try{await rebuildHQ()}catch(e){console.warn('[PRINT] HQ rebuild fallback to preview resolution',e)}
    return r;
  };
})();