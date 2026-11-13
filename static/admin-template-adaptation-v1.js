/* Batch review UI only. All target geometry is calculated by the same server engine. */
(function(){
  'use strict';
  const by=id=>document.getElementById(id),multi=()=>window.BenfuwanMultilayer;
  let master=null,rows=[],busy=false,generation=0;
  const notify=(text,error=false)=>{const message=by('master-message');if(message&&by('master-batch')?.open){message.textContent=text;message.style.color=error?'#b22445':'#267746';}window.BenfuwanAdminProductWorkspace?.notify(text,error?'error':'success');};
  const clone=v=>structuredClone(v);
  async function request(url,body){const r=await fetch(url,{method:body?'POST':'GET',credentials:'same-origin',cache:'no-store',headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});const data=await r.json();if(!r.ok||data.status!=='success'){const error=Error(data.msg||'資料無法讀取');error.code=data.code;throw error;}return data;}
  function lock(value){busy=value;by('master-batch').querySelectorAll('button,input,select').forEach(el=>el.disabled=value);}
  function close(){if(busy)return;generation++;by('master-batch').close();rows.forEach(r=>r.surface?.dispose());const old=by('master-original');old?._surface?.dispose();if(old)old._surface=null;rows=[];}
  const proxy=url=>{if(!url||/^(data:|blob:|\/)/.test(url))return url;try{if(new URL(url,location.href).origin===location.origin)return url;}catch(e){}return '/api/public/asset_proxy?url='+encodeURIComponent(url);};
  async function snapshot(){
    const c=window.visualCanvas,profile=window.benfuwanTemplateReferenceProfile?.();
    if(!c||!profile||!by('tpl-name')?.value.trim())throw Error('請先輸入模板名稱，並選擇已配置的基準型號及殼款');
    if(window.__bfEditingTemplate?.adaptation_target)throw Error('請開啟原始母版再適配，不可從型號版本二次轉換');
    if(multi()?.VERSION!==c.layer_contract_version)throw Error('請先啟用「多圖層可編輯模板」；舊模板保持原流程，可另存母版');
    await window.BenfuwanAdminMultilayer.bakeImages(c);await multi().fonts(c);await window.BenfuwanEditableSticker.rehydrate(c);
    const data=multi().exportTemplate(c);
    return {id:'master-preview',name:by('tpl-name').value.trim(),category:by('tpl-category').value.trim()||'熱門',
      template_version:3,universal:true,model_id:'*',layer_contract_version:multi().VERSION,adaptation_contract_version:'master-v1',
      reference_model_id:by('tpl-model').value,reference_style_id:by('tpl-style').value,
      source_print_w:Number(profile.print_w),source_print_h:Number(profile.print_h),source_canvas_w:c.width,source_canvas_h:c.height,
      objects_json:data,slots:[]};
  }
  async function surface(element,template,target){
    const source=typeof template.objects_json==='string'?JSON.parse(template.objects_json):clone(template.objects_json);
    source.objects.forEach(o=>{if(o.type==='image'&&o.src){o.src=proxy(o.publicSrc||o.src);o.crossOrigin='anonymous';}});
    const c=new fabric.StaticCanvas(element,{width:template.source_canvas_w,height:template.source_canvas_h,enableRetinaScaling:true});
    await new Promise((resolve,reject)=>{try{c.loadFromJSON(source,resolve);}catch(e){reject(e);}});
    if(c.getObjects().some(o=>o.type==='image'&&!o.getElement()?.width)){c.dispose();throw Error('模板圖片無法載入');}
    await window.BenfuwanEditableSticker.textFonts(c);await window.BenfuwanEditableSticker.rehydrate(c);
    // Preview uses full-frame print alpha, identical to editor/HQ mask semantics.
    const url=target?.profile?.print_line_img;
    if(url){const image=await new Promise((resolve,reject)=>fabric.Image.fromURL(proxy(url),o=>o?.width?resolve(o):reject(Error('刀模無法載入')),{crossOrigin:'anonymous'}));
      image.set({left:0,top:0,scaleX:c.width/image.width,scaleY:c.height/image.height,absolutePositioned:true});c.clipPath=image;
    }
    c.renderAll();return c;
  }
  function roleEditor(){const list=by('master-roles');list.replaceChildren();
    for(const [index,item] of master.objects_json.objects.entries()){
      const label=document.createElement('label');label.textContent=item.layerName||item.text?.slice(0,15)||'圖層 '+(index+1);
      const select=document.createElement('select');select.dataset.masterRole=String(index);
      for(const [value,text] of [['composition','保留構圖'],['subject','主視覺'],['important-text','重要文字'],['background-crop','可裁切背景'],['decoration','可移動裝飾']]){
        const option=document.createElement('option');option.value=value;option.textContent=text;option.disabled=!!item.editableStickerInstanceId&&['background-crop','decoration'].includes(value);select.append(option);
      }
      select.value=item.adaptationRole||'composition';select.onchange=()=>{master.objects_json.objects[index].adaptationRole=select.value;generation++;const targets=rows.map(r=>r.target);rows.forEach(r=>r.surface?.dispose());by('master-targets').replaceChildren();rows=targets.map(card);notify('策略已改變，請重新產生預覽');};
      label.append(select);list.append(label);
    }
  }
  function card(target){const element=document.createElement('article');element.className='master-target';
    const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';
    const title=document.createElement('strong');title.textContent=target.model_name+' · '+target.style_name;label.append(check,title);
    const status=document.createElement('p');status.className='master-status';status.textContent='尚未預覽';
    const canvas=document.createElement('canvas');canvas.setAttribute('aria-label',target.model_name+'套版預覽');
    const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='此型號微調';details.append(summary);
    const fields={};for(const [key,text,value,min,max] of [['x','構圖水平位移（%）',0,-15,15],['y','構圖垂直位移（%）',0,-15,15],['scale','整體大小（%）',100,50,115]]){
      const field=document.createElement('label');field.textContent=text;const input=document.createElement('input');input.type='number';input.value=value;input.min=min;input.max=max;input.step=1;field.append(input);details.append(field);fields[key]=input;
      input.oninput=()=>{row.ready=false;check.checked=false;status.textContent='微調尚未驗證，請重新預覽';};
    }
    const decoration={};for(const [index,item] of master.objects_json.objects.entries())if(item.adaptationRole==='decoration'){
      const field=document.createElement('label');field.textContent=(item.layerName||'裝飾')+' 位移 X/Y（%）';const axes={};
      for(const a of ['x','y']){const input=document.createElement('input');input.type='number';input.value=0;input.min=-10;input.max=10;input.oninput=()=>{row.ready=false;check.checked=false;};field.append(input);axes[a]=input;}
      decoration[item.layerId||'object-'+index]=axes;details.append(field);
    }
    const button=document.createElement('button');button.type='button';button.textContent='重新預覽此型號';button.onclick=async()=>{if(busy)return;lock(true);try{await preview(row,true);}finally{lock(false);}};details.append(button);
    element.append(label,status,canvas,details);by('master-targets').append(element);
    const row={target,element,check,status,canvas,fields,decoration,ready:false,overrides:null,surface:null};return row;
  }
  async function preview(row,manual=false){const current=generation;row.ready=false;row.check.checked=false;row.status.textContent='檢查刀模中…';
    try{
      const overrides=manual?{x:Number(row.fields.x.value)/100,y:Number(row.fields.y.value)/100,scale:Number(row.fields.scale.value)/100,
        layers:Object.fromEntries(Object.entries(row.decoration).map(([k,v])=>[k,{x:Number(v.x.value)/100,y:Number(v.y.value)/100}]))}:null;
      const data=await request('/api/admin/template-adaptation/preview',{master,model_id:row.target.model_id,style_id:row.target.style_id,overrides});
      if(current!==generation)return;
      row.surface?.dispose();row.surface=await surface(row.canvas,data.template,row.target);
      if(current!==generation)return;
      row.report=data.report;row.overrides=overrides;row.ready=data.report.status==='success';row.check.checked=row.ready;
      row.status.textContent=row.ready?'✓ 適配成功':'⚠ 需要人工微調 · '+data.report.issues.length+' 個元素碰到刀模／安全區';
      row.element.dataset.result=data.report.status;
    }catch(error){row.status.textContent='失敗：'+error.message;row.element.dataset.result='failed';}
  }
  async function all(){if(busy)return;lock(true);generation++;try{for(const row of rows)await preview(row);}finally{lock(false);}}
  async function save(){if(busy)return;const selected=rows.filter(r=>r.check.checked);
    if(!selected.length)return notify('請選擇至少一個已驗證型號',true);
    if(selected.some(r=>!r.ready))return notify('所選型號仍未通過刀模檢查，請先微調並重新預覽',true);
    if(!confirm('確認另存原始母版及 '+selected.length+' 個型號版本？現有模板保持不變。'))return;
    lock(true);try{
      // Thumbnail only; the independent sources and layers remain the production contract.
      const targets=[];for(const row of selected){const blob=await new Promise(resolve=>row.surface.toCanvasElement(2).toBlob(resolve,'image/png'));const thumb=await uploadAdminImage(new File([blob],'adaptation-preview.png',{type:'image/png'}),'template');targets.push({model_id:row.target.model_id,style_id:row.target.style_id,overrides:row.overrides,thumb_url:thumb});}
      await request('/api/admin/template-adaptation/save',{master,targets,expected_version:templatesVersion});
      await loadTemplates(true);renderTemplateTabs();renderTemplates();notify('母版與各型號版本已另存');lock(false);close();
    }catch(error){notify(error.message,true);if(error.code==='STALE_DATA')await loadTemplates(true);}finally{lock(false);}
  }
  async function open(){if(busy)return;busy=true;try{master=await snapshot();generation++;mount();by('master-message').textContent='';by('master-batch').showModal();lock(true);
      const data=await request('/api/admin/template-adaptation/targets');rows.forEach(r=>r.surface?.dispose());rows=[];by('master-targets').replaceChildren();roleEditor();
      const reference=data.targets.find(t=>t.model_id===master.reference_model_id&&t.style_id===master.reference_style_id);
      const old=by('master-original');old._surface?.dispose();old._surface=await surface(old,master,reference);
      rows=data.targets.map(card);by('master-count').textContent='共 '+rows.length+' 組有效手機殼設定；鏡頭底膜不參與';
    }catch(error){notify(error.message,true);}finally{if(by('master-batch'))lock(false);else busy=false;}}
  function mount(){if(by('master-batch'))return;const dialog=document.createElement('dialog');dialog.id='master-batch';
    dialog.innerHTML='<header><h2>母版跨型號適配</h2><button type="button" id="master-close">關閉</button></header><p>保留原始母版，各型號從母版獨立計算。碰到刀模或安全區時須先微調，不會自動宣告成功。</p><p id="master-message" role="status" aria-live="polite"></p><details><summary>元素適配策略</summary><div id="master-roles"></div></details><figure><figcaption>不可變原始母版</figcaption><canvas id="master-original"></canvas></figure><p id="master-count"></p><div class="master-actions"><button type="button" id="master-preview-all">批次適配所有型號</button><button type="button" id="master-save">確認後另存所選型號</button></div><div id="master-targets"></div>';
    document.body.append(dialog);by('master-close').onclick=close;by('master-preview-all').onclick=all;by('master-save').onclick=save;dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
  }
  window.bfInstallMasterTemplate=function(){if(by('master-open'))return;const tools=by('multilayer-admin-tools');if(!tools)return;const button=document.createElement('button');button.id='master-open';button.type='button';button.className='btn alt';button.textContent='母版跨型號適配';button.onclick=open;tools.append(button);};
  window.BenfuwanMasterTemplateAdmin={open,previewAll:all,snapshot};
})();
