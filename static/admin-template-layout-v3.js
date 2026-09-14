/* 本福丸模板 layout v3：儲存相對座標，跨型號不再用絕對 px 疊成一團。 */
(function(){
  'use strict';
  if(window.__benfuwanTemplateLayoutV3Installed)return;
  window.__benfuwanTemplateLayoutV3Installed=true;
  const by=id=>document.getElementById(id);
  const CUSTOM=['isSlot','isTplBg','slotId','publicSrc','originalName','stickerId','role','materialType','aiBackgroundRemoved','aiExpanded','aiOutlineSourcePublic','aiOutlineStyle','aiOutlineWidth','aiOutlineColor','aiOutlineSource','aiOutlineStrength','__bfAdjust'];

  function norm(v,size){return Math.max(-2,Math.min(3,(Number(v)||0)/Math.max(1,size)))}
  function serializeObject(o,W,H){
    const j=o.toObject(CUSTOM),c=o.getCenterPoint(),dw=Math.max(0.01,o.getScaledWidth()),dh=Math.max(0.01,o.getScaledHeight());
    if(o.publicSrc){j.src=o.publicSrc;j.publicSrc=o.publicSrc;delete j.crossOrigin}
    j.originX='center';j.originY='center';j.left=c.x;j.top=c.y;
    return {
      object:j,
      nx:norm(c.x,W),ny:norm(c.y,H),nw:Math.max(.0001,dw/Math.max(1,W)),nh:Math.max(.0001,dh/Math.max(1,H)),
      preserveAspect:!o.isTplBg,
      kind:o.isTplBg?'background':(['text','textbox','i-text'].includes(o.type)?'text':(o.type==='image'?'image':'object'))
    };
  }
  function slotRecord(o,W,H){const c=o.getCenterPoint(),dw=o.getScaledWidth(),dh=o.getScaledHeight();return {id:o.slotId||('slot_'+Date.now()),nx:norm(c.x,W),ny:norm(c.y,H),nw:dw/Math.max(1,W),nh:dh/Math.max(1,H)} }
  function legacySlot(r,W,H){return {id:r.id,x:(r.nx-r.nw/2)*W/VISUAL_SCALE,y:(r.ny-r.nh/2)*H/VISUAL_SCALE,w:r.nw*W/VISUAL_SCALE,h:r.nh*H/VISUAL_SCALE}}

  window.saveTemplate=async function(){
    const c=window.visualCanvas;if(!c)return alert('模板畫布尚未準備好');
    const id=by('tpl-id')?.value||'',name=by('tpl-name')?.value.trim()||'',category=by('tpl-category')?.value.trim()||'熱門',reference_model_id=by('tpl-model')?.value||'';
    if(!name||!reference_model_id)return alert('請填名稱並選擇設計基準型號');
    const ref=(shopData.models||[]).find(x=>String(x.id)===String(reference_model_id))||{},W=Math.max(1,Number(tplW)||c.width||160),H=Math.max(1,Number(tplH)||c.height||320);
    const all=c.getObjects(),slotObjs=all.filter(o=>o.isSlot),layoutObjects=all.filter(o=>!o.isSlot).map(o=>serializeObject(o,W,H)),layoutSlots=slotObjs.map(o=>slotRecord(o,W,H));
    const legacy=c.toJSON(CUSTOM);legacy.objects=(legacy.objects||[]).filter(o=>!o.isSlot).map(o=>{if(o.publicSrc){o.src=o.publicSrc;delete o.crossOrigin}return o});
    const old=id?(templatesData.templates||[]).find(x=>x.id===id):null;

    c.discardActiveObject();const op=slotObjs.map(o=>o.opacity);slotObjs.forEach(o=>o.set('opacity',0));c.renderAll();
    let dataUrl;try{dataUrl=c.toDataURL({format:'png',multiplier:1.35})}finally{slotObjs.forEach((o,i)=>o.set('opacity',op[i]??1));c.renderAll()}

    try{
      const blob=await (await fetch(dataUrl)).blob(),thumb=await uploadAdminImage(new File([blob],'template-thumb.png',{type:'image/png'}),'template');
      const data={...(old||{}),id:id||('tpl_'+Date.now()),name,category,universal:true,template_version:3,model_id:'*',reference_model_id,source_print_w:Number(ref.print_w)||80,source_print_h:Number(ref.print_h)||160,source_canvas_w:W,source_canvas_h:H,thumb_url:thumb,slots:layoutSlots.map(s=>legacySlot(s,W,H)),objects_json:legacy,layout_v3:{version:3,source_w:W,source_h:H,objects:layoutObjects,slots:layoutSlots}};
      if(id){const i=templatesData.templates.findIndex(x=>x.id===id);if(i>=0)templatesData.templates[i]=data;else templatesData.templates.push(data)}else templatesData.templates.push(data);
      if(!templatesData.categories.includes(category))templatesData.categories.push(category);
      await apiJson('/api/admin/save_templates',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(templatesData)});renderTemplateTabs?.();renderTemplates?.();closeModal?.('template-modal');alert('模板已儲存 ✓（新版跨型號精準座標）');
    }catch(e){console.error('[TPL LAYOUT V3]',e);alert('模板儲存失敗：'+(e.message||e))}
  };

  console.info('[ADMIN] normalized universal template layout v3 enabled');
})();
