/* 本福丸前台：依「手機型號 + 殼款」顯示可選顏色 */
(function(){
  'use strict';
  if(window.__benfuwanModelColorsFrontInstalled)return;
  window.__benfuwanModelColorsFrontInstalled=true;

  const cleanList=v=>{
    const arr=Array.isArray(v)?v:String(v||'').split(/[,，]/);
    const out=[];
    arr.map(x=>String(x||'').trim()).filter(Boolean).forEach(x=>{if(!out.includes(x))out.push(x)});
    return out;
  };
  const colorDot=name=>{
    const n=String(name||'').toLowerCase();
    const map=[
      [['白','white','透明'],'#f7f7f7'],[['黑','black'],'#252525'],[['粉','pink'],'#f5a9c2'],[['紅','red'],'#e95b62'],
      [['藍','blue'],'#6aaee8'],[['紫','purple'],'#a887d8'],[['綠','green'],'#7fc59b'],[['黃','yellow'],'#f1d66f'],
      [['橘','orange'],'#efa45c'],[['灰','gray','grey'],'#999999'],[['咖','棕','brown'],'#9b745e'],[['銀','silver'],'#c9c9c9'],[['金','gold'],'#d9b568']
    ];
    for(const [keys,c] of map)if(keys.some(k=>n.includes(k)))return c;
    return '#ffd9e5';
  };
  function colorsFor(style,modelId){
    if(!style)return [];
    const map=(style.model_colors&&typeof style.model_colors==='object')?style.model_colors:{};
    const override=cleanList(map[modelId]||[]);
    return override.length?override:cleanList(style.colors||[]);
  }
  function currentStyle(){return (shopData.styles||[]).find(s=>String(s.id)===String(ctx.styleId))||null}

  function ensureStyles(){
    if(document.getElementById('bf-front-color-style'))return;
    const s=document.createElement('style');s.id='bf-front-color-style';
    s.textContent=`
      .bf-style-color-summary{font-size:10px;color:#978b90;margin-top:5px;line-height:1.35;min-height:14px}
      .bf-color-panel{margin:2px 14px 16px;padding:13px;background:#fff;border:1px solid var(--line);border-radius:18px;box-shadow:0 5px 16px rgba(120,75,90,.05)}
      .bf-color-panel.hidden{display:none}.bf-color-title{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:9px;font-size:12px;font-weight:900}
      .bf-color-title small{font-size:10px;color:#9a8e94;font-weight:600}.bf-color-options{display:flex;gap:8px;flex-wrap:wrap}
      .bf-color-chip{border:1px solid #eadce1;background:#fff;border-radius:999px;padding:8px 11px;font-size:12px;font-weight:850;color:#60565b;display:flex;align-items:center;gap:7px}
      .bf-color-chip.active{border-color:var(--pink);background:var(--pink-soft);color:var(--pink-dark);box-shadow:0 0 0 2px rgba(255,111,154,.08)}
      .bf-color-dot{width:15px;height:15px;border-radius:50%;border:1px solid rgba(0,0,0,.13);box-shadow:inset 0 0 0 1px rgba(255,255,255,.5)}
      .bf-color-required{font-size:10px;color:#d95c7f;margin-top:8px}.style-grid.bf-color-open{padding-bottom:10px}
    `;
    document.head.appendChild(s);
  }

  function ensurePanel(){
    ensureStyles();
    let panel=document.getElementById('bf-color-panel');
    if(panel)return panel;
    const grid=document.getElementById('style-grid');
    if(!grid)return null;
    panel=document.createElement('div');panel.id='bf-color-panel';panel.className='bf-color-panel hidden';
    panel.innerHTML='<div class="bf-color-title"><span><i class="fa-solid fa-palette"></i> 選擇手機殼顏色</span><small id="bf-color-model-note"></small></div><div class="bf-color-options" id="bf-color-options"></div><div class="bf-color-required" id="bf-color-required"></div>';
    grid.insertAdjacentElement('afterend',panel);
    return panel;
  }

  function hidePanel(){const p=ensurePanel();p?.classList.add('hidden');document.getElementById('style-grid')?.classList.remove('bf-color-open')}
  function chooseColor(name){ctx.colorName=String(name||'');renderColorPanel(currentStyle());const next=document.getElementById('style-next');if(next)next.disabled=false}
  window.chooseCaseColor=chooseColor;

  function renderColorPanel(style){
    const panel=ensurePanel();if(!panel)return;
    if(!style){hidePanel();return}
    const colors=colorsFor(style,ctx.modelId);
    const options=document.getElementById('bf-color-options'),req=document.getElementById('bf-color-required'),note=document.getElementById('bf-color-model-note');
    if(note)note.textContent=ctx.modelName||'';
    if(!colors.length){
      panel.classList.remove('hidden');document.getElementById('style-grid')?.classList.add('bf-color-open');
      options.innerHTML='<span style="font-size:12px;color:#8f8489">此款不分顏色</span>';req.textContent='';
      ctx.colorName='';const next=document.getElementById('style-next');if(next)next.disabled=false;return;
    }
    panel.classList.remove('hidden');document.getElementById('style-grid')?.classList.add('bf-color-open');
    options.innerHTML='';
    colors.forEach(c=>{
      const b=document.createElement('button');b.type='button';b.className='bf-color-chip'+(ctx.colorName===c?' active':'');
      b.innerHTML=`<span class="bf-color-dot" style="background:${colorDot(c)}"></span><span>${escapeHtml(c)}</span>`;
      b.onclick=()=>chooseColor(c);options.appendChild(b);
    });
    if(colors.length===1&&!ctx.colorName)ctx.colorName=colors[0];
    if(colors.length===1){
      options.querySelector('.bf-color-chip')?.classList.add('active');req.textContent='';const next=document.getElementById('style-next');if(next)next.disabled=false;
    }else{
      req.textContent=ctx.colorName?'已選擇：'+ctx.colorName:'請先選擇一個顏色，再進入下一步。';
      const next=document.getElementById('style-next');if(next)next.disabled=!ctx.colorName;
    }
  }

  const originalRenderStyles=window.renderStyles;
  if(typeof originalRenderStyles==='function'){
    window.renderStyles=function(){
      originalRenderStyles();
      const styles=(shopData.styles||[]).filter(s=>s.status!==false);
      const cards=[...document.querySelectorAll('#style-grid .style-card')];
      cards.forEach((card,i)=>{
        const s=styles[i];if(!s)return;
        const colors=colorsFor(s,ctx.modelId);
        let label='不分顏色';
        if(colors.length){label='可選：'+colors.slice(0,4).join('、')+(colors.length>4?` 等 ${colors.length} 色`:'')}
        const d=document.createElement('div');d.className='bf-style-color-summary';d.textContent=label;card.appendChild(d);
      });
    };
  }

  const originalSelectModel=window.selectModel;
  if(typeof originalSelectModel==='function'){
    window.selectModel=function(m){ctx.colorName='';originalSelectModel(m);hidePanel()};
  }

  const originalSelectStyle=window.selectStyle;
  if(typeof originalSelectStyle==='function'){
    window.selectStyle=function(s){
      ctx.colorName='';
      originalSelectStyle(s);
      const colors=colorsFor(s,ctx.modelId);
      if(colors.length===1)ctx.colorName=colors[0];
      renderColorPanel(s);
    };
  }

  const originalStartEditor=window.startEditor;
  if(typeof originalStartEditor==='function'){
    window.startEditor=function(applyTemplateNow){
      const s=currentStyle(),colors=colorsFor(s,ctx.modelId);
      if(colors.length>1&&!ctx.colorName){toast('請先選擇手機殼顏色');navigate('page-style');renderColorPanel(s);return}
      originalStartEditor(applyTemplateNow);
      const badge=document.getElementById('editor-style');
      if(badge)badge.textContent=(ctx.styleName||'')+(ctx.colorName?'・'+ctx.colorName:'');
    };
  }

  const originalOpenPreview=window.openPreview;
  if(typeof originalOpenPreview==='function'){
    window.openPreview=function(){
      originalOpenPreview();
      setTimeout(()=>{const title=document.getElementById('preview-title');if(title&&ctx.colorName)title.textContent=`${ctx.modelName||''}・${ctx.styleName||''}・${ctx.colorName}`},80);
    };
  }

  const originalConfirm=window.confirmDesignToCart;
  if(typeof originalConfirm==='function'){
    window.confirmDesignToCart=async function(){
      const s=currentStyle(),colors=colorsFor(s,ctx.modelId);
      if(colors.length>1&&!ctx.colorName){toast('請先選擇手機殼顏色');navigate('page-style');renderColorPanel(s);return}
      await originalConfirm();
      if(cartItem){cartItem.colorName=ctx.colorName||'';await idbSet('cart',cartItem);renderCart()}
    };
  }

  const originalRenderCart=window.renderCart;
  if(typeof originalRenderCart==='function'){
    window.renderCart=function(){
      originalRenderCart();
      if(!cartItem)return;
      const c=cartItem.colorName||'';
      const desc=document.getElementById('cart-desc');
      if(desc&&c)desc.innerHTML=`${escapeHtml(cartItem.modelName||'')}<br>${escapeHtml(cartItem.styleName||'')}<br><b style="color:var(--pink-dark)">顏色：${escapeHtml(c)}</b>`;
      const item=document.getElementById('checkout-item');if(item&&c)item.textContent=`${cartItem.modelName||''} / ${cartItem.styleName||''} / ${c}`;
    };
  }

  // 不改原本結帳函式，只在送 /api/create_order 時把選到的顏色一起帶給後端。
  const nativeFetch=window.fetch.bind(window);
  window.fetch=function(input,init){
    try{
      const url=typeof input==='string'?input:(input?.url||'');
      if(url==='/api/create_order'&&init&&typeof init.body==='string'){
        const body=JSON.parse(init.body);const c=cartItem?.colorName||ctx.colorName||'';
        if(c)body.color_name=c;
        init={...init,body:JSON.stringify(body)};
      }
    }catch(e){console.warn('[COLOR] order payload patch skipped',e)}
    return nativeFetch(input,init);
  };

  const originalReset=window.resetDesignState;
  if(typeof originalReset==='function')window.resetDesignState=function(clearCanvas=true){originalReset(clearCanvas);ctx.colorName='';hidePanel()};

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ensurePanel,{once:true});else ensurePanel();
  console.info('[FRONT] model-specific case colors enabled');
})();
