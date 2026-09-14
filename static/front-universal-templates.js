/* 本福丸前台：通用模板 v2。依每個型號的可印遮罩自動避開鏡頭區並重新對位。 */
(function(){
  'use strict';
  if(window.__benfuwanUniversalTemplatesFrontV2Installed)return;
  window.__benfuwanUniversalTemplatesFrontV2Installed=true;

  const originalApplyTemplate=window.applyTemplate;
  const maskBoxCache=new Map();

  function isUniversal(t){return !!(t&&(t.universal===true||t.model_id==='*'||Number(t.template_version)>=2))}
  function deepClone(v){return JSON.parse(JSON.stringify(v))}
  function parseObjects(raw){if(!raw)return null;if(typeof raw==='string'){try{return JSON.parse(raw)}catch(e){return null}}return deepClone(raw)}
  function clamp(v,a,b){return Math.max(a,Math.min(b,v))}

  function proxyUrl(url){
    url=String(url||'').trim();
    if(!url||url.startsWith('data:')||url.startsWith('blob:')||url.startsWith('/'))return url;
    try{const u=new URL(url,location.href);if(u.origin===location.origin)return u.href}catch(e){}
    return '/api/public/asset_proxy?url='+encodeURIComponent(url);
  }

  function loadImage(url){
    return new Promise((resolve,reject)=>{
      const img=new Image();
      const timer=setTimeout(()=>{img.src='';reject(new Error('mask timeout'))},12000);
      img.onload=()=>{clearTimeout(timer);resolve(img)};
      img.onerror=()=>{clearTimeout(timer);reject(new Error('mask load failed'))};
      img.src=proxyUrl(url);
    });
  }

  function percentile(values,p){
    if(!values.length)return 0;
    const a=values.slice().sort((x,y)=>x-y),i=Math.max(0,Math.min(a.length-1,Math.round((a.length-1)*p)));
    return a[i];
  }

  function detectSafeBox(img){
    const W=180,H=Math.max(260,Math.round(W*(img.naturalHeight||1)/(img.naturalWidth||1)));
    const c=document.createElement('canvas');c.width=W;c.height=H;
    const g=c.getContext('2d',{willReadFrequently:true});g.drawImage(img,0,0,W,H);
    const d=g.getImageData(0,0,W,H).data;
    const rows=[];let minX=W,minY=H,maxX=-1,maxY=-1,maxCount=0;
    for(let y=0;y<H;y++){
      let count=0,left=W,right=-1;
      for(let x=0;x<W;x++){
        const a=d[(y*W+x)*4+3];
        if(a>24){count++;if(x<left)left=x;if(x>right)right=x;if(x<minX)minX=x;if(x>maxX)maxX=x;if(y<minY)minY=y;if(y>maxY)maxY=y}
      }
      rows.push({count,left,right});if(count>maxCount)maxCount=count;
    }
    if(maxX<minX||maxY<minY||maxCount<8)return {x:.03,y:.03,w:.94,h:.94};

    const threshold=Math.max(W*.38,maxCount*.78);
    let best={start:minY,end:maxY,len:0},start=-1;
    for(let y=minY;y<=maxY+1;y++){
      const good=y<=maxY&&rows[y].count>=threshold;
      if(good&&start<0)start=y;
      if((!good||y===maxY+1)&&start>=0){const end=y-1,len=end-start+1;if(len>best.len)best={start,end,len};start=-1}
    }
    if(best.len<H*.18)best={start:minY,end:maxY,len:maxY-minY+1};
    const lefts=[],rights=[];
    for(let y=best.start;y<=best.end;y++){if(rows[y].right>=rows[y].left){lefts.push(rows[y].left);rights.push(rows[y].right)}}
    let l=lefts.length?percentile(lefts,.78):minX;
    let r=rights.length?percentile(rights,.22):maxX;
    if(r-l<W*.35){l=minX;r=maxX}
    const mx=Math.max(2,W*.025),my=Math.max(2,H*.018);
    l=clamp(l+mx,0,W-2);r=clamp(r-mx,l+2,W);
    const t=clamp(best.start+my,0,H-2),b=clamp(best.end-my,t+2,H);
    return {x:l/W,y:t/H,w:(r-l)/W,h:(b-t)/H};
  }

  async function maskBox(url){
    if(!url)return {x:.03,y:.03,w:.94,h:.94};
    const key=String(url);
    if(maskBoxCache.has(key))return maskBoxCache.get(key);
    const p=loadImage(key).then(detectSafeBox).catch(()=>({x:.03,y:.03,w:.94,h:.94}));
    maskBoxCache.set(key,p);return p;
  }

  function boxPx(frac,w,h){return {x:frac.x*w,y:frac.y*h,w:frac.w*w,h:frac.h*h}}
  function mapPoint(v,srcStart,srcSize,dstStart,dstSize){const n=(Number(v)-srcStart)/Math.max(1,srcSize);return dstStart+clamp(n,.025,.975)*dstSize}

  async function adaptUniversal(tpl){
    const sourceModel=(shopData.models||[]).find(m=>String(m.id)===String(tpl.reference_model_id||''))||{};
    const targetModel=(shopData.models||[]).find(m=>String(m.id)===String(ctx.modelId||''))||{};
    const sourceW=Math.max(1,Number(tpl.source_print_w)||Number(sourceModel.print_w)||80);
    const sourceH=Math.max(1,Number(tpl.source_print_h)||Number(sourceModel.print_h)||160);
    const targetW=Math.max(1,Number(ctx.printW)||Number(targetModel.print_w)||80);
    const targetH=Math.max(1,Number(ctx.printH)||Number(targetModel.print_h)||160);
    const sourceMask=sourceModel.print_line_img||sourceModel.line_img||'';
    const targetMask=ctx.printLineUrl||targetModel.print_line_img||targetModel.line_img||'';
    const [sourceFrac,targetFrac]=await Promise.all([maskBox(sourceMask),maskBox(targetMask)]);

    const adapted=deepClone(tpl);
    adapted.universal=false;adapted.model_id=ctx.modelId;

    const sMm=boxPx(sourceFrac,sourceW,sourceH),tMm=boxPx(targetFrac,targetW,targetH);
    adapted.slots=(tpl.slots||[]).map(s=>{
      const x=Number(s.x)||0,y=Number(s.y)||0,w=Number(s.w??s.width)||0,h=Number(s.h??s.height)||0;
      const sx=tMm.w/Math.max(1,sMm.w),sy=tMm.h/Math.max(1,sMm.h);
      return {...s,x:mapPoint(x,sMm.x,sMm.w,tMm.x,tMm.w),y:mapPoint(y,sMm.y,sMm.h,tMm.y,tMm.h),w:w*sx,h:h*sy};
    });

    const raw=parseObjects(tpl.objects_json);
    if(raw&&Array.isArray(raw.objects)){
      const sourceRawW=Math.max(1,Number(tpl.source_canvas_w)||sourceW*2);
      const sourceRawH=Math.max(1,Number(tpl.source_canvas_h)||sourceH*2);
      const targetRawW=targetW*2,targetRawH=targetH*2;
      const sRaw=boxPx(sourceFrac,sourceRawW,sourceRawH),tRaw=boxPx(targetFrac,targetRawW,targetRawH);
      const uniform=Math.min(tRaw.w/Math.max(1,sRaw.w),tRaw.h/Math.max(1,sRaw.h));

      raw.objects=raw.objects.map(o=>{
        if(o.isSlot)return o;
        const n={...o};
        if(n.type==='image'&&n.src){n.src=proxyUrl(n.src);delete n.crossOrigin}
        if(n.isTplBg){
          const iw=Math.max(1,Number(n.width)||1),ih=Math.max(1,Number(n.height)||1);
          const cover=Math.max(targetRawW/iw,targetRawH/ih);
          n.left=targetRawW/2;n.top=targetRawH/2;n.originX='center';n.originY='center';n.scaleX=cover;n.scaleY=cover;
        }else{
          n.left=mapPoint(Number(n.left)||0,sRaw.x,sRaw.w,tRaw.x,tRaw.w);
          n.top=mapPoint(Number(n.top)||0,sRaw.y,sRaw.h,tRaw.y,tRaw.h);
          n.scaleX=(Number(n.scaleX)||1)*uniform;
          n.scaleY=(Number(n.scaleY)||1)*uniform;
        }
        return n;
      });
      adapted.objects_json=raw;
    }
    if(adapted.thumb_url)adapted.thumb_url=proxyUrl(adapted.thumb_url);
    adapted.__safeAdapt={source:sourceFrac,target:targetFrac};
    return adapted;
  }

  window.renderTemplates=function(cat='全部'){
    const box=$('tpl-grid');if(!box)return;
    let list=(templatesData.templates||[]).filter(t=>(isUniversal(t)||t.model_id===ctx.modelId)&&(!t.case_style_id||t.case_style_id===ctx.styleId));
    if(cat!=='全部')list=list.filter(t=>(t.category||'全部')===cat);
    box.innerHTML='';
    if(!list.length){box.innerHTML='<div class="tpl-empty">目前還沒有模板。<br>可以按「跳過」直接自由設計 ♡</div>';return}
    list.forEach(t=>{
      const c=document.createElement('div');c.className='card tpl-card'+(selectedTpl?.id===t.id?' selected':'');
      c.innerHTML=`<img loading="lazy" decoding="async" src="${attr(t.thumb_url||'')}" alt=""><div class="name">${escapeHtml(t.name||'模板')}</div>${isUniversal(t)?'<div style="font-size:9px;color:#ff6f9a;padding:0 4px 5px;font-weight:800">全型號自動對位</div>':''}`;
      c.onclick=()=>{selectedTpl=t;$('tpl-next').disabled=false;renderTemplates(cat)};box.appendChild(c);
    });
  };

  window.applyTemplate=function(tpl,done){
    if(!isUniversal(tpl)||typeof originalApplyTemplate!=='function')return originalApplyTemplate?.(tpl,done);
    const targetCanvas=canvas;
    if(typeof setBusy==='function')setBusy(true,'正在依手機型號自動對位模板...');
    adaptUniversal(tpl).then(adapted=>{
      if(canvas!==targetCanvas&&targetCanvas)return;
      console.info('[FRONT] universal template v2 adapted',tpl.name,adapted.__safeAdapt);
      originalApplyTemplate(adapted,()=>{if(typeof setBusy==='function')setBusy(false);done?.()});
    }).catch(err=>{
      console.error('[FRONT] template auto-fit failed',err);
      if(typeof setBusy==='function')setBusy(false);
      if(typeof toast==='function')toast('模板自動對位失敗，已使用基本比例套用');
      originalApplyTemplate(tpl,done);
    });
  };

  window.benfuwanTemplateProxyUrl=proxyUrl;
  console.info('[FRONT] universal template v2 safe-area auto-fit enabled');
})();
