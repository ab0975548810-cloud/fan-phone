/* 本福丸通用 AI 去背核心 v3：邊界連通背景優先，複雜背景才交給 AI，最後套回原始解析度 PNG。 */
(function(){
  'use strict';
  if(window.BenfuwanAiRemoveV2)return;

  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const clamp=(n,min,max)=>Math.max(min,Math.min(max,n));

  function elementSize(el){return {width:Number(el?.naturalWidth||el?.videoWidth||el?.width||0),height:Number(el?.naturalHeight||el?.videoHeight||el?.height||0)}}
  function canvasBlob(canvas,type='image/png',quality){return new Promise((resolve,reject)=>{try{canvas.toBlob(b=>b?resolve(b):reject(new Error('圖片壓縮失敗')),type,quality)}catch(e){reject(e)}})}
  function drawElement(el,width,height){
    const c=document.createElement('canvas');c.width=width;c.height=height;const g=c.getContext('2d',{alpha:true,willReadFrequently:true});
    if(!g)throw new Error('瀏覽器無法建立圖片處理畫布');
    g.clearRect(0,0,width,height);g.imageSmoothingEnabled=true;g.imageSmoothingQuality='high';
    try{g.drawImage(el,0,0,width,height)}catch(e){c.width=c.height=1;const err=new Error('圖片來源無法讀取，請重新上傳這張圖片再試');err.cause=e;throw err}
    return c;
  }

  async function sourceBlobFromElement(el,opts={}){
    const maxEdge=Math.max(640,Number(opts.maxEdge||4096)),maxBytes=Math.max(512*1024,Number(opts.maxBytes||5.5*1024*1024)),maxPixels=Math.max(1_000_000,Number(opts.maxPixels||32_000_000));
    const size=elementSize(el);if(!size.width||!size.height)throw new Error('讀不到原始圖片尺寸');
    if(size.width*size.height>maxPixels)throw new Error('圖片像素過大，請使用 3,200 萬像素以內的圖片');
    const ratio=Math.min(1,maxEdge/Math.max(size.width,size.height));let w=Math.max(1,Math.round(size.width*ratio)),h=Math.max(1,Math.round(size.height*ratio));
    for(let pass=0;pass<7;pass++){
      const c=drawElement(el,w,h),b=await canvasBlob(c,'image/png');c.width=c.height=1;if(b.size<=maxBytes)return b;
      const shrink=clamp(Math.sqrt(maxBytes/b.size)*.94,.68,.9);w=Math.max(1,Math.round(w*shrink));h=Math.max(1,Math.round(h*shrink));
    }
    throw new Error('圖片轉成透明 PNG 後仍然太大，請換一張較小的圖片再試');
  }

  function loadBlobImage(blob){return new Promise((resolve,reject)=>{
    if(!(blob instanceof Blob)||!blob.size){reject(new Error('AI 沒有回傳圖片'));return}
    const url=URL.createObjectURL(blob),img=new Image();let done=false;const finish=err=>{if(done)return;done=true;clearTimeout(timer);try{URL.revokeObjectURL(url)}catch(e){}err?reject(err):resolve(img)};
    const timer=setTimeout(()=>finish(new Error('AI 回傳圖片讀取逾時')),15000);img.onload=()=>finish();img.onerror=()=>finish(new Error('AI 回傳的圖片格式無法讀取'));img.src=url;
  })}

  async function validate(blob){
    const img=await loadBlobImage(blob),iw=img.naturalWidth||img.width,ih=img.naturalHeight||img.height;if(!iw||!ih)throw new Error('AI 回傳圖片尺寸錯誤');
    const scale=Math.min(1,512/Math.max(iw,ih)),w=Math.max(1,Math.round(iw*scale)),h=Math.max(1,Math.round(ih*scale)),c=drawElement(img,w,h),g=c.getContext('2d',{willReadFrequently:true});
    let data;try{data=g.getImageData(0,0,w,h).data}catch(e){c.width=c.height=1;throw new Error('AI 回傳圖片無法驗證透明背景')}
    let visible=0,transparent=0,partial=0;const total=w*h;for(let i=3;i<data.length;i+=4){const a=data[i];if(a>8)visible++;if(a<247)transparent++;if(a>8&&a<247)partial++}c.width=c.height=1;
    if(visible<Math.max(16,total*.002))throw new Error('AI 回傳幾乎是空白圖片，原圖已保留');
    if(transparent<Math.max(16,total*.001))throw new Error('AI 回傳沒有透明背景，原圖已保留，請再試一次');
    return {blob,width:iw,height:ih,transparentRatio:transparent/total,partialRatio:partial/total};
  }

  function colorDistance(data,index,color){const dr=data[index]-color[0],dg=data[index+1]-color[1],db=data[index+2]-color[2];return Math.sqrt(dr*dr*.24+dg*dg*.66+db*db*.1)}
  function dominantBorder(data,w,h){
    const bins=new Map(),points=[];const add=(x,y)=>{const i=(y*w+x)*4,a=data[i+3];if(a<16)return;const key=((data[i]>>4)<<8)|((data[i+1]>>4)<<4)|(data[i+2]>>4);let row=bins.get(key);if(!row){row=[0,0,0,0];bins.set(key,row)}row[0]++;row[1]+=data[i];row[2]+=data[i+1];row[3]+=data[i+2];points.push(i)};
    const step=Math.max(1,Math.floor(Math.max(w,h)/700));for(let x=0;x<w;x+=step){add(x,0);if(h>1)add(x,h-1)}for(let y=step;y<h-1;y+=step){add(0,y);if(w>1)add(w-1,y)}
    let best=null;for(const row of bins.values())if(!best||row[0]>best[0])best=row;if(!best||!points.length)return null;
    const color=[best[1]/best[0],best[2]/best[0],best[3]/best[0]],tolerance=34;let matches=0,spread=0;
    for(const i of points){const d=colorDistance(data,i,color);if(d<=tolerance)matches++;spread+=d}return {color,tolerance,borderMatch:matches/points.length,meanDistance:spread/points.length};
  }

  async function connectedBackgroundMask(el,opts={}){
    const size=elementSize(el),maxEdge=Math.max(320,Number(opts.analysisMaxEdge||1200));if(!size.width||!size.height)return null;
    const ratio=Math.min(1,maxEdge/Math.max(size.width,size.height)),w=Math.max(1,Math.round(size.width*ratio)),h=Math.max(1,Math.round(size.height*ratio)),c=drawElement(el,w,h),g=c.getContext('2d',{willReadFrequently:true}),image=g.getImageData(0,0,w,h),data=image.data,total=w*h;
    let transparentBorder=0,borderTotal=0;const borderAlpha=(x,y)=>{borderTotal++;if(data[(y*w+x)*4+3]<24)transparentBorder++};
    for(let x=0;x<w;x++){borderAlpha(x,0);if(h>1)borderAlpha(x,h-1)}for(let y=1;y<h-1;y++){borderAlpha(0,y);if(w>1)borderAlpha(w-1,y)}
    if(transparentBorder/Math.max(1,borderTotal)>.55){c.width=c.height=1;return {kind:'already-transparent',confidence:1,mask:null,width:w,height:h}}
    const bg=dominantBorder(data,w,h);if(!bg||bg.borderMatch<.68||bg.meanDistance>42){c.width=c.height=1;return null}
    const seen=new Uint8Array(total),queue=new Uint32Array(total);let head=0,tail=0;const accept=p=>{if(seen[p])return;const i=p*4;if(data[i+3]<24||colorDistance(data,i,bg.color)<=bg.tolerance){seen[p]=1;queue[tail++]=p}};
    for(let x=0;x<w;x++){accept(x);if(h>1)accept((h-1)*w+x)}for(let y=1;y<h-1;y++){accept(y*w);if(w>1)accept(y*w+w-1)}
    while(head<tail){const p=queue[head++],x=p%w,y=(p/w)|0;if(x)accept(p-1);if(x+1<w)accept(p+1);if(y)accept(p-w);if(y+1<h)accept(p+w)}
    const removed=tail/total;if(removed<.015||removed>.965){c.width=c.height=1;return null}
    const mask=document.createElement('canvas');mask.width=w;mask.height=h;const mg=mask.getContext('2d',{willReadFrequently:true}),out=mg.createImageData(w,h),od=out.data;
    for(let p=0;p<total;p++){
      const i=p*4;if(seen[p]){od[i+3]=0;continue}
      let edge=false,x=p%w,y=(p/w)|0;if(x&&seen[p-1])edge=true;else if(x+1<w&&seen[p+1])edge=true;else if(y&&seen[p-w])edge=true;else if(y+1<h&&seen[p+w])edge=true;
      let a=data[i+3];if(edge){const d=colorDistance(data,i,bg.color);a=Math.round(a*clamp((d-bg.tolerance*.65)/(bg.tolerance*.8),0,1))}od[i]=od[i+1]=od[i+2]=255;od[i+3]=a;
    }
    mg.putImageData(out,0,0);c.width=c.height=1;return {kind:'edge-connected',confidence:Math.min(1,bg.borderMatch*(1-Math.min(.5,bg.meanDistance/100))),mask,width:w,height:h,removedRatio:removed,background:bg.color};
  }

  async function compositeWithMask(el,maskSource,opts={}){
    const size=elementSize(el),maxPixels=Math.max(1_000_000,Number(opts.maxPixels||32_000_000));if(!size.width||!size.height||size.width*size.height>maxPixels)throw new Error('原圖像素過大，無法安全產生透明 PNG');
    const out=drawElement(el,size.width,size.height),g=out.getContext('2d',{alpha:true});
    if(maskSource){
      const mask=maskSource instanceof Blob?await loadBlobImage(maskSource):maskSource,mc=document.createElement('canvas');mc.width=size.width;mc.height=size.height;const mg=mc.getContext('2d',{alpha:true});mg.imageSmoothingEnabled=true;mg.imageSmoothingQuality='high';mg.drawImage(mask,0,0,size.width,size.height);g.globalCompositeOperation='destination-in';g.drawImage(mc,0,0);g.globalCompositeOperation='source-over';mc.width=mc.height=1;
      // Solid/near-solid connected backgrounds can leave their RGB in antialiased edge pixels.
      // Unmatte only those partial-alpha pixels; fully opaque whites inside artwork stay untouched.
      const bg=opts.backgroundColor;if(Array.isArray(bg)&&bg.length>=3&&size.width*size.height<=12_000_000){
        const image=g.getImageData(0,0,size.width,size.height),d=image.data;
        for(let i=0;i<d.length;i+=4){const a=d[i+3]/255;if(a<=.03){d[i+3]=0;continue}if(a>=.995)continue;d[i]=clamp(Math.round((d[i]-(1-a)*bg[0])/a),0,255);d[i+1]=clamp(Math.round((d[i+1]-(1-a)*bg[1])/a),0,255);d[i+2]=clamp(Math.round((d[i+2]-(1-a)*bg[2])/a),0,255)}
        g.putImageData(image,0,0);
      }
    }
    const blob=await canvasBlob(out,'image/png');out.width=out.height=1;return blob;
  }

  async function decontaminateTransparentElement(el,opts={}){
    const size=elementSize(el),maxPixels=Math.max(1_000_000,Number(opts.maxPixels||32_000_000));
    if(!size.width||!size.height||size.width*size.height>maxPixels)throw new Error('原圖像素過大，無法安全清理透明邊緣');
    const out=drawElement(el,size.width,size.height),g=out.getContext('2d',{alpha:true,willReadFrequently:true}),image=g.getImageData(0,0,size.width,size.height),d=image.data,w=size.width,h=size.height;
    const bins=new Map();let edgeCount=0;
    const isTransparent=p=>p<0||p>=w*h||d[p*4+3]<12;
    for(let y=0;y<h;y++)for(let x=0;x<w;x++){
      const p=y*w+x,i=p*4,a=d[i+3];if(a<=8||a>=247)continue;
      if(!((x&&isTransparent(p-1))||(x+1<w&&isTransparent(p+1))||(y&&isTransparent(p-w))||(y+1<h&&isTransparent(p+w))))continue;
      edgeCount++;const key=((d[i]>>4)<<8)|((d[i+1]>>4)<<4)|(d[i+2]>>4);let row=bins.get(key);if(!row){row=[0,0,0,0];bins.set(key,row)}row[0]++;row[1]+=d[i];row[2]+=d[i+1];row[3]+=d[i+2];
    }
    let best=null;for(const row of bins.values())if(!best||row[0]>best[0])best=row;
    const matte=best&&edgeCount? [best[1]/best[0],best[2]/best[0],best[3]/best[0]]:null,matteShare=best&&edgeCount?best[0]/edgeCount:0;
    if(matte){
      const source=new Uint8ClampedArray(d);
      const sourceTransparent=p=>p<0||p>=w*h||source[p*4+3]<12;
      for(let y=0;y<h;y++)for(let x=0;x<w;x++){
        const p=y*w+x,i=p*4,a=source[i+3];if(a<=8||a>=247)continue;
        if(!((x&&sourceTransparent(p-1))||(x+1<w&&sourceTransparent(p+1))||(y&&sourceTransparent(p-w))||(y+1<h&&sourceTransparent(p+w))))continue;
        const whiteLike=source[i]>224&&source[i+1]>224&&source[i+2]>224&&Math.max(source[i],source[i+1],source[i+2])-Math.min(source[i],source[i+1],source[i+2])<24;
        if(!whiteLike&&!(matteShare>=.12&&colorDistance(source,i,matte)<=42))continue;
        let bestNeighbor=-1,bestAlpha=a;
        for(let oy=-1;oy<=1;oy++)for(let ox=-1;ox<=1;ox++){
          if(!ox&&!oy)continue;const nx=x+ox,ny=y+oy;if(nx<0||nx>=w||ny<0||ny>=h)continue;const ni=(ny*w+nx)*4,na=source[ni+3];if(na>bestAlpha){bestAlpha=na;bestNeighbor=ni}
        }
        if(bestNeighbor>=0){d[i]=source[bestNeighbor];d[i+1]=source[bestNeighbor+1];d[i+2]=source[bestNeighbor+2]}
        const choke=Math.min(40,8+Math.round((255-a)*.12));d[i+3]=Math.max(0,a-choke);
      }
      g.putImageData(image,0,0);
    }
    const blob=await canvasBlob(out,'image/png');out.width=out.height=1;return blob;
  }

  async function request(blob,filename='photo.png',opts={}){
    if(!(blob instanceof Blob)||!blob.size)throw new Error('沒有可送給 AI 的圖片');const timeoutMs=Math.max(30000,Number(opts.timeoutMs||195000)),controller=typeof AbortController!=='undefined'?new AbortController():null,timer=controller?setTimeout(()=>controller.abort(),timeoutMs):null;
    try{const fd=new FormData();fd.append('image',blob,filename||'photo.png');const r=await fetch('/api/ai/remove-background',{method:'POST',body:fd,cache:'no-store',signal:controller?.signal});if(!r.ok){let msg='AI 摳圖失敗';try{const j=await r.clone().json();msg=j?.msg||j?.error||msg}catch(e){try{const t=(await r.text()).trim();if(t)msg=t.slice(0,180)}catch(_) {}}throw new Error(msg+'（HTTP '+r.status+'）')}const out=await r.blob();if(!out.size)throw new Error('AI 沒有回傳圖片');return out}catch(e){if(e?.name==='AbortError')throw new Error('AI 處理逾時，原圖已保留，請再試一次');throw e}finally{if(timer)clearTimeout(timer)}
  }

  async function universalRemoveFromElement(el,opts={}){
    const local=await connectedBackgroundMask(el,opts);
    if(local?.kind==='already-transparent'){
      const blob=await decontaminateTransparentElement(el,opts);await validate(blob);return {blob,mode:'transparent-decontaminated',analysis:local};
    }
    if(local?.mask&&local.confidence>=Number(opts.localConfidence||.58)){const blob=await compositeWithMask(el,local.mask,{...opts,backgroundColor:local.background});local.mask.width=local.mask.height=1;await validate(blob);return {blob,mode:'edge-connected',analysis:local}}
    if(opts.localOnly)throw new Error('圖片背景較複雜，需要 AI 協助去背');
    const input=await sourceBlobFromElement(el,{maxEdge:opts.aiMaxEdge||4096,maxBytes:opts.maxBytes||5.5*1024*1024,maxPixels:opts.maxPixels}),ai=await request(input,opts.filename||'photo.png',{timeoutMs:opts.timeoutMs});await validate(ai);
    const blob=await compositeWithMask(el,ai,opts);await validate(blob);return {blob,mode:'ai-mask',input,analysis:local};
  }

  function blobToDataURL(blob){return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result||''));r.onerror=()=>reject(r.error||new Error('AI 圖片讀取失敗'));r.readAsDataURL(blob)})}
  async function fingerprint(blob,version='universal-bg-v3'){if(!window.crypto?.subtle||!(blob instanceof Blob))return '';try{const prefix=new TextEncoder().encode(version+'|'),body=new Uint8Array(await blob.arrayBuffer()),all=new Uint8Array(prefix.length+body.length);all.set(prefix);all.set(body,prefix.length);const hash=await crypto.subtle.digest('SHA-256',all.buffer);return [...new Uint8Array(hash)].map(b=>b.toString(16).padStart(2,'0')).join('')}catch(e){return ''}}
  async function cacheIdentityFromElement(el,opts={}){
    const size=elementSize(el);if(!size.width||!size.height)return '';
    const normalized=await sourceBlobFromElement(el,{maxEdge:opts.maxEdge||1200,maxBytes:opts.maxBytes||5.5*1024*1024,maxPixels:opts.maxPixels}),hash=await fingerprint(normalized,'universal-bg-v4-normalized');
    return hash?['universal-bg-v4',size.width,size.height,hash].join(':'):'';
  }
  async function validateWithRetry(blob){try{return await validate(blob)}catch(e){if(!/讀取|格式/.test(String(e?.message||'')))throw e;await sleep(40);return validate(blob)}}

  window.BenfuwanAiRemoveV2={sourceBlobFromElement,request,validate:validateWithRetry,blobToDataURL,fingerprint,cacheIdentityFromElement,elementSize,connectedBackgroundMask,compositeWithMask,decontaminateTransparentElement,universalRemoveFromElement,version:'4.0-transparent-decontaminate'};
  console.info('[AI REMOVE] universal high-resolution client v4 ready');
})();
