/* 本福丸 AI 大頭互動式分割 v1：使用者用筆刷指定要保留/排除的區域，再由 MediaPipe MagicTouch 產生 mask。 */
(function(){
  'use strict';
  if(window.__bfAiHeadInteractiveV1)return;window.__bfAiHeadInteractiveV1=true;

  // iPhone Safari 對跨網域 dynamic import 偶發失敗，所以 JS / WASM / model 全部改走本站同網域 proxy。
  const MP_ESM='/vendor/mediapipe/vision_bundle.mjs?v=1.0.1';
  const MP_WASM='/vendor/mediapipe/wasm';
  const MODEL='/vendor/mediapipe/interactive_segmentation.task';
  let toolPromise=null;

  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  const dims=el=>({w:Number(el?.naturalWidth||el?.videoWidth||el?.width||0),h:Number(el?.naturalHeight||el?.videoHeight||el?.height||0)});

  function normalizeModule(mod){
    if(mod?.InteractiveSegmenter&&mod?.FilesetResolver)return mod;
    if(mod?.default?.InteractiveSegmenter&&mod?.default?.FilesetResolver)return mod.default;
    return mod;
  }

  async function tool(){
    if(toolPromise)return toolPromise;
    toolPromise=(async()=>{
      console.info('[AI HEAD GUIDE] loading same-origin MediaPipe module',MP_ESM);
      const mod=normalizeModule(await import(MP_ESM));
      if(!mod?.InteractiveSegmenter||!mod?.FilesetResolver||!mod?.BrushMode){
        throw new Error('MediaPipe 模組不完整，請重新整理後再試');
      }
      console.info('[AI HEAD GUIDE] loading same-origin WASM',MP_WASM);
      const vision=await mod.FilesetResolver.forVisionTasks(MP_WASM);
      let segmenter;
      try{
        segmenter=await mod.InteractiveSegmenter.createFromOptions(vision,{baseOptions:{modelAssetPath:MODEL,delegate:'CPU'}});
      }catch(cpuErr){
        console.warn('[AI HEAD GUIDE] CPU delegate fallback',cpuErr);
        segmenter=await mod.InteractiveSegmenter.createFromOptions(vision,{baseOptions:{modelAssetPath:MODEL}});
      }
      console.info('[AI HEAD GUIDE] same-origin segmenter ready');
      return {segmenter,BrushMode:mod.BrushMode};
    })().catch(err=>{
      toolPromise=null;
      console.error('[AI HEAD GUIDE] same-origin engine failed',err);
      throw new Error('AI 核心載入失敗，請重新整理後再試'+(err?.message?`（${err.message}）`:''));
    });
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
    const left=cx-bw*.72,right=cx+bw*.72,top=cy-bh*.78,bottom=cy+bh*.68;
    const x=clamp(left,0,1),y=clamp(top,0,1),r=clamp(right,0,1),b=clamp(bottom,0,1);
    return {x,y,w:Math.max(.01,r-x),h:Math.max(.01,b-y)};
  }

  function maskCanvas(result){
    const w=Number(result?.width||0),h=Number(result?.height||0),data=result?.data;if(!w||!h||!data||data.length<w*h)throw new Error('AI 選取遮罩格式錯誤');
    const c=document.createElement('canvas');c.width=w;c.height=h;const g=c.getContext('2d'),img=g.createImageData(w,h),d=img.data;
    for(let i=0,j=0;i<w*h;i++,j+=4){
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
    const {w,h}=dims(el);if(!w||!h)throw new Error('大頭圖片尺寸錯誤');
    const gate=positiveGate(strokes),x=Math.floor(gate.x*w),y=Math.floor(gate.y*h),cw=Math.max(1,Math.ceil(gate.w*w)),ch=Math.max(1,Math.ceil(gate.h*h));
    const m=maskCanvas(result),mx=gate.x*m.width,my=gate.y*m.height,mw=gate.w*m.width,mh=gate.h*m.height;
    const out=document.createElement('canvas');out.width=cw;out.height=ch;const g=out.getContext('2d');
    g.drawImage(el,x,y,cw,ch,0,0,cw,ch);
    g.globalCompositeOperation='destination-in';g.drawImage(m,mx,my,mw,mh,0,0,cw,ch);g.globalCompositeOperation='source-over';
    return {canvas:trim(out),mode:'interactive-guided-v2-same-origin'};
  }

  function drawPreview(canvas,result,strokes){
    if(!canvas)return;const g=canvas.getContext('2d'),w=canvas.width,h=canvas.height,m=maskCanvas(result),gate=positiveGate(strokes);
    g.clearRect(0,0,w,h);const tmp=document.createElement('canvas');tmp.width=w;tmp.height=h;const t=tmp.getContext('2d');
    t.drawImage(m,0,0,w,h);t.globalCompositeOperation='destination-in';t.fillStyle='#fff';t.fillRect(gate.x*w,gate.y*h,gate.w*w,gate.h*h);
    g.save();g.globalAlpha=.34;g.fillStyle='#ff4f8b';g.fillRect(0,0,w,h);g.globalCompositeOperation='destination-in';g.drawImage(tmp,0,0);g.restore();
  }

  window.BenfuwanInteractiveHead={snapshot,segment,cut,drawPreview,gate:positiveGate,version:'1.2-magic-touch-same-origin'};
  console.info('[AI HEAD GUIDE] same-origin interactive MagicTouch ready');
})();
