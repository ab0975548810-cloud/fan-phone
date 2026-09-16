/* 本福丸 AI 摳圖共用核心 v2：前後台統一圖片前處理、逾時與透明結果驗證。 */
(function(){
  'use strict';
  if(window.BenfuwanAiRemoveV2)return;

  const sleep=ms=>new Promise(r=>setTimeout(r,ms));

  function elementSize(el){
    return {
      width:Number(el?.naturalWidth||el?.videoWidth||el?.width||0),
      height:Number(el?.naturalHeight||el?.videoHeight||el?.height||0)
    };
  }

  function canvasBlob(canvas,type='image/jpeg',quality=.92){
    return new Promise((resolve,reject)=>{
      try{canvas.toBlob(b=>b?resolve(b):reject(new Error('圖片壓縮失敗')),type,quality)}catch(e){reject(e)}
    });
  }

  async function sourceBlobFromElement(el,opts={}){
    const maxEdge=Math.max(640,Number(opts.maxEdge||1800));
    const maxBytes=Math.max(512*1024,Number(opts.maxBytes||5.5*1024*1024));
    const size=elementSize(el);
    if(!size.width||!size.height)throw new Error('讀不到原始圖片尺寸');

    const ratio=Math.min(1,maxEdge/Math.max(size.width,size.height));
    let w=Math.max(1,Math.round(size.width*ratio));
    let h=Math.max(1,Math.round(size.height*ratio));
    let quality=.92;

    for(let pass=0;pass<8;pass++){
      const c=document.createElement('canvas');c.width=w;c.height=h;
      const g=c.getContext('2d',{alpha:false});
      if(!g)throw new Error('瀏覽器無法建立圖片處理畫布');
      g.imageSmoothingEnabled=true;g.imageSmoothingQuality='high';
      g.fillStyle='#fff';g.fillRect(0,0,w,h);
      try{g.drawImage(el,0,0,w,h)}catch(e){
        c.width=c.height=1;
        const err=new Error('圖片來源無法讀取，請重新上傳這張圖片再試');err.cause=e;throw err;
      }
      const b=await canvasBlob(c,'image/jpeg',quality);c.width=c.height=1;
      if(b.size<=maxBytes)return b;
      if(quality>.66){quality=Math.max(.64,quality-.08);continue}
      // 兩邊使用同一倍率，任何長寬比都不會被壓扁或拉長。
      w=Math.max(1,Math.round(w*.82));h=Math.max(1,Math.round(h*.82));quality=.82;
    }
    throw new Error('圖片資料仍然太大，請換一張較小的照片再試');
  }

  function loadBlobImage(blob){
    return new Promise((resolve,reject)=>{
      if(!(blob instanceof Blob)||!blob.size){reject(new Error('AI 沒有回傳圖片'));return}
      const url=URL.createObjectURL(blob),img=new Image();let done=false;
      const finish=(err)=>{if(done)return;done=true;clearTimeout(timer);try{URL.revokeObjectURL(url)}catch(e){};err?reject(err):resolve(img)};
      const timer=setTimeout(()=>finish(new Error('AI 回傳圖片讀取逾時')),15000);
      img.onload=()=>finish();img.onerror=()=>finish(new Error('AI 回傳的圖片格式無法讀取'));img.src=url;
    });
  }

  async function validate(blob){
    const img=await loadBlobImage(blob);
    const iw=img.naturalWidth||img.width,ih=img.naturalHeight||img.height;
    if(!iw||!ih)throw new Error('AI 回傳圖片尺寸錯誤');
    const scale=Math.min(1,512/Math.max(iw,ih)),w=Math.max(1,Math.round(iw*scale)),h=Math.max(1,Math.round(ih*scale));
    const c=document.createElement('canvas');c.width=w;c.height=h;const g=c.getContext('2d',{willReadFrequently:true});
    if(!g)throw new Error('瀏覽器無法驗證 AI 圖片');
    g.clearRect(0,0,w,h);g.drawImage(img,0,0,w,h);
    let data;try{data=g.getImageData(0,0,w,h).data}catch(e){c.width=c.height=1;throw new Error('AI 回傳圖片無法驗證透明背景')}
    let visible=0,transparent=0,partial=0;const total=w*h;
    for(let i=3;i<data.length;i+=4){const a=data[i];if(a>8)visible++;if(a<247)transparent++;if(a>8&&a<247)partial++}
    c.width=c.height=1;
    if(visible<Math.max(16,total*.002))throw new Error('AI 回傳幾乎是空白圖片，原圖已保留');
    if(transparent<Math.max(16,total*.001))throw new Error('AI 回傳沒有透明背景，原圖已保留，請再試一次');
    return {blob,width:iw,height:ih,transparentRatio:transparent/total,partialRatio:partial/total};
  }

  async function request(blob,filename='photo.jpg',opts={}){
    if(!(blob instanceof Blob)||!blob.size)throw new Error('沒有可送給 AI 的圖片');
    const timeoutMs=Math.max(30000,Number(opts.timeoutMs||195000));
    const controller=typeof AbortController!=='undefined'?new AbortController():null;
    const timer=controller?setTimeout(()=>controller.abort(),timeoutMs):null;
    try{
      const fd=new FormData();fd.append('image',blob,filename||'photo.jpg');
      const r=await fetch('/api/ai/remove-background',{method:'POST',body:fd,cache:'no-store',signal:controller?.signal});
      if(!r.ok){
        let msg='AI 摳圖失敗';
        try{const j=await r.clone().json();msg=j?.msg||j?.error||msg}catch(e){try{const t=(await r.text()).trim();if(t)msg=t.slice(0,180)}catch(_) {}}
        throw new Error(msg+'（HTTP '+r.status+'）');
      }
      const out=await r.blob();if(!out.size)throw new Error('AI 沒有回傳圖片');return out;
    }catch(e){
      if(e?.name==='AbortError')throw new Error('AI 處理逾時，原圖已保留，請再試一次');throw e;
    }finally{if(timer)clearTimeout(timer)}
  }

  function blobToDataURL(blob){
    return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result||''));r.onerror=()=>reject(r.error||new Error('AI 圖片讀取失敗'));r.readAsDataURL(blob)});
  }

  async function fingerprint(blob,version='birefnet-v2'){
    if(!window.crypto?.subtle||!(blob instanceof Blob))return '';
    try{
      const prefix=new TextEncoder().encode(version+'|'),body=new Uint8Array(await blob.arrayBuffer()),all=new Uint8Array(prefix.length+body.length);all.set(prefix);all.set(body,prefix.length);
      const hash=await crypto.subtle.digest('SHA-256',all.buffer);return [...new Uint8Array(hash)].map(b=>b.toString(16).padStart(2,'0')).join('');
    }catch(e){return ''}
  }

  async function validateWithRetry(blob){
    try{return await validate(blob)}catch(e){
      if(!/讀取|格式/.test(String(e?.message||'')))throw e;
      await sleep(40);return validate(blob);
    }
  }

  window.BenfuwanAiRemoveV2={sourceBlobFromElement,request,validate:validateWithRetry,blobToDataURL,fingerprint,elementSize,version:'2.0-validated-birefnet'};
  console.info('[AI REMOVE] shared validated client v2 ready');
})();
