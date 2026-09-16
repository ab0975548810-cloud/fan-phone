/* 本福丸 AI 大頭 v3：強制輸出頭部素材；fallback 依逐列輪廓抓頭寬，避免手臂/身體被當成大頭。 */
(function(){
  'use strict';
  if(window.__bfAiHeadForceV3)return;window.__bfAiHeadForceV3=true;
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
    if(maxX<minX)return null;
    return {r,sw,sh,minX,minY,maxX,maxY,rows,w,h};
  }

  function avgWidth(a,y1,y2){let s=0,n=0;for(let y=Math.max(a.minY,Math.floor(y1));y<=Math.min(a.maxY,Math.ceil(y2));y++){const q=a.rows[y];if(q){s+=q.w;n++}}return n?s/n:0}

  function silhouetteHead(a){
    const bodyH=a.maxY-a.minY+1;
    // 找第一個明顯的水平擴張點：通常是下巴/肩膀或伸出的手臂。裁切底線放在擴張前。
    let cutY=Math.round(a.minY+bodyH*.30);
    const start=Math.round(a.minY+bodyH*.10),end=Math.round(a.minY+bodyH*.48);
    for(let y=start+5;y<end-6;y++){
      const before=avgWidth(a,y-5,y-1),after=avgWidth(a,y+1,y+6);
      if(before>8&&after>before*1.24){cutY=y;break}
    }
    cutY=clamp(cutY,Math.round(a.minY+bodyH*.20),Math.round(a.minY+bodyH*.38));

    // 關鍵修正：只用「頭部區間」自己的左右邊界，不再使用整個人的 minX/maxX，這樣伸手不會被包含。
    let headL=a.sw,headR=-1;
    const headStart=a.minY,headEnd=Math.min(cutY,Math.round(a.minY+bodyH*.34));
    for(let y=headStart;y<=headEnd;y++){
      const q=a.rows[y];if(!q)continue;
      headL=Math.min(headL,q.l);headR=Math.max(headR,q.rr);
    }
    if(headR<headL){headL=a.minX;headR=a.maxX}

    const headW=headR-headL+1,headH=Math.max(1,cutY-a.minY+1);
    const cx=(headL+headR)/2;
    // 保留頭髮、耳朵與一點下巴/脖子；左右只加少量安全邊，不碰手臂。
    const outW=Math.max(headW*1.16,headH*.82),outH=Math.max(headH*1.18,outW*1.02);
    const top=a.minY-headH*.08;
    return {x:(cx-outW/2)/a.r,y:top/a.r,w:outW/a.r,h:outH/a.r};
  }

  function faceHead(face,w,h){
    const fx=face.x*w,fy=face.y*h,fw=face.w*w,fh=face.h*h,cx=fx+fw/2;
    // 正臉成功時直接做真正的大頭：完整頭髮/耳朵 + 少量下巴，不保留肩膀。
    const cw=Math.max(fw*1.72,fh*1.48),ch=Math.max(fh*1.86,cw*1.03),cy=fy+fh*.43;
    return {x:cx-cw/2,y:cy-ch*.48,w:cw,h:ch};
  }

  function trim(c,p=.045){
    const w=c.width,h=c.height,g=c.getContext('2d',{willReadFrequently:true});let d;try{d=g.getImageData(0,0,w,h).data}catch(e){return c}
    let x1=w,y1=h,x2=-1,y2=-1;for(let y=0;y<h;y++)for(let x=0;x<w;x++)if(d[(y*w+x)*4+3]>8){x1=Math.min(x1,x);x2=Math.max(x2,x);y1=Math.min(y1,y);y2=Math.max(y2,y)}
    if(x2<x1)return c;const pad=Math.max(4,Math.round(Math.max(x2-x1+1,y2-y1+1)*p)),sx=Math.max(0,x1-pad),sy=Math.max(0,y1-pad),ex=Math.min(w,x2+1+pad),ey=Math.min(h,y2+1+pad);
    if(!sx&&!sy&&ex===w&&ey===h)return c;const o=document.createElement('canvas');o.width=ex-sx;o.height=ey-sy;o.getContext('2d').drawImage(c,sx,sy,o.width,o.height,0,0,o.width,o.height);return o;
  }

  core.cropTransparent=function(el,face){
    const {w,h}=dims(el);if(!w||!h)throw new Error('去背圖片尺寸錯誤');
    const a=alphaInfo(el);if(!a)throw new Error('找不到去背後的人像輪廓');
    const rect=face?faceHead(face,w,h):silhouetteHead(a);
    const x=Math.floor(clamp(rect.x,0,w-1)),y=Math.floor(clamp(rect.y,0,h-1)),cw=Math.max(1,Math.ceil(Math.min(rect.w,w-x))),ch=Math.max(1,Math.ceil(Math.min(rect.h,h-y)));
    const c=document.createElement('canvas');c.width=cw;c.height=ch;c.getContext('2d').drawImage(el,x,y,cw,ch,0,0,cw,ch);
    return {canvas:trim(c),mode:face?'face':'silhouette-head-v3',faceCount:Number(face?.count||0),score:Number(face?.score||0)};
  };
  core.version='3.0-head-only';
  console.info('[AI HEAD] head-only v3 enabled');
})();
