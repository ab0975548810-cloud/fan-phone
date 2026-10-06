(function(){
  'use strict';const multi=window.BenfuwanMultilayer,editable=window.BenfuwanEditableSticker;if(!multi)return;
  let mode=false,saving=false,hooked=new WeakSet(),observed=null;
  const by=id=>document.getElementById(id),canvas=()=>window.visualCanvas;
  const notify=(m,error=false)=>window.BenfuwanAdminProductWorkspace?.notify?.(m,error?'error':'success')||console.info(m);
  function background(c){if(!c||c.getObjects().some(o=>o.isTplBg))return;
    const bg=new fabric.Rect({width:c.width,height:c.height,left:0,top:0,strokeWidth:0,fill:typeof c.backgroundColor==='string'&&c.backgroundColor!=='transparent'?c.backgroundColor:'#fff',isTplBg:true,role:'template-bg',layerName:'背景'});multi.decorate(bg,c);c.insertAt(bg,0,false);c.backgroundColor='transparent';multi.permissions(c,bg,true);c.requestRenderAll();
  }
  function controls(){const editor=by('template-modal')?.querySelector('.editor');if(!editor||by('multilayer-admin-tools'))return;
    const bar=document.createElement('div');bar.id='multilayer-admin-tools';bar.className='multi-admin-tools';bar.innerHTML='<label><input type="checkbox" id="multilayer-enable"> 多圖層可編輯模板</label><button type="button" class="btn alt" id="multilayer-upload">加入 PNG 圖層</button><input id="multilayer-files" type="file" accept=".png,image/png" multiple hidden><small>背景預設鎖定；每個圖片／文字／照片框保持獨立。</small>';
    editor.parentElement.insertBefore(bar,editor);by('multilayer-enable').checked=mode;
    by('multilayer-enable').onchange=e=>{if(saving){e.target.checked=mode;return;}if(!e.target.checked&&window.__bfEditingTemplate?.layer_contract_version===multi.VERSION){e.target.checked=true;notify('已保存的多圖層模板不能降級；舊模板維持原流程',true);return;}mode=e.target.checked;
      if(!mode){for(const o of canvas()?.getObjects()||[])for(const key of ['layerId','templateLayerId','layerInstanceId','templateApplicationId','normalizedGeometry','zIndex',...multi.FLAGS])delete o[key];if(canvas()){delete canvas().templateState;delete canvas().layer_contract_version;}}
      if(mode){background(canvas());notify('已啟用多圖層；普通文字使用站內固定字型，請確認排版');for(const o of canvas()?.getObjects()||[]){multi.decorate(o,canvas());if(['text','textbox','i-text'].includes(o.type)&&!editable.FONTS[o.fontFamily]&&!editable.LEGACY[o.fontFamily]&&!Object.values(editable.LEGACY).includes(o.fontFamily))o.set('fontFamily','NotoSansTC');}}
      fontOptions();render();};
    by('multilayer-upload').onclick=()=>by('multilayer-files').click();by('multilayer-files').onchange=e=>upload(e,false);
  }
  const originalFontOptions=new WeakMap();
  function fontOptions(){const select=by('bf-tpl-font');if(!select)return;if(!originalFontOptions.has(select))originalFontOptions.set(select,select.innerHTML);
    const current=select.value;
    if(mode){select.replaceChildren();for(const [value,label] of [['jf-openhuninn','可愛粉圓'],['NotoSansTC','思源黑體'],[editable.LEGACY.Arial,'Arial（固定字型）'],[editable.LEGACY.serif,'明體（固定字型）'],[editable.LEGACY.cursive,'手寫（固定字型）']]){const option=document.createElement('option');option.value=value;option.textContent=label;select.append(option);}select.value=[...select.options].some(o=>o.value===current)?current:'jf-openhuninn';}
    else select.innerHTML=originalFontOptions.get(select);
  }
  async function originalPng(file){if(!file||file.type!=='image/png'||file.size>10*1024*1024)throw Error('圖層請使用 10MB 內原始 PNG，不會自動縮圖');
    const form=new FormData();form.append('file',file);form.append('type','template');form.append('source_contract','multilayer-v1');const response=await apiJson('/api/admin/upload_image',{method:'POST',body:form});return response.url;
  }
  async function upload(event,bg){const files=[...(event.target.files||[])];event.target.value='';const c=canvas();if(!c)return;
    if(!mode){if(bg)return legacyBackground(event);return;}
    try{for(const file of files){const url=await originalPng(file),o=await new Promise((resolve,reject)=>fabric.Image.fromURL(url,img=>img?.width?resolve(img):reject(Error('PNG 無法讀取')),{crossOrigin:'anonymous'}));
      o.set({left:c.width/2,top:c.height/2,originX:'center',originY:'center',strokeWidth:0,publicSrc:url,originalName:file.name,role:bg?'template-bg':'template-sticker',isTplBg:bg});
      if(bg){const sc=Math.max(c.width/o.width,c.height/o.height),width=c.width/sc,height=c.height/sc;o.set({cropX:(o.width-width)/2,cropY:(o.height-height)/2,width,height,scaleX:sc,scaleY:sc});c.getObjects().filter(x=>x.isTplBg).forEach(x=>c.remove(x));}
      else{const sc=Math.min(c.width*.35/o.width,c.height*.35/o.height,1);o.set({scaleX:sc,scaleY:sc});}
      multi.decorate(o,c);c.add(o);if(bg)c.sendToBack(o);multi.permissions(c,o,true);c.setActiveObject(o);c.requestRenderAll();}
      render();notify('原始 PNG 已加入獨立圖層');
    }catch(error){notify(error.message,true);}
  }
  function pairedFlags(c,o,patch){const pair=editable.isMember(o)?editable.pair(c,o):null;const objects=pair?[pair.bg,pair.text]:[o];for(const item of objects){if(!item)continue;Object.assign(item,patch);if(item.locked)multi.FLAGS.filter(k=>k!=='locked').forEach(k=>item[k]=false);multi.permissions(c,item,true);}render();}
  function render(){controls();const c=canvas(),box=by('bf-tpl-layer-list');if(!box||!c||!mode)return;
    if(observed!==box){observed=box;new MutationObserver(()=>{if(mode&&box.children.length&&!box.firstElementChild?.classList.contains('multi-admin-layer')&&!box.firstElementChild?.classList.contains('multi-admin-empty'))render();}).observe(box,{childList:true});}
    const fragment=document.createDocumentFragment();
    for(const o of [...c.getObjects()].reverse()){
      multi.decorate(o,c);const row=document.createElement('div');row.className='multi-admin-layer';row.dataset.layerId=o.layerId;
      const top=document.createElement('div');top.className='multi-row-top';const field=document.createElement('input');field.type='text';field.dataset.name='';field.value=multi.name(o);field.maxLength=100;field.onchange=()=>{o.layerName=field.value.trim()||multi.name(o);};
      const type=document.createElement('span');type.dataset.type='';type.textContent=o.templateSlot?'照片框':o.isTplBg?'背景':o.type==='image'?'PNG':o.type==='textbox'?'文字':o.type;
      top.append(field,type);
      const locked=document.createElement('label');const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.checked=o.locked;checkbox.dataset.locked='';locked.append(checkbox,document.createTextNode('鎖定'));checkbox.onchange=()=>pairedFlags(c,o,Object.fromEntries(multi.FLAGS.map(flag=>[flag,flag==='locked'?checkbox.checked:!checkbox.checked])));top.append(locked);
      for(const [title,fn] of [['顯示／隱藏',()=>o.set('visible',o.visible===false)],['上移',()=>c.bringForward(o)],['下移',()=>c.sendBackwards(o)]]){
        const button=document.createElement('button');button.type='button';button.title=title;button.setAttribute('aria-label',title);button.textContent=title==='上移'?'↑':title==='下移'?'↓':o.visible===false?'顯示':'隱藏';button.onclick=()=>{fn();c.requestRenderAll();c.fire('object:modified',{target:o});render();};top.append(button);
      }
      row.append(top);const details=document.createElement('details');const summary=document.createElement('summary');summary.textContent='客人可編輯權限';const flags=document.createElement('div');
      for(const [key,label] of [['canMove','移動／圖層順序'],['canScale','縮放'],['canRotate','旋轉'],['canDelete','刪除'],['canDuplicate','複製'],['canEdit','文字／內容／翻轉']]){
        const labelEl=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.checked=o[key];input.disabled=o.locked;input.dataset.permission=key;input.onchange=()=>pairedFlags(c,o,{[key]:input.checked});labelEl.append(input,document.createTextNode(label));flags.append(labelEl);
      }
      details.append(summary,flags);row.append(details);row.onclick=e=>{if(e.target.closest('button,input,label,details'))return;c.setActiveObject(o);c.requestRenderAll();};fragment.append(row);
    }
    if(!fragment.childNodes.length){const empty=document.createElement('div');empty.className='multi-admin-empty';empty.textContent='目前沒有圖層';fragment.append(empty);}box.replaceChildren(fragment);
  }
  function hook(c){if(!c||hooked.has(c))return;hooked.add(c);multi.bind(c,true);
    for(const event of ['object:added','object:removed','object:modified','selection:created','selection:updated','selection:cleared'])c.on(event,({target})=>{if(mode&&target&&event==='object:added'){multi.decorate(target,c);multi.permissions(c,target,true);}if(mode)setTimeout(render,0);});
  }
  let legacyBackground=null;
  window.bfInstallMultilayerTemplate=function(){if(window.__multiAdminInstalled)return;window.__multiAdminInstalled=true;controls();
    const oldInit=window.initEditor;window.initEditor=function(slots=[],raw=null,fallback=''){
      const parsed=typeof raw==='string'?JSON.parse(raw):raw;if(parsed?.layer_contract_version===multi.VERSION){mode=true;const result=oldInit.call(this,[],null,'');hook(canvas());multi.apply(canvas(),{id:by('tpl-id').value,objects_json:parsed},{},true).then(()=>{controls();by('multilayer-enable').checked=true;fontOptions();render();}).catch(e=>notify(e.message,true));return result;}
      const result=oldInit.apply(this,arguments);mode=!window.__bfEditingTemplate;controls();by('multilayer-enable').checked=mode;hook(canvas());if(mode)background(canvas());fontOptions();setTimeout(render,100);return result;
    };
    legacyBackground=window.uploadTemplateBg;window.uploadTemplateBg=function(event){if(!mode)return legacyBackground.apply(this,arguments);return upload(event,true);};
    const oldText=window.addText;window.addText=async function(){if(!mode)return oldText.apply(this,arguments);try{await editable.font('jf-openhuninn','輸入文字');const c=canvas(),o=new fabric.Textbox('輸入文字',{fontFamily:'jf-openhuninn',fontSize:28,fill:'#603c48',width:c.width*.6,left:c.width/2,top:c.height/2,originX:'center',originY:'center',role:'template-text',strokeWidth:0});multi.decorate(o,c);c.add(o);c.setActiveObject(o);c.requestRenderAll();render();}catch(e){notify(e.message,true);}};
    const oldSave=window.saveTemplate;window.saveTemplate=async function(){if(!mode)return oldSave.apply(this,arguments);if(saving)return;const c=canvas(),name=by('tpl-name').value.trim(),model=by('tpl-model').value,style=by('tpl-style').value,profile=window.benfuwanTemplateReferenceProfile?.();if(!c||!name||!model||!style||!profile)return notify('請填名稱並選擇已配置型號／殼款',true);
      const buttons=[...by('template-modal').querySelectorAll('.mf button')];saving=true;buttons.forEach(b=>b.disabled=true);
      try{await multi.fonts(c);await editable.rehydrate(c);const objects=multi.exportTemplate(c);c.discardActiveObject();const blob=await new Promise(resolve=>c.toCanvasElement(1).toBlob(resolve,'image/png'));const thumb=await uploadAdminImage(new File([blob],'template-preview.png',{type:'image/png'}),'template');
        const id=by('tpl-id').value||'tpl_'+multi.uid(),old=(templatesData.templates||[]).find(t=>t.id===id)||{},next=structuredClone(templatesData),category=by('tpl-category').value.trim()||'熱門';
        const item={...old,id,name,category,universal:true,template_version:Math.max(3,old.template_version||0),model_id:'*',reference_model_id:model,reference_style_id:style,source_print_w:profile.print_w,source_print_h:profile.print_h,source_canvas_w:c.width,source_canvas_h:c.height,layer_contract_version:multi.VERSION,objects_json:objects,slots:[],thumb_url:thumb};delete item.layout_v3;
        const index=next.templates.findIndex(t=>t.id===id);if(index<0)next.templates.push(item);else next.templates[index]=item;if(!next.categories.includes(category))next.categories.push(category);
        await saveTemplates(next);await loadTemplates();renderTemplateTabs();renderTemplates();closeModal('template-modal');notify('多圖層模板已儲存');
      }catch(e){notify('模板儲存失敗：'+e.message,true);}finally{saving=false;buttons.forEach(b=>b.disabled=false);}
    };
    by('template-modal').addEventListener('click',async e=>{const b=e.target.closest('[data-act="clone"]');if(!mode||!b||!editable.isMember(canvas()?.getActiveObject()))return;e.stopImmediatePropagation();e.preventDefault();await editable.duplicate(canvas(),canvas().getActiveObject());render();},true);
    by('template-modal').addEventListener('click',e=>{if(saving&&(e.target===by('template-modal')||e.target.closest('[onclick*="closeModal"]'))){e.preventDefault();e.stopImmediatePropagation();}},true);
    document.addEventListener('keydown',e=>{if(saving&&e.key==='Escape'){e.preventDefault();e.stopImmediatePropagation();}},true);
  };
})();
