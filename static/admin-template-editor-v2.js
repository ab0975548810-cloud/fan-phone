/* 本福丸後台模板編輯器 v2：修底圖/貼紙、完整文字工具、可靠儲存 */
(function(){
  'use strict';
  if(window.__benfuwanTemplateEditorV2Installed)return;
  window.__benfuwanTemplateEditorV2Installed=true;

  let saving=false;
  const isText=o=>o&&['text','textbox','i-text'].includes(o.type);
  const clone=v=>JSON.parse(JSON.stringify(v));

  function proxyUrl(url){
    url=String(url||'').trim();
    if(!url||url.startsWith('data:')||url.startsWith('blob:')||url.startsWith('/'))return url;
    try{const u=new URL(url,location.href);if(u.origin===location.origin)return u.href}catch(e){}
    return '/api/admin/template_asset_proxy?url='+encodeURIComponent(url);
  }

  function fileToDataURL(file){return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result||''));r.onerror=()=>reject(new Error('圖片讀取失敗'));r.readAsDataURL(file)})}
  function loadImageElement(src){return new Promise((resolve,reject)=>{const img=new Image();const timer=setTimeout(()=>{img.src='';reject(new Error('圖片載入逾時'))},15000);img.onload=()=>{clearTimeout(timer);resolve(img)};img.onerror=()=>{clearTimeout(timer);reject(new Error('圖片載入失敗'))};img.src=src})}

  function ensureCss(){
    if(document.getElementById('bf-tpl-v2-css'))return;
    const s=document.createElement('style');s.id='bf-tpl-v2-css';s.textContent=`
      #template-modal .box.wide{width:min(1120px,98vw)}
      #bf-tpl-tools{margin-top:12px;border:1px solid #f0dfe5;border-radius:16px;background:#fff9fb;padding:12px}
      .bf-tpl-panel{display:none;margin-top:10px;border:1px solid #efdce3;border-radius:14px;background:#fff;padding:12px}
      .bf-tpl-panel.show{display:block}.bf-tpl-panel-head{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:10px}.bf-tpl-panel-head b{color:#d95580}
      .bf-tpl-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px}.bf-tpl-field label{display:block;font-size:11px;font-weight:850;color:#766a70;margin-bottom:4px}.bf-tpl-field input,.bf-tpl-field select{width:100%;border:1px solid #eadce1;border-radius:10px;padding:8px;background:#fff}.bf-tpl-checks{display:flex;gap:13px;flex-wrap:wrap;align-items:center;margin:10px 0}.bf-tpl-checks label{font-size:12px;font-weight:800}.bf-tpl-presets{display:flex;gap:7px;flex-wrap:wrap;margin:8px 0 10px}
      #bf-tpl-sticker-cats{display:flex;gap:6px;overflow:auto;padding-bottom:8px}#bf-tpl-sticker-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px;max-height:280px;overflow:auto}.bf-tpl-sticker{border:1px solid #f0dfe5;background:#fffafb;border-radius:12px;aspect-ratio:1;padding:6px;cursor:pointer}.bf-tpl-sticker img{width:100%;height:100%;object-fit:contain}.bf-tpl-status{font-size:11px;color:#91848a;margin-top:8px}.bf-tpl-saving{opacity:.65;pointer-events:none}
      @media(max-width:800px){.bf-tpl-grid{grid-template-columns:repeat(2,minmax(0,1fr))}#bf-tpl-sticker-grid{grid-template-columns:repeat(4,minmax(0,1fr))}#template-modal .editor{height:430px}}
    `;document.head.appendChild(s);
  }

  function ensureUi(){
    ensureCss();
    const modal=document.getElementById('template-modal');if(!modal)return;
    const toolbar=modal.querySelector('.toolbar');if(!toolbar||document.getElementById('bf-tpl-tools'))return;
    const removeBg=document.createElement('button');removeBg.className='btn alt mini';removeBg.innerHTML='<i class="fa-solid fa-eraser"></i> 移除底圖';removeBg.onclick=removeTemplateBg;toolbar.appendChild(removeBg);
    const wrap=document.createElement('div');wrap.id='bf-tpl-tools';
    wrap.innerHTML=`
      <div id="bf-tpl-text-panel" class="bf-tpl-panel">
        <div class="bf-tpl-panel-head"><b>文字設定</b><button class="btn alt mini" id="bf-tpl-text-close">收起</button></div>
        <div class="bf-tpl-grid">
          <div class="bf-tpl-field" style="grid-column:span 2"><label>文字內容</label><input id="bf-tpl-text" value="輸入文字"></div>
          <div class="bf-tpl-field"><label>字體</label><select id="bf-tpl-font"><option value="PingFang TC">蘋方黑體</option><option value="Noto Sans TC">思源黑體</option><option value="Noto Serif TC">思源明體</option><option value="Arial">Arial</option><option value="serif">明體</option><option value="cursive">手寫風</option></select></div>
          <div class="bf-tpl-field"><label>大小</label><input id="bf-tpl-size" type="number" min="8" max="180" value="28"></div>
          <div class="bf-tpl-field"><label>粗細</label><select id="bf-tpl-weight"><option value="400">一般</option><option value="600">中粗</option><option value="700">粗體</option><option value="900">特粗</option></select></div>
          <div class="bf-tpl-field"><label>對齊</label><select id="bf-tpl-align"><option value="left">靠左</option><option value="center">置中</option><option value="right">靠右</option></select></div>
          <div class="bf-tpl-field"><label>文字顏色</label><input id="bf-tpl-color" type="color" value="#333333"></div>
          <div class="bf-tpl-field"><label>描邊顏色</label><input id="bf-tpl-stroke" type="color" value="#ffffff"></div>
          <div class="bf-tpl-field"><label>描邊粗細</label><input id="bf-tpl-stroke-width" type="number" min="0" max="10" step="0.5" value="0"></div>
          <div class="bf-tpl-field"><label>透明度 %</label><input id="bf-tpl-opacity" type="number" min="10" max="100" value="100"></div>
          <div class="bf-tpl-field"><label>陰影模糊</label><input id="bf-tpl-shadow-blur" type="number" min="0" max="30" value="6"></div>
          <div class="bf-tpl-field"><label>陰影 X</label><input id="bf-tpl-shadow-x" type="number" min="-30" max="30" value="2"></div>
          <div class="bf-tpl-field"><label>陰影 Y</label><input id="bf-tpl-shadow-y" type="number" min="-30" max="30" value="3"></div>
        </div>
        <div class="bf-tpl-checks"><label><input id="bf-tpl-italic" type="checkbox"> 斜體</label><label><input id="bf-tpl-underline" type="checkbox"> 底線</label><label><input id="bf-tpl-shadow" type="checkbox"> 陰影</label></div>
        <div class="bf-tpl-presets"><button class="btn alt mini" data-bf-preset="basic">基本</button><button class="btn alt mini" data-bf-preset="bold">粗體</button><button class="btn alt mini" data-bf-preset="outline">白框</button><button class="btn alt mini" data-bf-preset="shadow">陰影</button><button class="btn alt mini" data-bf-preset="hand">手寫</button></div>
        <button class="btn" id="bf-tpl-apply-text">套用文字設定</button>
      </div>
      <div id="bf-tpl-sticker-panel" class="bf-tpl-panel">
        <div class="bf-tpl-panel-head"><b>選擇貼紙</b><button class="btn alt mini" id="bf-tpl-sticker-close">收起</button></div>
        <div id="bf-tpl-sticker-cats"></div><div id="bf-tpl-sticker-grid"></div>
      </div>
      <div class="bf-tpl-status" id="bf-tpl-status">提示：底圖、貼紙、文字都會一起儲存並套用到所有手機型號。</div>`;
    toolbar.insertAdjacentElement('afterend',wrap);
    document.getElementById('bf-tpl-text-close').onclick=()=>showPanel('');
    document.getElementById('bf-tpl-sticker-close').onclick=()=>showPanel('');
    document.getElementById('bf-tpl-apply-text').onclick=applyTextControls;
    wrap.querySelectorAll('[data-bf-preset]').forEach(b=>b.onclick=()=>applyPreset(b.dataset.bfPreset));
  }

  function showPanel(which){ensureUi();document.getElementById('bf-tpl-text-panel')?.classList.toggle('show',which==='text');document.getElementById('bf-tpl-sticker-panel')?.classList.toggle('show',which==='sticker')}
  function setStatus(msg){const e=document.getElementById('bf-tpl-status');if(e)e.textContent=msg}

  function hookCanvas(){
    if(!visualCanvas)return;
    const sync=()=>syncTextControls(visualCanvas.getActiveObject());
    visualCanvas.on('selection:created',sync);visualCanvas.on('selection:updated',sync);visualCanvas.on('selection:cleared',()=>{});
  }

  function syncTextControls(o){
    if(!isText(o))return;
    showPanel('text');
    const set=(id,v)=>{const e=document.getElementById(id);if(e)e.value=v};
    set('bf-tpl-text',o.text||'');set('bf-tpl-font',o.fontFamily||'PingFang TC');set('bf-tpl-size',Math.round(Number(o.fontSize)||28));set('bf-tpl-weight',String(o.fontWeight||400));set('bf-tpl-align',o.textAlign||'left');set('bf-tpl-color',o.fill||'#333333');set('bf-tpl-stroke',o.stroke||'#ffffff');set('bf-tpl-stroke-width',Number(o.strokeWidth)||0);set('bf-tpl-opacity',Math.round((Number(o.opacity)||1)*100));
    const sh=o.shadow||{};set('bf-tpl-shadow-blur',Number(sh.blur)||6);set('bf-tpl-shadow-x',Number(sh.offsetX)||2);set('bf-tpl-shadow-y',Number(sh.offsetY)||3);
    const chk=(id,v)=>{const e=document.getElementById(id);if(e)e.checked=!!v};chk('bf-tpl-italic',o.fontStyle==='italic');chk('bf-tpl-underline',o.underline);chk('bf-tpl-shadow',!!o.shadow);
  }

  function readTextSettings(){
    const v=id=>document.getElementById(id)?.value;
    const c=id=>!!document.getElementById(id)?.checked;
    const shadow=c('bf-tpl-shadow')?new fabric.Shadow({color:'rgba(0,0,0,.32)',blur:Number(v('bf-tpl-shadow-blur'))||6,offsetX:Number(v('bf-tpl-shadow-x'))||0,offsetY:Number(v('bf-tpl-shadow-y'))||0}):null;
    return {text:v('bf-tpl-text')||'文字',fontFamily:v('bf-tpl-font')||'PingFang TC',fontSize:Number(v('bf-tpl-size'))||28,fontWeight:v('bf-tpl-weight')||'400',textAlign:v('bf-tpl-align')||'left',fill:v('bf-tpl-color')||'#333333',stroke:Number(v('bf-tpl-stroke-width'))>0?(v('bf-tpl-stroke')||'#ffffff'):null,strokeWidth:Number(v('bf-tpl-stroke-width'))||0,opacity:Math.max(.1,Math.min(1,(Number(v('bf-tpl-opacity'))||100)/100)),fontStyle:c('bf-tpl-italic')?'italic':'normal',underline:c('bf-tpl-underline'),shadow};
  }

  function applyTextControls(){
    if(!visualCanvas)return;
    let o=visualCanvas.getActiveObject();
    if(!isText(o)){o=new fabric.Textbox('輸入文字',{left:tplW/2,top:tplH/2,originX:'center',originY:'center',width:Math.max(90,tplW*.65)});visualCanvas.add(o);visualCanvas.setActiveObject(o)}
    const s=readTextSettings();o.set(s);o.set({text:s.text});o.setCoords();visualCanvas.requestRenderAll();setStatus('文字設定已套用');
  }

  function applyPreset(p){
    const by=id=>document.getElementById(id);
    if(p==='basic'){by('bf-tpl-font').value='PingFang TC';by('bf-tpl-weight').value='400';by('bf-tpl-stroke-width').value='0';by('bf-tpl-shadow').checked=false;by('bf-tpl-italic').checked=false}
    if(p==='bold'){by('bf-tpl-weight').value='900';by('bf-tpl-stroke-width').value='0';by('bf-tpl-shadow').checked=false}
    if(p==='outline'){by('bf-tpl-weight').value='900';by('bf-tpl-stroke').value='#ffffff';by('bf-tpl-stroke-width').value='2';by('bf-tpl-shadow').checked=false}
    if(p==='shadow'){by('bf-tpl-weight').value='700';by('bf-tpl-shadow').checked=true;by('bf-tpl-shadow-blur').value='8';by('bf-tpl-shadow-x').value='2';by('bf-tpl-shadow-y').value='3'}
    if(p==='hand'){by('bf-tpl-font').value='cursive';by('bf-tpl-weight').value='700';by('bf-tpl-italic').checked=false}
    applyTextControls();
  }

  window.addText=function(){
    if(!visualCanvas)return;
    ensureUi();showPanel('text');
    const o=new fabric.Textbox('輸入文字',{left:tplW/2,top:tplH/2,originX:'center',originY:'center',width:Math.max(90,tplW*.65),fontSize:28,fontFamily:'PingFang TC',fill:'#333',fontWeight:'700',textAlign:'center'});visualCanvas.add(o);visualCanvas.setActiveObject(o);syncTextControls(o);visualCanvas.requestRenderAll();
  };

  async function addStickerItem(s){
    if(!visualCanvas||!s?.url)return;
    try{setStatus('貼紙載入中…');const el=await loadImageElement(proxyUrl(s.url));const img=new fabric.Image(el,{left:tplW/2,top:tplH/2,originX:'center',originY:'center'});img.publicSrc=s.url;img.stickerId=s.id||'';img.scaleToWidth(Math.min(90,Math.max(55,tplW*.28)));visualCanvas.add(img);visualCanvas.setActiveObject(img);visualCanvas.requestRenderAll();showPanel('');setStatus('貼紙已加入，可以直接拖曳縮放')}
    catch(e){console.error(e);alert('貼紙載入失敗：'+e.message)}
  }

  function renderStickerPicker(cat='全部'){
    const cats=['全部',...(assetsData.categories||[]).filter((x,i,a)=>x&&x!=='全部'&&a.indexOf(x)===i)];
    const cb=document.getElementById('bf-tpl-sticker-cats'),gb=document.getElementById('bf-tpl-sticker-grid');if(!cb||!gb)return;
    cb.innerHTML='';cats.forEach(c=>{const b=document.createElement('button');b.className='pill'+(c===cat?' active':'');b.textContent=c;b.onclick=()=>renderStickerPicker(c);cb.appendChild(b)});
    const list=(assetsData.stickers||[]).filter(s=>cat==='全部'||s.category===cat);gb.innerHTML='';list.slice(0,120).forEach(s=>{const b=document.createElement('button');b.className='bf-tpl-sticker';const img=document.createElement('img');img.loading='lazy';img.decoding='async';img.src=s.url||'';b.appendChild(img);b.onclick=()=>addStickerItem(s);gb.appendChild(b)});if(!list.length)gb.innerHTML='<div class="empty" style="grid-column:1/-1">這個分類沒有貼紙</div>';
  }

  window.pickSticker=async function(){
    try{await loadAssets();ensureUi();showPanel('sticker');renderStickerPicker('全部')}catch(e){alert(e.message||'貼紙庫載入失敗')}
  };

  async function addBackgroundFromSource(src,publicSrc){
    const el=await loadImageElement(src);const img=new fabric.Image(el);const sc=Math.max(tplW/(img.width||1),tplH/(img.height||1));img.set({left:tplW/2,top:tplH/2,originX:'center',originY:'center',scaleX:sc,scaleY:sc,selectable:false,evented:false,isTplBg:true});img.publicSrc=publicSrc||'';visualCanvas.getObjects().filter(o=>o.isTplBg).forEach(o=>visualCanvas.remove(o));visualCanvas.add(img);visualCanvas.sendToBack(img);visualCanvas.requestRenderAll();return img;
  }

  window.uploadTemplateBg=async function(e){
    const f=e.target.files?.[0];if(!f||!visualCanvas)return;
    try{setStatus('底圖上傳中…');const local=await fileToDataURL(f);const url=await uploadAdminImage(f,'template');await addBackgroundFromSource(local,url);setStatus('底圖已加入')}
    catch(err){console.error(err);alert('底圖加入失敗：'+(err.message||err))}
    finally{e.target.value=''}
  };

  function removeTemplateBg(){if(!visualCanvas)return;visualCanvas.getObjects().filter(o=>o.isTplBg).forEach(o=>visualCanvas.remove(o));visualCanvas.requestRenderAll();setStatus('底圖已移除')}

  function prepareObjectsForEditor(objectsJson){
    let raw=objectsJson;if(typeof raw==='string'){try{raw=JSON.parse(raw)}catch(e){return null}}if(!raw)return null;raw=clone(raw);(raw.objects||[]).forEach(o=>{if(o&&o.src){const pub=o.publicSrc||o.src;o.publicSrc=pub;if(!String(pub).startsWith('data:')&&!String(pub).startsWith('blob:'))o.src=proxyUrl(pub);delete o.crossOrigin}});return raw;
  }

  window.initEditor=function(slots=[],objectsJson=null,fallback=''){
    ensureUi();if(!window.fabric)return;const id=$('tpl-model').value;if(!id)return;const m=shopData.models.find(x=>x.id===id);const w=Number(m?.print_w)||80,h=Number(m?.print_h)||160;tplW=w*VISUAL_SCALE;tplH=h*VISUAL_SCALE;$('canvas-wrap').style.width=tplW+'px';$('canvas-wrap').style.height=tplH+'px';if(visualCanvas){visualCanvas.dispose();visualCanvas=null}$('tpl-canvas').width=tplW;$('tpl-canvas').height=tplH;visualCanvas=new fabric.Canvas('tpl-canvas',{width:tplW,height:tplH,backgroundColor:'#fff',preserveObjectStacking:true});hookCanvas();
    const draw=()=>drawSlots(slots||[]);const prepared=prepareObjectsForEditor(objectsJson);
    if(prepared&&Array.isArray(prepared.objects)&&prepared.objects.length){visualCanvas.loadFromJSON(prepared,()=>{visualCanvas.getObjects().forEach(o=>{if(o.isTplBg){o.selectable=false;o.evented=false;visualCanvas.sendToBack(o)}});draw();visualCanvas.renderAll();setStatus('模板內容已載入')});return}
    if(fallback){addBackgroundFromSource(proxyUrl(fallback),fallback).then(()=>{draw();setStatus('模板底圖已載入')}).catch(err=>{console.error(err);draw();setStatus('底圖讀取失敗，請重新上傳')});return}draw();
  };

  function dataUrlToFile(dataUrl,name){const parts=dataUrl.split(',');const mime=(parts[0].match(/data:([^;]+)/)||[])[1]||'image/png';const bin=atob(parts[1]||'');const bytes=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)bytes[i]=bin.charCodeAt(i);return new File([bytes],name,{type:mime})}

  function serializedObjects(){
    const obj=visualCanvas.toJSON(['isSlot','isTplBg','slotId','publicSrc','stickerId']);obj.objects=(obj.objects||[]).filter(o=>!o.isSlot);obj.objects.forEach(o=>{if(o.publicSrc){o.src=o.publicSrc;delete o.crossOrigin}});return obj;
  }

  window.saveTemplate=async function(){
    if(saving)return;const id=$('tpl-id').value,name=$('tpl-name').value.trim(),category=$('tpl-category').value.trim()||'熱門',reference_model_id=$('tpl-model').value;if(!name||!reference_model_id||!visualCanvas)return alert('請填模板名稱並選擇設計基準型號');
    const ref=(shopData.models||[]).find(x=>x.id===reference_model_id);const sourcePrintW=Number(ref?.print_w)||80,sourcePrintH=Number(ref?.print_h)||160;const slots=[],slotObjs=[];visualCanvas.getObjects().forEach(o=>{if(o.isSlot){slots.push({id:o.slotId||'slot_'+Date.now(),x:o.left/VISUAL_SCALE,y:o.top/VISUAL_SCALE,w:o.width*o.scaleX/VISUAL_SCALE,h:o.height*o.scaleY/VISUAL_SCALE});slotObjs.push(o)}});
    const saveBtn=[...document.querySelectorAll('#template-modal .mf .btn')].find(b=>b.textContent.includes('儲存'));const oldBtn=saveBtn?.innerHTML;saving=true;if(saveBtn){saveBtn.disabled=true;saveBtn.classList.add('bf-tpl-saving');saveBtn.innerHTML='<i class="fa-solid fa-spinner fa-spin"></i> 儲存中'}
    try{
      visualCanvas.discardActiveObject();slotObjs.forEach(o=>o.set('opacity',0));visualCanvas.renderAll();let dataUrl;try{dataUrl=visualCanvas.toDataURL({format:'png',multiplier:2})}finally{slotObjs.forEach(o=>o.set('opacity',1));visualCanvas.renderAll()}
      if(!dataUrl||!dataUrl.startsWith('data:image/png'))throw new Error('預覽圖輸出失敗');
      const objects=serializedObjects();setStatus('上傳模板預覽中…');const thumbUrl=await uploadAdminImage(dataUrlToFile(dataUrl,'template.png'),'template');
      const data={id:id||'tpl_'+Date.now(),name,category,universal:true,template_version:3,model_id:'*',reference_model_id,source_print_w:sourcePrintW,source_print_h:sourcePrintH,source_canvas_w:tplW,source_canvas_h:tplH,thumb_url:thumbUrl,slots,objects_json:objects};
      const next=clone(templatesData||{templates:[],categories:['全部','熱門']});next.templates=Array.isArray(next.templates)?next.templates:[];const idx=next.templates.findIndex(x=>x.id===data.id);if(idx>=0)next.templates[idx]=data;else next.templates.push(data);next.categories=Array.isArray(next.categories)?next.categories:[];if(!next.categories.includes('全部'))next.categories.unshift('全部');if(!next.categories.includes(category))next.categories.push(category);
      setStatus('寫入模板資料中…');await apiJson('/api/admin/save_templates',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(next)});templatesData.templates=next.templates;templatesData.categories=next.categories;renderTemplateTabs();renderTemplates();closeModal('template-modal');alert('模板儲存成功（全型號通用）');
    }catch(e){console.error('[TEMPLATE SAVE]',e);alert('模板儲存失敗：'+(e.message||e));setStatus('儲存失敗，請再試一次')}
    finally{saving=false;if(saveBtn){saveBtn.disabled=false;saveBtn.classList.remove('bf-tpl-saving');saveBtn.innerHTML=oldBtn||'儲存模板'}}
  };

  function boot(){ensureUi();console.info('[ADMIN] template editor v2 enabled: reliable images + text controls + safe save')}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
