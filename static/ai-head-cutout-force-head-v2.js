/* 本福丸 AI 大頭 v4：臉部辨識成功時，直接依臉框建立頭部遮罩；不再靠人物透明輪廓判斷肩膀/手臂。 */
(function(){
  'use strict';
  if(window.__bfAiHeadForceV4)return;window.__bfAiHeadForceV4=true;
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
      rows[y]=rr>=l?{l,rr,w:rr-l+1}:null;
    }
    if(maxX<minX)return null;return {r,sw,sh,minX,minY,maxX,maxY,rows,w,h};
  }
  function avgWidth(a,y1,y2){let s=0,n=0;for(let y=Math.max(a.minY,Math.floor(y1));y<=Math.min(a.maxY,Math.ceil(y2));y++){const q=a.rows[y];if(q){s+=q.w;n++}}return n?s/n:0}
  function silhouetteHead(a){
    const bodyH=a.maxY-a.minY+1;let cutY=Math.round(a.minY+bodyH*.27),start=Math.round(a.minY+bodyH*.08),end=Math.round(a.minY+bodyH*.42);
    for(let y=start+5;y<end-6;y++){const before=avgWidth(a,y-5,y-1),after=avgWidth(a,y+1,y+6);if(before>8&&after>before*1.22){cutY=y;break}}
    cutY=clamp(cutY,Math.round(a.minY+bodyH*.18),Math.round(a.minY+bodyH*.32));
    let l=a.sw,r=-1;for(let y=a.minY;y<=cutY;y++){const q=a.rows[y];if(q){l=Math.min(l,q.l);r=Math.max(r,q.rr)}}if(r<l){l=a.minX;r=a.maxX}
    const hw=r-l+1,hh=cutY-a.minY+1,cx=(l+r)/2,ow=Math.max(hw*1.08,hh*.78),oh=Math.max(hh*1.08,ow*.98);
    return {x:(cx-ow/2)/a.r,y:(a.minY-hh*.04)/a.r,w:ow/a.r,h:oh/a.r};
  }

  function faceMaskCrop(el,face){
    const {w,h}=dims(el),fx=face.x*w,fy=face.y*h,fw=face.w*w,fh=face.h*h,cx=fx+fw/2;
    // 臉框通常不含完整頭髮：上方多留約 0.72 個臉高；底部只留到下巴下一點點。
    const left=cx-fw*.92,right=cx+fw*.92,top=fy-fh*.72,bottom=fy+fh*1.18;
    const x=Math.floor(clamp(left,0,w-1)),y=Math.floor(clamp(top,0,h-1)),cw=Math.max(1,Math.ceil(clamp(right,1,w)-x)),ch=Math.max(1,Math.ceil(clamp(bottom,1,h)-y));
    const src=document.createElement('canvas');src.width=cw;src.height=ch;src.getContext('2d').drawImage(el,x,y,cw,ch,0,0,cw,ch);

    // 關鍵：裁切矩形仍可能碰到伸手/肩膀，所以再用「頭型遮罩」把矩形四角與下半身直接清掉。
    const out=document.createElement('canvas');out.width=cw;out.height=ch;const g=out.getContext('2d');
    const rx=cw*.49, ry=ch*.50, ecx=cw*.5, ecy=ch*.48;
    g.save();g.beginPath();g.ellipse(ecx,ecy,rx,ry,0,0,Math.PI*2);g.clip();g.drawImage(src,0,0);g.restore();
    return out;
  }

  function trim(c,p=.035){
    const w=c.width,h=c.height,g=c.getContext('2d',{willReadFrequently:true});let d;try{d=g.getImageData(0,0,w,h).data}catch(e){return c}
    let x1=w,y1=h,x2=-1,y2=-1;for(let y=0;y<h;y++)for(let x=0;x<w;x++)if(d[(y*w+x)*4+3]>8){x1=Math.min(x1,x);x2=Math.max(x2,x);y1=Math.min(y1,y);y2=Math.max(y2,y)}
    if(x2<x1)return c;const pad=Math.max(3,Math.round(Math.max(x2-x1+1,y2-y1+1)*p)),sx=Math.max(0,x1-pad),sy=Math.max(0,y1-pad),ex=Math.min(w,x2+1+pad),ey=Math.min(h,y2+1+pad);
    if(!sx&&!sy&&ex===w&&ey===h)return c;const o=document.createElement('canvas');o.width=ex-sx;o.height=ey-sy;o.getContext('2d').drawImage(c,sx,sy,o.width,o.height,0,0,o.width,o.height);return o;
  }

  core.cropTransparent=function(el,face){
    const {w,h}=dims(el);if(!w||!h)throw new Error('去背圖片尺寸錯誤');
    if(face){return {canvas:trim(faceMaskCrop(el,face)),mode:'face-mask-v4',faceCount:Number(face.count||0),score:Number(face.score||0)}}
    const a=alphaInfo(el);if(!a)throw new Error('找不到去背後的人像輪廓');const rect=silhouetteHead(a);
    const x=Math.floor(clamp(rect.x,0,w-1)),y=Math.floor(clamp(rect.y,0,h-1)),cw=Math.max(1,Math.ceil(Math.min(rect.w,w-x))),ch=Math.max(1,Math.ceil(Math.min(rect.h,h-y)));
    const c=document.createElement('canvas');c.width=cw;c.height=ch;c.getContext('2d').drawImage(el,x,y,cw,ch,0,0,cw,ch);
    return {canvas:trim(c),mode:'silhouette-head-v4',faceCount:0,score:0};
  };
  core.version='4.0-face-mask';console.info('[AI HEAD] face-mask v4 enabled');
})();
