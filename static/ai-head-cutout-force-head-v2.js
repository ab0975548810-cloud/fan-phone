/* 本福丸 AI 大頭 v2：強制輸出頭部素材；抓不到臉時也不退回全身去背。 */
(function(){
  'use strict';
  if(window.__bfAiHeadForceV2)return;window.__bfAiHeadForceV2=true;
  const core=window.BenfuwanHeadCutout;if(!core)return;
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  const dims=el=>({w:Number(el?.naturalWidth||el?.videoWidth||el?.width||0),h:Number(el?.naturalHeight||el?.videoHeight||el?.height||0)});

  function alphaInfo(el){
    const {w,h}=dims(el);if(!w||!h)return null;
    const edge=900,r=Math.min(1,edge/Math.max(w,h)),sw=Math.max(1,Math.round(w*r)),sh=Math.max(1,Math.round(h*r));
    const c=document.createElement('canvas');c.width=sw;c.height=sh;const g=c.getContext('2d',{willReadFrequently:true});g.drawImage(el,0,0,sw,sh);
    let d;try{d=g.getImageData(0,0,sw,sh).data}catch(e){return null}
    let minX=sw,minY=sh,maxX=-1,maxY=-1;const rows=[];
    for(let y=0;y<sh;y++){
      let l=sw,rr=-1;
      for(let x=0;x<sw;x++)if(d[(y*sw+x)*4+3]>14){l=Math.min(l,x);rr=Math.max(rr,x);minX=Math.min(minX,x);maxX=Math.max(maxX,x);minY=Math.min(minY,y);maxY=Math.max(maxY,y)}
      rows[y]=rr>=l?rr-l+1:0;
    }
    if(maxX<minX)return null;
    return {r,sw,sh,minX,minY,maxX,maxY,rows,w,h};
  }

  function silhouetteHead(a){
    const height=a.maxY-a.minY+1,width=a.maxX-a.minX+1,start=a.minY+Math.round(height*.14),end=a.minY+Math.round(height*.62);
    let neck=Math.round(a.minY+height*.40);
    for(let y=start+5;y<end-5;y++){
      let p=0,n=0;for(let k=1;k<=5;k++){p+=a.rows[y-k]||0;n+=a.rows[y+k]||0}p/=5;n/=5;
      if(p>6&&n>p*1.27){neck=y;break}
    }
    neck=clamp(neck,a.minY+height*.29,a.minY+height*.52);
    let l=a.sw,rr=-1;for(let y=a.minY;y<=neck;y++){if(!a.rows[y])continue;for(let x=a.minX;x<=a.maxX;x++){/* bounds refined below */}}
    // 頭部水平範圍用主體寬度；垂直最多保留約一半主體，避免衣服整件留下。
    const headH=Math.max(1,neck-a.minY+1),padX=width*.10,padTop=headH*.08,padBottom=headH*.18;
    return {x:(a.minX-padX)/a.r,y:(a.minY-padTop)/a.r,w:(width+padX*2)/a.r,h:(headH+padTop+padBottom)/a.r};
  }

  function faceHead(face,w,h){
    const fx=face.x*w,fy=face.y*h,fw=face.w*w,fh=face.h*h,cx=fx+fw/2;
    // 比舊版更積極：保留完整頭髮、耳朵、少量脖子，不保留胸口/全身。
    const cw=Math.max(fw*2.05,fh*1.72),ch=Math.max(fh*2.12,cw*1.02),cy=fy+fh*.48;
    return {x:cx-cw/2,y:cy-ch*.47,w:cw,h:ch};
  }

  function trim(c,p=.05){
    const w=c.width,h=c.height,g=c.getContext('2d',{willReadFrequently:true});let d;try{d=g.getImageData(0,0,w,h).data}catch(e){return c}
    let x1=w,y1=h,x2=-1,y2=-1;for(let y=0;y<h;y++)for(let x=0;x<w;x++)if(d[(y*w+x)*4+3]>8){x1=Math.min(x1,x);x2=Math.max(x2,x);y1=Math.min(y1,y);y2=Math.max(y2,y)}
    if(x2<x1)return c;const pad=Math.max(4,Math.round(Math.max(x2-x1+1,y2-y1+1)*p)),sx=Math.max(0,x1-pad),sy=Math.max(0,y1-pad),ex=Math.min(w,x2+1+pad),ey=Math.min(h,y2+1+pad);
    if(!sx&&!sy&&ex===w&&ey===h)return c;const o=document.createElement('canvas');o.width=ex-sx;o.height=ey-sy;o.getContext('2d').drawImage(c,sx,sy,o.width,o.height,0,0,o.width,o.height);return o;
  }

  core.cropTransparent=function(el,face){
    const {w,h}=dims(el);if(!w||!h)throw new Error('去背圖片尺寸錯誤');
    const a=alphaInfo(el);if(!a)throw new Error('找不到去背後的人像輪廓');
    let rect=face?faceHead(face,w,h):silhouetteHead(a);
    let x=Math.floor(clamp(rect.x,0,w-1)),y=Math.floor(clamp(rect.y,0,h-1)),cw=Math.max(1,Math.ceil(Math.min(rect.w,w-x))),ch=Math.max(1,Math.ceil(Math.min(rect.h,h-y)));
    // fallback 也禁止裁到透明主體底部 60% 以下，確保結果真的是「大頭」。
    if(!face){const maxBottom=(a.minY+(a.maxY-a.minY+1)*.58)/a.r;ch=Math.max(1,Math.min(ch,Math.ceil(maxBottom-y)))}
    const c=document.createElement('canvas');c.width=cw;c.height=ch;c.getContext('2d').drawImage(el,x,y,cw,ch,0,0,cw,ch);
    return {canvas:trim(c),mode:face?'face':'silhouette-head',faceCount:Number(face?.count||0),score:Number(face?.score||0)};
  };
  core.version='2.0-force-head';
  console.info('[AI HEAD] force-head v2 enabled');
})();
