(function(){
  'use strict';
  const core=window.BenfuwanEditableSticker;if(!core)return;
  CUSTOM_PROPS.push(...core.PROPS.filter(k=>!CUSTOM_PROPS.includes(k)));
  const say=m=>typeof toast==='function'&&toast(m);
  const get=()=>typeof canvas!=='undefined'?canvas:null;
  const has=c=>c?.getObjects().some(core.isMember);
  const history=window.recordHistory;
  window.recordHistory=function(){const c=get();if(has(c))core.syncAll(c);return history.apply(this,arguments);};
  const init=window.initCanvas;
  window.initCanvas=function(){const r=init.apply(this,arguments);window.__editableFrontCanvas=get();core.bind(get());return r;};
  const hydrate=window.rehydrateCanvas;
  window.rehydrateCanvas=function(){const r=hydrate.apply(this,arguments);const c=get();if(has(c))core.rehydrate(c).catch(e=>say(e.message));return r;};
  const fonts=window.ensureCanvasFonts;
  window.ensureCanvasFonts=async function(){await fonts?.();if(has(get()))await core.rehydrate(get());};
  for(const name of ['nudgeActive','centerActive','changeAngle','changeOpacity','flipActive','commitObjectAdjustment','bringForward','sendBackward','moveToTop','moveToBottom']){
    const old=window[name];window[name]=function(){const r=old.apply(this,arguments),c=get();if(has(c)){core.syncAll(c);c.requestRenderAll();}return r;};
  }
  const duplicate=window.duplicateActive;
  window.duplicateActive=async function(){const c=get(),o=c?.getActiveObject();if(!core.isMember(o))return duplicate.apply(this,arguments);try{await core.duplicate(c,o);recordHistory();renderLayerList();}catch(e){say(e.message);}};
  const cart=window.confirmDesignToCart;
  window.confirmDesignToCart=async function(){
    if(!has(get()))return cart.apply(this,arguments);
    try{await ensureCanvasFonts();const data=await core.serialize(get(),ctx),previous=cartItem;await cart.apply(this,arguments);
      if(cartItem&&cartItem!==previous&&cartItem.printBase64===ctx.printBase64&&cartItem.modelId===ctx.modelId&&cartItem.styleId===ctx.styleId){cartItem.designJson=data;await idbSet('cart',cartItem);}
    }catch(e){say('文字貼紙無法保存：'+e.message);}
  };
  const renderCats=window.renderStickerCats;
  window.renderStickerCats=function(){renderCats.apply(this,arguments);const box=document.getElementById('sticker-cats');if(!box)return;
    const button=document.createElement('button');button.className='pill';button.textContent='文字貼紙';button.dataset.editableStickerCategory='true';
    button.onclick=()=>{box.querySelectorAll('.pill').forEach(x=>x.classList.remove('active'));button.classList.add('active');renderEditableLibrary();};box.appendChild(button);
  };
  function renderEditableLibrary(){
    const box=document.getElementById('sticker-grid');if(!box)return;box.innerHTML='';
    const list=assetsData.editable_stickers||[];
    if(!list.length){box.textContent='目前沒有文字貼紙，請店員先建立對話框';return;}
    for(const asset of list){const b=document.createElement('button');b.className='editable-sticker-choice';const img=document.createElement('img');img.alt='';img.src=asset.imageSrc;img.onerror=()=>img.hidden=true;const name=document.createElement('span');name.textContent=asset.name;b.append(img,name);
      b.onclick=async()=>{b.disabled=true;try{await core.add(get(),asset);recordHistory();renderLayerList();closeSheets();}catch(e){say(e.message);}finally{b.disabled=false;}};box.append(b);}
  }
  let selected=null;
  const dock=document.createElement('div');dock.id='editable-text-tools';dock.hidden=true;dock.className='editable-text-dock';
  dock.innerHTML='<div class="editable-text-head"><b>文字貼紙</b><button type="button" data-edit-text>編輯文字</button><button type="button" data-close>收合</button></div><form><label>內容<textarea name="text" rows="2"></textarea></label><div class="editable-fields"><label>字型<select name="fontFamily"></select></label><label>字級<input name="fontSize" type="number" min="1" max="1000"></label><label>顏色<input name="fill" type="color"></label><label>描邊色<input name="stroke" type="color"></label><label>描邊粗細<input name="strokeWidth" type="number" min="0" max="30" step=".5"></label><label>對齊<select name="textAlign"><option value="left">靠左</option><option value="center">置中</option><option value="right">靠右</option></select></label><label>字距<input name="charSpacing" type="number" min="-100" max="1000"></label><label>行距<input name="lineHeight" type="number" min=".8" max="3" step=".1"></label><label>粗體<input name="fontWeight" type="checkbox"></label><label>斜體<input name="fontStyle" type="checkbox"></label></div><button type="submit">套用文字</button><span data-message role="status"></span></form>';
  const toolbar=document.querySelector('#page-editor>.toolbar');toolbar?.before(dock);
  new MutationObserver(()=>requestAnimationFrame(()=>window.BenfuwanEditorAccess?.fitCanvas?.())).observe(dock,{attributes:true,attributeFilter:['hidden']});
  const select=dock.querySelector('[name=fontFamily]');for(const [value,item] of Object.entries(core.FONTS)){const option=document.createElement('option');option.value=value;option.textContent=item.name;select.append(option);}
  window.bfEditableSelection=(c,o)=>{
    if(c!==get()||!core.isMember(o)){dock.hidden=true;return;}selected=o;const {text}=core.pair(c,o);if(!text)return;
    dock.hidden=false;const form=dock.querySelector('form');
    for(const name of ['text','fontFamily','fontSize','fill','stroke','strokeWidth','textAlign','charSpacing','lineHeight'])form.elements[name].value=name==='fontSize'?(text.requestedFontSize||text.fontSize):(text[name]??(name==='stroke'?'#ffffff':''));
    form.elements.fontWeight.checked=String(text.fontWeight)==='700';form.elements.fontStyle.checked=text.fontStyle==='italic';
  };
  dock.querySelector('[data-close]').onclick=()=>dock.hidden=true;
  dock.querySelector('[data-edit-text]').onclick=()=>{const {text}=core.pair(get(),selected);text.__editableEntering=true;get().setActiveObject(text);text.enterEditing();text.__editableEntering=false;text.selectAll();};
  dock.querySelector('form').onsubmit=async event=>{event.preventDefault();const form=event.target,button=form.querySelector('[type=submit]'),msg=form.querySelector('[data-message]');button.disabled=true;
    const p={};for(const key of ['text','fontFamily','fill','stroke','textAlign'])p[key]=form.elements[key].value;
    for(const key of ['fontSize','strokeWidth','charSpacing','lineHeight'])p[key]=Number(form.elements[key].value);
    p.fontWeight=form.elements.fontWeight.checked?'700':'400';p.fontStyle=form.elements.fontStyle.checked?'italic':'normal';
    try{await core.update(get(),selected,p);recordHistory();msg.textContent='已更新';}catch(e){msg.textContent=e.message;}finally{button.disabled=false;}
  };
  const oldOpenText=window.openTextSheet;window.openTextSheet=function(){const o=get()?.getActiveObject();if(core.isMember(o)){window.bfEditableSelection(get(),o);return;}return oldOpenText.apply(this,arguments);};
  const css=document.createElement('link');css.rel='stylesheet';css.href='/static/editable-stickers-v1.css?v=20261006a';document.head.append(css);
})();
