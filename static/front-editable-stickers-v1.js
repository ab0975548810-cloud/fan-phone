(function(){
  'use strict';
  const core=window.BenfuwanEditableSticker;if(!core)return;
  CUSTOM_PROPS.push(...core.PROPS.filter(k=>!CUSTOM_PROPS.includes(k)));
  const say=m=>typeof toast==='function'&&toast(m);
  let fontNoticed=false;window.bfLegacyFontNotice=()=>{if(!fontNoticed){fontNoticed=true;say('舊系統字型已轉為站內固定字型，請在編輯器確認文字排版；Emoji 為固定單色。');}};
  // Explicit fixed-font choices are shown before creation, never converted at checkout.
  const fontSelect=document.getElementById('text-font');
  fontSelect?.closest('.field').classList.add('full','bf-font-field');
  for(const option of fontSelect?.options||[]){if(core.LEGACY[option.value]){option.value=core.LEGACY[option.value];option.textContent+='（站內固定字型）';}}
  if(fontSelect){
    const option=document.createElement('option');option.value='NotoSansTC';option.textContent='思源黑體・繁中推薦';fontSelect.prepend(option);fontSelect.value=option.value;
  }
  // Preserve a legacy object's exact family when opening tools; selecting a
  // preview changes only the form until the customer explicitly applies it.
  const loadText=window.loadTextControls;
  window.loadTextControls=function(o){
    if(fontSelect&&o.fontFamily&&![...fontSelect.options].some(x=>x.value===o.fontFamily)){
      const option=document.createElement('option');option.value=o.fontFamily;option.textContent='原設計字型：'+o.fontFamily;fontSelect.append(option);
    }
    return loadText.apply(this,arguments);
  };
  const previews=document.createElement('div');previews.id='bf-font-previews';previews.className='field full';previews.setAttribute('aria-label','字型效果預覽');
  fontSelect?.closest('.field').after(previews);
  let previewPromise=null;
  function refreshFontSelection(){previews.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.family===fontSelect.value)));}
  function showFontPreviews(){
    if(previewPromise){refreshFontSelection();return previewPromise;}
    const sample='本福丸 ABC 123';
    previewPromise=Promise.all([...fontSelect.options].map(async option=>{
      const button=document.createElement('button');button.type='button';button.dataset.family=option.value;button.disabled=true;
      const label=document.createElement('small');label.textContent=option.textContent;
      const text=document.createElement('span');text.textContent='字型載入中…';button.append(label,text);previews.append(button);
      button.onclick=()=>{fontSelect.value=option.value;refreshFontSelection();};
      try{
        if(core.FONTS[option.value])await core.font(option.value,sample);else await core.ordinaryFont(option.value,sample);
        text.style.fontFamily=option.value;text.textContent=sample;button.disabled=false;
      }catch(error){text.textContent='暫時無法載入';console.warn('Font preview unavailable',error);}
    }));
    refreshFontSelection();return previewPromise;
  }
  fontSelect?.addEventListener('change',refreshFontSelection);
  const previewCss=document.createElement('style');previewCss.textContent='#bf-font-previews{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}#bf-font-previews button{min-width:0;min-height:76px;border:1px solid #efdbe3;border-radius:12px;background:#fff8fb;padding:9px;text-align:left;color:#4f3742}#bf-font-previews button[aria-pressed="true"]{border:2px solid #ed5e8f;background:#fff0f6}#bf-font-previews small{display:block;font-size:11px;line-height:1.5}#bf-font-previews span{display:block;font-size:18px;line-height:1.6;overflow-wrap:anywhere}';document.head.append(previewCss);
  const fontNote=document.createElement('small');fontNote.style.cssText='display:block;font-size:11px;line-height:1.6;color:#88747d;margin-top:6px';fontNote.textContent='一般文字使用站內固定字型；Emoji 使用固定單色字型，預覽與生產一致。';fontSelect?.parentElement.append(fontNote);
  const editorFont=window.ensureEditorFont;
  window.ensureEditorFont=async function(family,text){if(core.FONTS[family])return core.font(family,text);return core.ordinaryFont(family,text);};
  const emoji=window.addEmojiSticker;
  window.addEmojiSticker=async function(value){try{await core.ordinaryFont('BF-Emoji',value);emoji(value);const o=get()?.getActiveObject();if(o){o.set('fontFamily','BF-Emoji');o.initDimensions();o.setCoords();get().requestRenderAll();recordHistory();}say('Emoji 使用站內固定單色字型');}catch(error){say(error.message);}};
  const get=()=>typeof canvas!=='undefined'?canvas:null;
  const has=c=>c?.getObjects().some(core.isMember);
  function restoreViewport(){const app=document.querySelector('.app');if(app){app.scrollTop=0;app.scrollLeft=0;}requestAnimationFrame(()=>window.BenfuwanEditorAccess?.fitCanvas?.());}
  const history=window.recordHistory;
  window.recordHistory=function(){const c=get();if(has(c))core.syncAll(c);return history.apply(this,arguments);};
  const init=window.initCanvas;
  window.initCanvas=function(){const r=init.apply(this,arguments);window.__editableFrontCanvas=get();core.bind(get());return r;};
  const hydrate=window.rehydrateCanvas;
  window.rehydrateCanvas=function(){const r=hydrate.apply(this,arguments);const c=get();if(has(c))core.rehydrate(c).catch(e=>say(e.message));return r;};
  const fonts=window.ensureCanvasFonts;
  window.ensureCanvasFonts=async function(){await fonts?.();if(get()){await core.textFonts(get());if(has(get()))await core.rehydrate(get());}};
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
      b.onclick=async()=>{b.blur();b.disabled=true;try{await core.add(get(),asset);recordHistory();renderLayerList();closeSheets();restoreViewport();}catch(e){say(e.message);}finally{b.disabled=false;}};box.append(b);}
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
    restoreViewport();
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
  const oldOpenText=window.openTextSheet;window.openTextSheet=function(){const o=get()?.getActiveObject();if(core.isMember(o)){window.bfEditableSelection(get(),o);return;}if(!o||!['text','textbox','i-text'].includes(o.type))fontSelect.value='NotoSansTC';const result=oldOpenText.apply(this,arguments);showFontPreviews();return result;};
  const css=document.createElement('link');css.rel='stylesheet';css.href='/static/editable-stickers-v1.css?v=20261006a';document.head.append(css);
})();
