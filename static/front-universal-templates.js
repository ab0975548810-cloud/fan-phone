/* Template catalog and one master-adaptation gateway; legacy geometry belongs to alignment-v6. */
(function(){
  'use strict';
  if(window.__benfuwanUniversalTemplatesFrontV2Installed)return;
  window.__benfuwanUniversalTemplatesFrontV2Installed=true;

  const originalApplyTemplate=window.applyTemplate;
  const TEMPLATE_THUMB_FALLBACK='/static/front-assets/benfuwan-case-fallback.webp?v=20261001a';

  function styleTemplateFallback(img){
    if(!img)return;
    img.classList.add('bf-template-thumb-fallback');
    img.alt='本福丸客製手機殼示意';
    img.style.objectFit='contain';
    img.style.padding='10px';
    img.style.background='linear-gradient(145deg,#fff8fa,#ffe6ee)';
  }

  function wireTemplateThumb(img,source){
    if(!img)return;
    const original=String(source||'').trim();
    img.style.visibility='hidden';
    const show=()=>{img.style.visibility='visible'};
    const loadFallback=()=>{
      if(img.dataset.bfFallback==='1'&&img.complete&&img.naturalWidth>0){show();return}
      img.dataset.bfFallback='1';
      styleTemplateFallback(img);
      img.onerror=()=>{img.style.visibility='visible'};
      img.onload=show;
      img.removeAttribute('src');
      img.src=TEMPLATE_THUMB_FALLBACK;
      if(img.complete&&img.naturalWidth>0)show();
    };
    img.onload=show;
    img.onerror=loadFallback;
    if(original)img.src=original;
    else loadFallback();
  }

  function isUniversal(t){return !!(t&&(t.universal===true||t.model_id==='*'||Number(t.template_version)>=2))}

  function proxyUrl(url){
    url=String(url||'').trim();
    if(!url||url.startsWith('data:')||url.startsWith('blob:')||url.startsWith('/'))return url;
    try{const u=new URL(url,location.href);if(u.origin===location.origin)return u.href}catch(e){}
    return '/api/public/asset_proxy?url='+encodeURIComponent(url);
  }

  function positive(value){const n=Number(value);return n>0?n:0}
  function sourceGeometry(tpl){
    const sourceModel=(shopData.models||[]).find(m=>String(m.id)===String(tpl.reference_model_id||''))||{};
    const explicitStyleId=String(tpl.reference_style_id||tpl.case_style_id||'');
    const legacyCrystalId=String(window.BenfuwanModelProfile?.LEGACY_CRYSTAL_STYLE_ID||'');
    const styleId=explicitStyleId||((isUniversal(tpl)&&legacyCrystalId)?legacyCrystalId:'');
    const profile=styleId?window.BenfuwanModelProfile?.profileFor?.(sourceModel,styleId):null;
    const canvasW=positive(tpl.source_canvas_w),canvasH=positive(tpl.source_canvas_h);
    const w=positive(tpl.source_print_w)||positive(profile?.printW)||(canvasW?canvasW/2:0);
    const h=positive(tpl.source_print_h)||positive(profile?.printH)||(canvasH?canvasH/2:0);
    if(!w||!h)throw new Error('模板缺少可驗證的 model + style source geometry');
    return {model:sourceModel,w,h,mask:profile?.ready?profile.printUrl:''};
  }
  function targetGeometry(){
    const w=positive(ctx.printW),h=positive(ctx.printH);
    if(!w||!h)throw new Error('目前殼款缺少生產尺寸');
    return {w,h,mask:String(ctx.printLineUrl||'')};
  }
  window.BenfuwanTemplateGeometry=Object.freeze({sourceGeometry,targetGeometry});

  window.renderTemplates=function(cat='全部'){
    const box=$('tpl-grid');if(!box)return;
    const all=templatesData.templates||[];
    const variants=all.filter(t=>t.adaptation_target?.model_id===ctx.modelId&&t.adaptation_target?.style_id===ctx.styleId);
    let list=all.filter(t=>(isUniversal(t)||t.model_id===ctx.modelId)&&(!t.case_style_id||t.case_style_id===ctx.styleId)
      &&(!t.adaptation_target||variants.includes(t))&&!variants.some(v=>v.master_template_id===t.id));
    if(cat!=='全部')list=list.filter(t=>(t.category||'全部')===cat);
    box.innerHTML='';
    if(!list.length){box.innerHTML='<div class="tpl-empty">目前還沒有模板。<br>可以按「跳過」直接自由設計 ♡</div>';return}
    list.forEach(t=>{
      const c=document.createElement('div');c.className='card tpl-card'+(selectedTpl?.id===t.id?' selected':'');
      const thumb=String(t.thumb_url||'').trim();
      c.innerHTML=`<img loading="lazy" decoding="async" alt="${escapeHtml(t.name||'模板')}預覽"><div class="name">${escapeHtml(t.name||'模板')}</div>${isUniversal(t)?'<div style="font-size:9px;color:#ff6f9a;padding:0 4px 5px;font-weight:800">'+(t.adaptation_contract_version==='master-v1'?'母版等比例適配':'全型號模板')+'</div>':''}`;
      wireTemplateThumb(c.querySelector('img'),thumb);
      c.onclick=()=>{selectedTpl=t;$('tpl-next').disabled=false;renderTemplates(cat)};box.appendChild(c);
    });
  };

  window.applyTemplate=function(tpl,done){
    if(tpl?.adaptation_contract_version==='master-v1'){
      const c=canvas,model=ctx.modelId,style=ctx.styleId;
      if(window.BenfuwanProducts?.type((shopData.models||[]).find(m=>m.id===model))!=='phone_case')return toast('手機殼母版不適用鏡頭底膜');
      setBusy(true,'正在檢查刀模與母版構圖…');
      return fetch('/api/template_adaptation/'+encodeURIComponent(tpl.id)+'?model_id='+encodeURIComponent(model)+'&style_id='+encodeURIComponent(style),{cache:'no-store',credentials:'same-origin'})
        .then(async r=>{const data=await r.json();if(!r.ok||data.status!=='success')throw Error(data.msg||'母版需要人工微調');
          if(canvas!==c||ctx.modelId!==model||ctx.styleId!==style)return;
          const result=data.template;result.universal=false;result.template_version=0;result.model_id=model;
          const objects=typeof result.objects_json==='string'?JSON.parse(result.objects_json):result.objects_json;
          objects?.objects?.forEach(o=>{if(o.type==='image'&&o.src){o.src=proxyUrl(o.publicSrc||o.src);delete o.crossOrigin;}});
          return new Promise(resolve=>originalApplyTemplate(result,()=>{resolve();done?.();}));
        }).catch(error=>{console.error('[MASTER TEMPLATE]',error);toast(error.message||'模板需要人工微調');}).finally(()=>setBusy(false));
    }
    return originalApplyTemplate?.(tpl,done); // Legacy mapping is owned only by alignment-v6.
  };

  window.benfuwanTemplateProxyUrl=proxyUrl;
  window.BenfuwanTemplateThumbFallback=Object.freeze({url:TEMPLATE_THUMB_FALLBACK,wire:wireTemplateThumb});
  console.info('[FRONT] template catalog + shared master adaptation gateway enabled');
})();
