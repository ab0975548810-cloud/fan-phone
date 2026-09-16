/* 本福丸 AI 大頭互動式分割 v1：使用者用筆刷指定要保留/排除的區域，再由 MediaPipe MagicTouch 產生 mask。 */
(function(){
  'use strict';
  if(window.__bfAiHeadInteractiveV1)return;window.__bfAiHeadInteractiveV1=true;

  const MP_VERSION='1.0.1';
  // 不再使用 jsDelivr 的 +esm 轉譯入口；部分瀏覽器/網路環境會直接 dynamic import 失敗。
  // 依序嘗試正式 package root、esm.sh，以及官方 vision_bundle.mjs，並同時提供 WASM CDN fallback。
  const MP_MODULES=[
    `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VERSION}`,
    `https://esm.sh/@mediapipe/tasks-vision@${MP_VERSION}?bundle`,
    `https://unpkg.com/@mediapipe/tasks-vision@${MP_VERSION}/vision_bundle.mjs`
  ];
  const MP_WASM_BASES=[
    `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VERSION}/wasm`,
    `https://unpkg.com/@mediapipe/tasks-vision@${MP_VERSION}/wasm`
  ];
  const MODELS=[
    'https://storage.googleapis.com/mediapipe-models/interactive_segmenter_v2/magic_touch/int8/1/interactive_segmentation.task',
    'https://storage.googleapis.com/mediapipe-models/interactive_segmenter_v2/magic_touch/int8/latest/interactive_segmentation.task'
  ];
  let toolPromise=null;

  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  const dims=el=>({w:Number(el?.naturalWidth||el?.videoWidth||el?.width||0),h:Number(el?.naturalHeight||el?.videoHeight||el?.height||0)});

  function normalizeModule(mod){
    if(mod?.InteractiveSegmenter&&mod?.FilesetResolver)return mod;
    if(mod?.default?.InteractiveSegmenter&&mod?.default?.FilesetResolver)return mod.default;
    return mod;
  }

  async function loadVisionModule(){
    let lastErr=null;
    for(const url of MP_MODULES){
      try{
        console.info('[AI HEAD GUIDE] loading MediaPipe module',url);
        const mod=normalizeModule(await import(url));
        if(!mod?.InteractiveSegmenter||!mod?.FilesetResolver||!mod?.BrushMode)throw new Error('MediaPipe exports incomplete');
        console.info('[AI HEAD GUIDE] MediaPipe module loaded',url);
        return mod;
      }catch(err){
        lastErr=err;
        console.warn('[AI HEAD GUIDE] MediaPipe module source failed',url,err);
      }
    }
    throw new Error('AI 核心載入失敗，請重新整理後再試'+(lastErr?.message?`（${lastErr.message}）`:''));
  }

  async function createSegmenter(mod){
    let lastErr=null;
    for(const wasmBase of MP_WASM_BASES){
      let vision;
      try{
        console.info('[AI HEAD GUIDE] loading WASM',wasmBase);
        vision=await mod.FilesetResolver.forVisionTasks(wasmBase);
      }catch(err){
        lastErr=err;
        console.warn('[AI HEAD GUIDE] WASM source failed',wasmBase,err);
        continue;
      }
      for(const modelAssetPath of MODELS){
        try{
          let segmenter;
          try{
            segmenter=await mod.InteractiveSegmenter.createFromOptions(vision,{baseOptions:{modelAssetPath,delegate:'CPU'}});
          }catch(cpuErr){
            console.warn('[AI HEAD GUIDE] CPU delegate fallback',cpuErr);
            segmenter=await mod.InteractiveSegmenter.createFromOptions(vision,{baseOptions:{modelAssetPath}});
          }
          console.info('[AI HEAD GUIDE] segmenter ready',wasmBase,modelAssetPath);
          return segmenter;
        }catch(err){
          lastErr=err;
          console.warn('[AI HEAD GUIDE] segmenter init failed',modelAssetPath,err);
        }
      }
    }
    throw new Error('AI 分割引擎啟動失敗，請確認網路後重新整理'+(lastErr?.message?`（${lastErr.message}）`:''));
  }

  async function tool(){
    if(toolPromise)return toolPromise;
    toolPromise=(async()=>{
      const mod=await loadVisionModule();
      const segmenter=await createSegmenter(mod);
      return {segmenter,BrushMode:mod.BrushMode};
    })().catch(err=>{toolPromise=null;throw err});
    return toolPromise;
  }

  function snapshot(el){
    const {w,h}=dims(el);if(!w||!h)throw new Error('找不到照片尺寸');
    const c=document.createElement('canvas');c.width=w;c.height=h;const g=c.getContext('2d');
    g.fillStyle='#fff';g.fillRect(0,0,w,h);g.drawImage(el,0,0,w,h);return c;
  }

  function normalizedStrokes(strokes,BrushMode){
    return (Array.isArray(strokes)?strokes:[]).filter(s=>Array.isArray(s?.points)&&s.points.length).map(s=>({
      brushMode:s.mode==='negative'?BrushMode.NEGATIVE:BrushMode.POSITIVE,
      point:s.points.map(p=>({x:clamp(Number(p.x)||0,0,1),y:clamp(Number(p.y)||0,0,1)})),
      isCompleted:true
    }));
  }

  async function segment(el,strokes){
    const positive=(strokes||[]).some(s=>s?.mode!=='negative'&&s?.points?.length);
    if(!positive)throw new Error('請先用粉紅色「保留」筆刷塗一下要留下的頭部');
    const {segmenter,BrushMode}=await tool();
    const input=normalizedStrokes(strokes,BrushMode);if(!input.length)throw new Error('沒有可用的筆刷範圍');
    segmenter.setImage(el);
    const mask=segmenter.segment(input);
    try{
      const raw=mask.getAsFloat32Array();
      return {data:new Float32Array(raw),width:Number(mask.width||0),height:Number(mask.height||0)};
    }finally{try{mask.close?.()}catch(e){}}
  }

  function positiveGate(strokes){
    const pts=[];(strokes||[]).forEach(s=>{if(s?.mode!=='negative'&&Array.isArray(s?.points))pts.push(...s.points)});
    if(!pts.length)return {x:0,y:0,w:1,h:1};
    let x1=1,y1=1,x2=0,y2=0;pts.forEach(p=>{x1=Math.min(x1,p.x);y1=Math.min(y1,p.y);x2=Math.max(x2,p.x);y2=Math.max(y2,p.y)});
    let bw=Math.max(.16,x2-x1+.03),bh=Math.max(.18,y2-y1+.03),cx=(x1+x2)/2,cy=(y1+y2)/2;
    // 使用者塗過的頭部只是「提示範圍」，四周再多留空間給頭髮、耳朵與少量脖子。
    const left=cx-bw*.72,right=cx+bw*.72,top=cy-bh*.78,bottom=cy+bh*.68;
    const x=clamp(left,0,1),y=clamp(top,0,1),r=clamp(right,0,1),b=clamp(bottom,0,1);
    return {x,y,w:Math.max(.01,r-x),h:Math.max(.01,b-y)};
  }

  function maskCanvas(result){
    const w=Number(result?.width||0),h=Number(result?.height||0),data=result?.data;if(!w||!h||!data||data.length<w*h)throw new Error('AI 選取遮罩格式錯誤');
    const c=document.createElement('canvas');c.width=w;c.height=h;const g=c.getContext('2d'),img=g.createImageData(w,h),d=img.data;
    for(let i=0,j=0;i<w*h;i++,j+=4){
      // MagicTouch 是 confidence mask；保留柔邊，但壓掉低信心雜訊。
      const v=clamp((Number(data[i]||0)-.12)/.78,0,1),a=Math.round(v*255);
      d[j]=255;d[j+1]=255;d[j+2]=255;d[j+3]=a;
    }
    g.putImageData(img,0,0);return c;
  }

  function trim(canvas,p=.035){
    const w=canvas.width,h=canvas.height,g=canvas.getContext('2d',{willReadFrequently:true});let d;try{d=g.getImageData(0,0,w,h).data}catch(e){return canvas}
    let x1=w,y1=h,x2=-1,y2=-1;for(let y=0;y<h;y++)for(let x=0;x<w;x++)if(d[(y*w+x)*4+3]>8){x1=Math.min(x1,x);x2=Math.max(x2,x);y1=Math.min(y1,y);y2=Math.max(y2,y)}
    if(x2<x1)return canvas;const pad=Math.max(3,Math.round(Math.max(x2-x1+1,y2-y1+1)*p)),sx=Math.max(0,x1-pad),sy=Math.max(0,y1-pad),ex=Math.min(w,x2+1+pad),ey=Math.min(h,y2+1+pad);
    if(!sx&&!sy&&ex===w&&ey===h)return canvas;const o=document.createElement('canvas');o.width=ex-sx;o.height=ey-sy;o.getContext('2d').drawImage(canvas,sx,sy,o.width,o.height,0,0,o.width,o.height);return o;
  }

  function cut(el,result,strokes){
    const {w,h}=dims(el);if(!w||!h)throw new Error('去背圖片尺寸錯誤');
    const gate=positiveGate(strokes),x=Math.floor(gate.x*w),y=Math.floor(gate.y*h),cw=Math.max(1,Math.ceil(gate.w*w)),ch=Math.max(1,Math.ceil(gate.h*h));
    const m=maskCanvas(result),mx=gate.x*m.width,my=gate.y*m.height,mw=gate.w*m.width,mh=gate.h*m.height;
    const out=document.createElement('canvas');out.width=cw;out.height=ch;const g=out.getContext('2d');
    g.drawImage(el,x,y,cw,ch,0,0,cw,ch);
    g.globalCompositeOperation='destination-in';g.drawImage(m,mx,my,mw,mh,0,0,cw,ch);g.globalCompositeOperation='source-over';
    return {canvas:trim(out),mode:'interactive-guided-v1'};
  }

  function drawPreview(canvas,result,strokes){
    if(!canvas)return;const g=canvas.getContext('2d'),w=canvas.width,h=canvas.height,m=maskCanvas(result),gate=positiveGate(strokes);
    g.clearRect(0,0,w,h);const tmp=document.createElement('canvas');tmp.width=w;tmp.height=h;const t=tmp.getContext('2d');
    t.drawImage(m,0,0,w,h);t.globalCompositeOperation='destination-in';t.fillStyle='#fff';t.fillRect(gate.x*w,gate.y*h,gate.w*w,gate.h*h);
    g.save();g.globalAlpha=.34;g.fillStyle='#ff4f8b';g.fillRect(0,0,w,h);g.globalCompositeOperation='destination-in';g.drawImage(tmp,0,0);g.restore();
  }

  window.BenfuwanInteractiveHead={snapshot,segment,cut,drawPreview,gate:positiveGate,version:'1.1-magic-touch-cdn-fallback'};
  console.info('[AI HEAD GUIDE] interactive MagicTouch ready');
})();
