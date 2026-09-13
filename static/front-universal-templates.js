/* 本福丸前台：通用模板依客人選擇的手機型號自動縮放套用 */
(function(){
  'use strict';
  if(window.__benfuwanUniversalTemplatesFrontInstalled)return;
  window.__benfuwanUniversalTemplatesFrontInstalled=true;

  const originalApplyTemplate=window.applyTemplate;

  function isUniversal(t){return !!(t&&(t.universal===true||t.model_id==='*'||Number(t.template_version)>=2))}
  function deepClone(v){return JSON.parse(JSON.stringify(v))}
  function parseObjects(raw){if(!raw)return null;if(typeof raw==='string'){try{return JSON.parse(raw)}catch(e){return null}}return deepClone(raw)}

  window.renderTemplates=function(cat='全部'){
    const box=$('tpl-grid');if(!box)return;
    let list=(templatesData.templates||[]).filter(t=>(isUniversal(t)||t.model_id===ctx.modelId)&&(!t.case_style_id||t.case_style_id===ctx.styleId));
    if(cat!=='全部')list=list.filter(t=>(t.category||'全部')===cat);
    box.innerHTML='';
    if(!list.length){box.innerHTML='<div class="tpl-empty">目前還沒有模板。<br>可以按「跳過」直接自由設計 ♡</div>';return}
    list.forEach(t=>{
      const c=document.createElement('div');
      c.className='card tpl-card'+(selectedTpl?.id===t.id?' selected':'');
      c.innerHTML=`<img loading="lazy" decoding="async" src="${attr(t.thumb_url||'')}" alt=""><div class="name">${escapeHtml(t.name||'模板')}</div>${isUniversal(t)?'<div style="font-size:9px;color:#ff6f9a;padding:0 4px 5px;font-weight:800">全型號自動適配</div>':''}`;
      c.onclick=()=>{selectedTpl=t;$('tpl-next').disabled=false;renderTemplates(cat)};
      box.appendChild(c);
    });
  };

  window.applyTemplate=function(tpl,done){
    if(!isUniversal(tpl)||typeof originalApplyTemplate!=='function')return originalApplyTemplate?.(tpl,done);

    const sourceW=Math.max(1,Number(tpl.source_print_w)||80),
      sourceH=Math.max(1,Number(tpl.source_print_h)||160),
      targetW=Math.max(1,Number(ctx.printW)||80),
      targetH=Math.max(1,Number(ctx.printH)||160),
      rx=targetW/sourceW,
      ry=targetH/sourceH,
      uniform=Math.min(rx,ry);

    const adapted=deepClone(tpl);
    adapted.universal=false;
    adapted.model_id=ctx.modelId;
    adapted.slots=(tpl.slots||[]).map(s=>({
      ...s,
      x:(Number(s.x)||0)*rx,
      y:(Number(s.y)||0)*ry,
      w:(Number(s.w??s.width)||0)*rx,
      h:(Number(s.h??s.height)||0)*ry
    }));

    const raw=parseObjects(tpl.objects_json);
    if(raw&&Array.isArray(raw.objects)){
      raw.objects=raw.objects.map(o=>{
        if(o.isSlot)return o;
        const n={...o};
        n.left=(Number(n.left)||0)*rx;
        n.top=(Number(n.top)||0)*ry;
        if(n.isTplBg){
          n.scaleX=(Number(n.scaleX)||1)*rx;
          n.scaleY=(Number(n.scaleY)||1)*ry;
        }else{
          n.scaleX=(Number(n.scaleX)||1)*uniform;
          n.scaleY=(Number(n.scaleY)||1)*uniform;
        }
        return n;
      });
      adapted.objects_json=raw;
    }

    console.info('[FRONT] universal template adapted',tpl.name,{source:[sourceW,sourceH],target:[targetW,targetH],rx,ry});
    return originalApplyTemplate(adapted,done);
  };

  console.info('[FRONT] universal template auto-fit enabled');
})();