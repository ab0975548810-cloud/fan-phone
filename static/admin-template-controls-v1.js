/* Admin template editor: keep sticker picker accessible and separate movement from resizing. */
(function(){
  'use strict';if(window.__bfAdminTemplateControls20261017)return;window.__bfAdminTemplateControls20261017=true;
  const by=id=>document.getElementById(id),current=()=>window.visualCanvas||null;
  const bound=new WeakSet();
  function css(){
    if(by('bf-tpl-direction-css'))return;
    const s=document.createElement('style');s.id='bf-tpl-direction-css';s.textContent=`
      #bf-tpl-objectbar .bf-tpl-nudge{display:flex;align-items:center;gap:5px;padding:4px 7px;background:#fff;border:1px solid #f1dce4;border-radius:12px;flex-wrap:wrap}
      #bf-tpl-objectbar .bf-tpl-nudge-label{font-size:11px;font-weight:900;color:#9a6980}
      #bf-tpl-objectbar .bf-tpl-nudge button{min-width:40px;min-height:40px;border-radius:10px;font-size:14px;background:#fff3f7}
      #bf-tpl-objectbar .bf-tpl-nudge button:active{background:#ffdce9}
      #bf-tpl-sticker-panel.show{display:block!important}
      #bf-tpl-sticker-panel .bf-tpl-sticker{touch-action:manipulation}
    `;document.head.append(s);
  }
  function moveControl(){
    if(!window.fabric?.Control||!fabric.controlsUtils?.dragHandler)return null;
    if(window.__bfAdminMoveCorner)return window.__bfAdminMoveCorner;
    const ctrl=new fabric.Control({
      x:.5,y:.5,offsetX:7,offsetY:7,cursorStyle:'move',actionName:'drag',
      actionHandler:fabric.controlsUtils.dragHandler,
      render(ctx,left,top){
        ctx.save();ctx.translate(left,top);ctx.fillStyle='#fff';ctx.strokeStyle='#df5581';ctx.lineWidth=2;
        ctx.beginPath();ctx.arc(0,0,12,0,2*Math.PI);ctx.fill();ctx.stroke();
        ctx.strokeStyle='#a82358';ctx.lineWidth=1.8;ctx.lineCap='round';
        ctx.beginPath();ctx.moveTo(-6,0);ctx.lineTo(6,0);ctx.moveTo(0,-6);ctx.lineTo(0,6);
        ctx.moveTo(-6,0);ctx.lineTo(-3,-3);ctx.moveTo(-6,0);ctx.lineTo(-3,3);
        ctx.moveTo(6,0);ctx.lineTo(3,-3);ctx.moveTo(6,0);ctx.lineTo(3,3);
        ctx.moveTo(0,-6);ctx.lineTo(-3,-3);ctx.moveTo(0,-6);ctx.lineTo(3,-3);
        ctx.moveTo(0,6);ctx.lineTo(-3,3);ctx.moveTo(0,6);ctx.lineTo(3,3);ctx.stroke();ctx.restore();
      }
    });
    ctrl.cornerSize=25;ctrl.touchCornerSize=42;
    window.__bfAdminMoveCorner=ctrl;return ctrl;
  }
  function tune(o){
    if(!o||o.isTplBg)return;
    const drag=moveControl();if(!drag)return;
    o.controls={...o.controls,br:drag};
    // Edge controls stretch only one axis. Keep corner scaling intentional,
    // and make the bottom-right corner a dedicated four-way move control.
    o.setControlsVisibility?.({ml:false,mr:false,mt:false,mb:false,br:true});
    o.setCoords?.();
  }
  function nudge(direction,step=2){
    const c=current(),o=c?.getActiveObject();if(!c||!o||o.isTplBg)return false;
    const moves={up:[0,-step],down:[0,step],left:[-step,0],right:[step,0]};
    if(!moves[direction])return false;
    const p=o.getCenterPoint(),[dx,dy]=moves[direction];
    o.setPositionByOrigin(new fabric.Point(Math.max(0,Math.min(c.width,p.x+dx)),Math.max(0,Math.min(c.height,p.y+dy))),'center','center');
    o.setCoords();c.requestRenderAll();c.fire('object:modified',{target:o});return true;
  }
  function ensureButtons(){
    css();const bar=by('bf-tpl-objectbar');if(!bar||by('bf-tpl-nudge'))return;
    const d=document.createElement('div');d.id='bf-tpl-nudge';d.className='bf-tpl-nudge';
    const title=document.createElement('span');title.className='bf-tpl-nudge-label';title.textContent='位置微調';d.append(title);
    for(const [direction,icon] of [['up','↑'],['down','↓'],['left','←'],['right','→']]){
      const b=document.createElement('button');b.type='button';b.dataset.bfNudge=direction;b.title=direction+'（按住 Shift 移動 10）';
      b.setAttribute('aria-label',{'up':'上移','down':'下移','left':'左移','right':'右移'}[direction]);b.textContent=icon;
      b.addEventListener('click',e=>{e.preventDefault();nudge(direction,e.shiftKey?10:2)});d.append(b);
    }
    const center=[...bar.querySelectorAll('button')].find(b=>b.dataset.act==='center');
    if(center)center.insertAdjacentElement('afterend',d);else bar.prepend(d);
  }
  function bind(c){
    ensureButtons();if(!c||bound.has(c))return;bound.add(c);
    c.getObjects().forEach(tune);
    c.on('object:added',e=>tune(e.target));
    c.on('selection:created',e=>tune(e.target));
    c.on('selection:updated',e=>tune(e.target));
    // The legacy editor may rehydrate via loadFromJSON without a new Canvas instance.
    c.on('after:render',()=>{const a=c.getActiveObject();if(a&&!a.isTplBg&&a.controls?.br!==moveControl())tune(a);});
  }
  const oldInit=window.initEditor;
  if(typeof oldInit==='function')window.initEditor=function(){const r=oldInit.apply(this,arguments);bind(current());return r;};
  const oldOpen=window.openTemplateEditor;
  if(typeof oldOpen==='function')window.openTemplateEditor=async function(){const r=await oldOpen.apply(this,arguments);ensureButtons();bind(current());return r;};
  function boot(){ensureButtons();bind(current());}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
  window.BenfuwanAdminTemplateControls={nudge,bind,tune};
})();
