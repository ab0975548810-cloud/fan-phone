/* 本福丸前台編輯器操作修正：物件工具列與復原/重做/圖層列都佔實際版面，不再浮蓋畫布；主工具列仍可直接使用。 */
(function(){
  'use strict';
  if(window.__bfFrontEditorAccessV1)return;window.__bfFrontEditorAccessV1=true;

  function addCss(){
    if(document.getElementById('bf-front-editor-access-css'))return;
    const s=document.createElement('style');s.id='bf-front-editor-access-css';s.textContent=`
      /* 復原 / 重做 / 圖層 / 模板：獨立正常版面列，不再浮在畫布上。 */
      #page-editor>.bf-editor-action-row{
        flex:0 0 50px!important;height:50px!important;width:100%!important;display:flex!important;align-items:center!important;justify-content:space-between!important;
        padding:4px 10px!important;background:rgba(255,255,255,.98)!important;border-top:1px solid var(--line)!important;z-index:73!important;
      }
      #page-editor>.bf-editor-action-row .editor-float,
      #page-editor>.bf-editor-action-row .editor-float.right{
        position:relative!important;left:auto!important;right:auto!important;top:auto!important;bottom:auto!important;display:flex!important;align-items:center!important;gap:7px!important;z-index:auto!important;
      }
      #page-editor>.bf-editor-action-row .round{
        width:40px!important;height:40px!important;box-shadow:0 3px 10px rgba(0,0,0,.07)!important;
      }

      /* 物件快捷列是 page-editor 的正常 flex 子元素：顯示時縮小 workspace，不覆蓋畫布。 */
      #page-editor>.object-bar.bf-docked-object-bar{
        display:none!important;position:relative!important;left:auto!important;right:auto!important;top:auto!important;bottom:auto!important;
        flex:0 0 56px!important;width:calc(100% - 16px)!important;height:56px!important;margin:0 8px 6px!important;
        z-index:74!important;border-radius:16px!important;border:1px solid var(--line)!important;
        background:rgba(255,255,255,.99)!important;box-shadow:0 5px 16px rgba(0,0,0,.08)!important;padding:4px 6px!important;
        grid-template-columns:none!important;gap:2px!important;overflow-x:auto!important;overflow-y:hidden!important;
        -webkit-overflow-scrolling:touch;scrollbar-width:none;white-space:nowrap;pointer-events:auto!important;
      }
      #page-editor>.object-bar.bf-docked-object-bar::-webkit-scrollbar{display:none}
      #page-editor>.object-bar.bf-docked-object-bar.show{display:flex!important;align-items:center!important}
      #page-editor>.object-bar.bf-docked-object-bar button{flex:1 0 48px!important;min-width:48px!important;height:46px!important;padding:3px 2px!important;font-size:9px!important;line-height:1.1!important}
      #page-editor>.object-bar.bf-docked-object-bar button i{margin-bottom:3px!important}
      #page-editor>.workspace{min-height:0!important;flex:1 1 auto!important}
      #page-editor>.toolbar{position:relative!important;z-index:76!important;visibility:visible!important;pointer-events:auto!important;flex:0 0 78px!important}
    `;document.head.appendChild(s);
  }

  function fitCanvasToWorkspace(){
    try{
      const workspace=document.querySelector('#page-editor>.workspace'),shell=document.getElementById('canvas-shell');
      if(!workspace||!shell||typeof canvas==='undefined'||!canvas)return;
      if(!document.getElementById('page-editor')?.classList.contains('active'))return;
      const logicalW=Number(canvas.width||0),logicalH=Number(canvas.height||0);
      if(!(logicalW>0&&logicalH>0))return;
      const model=(shopData.models||[]).find(m=>String(m.id)===String(ctx.modelId));
      const film=window.BenfuwanModelProfile?.isFilm(model);
      const padding=film?48:32;
      const maxW=Math.max(1,workspace.clientWidth-padding),maxH=Math.max(1,workspace.clientHeight-padding);
      // Display-only fit: allow a physically small landscape film to grow to a usable size.
      // Both axes share one scale; Fabric's logical pixels and print dimensions are unchanged.
      const ratio=Math.min(maxW/logicalW,maxH/logicalH);
      const displayW=logicalW*ratio,displayH=logicalH*ratio;
      if(film){
        // Fabric 5 normally allocates logical pixels * DPR, although cssOnly
        // fit can enlarge this film. Keep this override on this canvas only;
        // toCanvasElement disables retina while exporting production artwork.
        if(!canvas.__bfFilmRetina){
          canvas.__bfFilmRetina=true;
          canvas.getRetinaScaling=function(){return this.enableRetinaScaling?this.__bfFilmPixelRatio:1};
          canvas._isRetinaScaling=function(){return this.enableRetinaScaling&&this.__bfFilmPixelRatio!==1};
          canvas._initRetinaScaling=function(){
            if(!this.enableRetinaScaling)return;
            const density=this.getRetinaScaling();
            this.__initRetinaScaling(density,this.lowerCanvasEl,this.contextContainer);
            if(this.upperCanvasEl)this.__initRetinaScaling(density,this.upperCanvasEl,this.contextTop);
            this.contextContainer.imageSmoothingEnabled=true;
            this.contextContainer.imageSmoothingQuality='high';
          };
        }
        canvas.__bfFilmDisplayScale=ratio;
        canvas.__bfFilmPixelRatio=ratio*Math.max(1,Math.min(Number(window.devicePixelRatio)||1,3));
      }
      shell.style.width=displayW+'px';shell.style.height=displayH+'px';
      // initCanvas applies its own transform scale. Once this responsive fit
      // takes over, leaving that transform in place scales Fabric a second
      // time while the shell and mask keep the cssOnly dimensions.
      if(canvas.wrapperEl){canvas.wrapperEl.style.transform='none';canvas.wrapperEl.style.transformOrigin=''}
      if(typeof canvas.setDimensions==='function')canvas.setDimensions({width:displayW+'px',height:displayH+'px'},{cssOnly:true});
      if(film)window.BenfuwanPrintMask?.refreshFilmDisplay(canvas);
      canvas.calcOffset?.();canvas.renderAll?.();
    }catch(e){console.warn('[FRONT UX] canvas fit warning',e)}
  }

  function clearSelectionForMainTool(){
    try{
      if(typeof canvas==='undefined'||!canvas||!canvas.getActiveObject?.())return;
      canvas.discardActiveObject();
      document.getElementById('object-bar')?.classList.remove('show');
      canvas.requestRenderAll?.();
      requestAnimationFrame(fitCanvasToWorkspace);
    }catch(e){console.warn('[FRONT UX] selection release warning',e)}
  }

  function dockActionRow(){
    const page=document.getElementById('page-editor'),workspace=page?.querySelector(':scope>.workspace');
    if(!page||!workspace)return;
    const left=workspace.querySelector(':scope>.editor-float:not(.right)')||page.querySelector('.editor-float:not(.right)');
    const right=workspace.querySelector(':scope>.editor-float.right')||page.querySelector('.editor-float.right');
    if(!left&&!right)return;
    let row=page.querySelector(':scope>.bf-editor-action-row');
    if(!row){row=document.createElement('div');row.className='bf-editor-action-row';workspace.insertAdjacentElement('afterend',row)}
    if(left&&left.parentElement!==row)row.appendChild(left);
    if(right&&right.parentElement!==row)row.appendChild(right);
  }

  function dockInFlow(){
    const page=document.getElementById('page-editor'),bar=document.getElementById('object-bar'),toolbar=page?.querySelector(':scope>.toolbar');
    if(!page||!bar||!toolbar)return;
    dockActionRow();
    const actionRow=page.querySelector(':scope>.bf-editor-action-row');
    if(actionRow){
      if(bar.parentElement!==page||bar.previousElementSibling!==actionRow)actionRow.insertAdjacentElement('afterend',bar);
    }else if(bar.parentElement!==page||bar.nextElementSibling!==toolbar){
      page.insertBefore(bar,toolbar);
    }
    bar.classList.add('bf-docked-object-bar');
    if(!bar.dataset.bfFlowObserver){
      bar.dataset.bfFlowObserver='1';
      new MutationObserver(()=>requestAnimationFrame(fitCanvasToWorkspace)).observe(bar,{attributes:true,attributeFilter:['class']});
    }
  }

  function bind(){
    addCss();dockInFlow();
    const toolbar=document.querySelector('#page-editor>.toolbar');if(!toolbar)return;
    if(!toolbar.dataset.bfDirectAccess){
      toolbar.dataset.bfDirectAccess='1';
      // Capture 階段先取消目前物件選取，但不阻止原本按鈕事件。
      toolbar.addEventListener('click',clearSelectionForMainTool,true);
    }
    requestAnimationFrame(fitCanvasToWorkspace);
  }

  // The adjustment panel is an in-flow dock. Only CSS display dimensions are
  // fitted; Fabric coordinates, export geometry and print calibration stay put.
  function dockAdjust(){
    const page=document.getElementById('page-editor'),sheet=document.getElementById('sheet-adjust');
    if(!page||!sheet||sheet.dataset.bfDock)return;
    sheet.dataset.bfDock='1';page.querySelector('.workspace').after(sheet);
    const style=document.createElement('style');style.textContent=`
      #page-editor>#sheet-adjust{position:relative;inset:auto;display:none;flex:0 0 auto;height:auto;max-height:38%;width:calc(100% - 16px);margin:0 8px 6px;border:1px solid var(--line);border-radius:16px;z-index:74;transition:none;box-shadow:0 3px 16px #6d30431a;overflow:hidden}
      #page-editor>#sheet-adjust.show{display:flex}
      #sheet-adjust .sheet-header{height:42px;padding:0 10px;font-size:12px}
      #sheet-adjust .sheet-header button{min-height:36px;border:0;border-radius:10px;background:#fff0f5;color:#9e375e;padding:5px 9px}
      #sheet-adjust .sheet-body{min-height:0;flex:1 1 auto;padding:0 10px 8px;overflow:auto}
      #sheet-adjust.bf-collapsed .sheet-body{display:none}
      #sheet-adjust .range-row{display:grid;grid-template-columns:minmax(0,1fr) 78px;align-items:center;column-gap:10px;margin:0}
      #sheet-adjust .range-row .head{grid-column:1;grid-row:1;font-size:11px;margin-top:4px}
      #sheet-adjust .range-row input[type=range]{grid-column:1;grid-row:2;height:44px}
      #sheet-adjust .range-row input[type=text]{grid-column:2;grid-row:1 / span 2;width:78px;min-height:38px}
      #sheet-adjust input[type=text]{font-size:16px;border:1px solid #e4c4d0;border-radius:9px;padding:6px;text-align:right;background:#fff;max-width:100%}
      #sheet-adjust input:disabled{opacity:.45}
      #bf-adjust-more summary{padding:10px 0;color:#a33b62;font-size:12px;cursor:pointer}
      .bf-position-inputs{display:flex;flex-wrap:wrap;gap:8px}.bf-position-inputs p{flex-basis:100%;font-size:11px;line-height:1.5;margin:5px 0}.bf-position-inputs label{flex:1;display:flex;align-items:center;gap:5px}.bf-position-inputs input{width:110px;min-width:0}
      #page-editor.bf-adjust-open>.object-bar.bf-docked-object-bar{display:none!important}
      #page-editor.bf-adjust-open>.toolbar{padding-bottom:max(7px,env(safe-area-inset-bottom))!important}
        #page-editor.bf-adjust-open.bf-adjust-short>.top{height:40px}
        #page-editor.bf-adjust-open.bf-adjust-short>.toolbar{flex-basis:50px!important;height:50px;padding:3px!important}
        #page-editor.bf-adjust-open.bf-adjust-short>.toolbar .ico{height:22px;width:26px;font-size:13px;margin-bottom:1px}
        #page-editor.bf-adjust-open.bf-adjust-short>.bf-editor-action-row{flex-basis:40px!important;height:40px!important;padding:0 8px!important}
        #page-editor.bf-adjust-short>#sheet-adjust{max-height:36%}
    `;document.head.append(style);
    function viewport(){
      const open=sheet.classList.contains('show')&&page.classList.contains('active');
      page.classList.toggle('bf-adjust-open',open);
      const app=document.getElementById('app'),vv=window.visualViewport;
      page.classList.toggle('bf-adjust-short',open&&(vv?.height||innerHeight)<=600);
      if(open){
        document.getElementById('sheet-overlay')?.classList.remove('show');
        if(vv){app.style.height=vv.height+'px';app.style.top=vv.offsetTop+'px';}
      }else{app.style.removeProperty('height');app.style.removeProperty('top');}
      fitCanvasToWorkspace();
      const input=document.activeElement;if(open&&input?.matches('#sheet-adjust input[type=text],#sheet-adjust input[type=number]'))input.scrollIntoView({block:'nearest'});
    }
    new MutationObserver(viewport).observe(sheet,{attributes:true,attributeFilter:['class']});
    new MutationObserver(viewport).observe(page,{attributes:true,attributeFilter:['class']});
    window.visualViewport?.addEventListener('resize',viewport);
    window.visualViewport?.addEventListener('scroll',viewport);
    window.addEventListener('resize',viewport);
    sheet.addEventListener('focusin',viewport);
    sheet.querySelector('details')?.addEventListener('toggle',viewport);
    new ResizeObserver(fitCanvasToWorkspace).observe(sheet);
  }
  function boot(){
    bind();dockAdjust();
    const workspace=document.querySelector('#page-editor>.workspace');
    if(workspace)new ResizeObserver(()=>requestAnimationFrame(fitCanvasToWorkspace)).observe(workspace);
    const obs=new MutationObserver(bind);obs.observe(document.documentElement,{childList:true,subtree:true});setTimeout(()=>{try{obs.disconnect()}catch(e){}},30000);
    window.addEventListener('resize',()=>requestAnimationFrame(fitCanvasToWorkspace),{passive:true});
    window.addEventListener('orientationchange',()=>setTimeout(fitCanvasToWorkspace,80),{passive:true});
    window.BenfuwanEditorAccess={version:'2.1-docked-action-row',fitCanvas:fitCanvasToWorkspace};
    console.info('[FRONT] editor action row and selected-object toolbar use real layout space');
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
