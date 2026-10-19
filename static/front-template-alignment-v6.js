/* Single geometry contract for legacy templates. Fabric admin=2 px/mm,
   customer=3 px/mm; the base applyTemplate performs the final 3/2 conversion.
   Preserve layer_contract_version templates on their independent normalized path. */
(function(){
  'use strict';if(window.__bfTemplateAlignment20261017)return;window.__bfTemplateAlignment20261017=true;
  const previous=window.applyTemplate;
  const num=(x,f=0)=>Number.isFinite(Number(x))?Number(x):f;
  const positive=x=>num(x)>0?num(x):0;
  const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
  const universal=t=>!!t&&(t.universal===true||t.model_id==='*'||num(t.template_version)>=2);
  const clone=v=>JSON.parse(JSON.stringify(v));
  function geometry(t){
    const srcW=positive(t.source_canvas_w)||positive(t.source_print_w)*2,
          srcH=positive(t.source_canvas_h)||positive(t.source_print_h)*2;
    const dstW=positive(ctx.printW)*2,dstH=positive(ctx.printH)*2;
    if(!srcW||!srcH||!dstW||!dstH)throw Error('模板基準／目前型號缺少生產尺寸');
    return {srcW,srcH,dstW,dstH,sw:positive(t.source_print_w)||srcW/2,sh:positive(t.source_print_h)||srcH/2,
      tw:dstW/2,th:dstH/2,fit:Math.min(dstW/srcW,dstH/srcH)};
  }
  function sourceCenter(o,g){
    const cx=num(o.bfNormCX,NaN),cy=num(o.bfNormCY,NaN);
    if(Number.isFinite(cx)&&Number.isFinite(cy))return {x:cx*g.srcW,y:cy*g.srcH};
    const w=positive(o.width)*Math.abs(num(o.scaleX,1)),h=positive(o.height)*Math.abs(num(o.scaleY,1));
    const dx=(o.originX==='center'?0:o.originX==='right'?-w/2:w/2);
    const dy=(o.originY==='center'?0:o.originY==='bottom'?-h/2:h/2);
    const a=num(o.angle)*Math.PI/180;
    return{x:num(o.left)+dx*Math.cos(a)-dy*Math.sin(a),y:num(o.top)+dx*Math.sin(a)+dy*Math.cos(a)};
  }
  function adapt(t){
    if(!universal(t)||t.layer_contract_version)return t;
    const sameModel=String(t.reference_model_id||'')===String(ctx.modelId||'')
      &&(!t.reference_style_id||String(t.reference_style_id)===String(ctx.styleId||''));
    const g=geometry(t),out=clone(t);
    // The base renderer understands already-adapted legacy templates.
    out.universal=false;out.model_id=ctx.modelId;out.template_version=0;
    let raw=typeof out.objects_json==='string'?JSON.parse(out.objects_json):out.objects_json;
    if(raw&&Array.isArray(raw.objects)){
      raw.objects=raw.objects.map(o=>{
        if(!o||o.isSlot)return o;
        const n={...o};
        if(n.type==='image'&&n.src){
          const source=n.publicSrc||n.src;
          n.src=window.benfuwanTemplateProxyUrl?.(source)||source;
          delete n.crossOrigin;
        }
        if(sameModel)return n; // Keep identity geometry, but never bypass safe image sources.
        if(n.isTplBg){
          const ow=Math.max(1,positive(n.width)),oh=Math.max(1,positive(n.height));
          const cover=Math.max(g.dstW/ow,g.dstH/oh);
          return {...n,left:g.dstW/2,top:g.dstH/2,originX:'center',originY:'center',scaleX:cover,scaleY:cover};
        }
        const center=sourceCenter(n,g);
        // Positions derive from the author's canvas, never from camera-mask
        // edge detection; retain rotation and use ONE uniform scale on sizes.
        n.left=(center.x/g.srcW)*g.dstW;n.top=(center.y/g.srcH)*g.dstH;
        n.originX='center';n.originY='center';
        n.scaleX=num(n.scaleX,1)*g.fit;n.scaleY=num(n.scaleY,1)*g.fit;
        return n;
      });
      out.objects_json=raw;
    }
    if(sameModel)return out;
    const fitMm=Math.min(g.tw/g.sw,g.th/g.sh);
    out.slots=(out.slots||[]).map(s=>{
      const w=positive(s.w??s.width),h=positive(s.h??s.height);
      const nx=(num(s.x)+w/2)/g.sw,ny=(num(s.y)+h/2)/g.sh;
      const tw=w*fitMm,th=h*fitMm;
      return {...s,x:nx*g.tw-tw/2,y:ny*g.th-th/2,w:tw,h:th};
    });
    return out;
  }
  window.applyTemplate=function(tpl,done){
    if(!universal(tpl)||tpl.layer_contract_version||typeof previous!=='function')
      return previous?.apply(this,arguments);
    try{return previous.call(this,adapt(tpl),done)}
    catch(e){console.error('[TEMPLATE ALIGNMENT]',e);window.toast?.('模板座標無法解析，請聯絡店家調整模板');}
  };
  window.BenfuwanTemplateAlignment={adapt,geometry};
  console.info('[FRONT] deterministic normalized legacy template alignment installed');
})();
