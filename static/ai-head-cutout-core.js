/* 本福丸共用 AI 大頭摳圖核心：MediaPipe 臉部定位 + 透明輪廓智慧裁切 */
(function(){
  'use strict';
  if(window.BenfuwanHeadCutout)return;

  const MP_VERSION='1.0.1';
  const MP_ESM=`https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VERSION}/+esm`;
  const MP_WASM=`https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VERSION}/wasm`;
  const FACE_MODEL='https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_full_range/float16/latest/blaze_face_full_range.tflite';
  let detectorPromise=null;

  function dims(el){
    return {w:Number(el?.naturalWidth||el?.videoWidth||el?.width||0),h:Number(el?.naturalHeight||el?.videoHeight||el?.height||0)};
  }
  function clamp(v,a,b){return Math.max(a,Math.min(b,v))}

  async function detector(){
    if(detectorPromise)return detectorPromise;
    detectorPromise=(async()=>{
      const mod=await import(MP_ESM);
      const vision=await mod.FilesetResolver.forVisionTasks(MP_WASM);
      try{
        return await mod.FaceDetector.createFromOptions(vision,{baseOptions:{modelAssetPath:FACE_MODEL,delegate:'GPU'},runningMode:'IMAGE',minDetectionConfidence:.48,minSuppressionThreshold:.3});
      }catch(gpuErr){
        console.warn('[AI HEAD] GPU face detector unavailable, fallback CPU',gpuErr);
        return await mod.FaceDetector.createFromOptions(vision,{baseOptions:{modelAssetPath:FACE_MODEL},runningMode:'IMAGE',minDetectionConfidence:.48,minSuppressionThreshold:.3});
      }
    })().catch(err=>{detectorPromise=null;throw err});
    return detectorPromise;
  }

  async function detectFace(el){
    const {w,h}=dims(el);if(!w||!h)throw new Error('找不到照片尺寸');
    const d=await detector();
    const result=d.detect(el),list=Array.isArray(result?.detections)?result.detections:[];
    if(!list.length)return null;
    const best=[...list].sort((a,b)=>{
      const aa=(a?.boundingBox?.width||0)*(a?.boundingBox?.height||0),bb=(b?.boundingBox?.width||0)*(b?.boundingBox?.height||0);
      return bb-aa;
    })[0];
    const b=best?.boundingBox;if(!b||!b.width||!b.height)return null;
    return {
      x:clamp(Number(b.originX||0)/w,0,1),y:clamp(Number(b.originY||0)/h,0,1),
      w:clamp(Number(b.width||0)/w,0,1),h:clamp(Number(b.height||0)/h,0,1),
      score:Number(best?.categories?.[0]?.score||0),count:list.length
    };
  }

  function faceCrop(face,w,h){
    const fx=face.x*w,fy=face.y*h,fw=face.w*w,fh=face.h*h;
    // 多留頭髮、耳朵與少量脖子/肩膀，做手機殼常見的「大頭貼」效果。
    let x=fx-fw*.52,y=fy-fh*.68,r=fx+fw+fw*.52,b=fy+fh+fh*.78;
    const desiredW=Math.max(r-x,fw*1.85),desiredH=Math.max(b-y,fh*2.2);
    const cx=fx+fw/2,cy=fy+fh*.55;
    x=cx-desiredW/2;r=cx+desiredW/2;y=cy-desiredH*.48;b=y+desiredH;
    x=clamp(x,0,w);y=clamp(y,0,h);r=clamp(r,0,w);b=clamp(b,0,h);
    return {x,y,w:Math.max(1,r-x),h:Math.max(1,b-y)};
  }

  function alphaBounds(el){
    const {w,h}=dims(el);if(!w||!h)return null;
    const maxEdge=900,ratio=Math.min(1,maxEdge/Math.max(w,h)),sw=Math.max(1,Math.round(w*ratio)),sh=Math.max(1,Math.round(h*ratio));
    const c=document.createElement('canvas');c.width=sw;c.height=sh;const g=c.getContext('2d',{willReadFrequently:true});
    g.drawImage(el,0,0,sw,sh);
    let data;try{data=g.getImageData(0,0,sw,sh).data}catch(e){return null}
    let minX=sw,minY=sh,maxX=-1,maxY=-1;
    for(let y=0;y<sh;y++)for(let x=0;x<sw;x++)if(data[(y*sw+x)*4+3]>18){if(x<minX)minX=x;if(x>maxX)maxX=x;if(y<minY)minY=y;if(y>maxY)maxY=y}
    c.width=c.height=1;if(maxX<minX||maxY<minY)return null;
    return {x:minX/ratio,y:minY/ratio,w:(maxX-minX+1)/ratio,h:(maxY-minY+1)/ratio};
  }

  function silhouetteCrop(el){
    const {w,h}=dims(el),a=alphaBounds(el);if(!a)return {x:0,y:0,w,h};
    // 無法辨識人臉時，取透明主體上半部；對寵物、側臉、插畫也能有可用結果。
    const headH=Math.min(a.h,Math.max(a.w*1.28,a.h*.56));
    const padX=a.w*.07,padTop=a.h*.04,padBottom=Math.max(8,headH*.08);
    const x=clamp(a.x-padX,0,w),y=clamp(a.y-padTop,0,h),r=clamp(a.x+a.w+padX,0,w),b=clamp(a.y+headH+padBottom,0,h);
    return {x,y,w:Math.max(1,r-x),h:Math.max(1,b-y)};
  }

  function trimTransparent(canvas,padRatio=.055){
    const w=canvas.width,h=canvas.height,g=canvas.getContext('2d',{willReadFrequently:true});
    let data;try{data=g.getImageData(0,0,w,h).data}catch(e){return canvas}
    let minX=w,minY=h,maxX=-1,maxY=-1;
    for(let y=0;y<h;y++)for(let x=0;x<w;x++)if(data[(y*w+x)*4+3]>10){if(x<minX)minX=x;if(x>maxX)maxX=x;if(y<minY)minY=y;if(y>maxY)maxY=y}
    if(maxX<minX||maxY<minY)return canvas;
    const bw=maxX-minX+1,bh=maxY-minY+1,pad=Math.max(4,Math.round(Math.max(bw,bh)*padRatio));
    const sx=Math.max(0,minX-pad),sy=Math.max(0,minY-pad),ex=Math.min(w,maxX+1+pad),ey=Math.min(h,maxY+1+pad);
    if(sx===0&&sy===0&&ex===w&&ey===h)return canvas;
    const out=document.createElement('canvas');out.width=Math.max(1,ex-sx);out.height=Math.max(1,ey-sy);out.getContext('2d').drawImage(canvas,sx,sy,out.width,out.height,0,0,out.width,out.height);
    canvas.width=canvas.height=1;return out;
  }

  function cropTransparent(el,face){
    const {w,h}=dims(el);if(!w||!h)throw new Error('去背圖片尺寸錯誤');
    const rect=face?faceCrop(face,w,h):silhouetteCrop(el);
    const x=Math.floor(clamp(rect.x,0,w-1)),y=Math.floor(clamp(rect.y,0,h-1)),cw=Math.max(1,Math.ceil(Math.min(rect.w,w-x))),ch=Math.max(1,Math.ceil(Math.min(rect.h,h-y)));
    const c=document.createElement('canvas');c.width=cw;c.height=ch;c.getContext('2d').drawImage(el,x,y,cw,ch,0,0,cw,ch);
    return {canvas:trimTransparent(c),mode:face?'face':'silhouette',faceCount:Number(face?.count||0),score:Number(face?.score||0)};
  }

  function canvasBlob(c){return new Promise((resolve,reject)=>c.toBlob(b=>b?resolve(b):reject(new Error('大頭圖片輸出失敗')),'image/png'))}

  window.BenfuwanHeadCutout={detectFace,cropTransparent,canvasBlob,version:'1.0'};
  console.info('[AI HEAD] shared head cutout core ready');
})();
