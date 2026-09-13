/* 本福丸前台體驗修正 2026-09-13：圖層辨識 + 拖曳排序 + 手機殼預覽恢復 */
(function(){
  'use strict';

  const roleLabel = {
    photo:'照片',
    'slot-photo':'模板照片',
    sticker:'貼紙',
    material:'素材',
    text:'文字',
    'template-text':'模板文字',
    'template-sticker':'模板貼紙',
    'template-bg':'模板背景'
  };
  const materialLabel = {
    circle:'圓形', rect:'方形', triangle:'三角形', heart:'愛心', star:'星星',
    frame:'相框', line:'線條', speech:'對話框', sparkle:'閃亮裝飾'
  };

  function shortName(v,max=14){
    const s=String(v||'').replace(/\.[^.]+$/,'').replace(/\s+/g,' ').trim();
    if(!s)return '';
    return s.length>max?s.slice(0,max)+'…':s;
  }
  function shortText(v,max=12){
    const s=String(v||'').replace(/\s+/g,' ').trim();
    if(!s)return '';
    return s.length>max?s.slice(0,max)+'…':s;
  }
  function displayLayerName(o,n){
    const base=roleLabel[o.role]||'物件';
    if(o.role==='template-bg')return base;
    let detail='';
    if(o.role==='photo') detail=shortName(o.originalName);
    else if(o.role==='slot-photo') detail=o.slotId?('照片框 '+n):'';
    else if(o.role==='text'||o.role==='template-text') detail=shortText(o.text);
    else if((o.role==='sticker'||o.role==='template-sticker')&&o.type!=='image') detail=shortText(o.text,6);
    else if(o.role==='material') detail=materialLabel[o.materialType]||'';
    return `${base} ${n}${detail?'・'+detail:''}`;
  }
  function fillThumb(el,o){
    el.innerHTML='';
    if(o.type==='image'){
      try{
        const src=o.getSrc?.()||o._element?.src||'';
        if(src){
          const img=document.createElement('img');
          img.src=src; img.alt='';
          img.style.cssText='width:100%;height:100%;object-fit:cover;border-radius:9px;display:block';
          el.appendChild(img); return;
        }
      }catch(e){}
    }
    if(o.type==='text'||o.type==='textbox'){
      const t=document.createElement('span');
      t.textContent=shortText(o.text,2)||'T';
      t.style.cssText='font-weight:900;font-size:14px';
      el.appendChild(t); return;
    }
    const i=document.createElement('i');
    i.className=o.role==='material'?'fa-solid fa-shapes':'fa-solid fa-layer-group';
    el.appendChild(i);
  }

  function ensureLayerDragStyles(){
    if(document.getElementById('benfuwan-layer-drag-style'))return;
    const style=document.createElement('style');
    style.id='benfuwan-layer-drag-style';
    style.textContent=`
      .layer-drag-help{padding:2px 4px 10px;color:#9a8f94;font-size:10px;display:flex;align-items:center;gap:6px}
      .layer-row{transition:box-shadow .12s ease,transform .12s ease,opacity .12s ease;background:#fff}
      .layer-row.layer-dragging{opacity:.72;box-shadow:0 10px 24px rgba(80,45,58,.16);transform:scale(.99);position:relative;z-index:5}
      .layer-drag-handle{width:34px!important;height:34px!important;flex:0 0 34px;border:0!important;background:#fff3f7!important;color:#f45f8d!important;border-radius:10px!important;display:grid!important;place-items:center!important;touch-action:none;cursor:grab;font-size:15px!important}
      .layer-drag-handle:active{cursor:grabbing;background:#ffe5ee!important}
      .layer-drag-handle.locked{color:#c8bec2!important;background:#f7f4f5!important;cursor:default}
    `;
    document.head.appendChild(style);
  }

  function isLayerObject(o){return o&&!['guide','slot-guide'].includes(o.role);}

  // 依照畫面上的排序，把 Canvas 的圖層順序一次套用回去。
  // 清單最上面 = 畫布最上層；最下面 = 畫布最下層。
  function applyLayerOrderFromDom(box){
    if(typeof canvas==='undefined'||!canvas)return;
    const rows=[...box.querySelectorAll('.layer-row')];
    const topToBottom=rows.map(r=>r._layerObject).filter(Boolean);
    if(!topToBottom.length)return;

    // 模板背景固定在最底層，避免客人不小心把背景拖到照片上面。
    const movable=topToBottom.filter(o=>o.role!=='template-bg');
    const bg=topToBottom.filter(o=>o.role==='template-bg');
    const desiredBottomToTop=[...bg,...movable.reverse()];

    const oldAll=[...canvas.getObjects()];
    const editableSlots=oldAll.map((o,i)=>isLayerObject(o)?i:-1).filter(i=>i>=0);
    if(editableSlots.length!==desiredBottomToTop.length)return;

    const rebuilt=[...oldAll];
    editableSlots.forEach((slot,i)=>{rebuilt[slot]=desiredBottomToTop[i];});
    if(Array.isArray(canvas._objects)){
      canvas._objects.splice(0,canvas._objects.length,...rebuilt);
      canvas.renderAll();
      if(typeof recordHistory==='function')recordHistory();
    }
  }

  function bindDragHandle(handle,row,box,o){
    if(o.role==='template-bg'){
      handle.classList.add('locked');
      handle.title='模板背景固定在最下層';
      return;
    }
    handle.title='按住拖曳調整圖層';
    let dragging=false,pointerId=null;
    const scrollArea=box.closest('.sheet-body');

    const finish=e=>{
      if(!dragging)return;
      dragging=false;
      row.classList.remove('layer-dragging');
      try{if(pointerId!==null&&handle.hasPointerCapture?.(pointerId))handle.releasePointerCapture(pointerId);}catch(err){}
      pointerId=null;
      applyLayerOrderFromDom(box);
      window.renderLayerList();
      e?.preventDefault?.();
      e?.stopPropagation?.();
    };

    handle.addEventListener('pointerdown',e=>{
      if(e.button!==undefined&&e.button!==0)return;
      dragging=true;
      pointerId=e.pointerId;
      row.classList.add('layer-dragging');
      try{handle.setPointerCapture?.(pointerId);}catch(err){}
      e.preventDefault();
      e.stopPropagation();
    });

    handle.addEventListener('pointermove',e=>{
      if(!dragging)return;
      const y=e.clientY;
      const others=[...box.querySelectorAll('.layer-row:not(.layer-dragging)')].filter(r=>r._layerObject?.role!=='template-bg');
      let placed=false;
      for(const other of others){
        const rect=other.getBoundingClientRect();
        if(y<rect.top+rect.height/2){
          box.insertBefore(row,other);
          placed=true;
          break;
        }
      }
      if(!placed){
        const bgRow=[...box.querySelectorAll('.layer-row')].find(r=>r._layerObject?.role==='template-bg');
        if(bgRow)box.insertBefore(row,bgRow);else box.appendChild(row);
      }
      if(scrollArea){
        const r=scrollArea.getBoundingClientRect();
        if(y<r.top+55)scrollArea.scrollBy({top:-18,behavior:'auto'});
        else if(y>r.bottom-55)scrollArea.scrollBy({top:18,behavior:'auto'});
      }
      e.preventDefault();
      e.stopPropagation();
    });

    handle.addEventListener('pointerup',finish);
    handle.addEventListener('pointercancel',finish);
  }

  // 圖層：同類物件自動編號、縮圖辨識；用右側三條槓直接上下拖曳排序。
  window.renderLayerList=function(){
    if(typeof canvas==='undefined'||!canvas||!document.getElementById('layer-list'))return;
    ensureLayerDragStyles();
    const objs=[...canvas.getObjects()].filter(isLayerObject).reverse();
    const box=document.getElementById('layer-list');
    box.innerHTML='';
    if(!objs.length){box.innerHTML='<div style="padding:30px;text-align:center;color:#aaa">目前沒有圖層</div>';return;}

    const help=document.createElement('div');
    help.className='layer-drag-help';
    help.innerHTML='<i class="fa-solid fa-bars"></i><span>按住右側三條槓，上下拖曳調整圖層位置</span>';
    box.appendChild(help);

    const counts={};
    objs.forEach(o=>{
      const key=o.role||o.type||'object';
      counts[key]=(counts[key]||0)+1;
      const row=document.createElement('div');
      row.className='layer-row';
      row._layerObject=o;

      const thumb=document.createElement('div');
      thumb.className='layer-thumb';
      fillThumb(thumb,o);
      const name=document.createElement('div');
      name.className='layer-name';
      name.textContent=displayLayerName(o,counts[key]);

      const visible=document.createElement('button');
      visible.title='顯示/隱藏';
      visible.innerHTML=`<i class="fa-regular ${o.visible===false?'fa-eye-slash':'fa-eye'}"></i>`;
      visible.onclick=e=>{e.stopPropagation();o.visible=o.visible===false;canvas.renderAll();window.renderLayerList();if(typeof recordHistory==='function')recordHistory();};

      const handle=document.createElement('button');
      handle.className='layer-drag-handle';
      handle.innerHTML='<i class="fa-solid fa-bars"></i>';
      bindDragHandle(handle,row,box,o);

      row.append(thumb,name,visible,handle);
      row.onclick=e=>{
        if(e.target.closest('.layer-drag-handle')||e.target.closest('button'))return;
        if(o.selectable!==false){
          canvas.setActiveObject(o);
          canvas.renderAll();
          if(typeof syncSelection==='function')syncSelection();
          if(typeof closeSheets==='function')closeSheets();
        }
      };
      box.appendChild(row);
    });
  };

  function ensurePreviewMask(){
    const checker=document.querySelector('.design-checker');
    const design=document.getElementById('preview-image');
    if(!checker||!design)return null;
    checker.style.position='relative';
    design.style.position='absolute';
    design.style.inset='0';
    design.style.zIndex='1';
    let mask=document.getElementById('preview-phone-mask');
    if(!mask){
      mask=document.createElement('img');
      mask.id='preview-phone-mask';
      mask.alt='手機殼預覽';
      mask.style.cssText='position:absolute;inset:0;width:100%;height:100%;object-fit:fill;z-index:2;pointer-events:none;display:none';
      checker.appendChild(mask);
    }
    return mask;
  }

  // 再次檢查：高畫質設計照舊，另外疊回手機型號的預覽遮罩；生產圖仍保持乾淨，不把殼框印進去。
  window.openPreview=function(){
    if(typeof canvas==='undefined'||!canvas)return;
    if(typeof setBusy==='function')setBusy(true,'正在產生高畫質預覽...');
    requestAnimationFrame(()=>{
      try{
        canvas.discardActiveObject();
        document.getElementById('object-bar')?.classList.remove('show');
        const hidden=canvas.getObjects().filter(o=>['guide','slot-guide'].includes(o.role));
        const states=hidden.map(o=>o.visible);
        hidden.forEach(o=>o.visible=false);
        canvas.renderAll();
        ctx.printBase64=canvas.toDataURL({format:'png',multiplier:3,enableRetinaScaling:true});
        ctx.mockupBase64=canvas.toDataURL({format:'png',multiplier:1.5,enableRetinaScaling:true});
        hidden.forEach((o,i)=>o.visible=states[i]);
        canvas.renderAll();

        const design=document.getElementById('preview-image');
        if(design)design.src=ctx.printBase64;
        const mask=ensurePreviewMask();
        if(mask){
          const url=ctx.maskUrl||'';
          mask.src=url;
          mask.style.display=url?'block':'none';
          mask.onerror=()=>{mask.style.display='none';};
        }
        const title=document.getElementById('preview-title');
        if(title)title.textContent=`${ctx.modelName||''}・${ctx.styleName||''}`;
        if(typeof navigate==='function')navigate('page-preview');
      }catch(e){
        console.error(e);
        if(typeof toast==='function')toast('預覽產生失敗，請再試一次');
      }finally{
        if(typeof setBusy==='function')setBusy(false);
      }
    });
  };

  // 預覽頁已存在時先建立遮罩層；之後 openPreview 會更新圖片。
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ensurePreviewMask,{once:true});
  else ensurePreviewMask();
})();
