/* 本福丸前台模板 v5：所有物件使用同一組安全區仿射轉換，保留版型間距，不再逐物件擠成一團。 */
(function(){
'use strict';
if(window.__bfTplNormV5Front)return;window.__bfTplNormV5Front=true;
const previous=window.applyTemplate,cache=new Map();
const clone=v=>JSON.parse(JSON.stringify(v));
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const isUniversal=t=>!!(t&&(t.universal===true||t.model_id==='*'||Number(t.template_version)>=2));
const proxy=url=>typeof window.benfuwanTemplateProxyUrl==='function'?window.benfuwanTemplateProxyUrl(url):url;
function load(url){return new Promise((r,j)=>{if(!url)return r(null);const i=new Image(),tm=setTimeout(()=>{i.src='';j(new Error('mask timeout'))},7000);i.onload=()=>{clearTimeout(tm);r(i)};i.onerror=()=>{clearTimeout(tm);j(new Error('mask error'))};i.src=proxy(url)})}
function detect(img){
  if(!img)return {x:.03,y:.03,w:.94,h:.94};
  const W=120,H=Math.max(220,Math.round(W*(img.naturalHeight||1)/(img.naturalWidth||1))),c=document.createElement('canvas');c.width=W;c.height=H;const g=c.getContext('2d',{willReadFrequently:true});g.drawImage(img,0,0,W,H);const d=g.getImageData(0,0,W,H).data,rows=[];let max=0,minY=H,maxY=0;
  for(let y=0;y<H;y++){let n=0,l=W,r=-1;for(let x=0;x<W;x++){if(d[(y*W+x)*4+3]>32){n++;l=Math.min(l,x);r=Math.max(r,x);minY=Math.min(minY,y);maxY=Math.max(maxY,y)}}rows.push({n,l,r});max=Math.max(max,n)}
  if(max<8)return {x:.03,y:.03,w:.94,h:.94};
  const th=max*.76;let best={s:minY,e:maxY,len:0},s=-1;
  for(let y=minY;y<=maxY+1;y++){const ok=y<=maxY&&rows[y].n>=th;if(ok&&s<0)s=y;if((!ok||y===maxY+1)&&s>=0){const e=y-1,len=e-s+1;if(len>best.len)best={s,e,len};s=-1}}
  if(best.len<H*.2)best={s:minY,e:maxY,len:maxY-minY+1};
  const ls=[],rs=[];for(let y=best.s;y<=best.e;y++){if(rows[y].r>=rows[y].l){ls.push(rows[y].l);rs.push(rows[y].r)}}ls.sort((a,b)=>a-b);rs.sort((a,b)=>a-b);let l=ls[Math.floor(ls.length*.75)]??0,r=rs[Math.floor(rs.length*.25)]??W;if(r-l<W*.35){l=0;r=W}const mx=W*.02,my=H*.015;return{x:clamp((l+mx)/W,0,.95),y:clamp((best.s+my)/H,0,.95),w:clamp((r-l-2*mx)/W,.1,1),h:clamp((best.e-best.s-2*my)/H,.1,1)};
}
async function box(url){if(!url)return{x:.03,y:.03,w:.94,h:.94};if(cache.has(url))return cache.get(url);const p=load(url).then(detect).catch(()=>({x:.03,y:.03,w:.94,h:.94}));cache.set(url,p);return p}
function centerFromRaw(o,sw,sh){
  if(Number.isFinite(Number(o.bfNormCX))&&Number.isFinite(Number(o.bfNormCY)))return{x:Number(o.bfNormCX),y:Number(o.bfNormCY),w:Number(o.bfNormW)||0,h:Number(o.bfNormH)||0};
  const iw=Math.max(1,Number(o.width)||1),ih=Math.max(1,Number(o.height)||1),sx=Math.abs(Number(o.scaleX)||1),sy=Math.abs(Number(o.scaleY)||1),w=iw*sx,h=ih*sy,ox=o.originX||'left',oy=o.originY||'top';let cx=Number(o.left)||0,cy=Number(o.top)||0;if(ox==='left')cx+=w/2;else if(ox==='right')cx-=w/2;if(oy==='top')cy+=h/2;else if(oy==='bottom')cy-=h/2;return{x:cx/sw,y:cy/sh,w:w/sw,h:h/sh};
}
async function adapt(tpl){
  const target=(shopData.models||[]).find(m=>String(m.id)===String(ctx.modelId||''))||{},source=(shopData.models||[]).find(m=>String(m.id)===String(tpl.reference_model_id||''))||{};
  const tw=Math.max(1,Number(ctx.printW)||Number(target.print_w)||80),th=Math.max(1,Number(ctx.printH)||Number(target.print_h)||160),swmm=Math.max(1,Number(tpl.source_print_w)||Number(source.print_w)||80),shmm=Math.max(1,Number(tpl.source_print_h)||Number(source.print_h)||160);
  const tcw=tw*2,tch=th*2,scw=Math.max(1,Number(tpl.source_canvas_w)||swmm*2),sch=Math.max(1,Number(tpl.source_canvas_h)||shmm*2);
  const [sb,tb]=await Promise.all([box(source.print_line_img||source.line_img||''),box(ctx.printLineUrl||target.print_line_img||target.line_img||'')]);
  const sSafe={x:sb.x*scw,y:sb.y*sch,w:sb.w*scw,h:sb.h*sch},tSafe={x:tb.x*tcw,y:tb.y*tch,w:tb.w*tcw,h:tb.h*tch};
  const scale=Math.min(tSafe.w/Math.max(1,sSafe.w),tSafe.h/Math.max(1,sSafe.h));
  const out=clone(tpl);out.universal=false;out.model_id=ctx.modelId;out.template_version=1;
  let raw=typeof tpl.objects_json==='string'?(()=>{try{return JSON.parse(tpl.objects_json)}catch(e){return null}})():clone(tpl.objects_json);
  if(raw?.objects){raw.objects=raw.objects.map(o=>{const n={...o};if(n.type==='image'&&n.src){n.src=proxy(n.src);delete n.crossOrigin}if(n.isTplBg){const iw=Math.max(1,Number(n.width)||1),ih=Math.max(1,Number(n.height)||1),cover=Math.max(tcw/iw,tch/ih);return{...n,left:tcw/2,top:tch/2,originX:'center',originY:'center',scaleX:cover,scaleY:cover}}const q=centerFromRaw(n,scw,sch),srcCx=q.x*scw,srcCy=q.y*sch,rx=(srcCx-sSafe.x)/Math.max(1,sSafe.w),ry=(srcCy-sSafe.y)/Math.max(1,sSafe.h),cx=tSafe.x+rx*tSafe.w,cy=tSafe.y+ry*tSafe.h,targetW=Math.max(2,q.w*scw*scale),targetH=Math.max(2,q.h*sch*scale),iw=Math.max(1,Number(n.width)||1),ih=Math.max(1,Number(n.height)||1);n.left=cx;n.top=cy;n.originX='center';n.originY='center';n.scaleX=targetW/iw;n.scaleY=targetH/ih;return n});out.objects_json=raw}
  out.slots=(tpl.slots||[]).map(s=>{const cx=(Number(s.x)||0)+(Number(s.w)||0)/2,cy=(Number(s.y)||0)+(Number(s.h)||0)/2,sx=sb.x*swmm,sy=sb.y*shmm,sww=sb.w*swmm,shh=sb.h*shmm,tx=tb.x*tw,ty=tb.y*th,tww=tb.w*tw,thh=tb.h*th,rrx=(cx-sx)/Math.max(1,sww),rry=(cy-sy)/Math.max(1,shh),u=Math.min(tww/Math.max(1,sww),thh/Math.max(1,shh)),w=(Number(s.w)||0)*u,h=(Number(s.h)||0)*u,ncx=tx+rrx*tww,ncy=ty+rry*thh;return{...s,x:ncx-w/2,y:ncy-h/2,w,h}});
  if(out.thumb_url)out.thumb_url=proxy(out.thumb_url);return out;
}
window.applyTemplate=function(tpl,done){if(!isUniversal(tpl)||typeof previous!=='function')return previous?.(tpl,done);setBusy?.(true,'正在快速套用模板...');adapt(tpl).then(x=>previous(x,()=>{setBusy?.(false);done?.()})).catch(e=>{console.error('[TPL V5]',e);setBusy?.(false);previous(tpl,done)})};
console.info('[FRONT] normalized safe-area template v5 enabled');
})();