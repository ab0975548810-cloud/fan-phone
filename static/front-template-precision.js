/* 本福丸前台：通用模板精準對位。只做一次跨型號換算，避免舊通用模板層再次二次縮放。 */
(function(){
  'use strict';
  if(window.__benfuwanTemplatePrecisionInstalled)return;
  window.__benfuwanTemplatePrecisionInstalled=true;
  const previousApply=window.applyTemplate;
  const cache=new Map();
  const clone=v=>JSON.parse(JSON.stringify(v));
  const isUniversal=t=>!!(t&&(t.universal===true||t.model_id==='*'||Number(t.template_version)>=2));
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  const proxy=url=>typeof window.benfuwanTemplateProxyUrl==='function'?window.benfuwanTemplateProxyUrl(url):url;

  function load(url){return new Promise((res,rej)=>{const i=new Image(),tm=setTimeout(()=>{i.src='';rej(new Error('mask timeout'))},8000);i.onload=()=>{clearTimeout(tm);res(i)};i.onerror=()=>{clearTimeout(tm);rej(new Error('mask load failed'))};i.src=proxy(url)})}
  async function maskMap(url){
    if(!url)return null;if(cache.has(url))return cache.get(url);
    const p=load(url).then(img=>{const W=180,H=Math.max(260,Math.round(W*(img.naturalHeight||1)/(img.naturalWidth||1))),c=document.createElement('canvas');c.width=W;c.height=H;const g=c.getContext('2d',{willReadFrequently:true});g.drawImage(img,0,0,W,H);const d=g.getImageData(0,0,W,H).data;return {W,H,ok:(x,y)=>{const ix=clamp(Math.round(x*(W-1)),0,W-1),iy=clamp(Math.round(y*(H-1)),0,H-1);return d[(iy*W+ix)*4+3]>38}}}).catch(()=>null);cache.set(url,p);return p;
  }

  function rectScore(m,cx,cy,w,h,CW,CH){
    if(!m)return 1;let good=0,total=0;
    for(let yy=0;yy<7;yy++)for(let xx=0;xx<7;xx++){
      const px=cx-w/2+w*(xx/6),py=cy-h/2+h*(yy/6);total++;
      if(px>=0&&py>=0&&px<=CW&&py<=CH&&m.ok(px/CW,py/CH))good++;
    }
    return good/total;
  }
  function fitRect(m,cx,cy,w,h,CW,CH){
    cx=clamp(cx,w/2,CW-w/2);cy=clamp(cy,h/2,CH-h/2);
    if(!m||rectScore(m,cx,cy,w,h,CW,CH)>=.965)return {cx,cy};
    const step=Math.max(2,Math.round(Math.min(CW,CH)/45)),maxR=Math.round(Math.min(CH*.34,CW*.55));let best={cx,cy,score:rectScore(m,cx,cy,w,h,CW,CH),dist:999999};
    for(let r=step;r<=maxR;r+=step){
      for(let dy=-r;dy<=r;dy+=step){for(let dx=-r;dx<=r;dx+=step){if(Math.max(Math.abs(dx),Math.abs(dy))<r-step)continue;const x=clamp(cx+dx,w/2,CW-w/2),y=clamp(cy+dy,h/2,CH-h/2),s=rectScore(m,x,y,w,h,CW,CH),dist=Math.hypot(x-cx,y-cy);if(s>best.score+.002||(Math.abs(s-best.score)<.002&&dist<best.dist)){best={cx:x,cy:y,score:s,dist}}if(s>=.985)return {cx:x,cy:y}}}
    }
    return {cx:best.cx,cy:best.cy};
  }
  function centerOf(o,w,h){const ox=o.originX||'left',oy=o.originY||'top';return {x:(Number(o.left)||0)+(ox==='left'?w/2:ox==='right'?-w/2:0),y:(Number(o.top)||0)+(oy==='top'?h/2:oy==='bottom'?-h/2:0)}}

  async function precise(tpl){
    const target=(shopData.models||[]).find(m=>String(m.id)===String(ctx.modelId||''))||{};
    const source=(shopData.models||[]).find(m=>String(m.id)===String(tpl.reference_model_id||''))||{};
    const sourceW=Math.max(1,Number(tpl.source_print_w)||Number(source.print_w)||80),sourceH=Math.max(1,Number(tpl.source_print_h)||Number(source.print_h)||160),targetW=Math.max(1,Number(ctx.printW)||Number(target.print_w)||80),targetH=Math.max(1,Number(ctx.printH)||Number(target.print_h)||160);
    const sourceRawW=Math.max(1,Number(tpl.source_canvas_w)||sourceW*2),sourceRawH=Math.max(1,Number(tpl.source_canvas_h)||sourceH*2),targetRawW=targetW*2,targetRawH=targetH*2;
    const rx=targetRawW/sourceRawW,ry=targetRawH/sourceRawH,uniform=Math.min(rx,ry),m=await maskMap(ctx.printLineUrl||target.print_line_img||target.line_img||'');
    const out=clone(tpl);
    out.universal=false;
    out.model_id=ctx.modelId;
    /* 關鍵：已經完成精準轉換後，標記為一般模板，避免前一層 universal wrapper 再轉換第二次。 */
    out.template_version=0;

    out.slots=(tpl.slots||[]).map(s=>{const x=(Number(s.x)||0)*(targetW/sourceW),y=(Number(s.y)||0)*(targetH/sourceH),w=(Number(s.w??s.width)||0)*(targetW/sourceW),h=(Number(s.h??s.height)||0)*(targetH/sourceH),f=fitRect(m,(x+w/2)*2,(y+h/2)*2,w*2,h*2,targetRawW,targetRawH);return {...s,x:f.cx/2-w/2,y:f.cy/2-h/2,w,h}});

    let raw=tpl.objects_json;if(typeof raw==='string'){try{raw=JSON.parse(raw)}catch(e){raw=null}}else if(raw)raw=clone(raw);
    if(raw&&Array.isArray(raw.objects)){
      raw.objects=raw.objects.map(o=>{
        if(o.isSlot)return o;const n={...o};if(n.type==='image'&&n.src){n.src=proxy(n.src);delete n.crossOrigin}
        if(n.isTplBg){const iw=Math.max(1,Number(n.width)||1),ih=Math.max(1,Number(n.height)||1),cover=Math.max(targetRawW/iw,targetRawH/ih);n.left=targetRawW/2;n.top=targetRawH/2;n.originX='center';n.originY='center';n.scaleX=cover;n.scaleY=cover;return n}
        n.left=(Number(n.left)||0)*rx;n.top=(Number(n.top)||0)*ry;n.scaleX=(Number(n.scaleX)||1)*uniform;n.scaleY=(Number(n.scaleY)||1)*uniform;
        const bw=Math.max(2,(Number(n.width)||16)*Math.abs(Number(n.scaleX)||1)),bh=Math.max(2,(Number(n.height)||16)*Math.abs(Number(n.scaleY)||1)),a=(Number(n.angle)||0)*Math.PI/180,rw=Math.abs(bw*Math.cos(a))+Math.abs(bh*Math.sin(a)),rh=Math.abs(bw*Math.sin(a))+Math.abs(bh*Math.cos(a)),c=centerOf(n,bw,bh),f=fitRect(m,c.x,c.y,Math.min(rw,targetRawW*.96),Math.min(rh,targetRawH*.96),targetRawW,targetRawH);n.left+=f.cx-c.x;n.top+=f.cy-c.y;return n;
      });out.objects_json=raw;
    }
    if(out.thumb_url)out.thumb_url=proxy(out.thumb_url);return out;
  }

  window.applyTemplate=function(tpl,done){
    if(!isUniversal(tpl)||typeof previousApply!=='function')return previousApply?.(tpl,done);
    if(typeof setBusy==='function')setBusy(true,'正在精準對位模板...');
    precise(tpl).then(adapted=>previousApply(adapted,()=>{if(typeof setBusy==='function')setBusy(false);done?.()})).catch(err=>{console.error('[FRONT] precision template fit failed',err);if(typeof setBusy==='function')setBusy(false);previousApply(tpl,done)});
  };
  console.info('[FRONT] single-pass precision template positioning enabled');
})();