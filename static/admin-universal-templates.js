/* 本福丸後台：模板改為全型號通用，型號只作為設計基準畫布 */
(function(){
  'use strict';
  if(window.__benfuwanUniversalTemplatesAdminInstalled)return;
  window.__benfuwanUniversalTemplatesAdminInstalled=true;

  const pickReferenceModel=()=>{
    const list=Array.isArray(shopData?.models)?shopData.models:[];
    return list.find(m=>m.name==='iPhone 13')||list.find(m=>m.status!==false)||list[0]||null;
  };

  function relabelUi(){
    const sel=document.getElementById('tpl-model');
    if(!sel)return;
    const field=sel.closest('.field');
    const label=field?.querySelector('label');
    if(label)label.textContent='設計基準型號（不限制客人型號）';
    if(field&&!field.querySelector('.bf-universal-note')){
      const note=document.createElement('div');
      note.className='bf-universal-note notice';
      note.innerHTML='模板會儲存成 <b>全型號通用</b>。這裡選的型號只決定你編輯時看到的畫布比例，客人前台會依他選的手機型號自動套用。';
      field.appendChild(note);
    }
  }

  window.openTemplateEditor=async function(id=''){
    try{
      await Promise.all([loadShop(),loadAssets(),loadTemplates(),ensureFabric()]);
      const t=id?templatesData.templates.find(x=>x.id===id):null;
      const ref=pickReferenceModel();
      $('tpl-id').value=id;
      $('tpl-name').value=t?.name||'';
      $('tpl-category').value=t?.category||'熱門';
      $('tpl-model').innerHTML=(shopData.models||[]).filter(m=>m.status!==false).map(m=>`<option value="${esc(m.id)}">${esc(m.name)}</option>`).join('');
      const refId=t?.reference_model_id || (t?.model_id && t.model_id!=='*'?t.model_id:'') || ref?.id || shopData.models?.[0]?.id || '';
      $('tpl-model').value=refId;
      relabelUi();
      openModal('template-modal');
      setTimeout(()=>initEditor(t?.slots||[],t?.objects_json||null,t?.thumb_url||''),30);
    }catch(e){alert(e.message)}
  };

  window.renderTemplates=function(){
    const list=currentTpl==='全部'?(templatesData.templates||[]):(templatesData.templates||[]).filter(t=>t.category===currentTpl);
    const box=$('template-grid');box.className='grid';
    box.innerHTML=list.length?list.map(t=>`<div class="card"><button class="del" onclick="deleteTemplate('${esc(t.id)}')">×</button><img loading="lazy" decoding="async" src="${esc(t.thumb_url||'')}"><div class="name">${esc(t.name)}</div><small>${t.universal||t.model_id==='*'?'全型號通用':'舊版指定型號'}</small><div style="margin-top:8px"><button class="btn alt mini" onclick="openTemplateEditor('${esc(t.id)}')">編輯</button></div></div>`).join(''):'<div class="empty">目前沒有模板</div>';
  };

  window.saveTemplate=async function(){
    const id=$('tpl-id').value,
      name=$('tpl-name').value.trim(),
      category=$('tpl-category').value.trim()||'熱門',
      reference_model_id=$('tpl-model').value;
    if(!name||!reference_model_id||!visualCanvas)return alert('請填名稱並選擇設計基準型號');

    const ref=(shopData.models||[]).find(x=>x.id===reference_model_id);
    const sourcePrintW=Number(ref?.print_w)||80,
      sourcePrintH=Number(ref?.print_h)||160;
    const slots=[],slotObjs=[];
    visualCanvas.getObjects().forEach(o=>{
      if(o.isSlot){
        slots.push({
          id:o.slotId||'slot_'+Date.now(),
          x:o.left/VISUAL_SCALE,
          y:o.top/VISUAL_SCALE,
          w:o.width*o.scaleX/VISUAL_SCALE,
          h:o.height*o.scaleY/VISUAL_SCALE
        });
        slotObjs.push(o);
      }
    });

    visualCanvas.discardActiveObject();
    slotObjs.forEach(o=>o.set('opacity',0));visualCanvas.renderAll();
    const dataUrl=visualCanvas.toDataURL({format:'png',multiplier:2});
    slotObjs.forEach(o=>o.set('opacity',1));visualCanvas.renderAll();
    const objects=visualCanvas.toJSON(['isSlot','isTplBg','slotId']);
    objects.objects=(objects.objects||[]).filter(o=>!o.isSlot);

    try{
      const blob=await (await fetch(dataUrl)).blob();
      const url=await uploadAdminImage(new File([blob],'template.png',{type:'image/png'}),'template');
      const data={
        id:id||'tpl_'+Date.now(),
        name,category,
        universal:true,
        template_version:2,
        model_id:'*',
        reference_model_id,
        source_print_w:sourcePrintW,
        source_print_h:sourcePrintH,
        source_canvas_w:tplW,
        source_canvas_h:tplH,
        thumb_url:url,
        slots,
        objects_json:objects
      };
      if(id){const i=templatesData.templates.findIndex(x=>x.id===id);templatesData.templates[i]=data}else templatesData.templates.push(data);
      if(!templatesData.categories.includes(category))templatesData.categories.push(category);
      await apiJson('/api/admin/save_templates',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(templatesData)});
      renderTemplateTabs();renderTemplates();closeModal('template-modal');
      alert('模板已儲存為「全型號通用」');
    }catch(e){alert('模板儲存失敗：'+e.message)}
  };

  const oldInitEditor=window.initEditor;
  if(typeof oldInitEditor==='function'){
    window.initEditor=function(...args){relabelUi();return oldInitEditor.apply(this,args)};
  }

  console.info('[ADMIN] universal templates enabled');
})();