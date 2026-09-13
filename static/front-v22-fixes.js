/* 本福丸前台體驗修正 2026-09-13：圖層辨識 + 觸控拖曳排序 + 手機殼預覽恢復 */
(function(){
  'use strict';

  const roleLabel={photo:'照片','slot-photo':'模板照片',sticker:'貼紙',material:'素材',text:'文字','template-text':'模板文字','template-sticker':'模板貼紙','template-bg':'模板背景'};
  const materialLabel={circle:'圓形',rect:'方形',triangle:'三角形',heart:'愛心',star:'星星',frame:'相框',line:'線條',speech:'對話框',sparkle:'閃亮裝飾'};

  function shortName(v,max=14){const s=String(v||'').replace(/\.[^.]+$/,'').replace(/\s+/g,' ').trim();return !s?'':(s.length>max?s.slice(0,max)+'…':s)}
  function shortText(v,max=12){const s=String(v||'').replace(/\s+/g,' ').trim();return !s?'':(s.length>max?s.slice(0,max)+'…':s)}
  function displayLayerName(o,n){
    const base=roleLabel[o.role]||'物件';
    if(o.role==='template-bg')return base;
    let detail='';
    if(o.role==='photo')detail=shortName(o.originalName);
    else if(o.role==='slot-photo')detail=o.slotId?('照片框 '+n):'';
    else if(o.role==='text'||o.role==='template-text')detail=shortText(o.text);
    else if((o.role==='sticker'||o.role==='template-sticker')&&o.type!=='image')detail=shortText(o.text,6);
    else if(o.role==='material')detail=materialLabel[o.materialType]||'';
    return `${base} ${n}${detail?'・'+detail:''}`;
  }
  function fillThumb(el,o){
    el.innerHTML='';
    if(o.type==='image'){
      try{const src=o.getSrc?.()||o._element?.src||'';if(src){const img=document.createElement('img');img.src=src;img.alt='';img.style.cssText='width:100%;height:100%;object-fit:cover;border-radius:9px;display:block';el.appendChild(img);return}}catch(e){}
    }
    if(o.type==='text'||o.type==='textbox'){const t=document.createElement('span');t.textContent=shortText(o.text,2)||'T';t.style.cssText='font-weight:900;font-size:14px';el.appendChild(t);return}
    const i=document.createElement('i');i.className=o.role==='material'?'fa-solid fa-shapes':'fa-solid fa-layer-group';el.appendChild(i);
  }

  function ensureLayerDragStyles(){
    if(document.getElementById('benfuwan-layer-drag-style'))return;
    const style=document.createElement('style');style.id='benfuwan-layer-drag-style';
    style.textContent=`
      .layer-drag-help{padding:3px 4px 11px;color:#9a8f94;font-size:10px;display:flex;align-items:center;gap:6px}
      .layer-row{transition:box-shadow .12s ease,transform .12s ease,opacity .12s ease;background:#fff;position:relative}
      .layer-row.layer-dragging{opacity:.86;box-shadow:0 10px 25px rgba(80,45,58,.2);transform:scale(1.015);z-index:20;background:#fff8fb}
      .layer-drag-handle{width:40px!important;height:40px!important;flex:0 0 40px;border:0!important;background:#fff0f5!important;color:#f45f8d!important;border-radius:11px!important;display:grid!important;place-items:center!important;touch-action:none!important;-webkit-touch-callout:none!important;-webkit-user-select:none!important;user-select:none!important;cursor:grab;font-size:17px!important}
      .layer-drag-handle:active{cursor:grabbing;background:#ffe0eb!important}
      .layer-drag-handle.locked{color:#c8bec2!important;background:#f7f4f5!important;cursor:default}
      .layer-drop-line{height:3px;background:#ff6f9a;border-radius:999px;margin:0 4px;pointer-events:none}
      body.layer-sorting,body.layer-sorting *{-webkit-user-select:none!important;user-select:none!important}
    `;
    document.head.appendChild(style);
  }

  function isLayerObject(o){return o&&!['guide','slot-guide'].includes(o.role)}
  function applyLayerOrderFromDom(box){
    if(typeof canvas==='undefined'||!canvas)return;
    const rows=[...box.querySelectorAll('.layer-row')];
    const topToBottom=rows.map(r=>r._layerObject).filter(Boolean);
    if(!topToBottom.length)return;
    const bg=topToBottom.filter(o=>o.role==='template-bg');
    const movable=topToBottom.filter(o=>o.role!=='template-bg');
    const desiredBottomToTop=[...bg,...[...movable].reverse()];
    const oldAll=[...canvas.getObjects()];
    const layerSlots=oldAll.map((o,i)=>isLayerObject(o)?i:-1).filter(i=>i>=0);
    if(layerSlots.length!==desiredBottomToTop.length)return;
    const rebuilt=[...oldAll];
    layerSlots.forEach((slot,i)=>{rebuilt[slot]=desiredBottomToTop[i]});
    if(Array.isArray(canvas._objects)){
      canvas._objects.splice(0,canvas._objects.length,...rebuilt);
      canvas.renderAll();
      if(typeof recordHistory==='function')recordHistory();
    }
  }

  function moveDraggedRow(row,box,y,scrollArea){
    const bgRow=[...box.querySelectorAll('.layer-row')].find(r=>r._layerObject?.role==='template-bg');
    const others=[...box.querySelectorAll('.layer-row')].filter(r=>r!==row&&r._layerObject?.role!=='template-bg');
    let placed=false;
    for(const other of others){
      const rect=other.getBoundingClientRect();
      if(y<rect.top+rect.height/2){box.insertBefore(row,other);placed=true;break}
    }
    if(!placed){if(bgRow&&bgRow!==row)box.insertBefore(row,bgRow);else box.appendChild(row)}
    if(scrollArea){
      const r=scrollArea.getBoundingClientRect();
      if(y<r.top+60)scrollArea.scrollTop-=22;
      else if(y>r.bottom-60)scrollArea.scrollTop+=22;
    }
  }

  function bindDragHandle(handle,row,box,o){
    if(o.role==='template-bg'){handle.classList.add('locked');handle.title='模板背景固定在最下層';return}
    handle.title='按住並上下拖曳';
    const scrollArea=box.closest('.sheet-body');
    let dragging=false,moved=false,lastTouch=0;

    const begin=(y,e)=>{
      dragging=true;moved=false;row.classList.add('layer-dragging');document.body.classList.add('layer-sorting');
      row._startLayerIndex=[...box.querySelectorAll('.layer-row')].indexOf(row);
      e?.preventDefault?.();e?.stopPropagation?.();
    };
    const move=(y,e)=>{
      if(!dragging)return;
      moved=true;moveDraggedRow(row,box,y,scrollArea);e?.preventDefault?.();e?.stopPropagation?.();
    };
    const end=e=>{
      if(!dragging)return;
      dragging=false;row.classList.remove('layer-dragging');document.body.classList.remove('layer-sorting');
      if(moved)applyLayerOrderFromDom(box);
      window.renderLayerList();
      e?.preventDefault?.();e?.stopPropagation?.();
    };

    // iPhone / iPad：直接使用原生 touch 事件，不依賴 HTML5 drag 或 pointer capture。
    handle.addEventListener('touchstart',e=>{if(!e.touches?.length)return;lastTouch=Date.now();begin(e.touches[0].clientY,e)},{passive:false});
    document.addEventListener('touchmove',e=>{if(!dragging||!e.touches?.length)return;move(e.touches[0].clientY,e)},{passive:false});
    document.addEventListener('touchend',e=>{if(dragging)end(e)},{passive:false});
    document.addEventListener('touchcancel',e=>{if(dragging)end(e)},{passive:false});

    // 電腦滑鼠。
    handle.addEventListener('mousedown',e=>{if(Date.now()-lastTouch<800||e.button!==0)return;begin(e.clientY,e)});
    document.addEventListener('mousemove',e=>{if(dragging&&Date.now()-lastTouch>=800)move(e.clientY,e)});
    document.addEventListener('mouseup',e=>{if(dragging&&Date.now()-lastTouch>=800)end(e)});

    // 支援部分只送 Pointer Events 的裝置；touch 裝置由上面 touch 路徑優先處理。
    if(window.PointerEvent){
      let pointerDragging=false,pointerId=null;
      handle.addEventListener('pointerdown',e=>{
        if(e.pointerType==='touch'||Date.now()-lastTouch<800)return;
        if(e.button!==undefined&&e.button!==0)return;
        pointerDragging=true;pointerId=e.pointerId;begin(e.clientY,e);
      });
      document.addEventListener('pointermove',e=>{if(pointerDragging&&e.pointerId===pointerId)move(e.clientY,e)});
      document.addEventListener('pointerup',e=>{if(pointerDragging&&e.pointerId===pointerId){pointerDragging=false;pointerId=null;end(e)}});
      document.addEventListener('pointercancel',e=>{if(pointerDragging&&e.pointerId===pointerId){pointerDragging=false;pointerId=null;end(e)}});
    }
  }

  window.renderLayerList=function(){
    if(typeof canvas==='undefined'||!canvas||!document.getElementById('layer-list'))return;
    ensureLayerDragStyles();
    const objs=[...canvas.getObjects()].filter(isLayerObject).reverse();
    const box=document.getElementById('layer-list');box.innerHTML='';
    if(!objs.length){box.innerHTML='<div style="padding:30px;text-align:center;color:#aaa">目前沒有圖層</div>';return}
    const help=document.createElement('div');help.className='layer-drag-help';help.innerHTML='<i class="fa-solid fa-bars"></i><span>按住右側三條槓，再上下拖曳調整圖層</span>';box.appendChild(help);
    const counts={};
    objs.forEach(o=>{
      const key=o.role||o.type||'object';counts[key]=(counts[key]||0)+1;
      const row=document.createElement('div');row.className='layer-row';row._layerObject=o;
      const thumb=document.createElement('div');thumb.className='layer-thumb';fillThumb(thumb,o);
      const name=document.createElement('div');name.className='layer-name';name.textContent=displayLayerName(o,counts[key]);
      const visible=document.createElement('button');visible.title='顯示/隱藏';visible.innerHTML=`<i class="fa-regular ${o.visible===false?'fa-eye-slash':'fa-eye'}"></i>`;
      visible.onclick=e=>{e.stopPropagation();o.visible=o.visible===false;canvas.renderAll();window.renderLayerList();if(typeof recordHistory==='function')recordHistory()};
      const handle=document.createElement('button');handle.type='button';handle.className='layer-drag-handle';handle.setAttribute('aria-label','拖曳調整圖層');handle.innerHTML='<i class="fa-solid fa-bars"></i>';bindDragHandle(handle,row,box,o);
      row.append(thumb,name,visible,handle);
      row.onclick=e=>{if(e.target.closest('.layer-drag-handle')||e.target.closest('button'))return;if(o.selectable!==false){canvas.setActiveObject(o);canvas.renderAll();if(typeof syncSelection==='function')syncSelection();if(typeof closeSheets==='function')closeSheets()}};
      box.appendChild(row);
    });
  };

  function ensurePreviewMask(){
    const checker=document.querySelector('.design-checker'),design=document.getElementById('preview-image');if(!checker||!design)return null;
    checker.style.position='relative';design.style.position='absolute';design.style.inset='0';design.style.zIndex='1';
    let mask=document.getElementById('preview-phone-mask');
    if(!mask){mask=document.createElement('img');mask.id='preview-phone-mask';mask.alt='手機殼預覽';mask.style.cssText='position:absolute;inset:0;width:100%;height:100%;object-fit:fill;z-index:2;pointer-events:none;display:none';checker.appendChild(mask)}
    return mask;
  }

  window.openPreview=function(){
    if(typeof canvas==='undefined'||!canvas)return;
    if(typeof setBusy==='function')setBusy(true,'正在產生高畫質預覽...');
    requestAnimationFrame(()=>{
      try{
        canvas.discardActiveObject();document.getElementById('object-bar')?.classList.remove('show');
        const hidden=canvas.getObjects().filter(o=>['guide','slot-guide'].includes(o.role)),states=hidden.map(o=>o.visible);hidden.forEach(o=>o.visible=false);canvas.renderAll();
        ctx.printBase64=canvas.toDataURL({format:'png',multiplier:3,enableRetinaScaling:true});ctx.mockupBase64=canvas.toDataURL({format:'png',multiplier:1.5,enableRetinaScaling:true});
        hidden.forEach((o,i)=>o.visible=states[i]);canvas.renderAll();
        const design=document.getElementById('preview-image');if(design)design.src=ctx.printBase64;
        const mask=ensurePreviewMask();if(mask){const url=ctx.maskUrl||'';mask.src=url;mask.style.display=url?'block':'none';mask.onerror=()=>{mask.style.display='none'}}
        const title=document.getElementById('preview-title');if(title)title.textContent=`${ctx.modelName||''}・${ctx.styleName||''}`;
        if(typeof navigate==='function')navigate('page-preview');
      }catch(e){console.error(e);if(typeof toast==='function')toast('預覽產生失敗，請再試一次')}
      finally{if(typeof setBusy==='function')setBusy(false)}
    });
  };

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ensurePreviewMask,{once:true});else ensurePreviewMask();
})();
