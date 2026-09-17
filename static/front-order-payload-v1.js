/* 本福丸前台訂單：送單前移除 design_json 內重複的 data/blob 圖片資料，保留生產 PNG 與設計結構。 */
(function(){
  'use strict';
  if(window.__bfFrontOrderPayloadV1)return;window.__bfFrontOrderPayloadV1=true;

  const LIMIT=1500000;
  const embedded=v=>typeof v==='string'&&(/^(?:data:|blob:)/i.test(v));
  const safeUrl=v=>typeof v==='string'&&v&&!embedded(v)?v:'';

  function cloneCompact(value){
    if(value==null||typeof value==='number'||typeof value==='boolean')return value;
    if(typeof value==='string')return embedded(value)?'':value;
    if(Array.isArray(value))return value.map(cloneCompact);
    if(typeof value!=='object')return null;
    const out={};
    for(const [key,val] of Object.entries(value)){
      if(typeof val==='string'&&embedded(val)){
        if(key==='src'){
          const publicSrc=safeUrl(value.publicSrc);
          if(publicSrc)out.src=publicSrc;
        }
        continue;
      }
      out[key]=cloneCompact(val);
    }
    return out;
  }

  function manifestObject(o){
    if(!o||typeof o!=='object')return null;
    const keys=[
      'type','role','left','top','width','height','scaleX','scaleY','angle','flipX','flipY','opacity','visible',
      'text','fontFamily','fontSize','fontWeight','fontStyle','fill','stroke','strokeWidth','textAlign','charSpacing','lineHeight',
      'slotId','materialType','originalName','aiBackgroundRemoved','aiHeadCutout','aiHeadMode','aiOutlineStrength','aiOutlineColor'
    ];
    const out={};
    for(const key of keys){
      const val=o[key];
      if(val==null||typeof val==='function')continue;
      if(typeof val==='string'&&embedded(val))continue;
      if(['string','number','boolean'].includes(typeof val))out[key]=val;
    }
    const src=safeUrl(o.publicSrc)||safeUrl(o.src);
    if(src)out.src=src;
    return out;
  }

  function compactDesign(design){
    if(design==null)return null;
    if(typeof design!=='object')return null;
    let compact=cloneCompact(design);
    if(compact&&typeof compact==='object')compact.__benfuwanCompactVersion=1;
    try{
      if(JSON.stringify(compact).length<=LIMIT)return compact;
    }catch(e){}

    const objects=Array.isArray(design.objects)?design.objects.map(manifestObject).filter(Boolean):[];
    compact={
      __benfuwanCompactVersion:1,
      manifestOnly:true,
      objectCount:objects.length,
      background:typeof design.background==='string'&&!embedded(design.background)?design.background:null,
      objects
    };
    try{
      if(JSON.stringify(compact).length<=LIMIT)return compact;
    }catch(e){}
    return {__benfuwanCompactVersion:1,manifestOnly:true,truncated:true,objectCount:objects.length};
  }

  function designBytes(design){
    try{return new TextEncoder().encode(JSON.stringify(design??null)).length}catch(e){return 0}
  }

  async function compactCartBeforeSubmit(){
    let item=null;
    try{
      if(typeof cartItem!=='undefined'&&cartItem)item=cartItem;
      if(!item&&typeof idbGet==='function')item=await idbGet('cart');
      if(!item)return;
      const before=designBytes(item.designJson);
      item.designJson=compactDesign(item.designJson);
      const after=designBytes(item.designJson);
      if(typeof cartItem!=='undefined')cartItem=item;
      if(typeof idbSet==='function')await idbSet('cart',item);
      console.info('[ORDER] compact design payload',before,'->',after,'bytes');
    }catch(e){
      console.warn('[ORDER] design compaction fallback',e);
      try{
        if(item){item.designJson=null;if(typeof cartItem!=='undefined')cartItem=item}
      }catch(_){}
    }
  }

  const baseSubmit=window.submitOrder;
  if(typeof baseSubmit==='function'&&!baseSubmit.__bfPayloadWrapped){
    const wrapped=async function(){
      await compactCartBeforeSubmit();
      return baseSubmit.apply(this,arguments);
    };
    wrapped.__bfPayloadWrapped=true;
    window.submitOrder=wrapped;
  }

  window.BenfuwanOrderPayload={version:'1.0-compact-design',compactDesign,designBytes};
  console.info('[ORDER] compact design payload enabled');
})();
