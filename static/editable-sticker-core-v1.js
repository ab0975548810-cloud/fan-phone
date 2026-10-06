/* Shared full-resolution editable sticker layout. Fabric Image + Textbox, never baked. */
(function(){
  'use strict';
  if(window.BenfuwanEditableSticker)return;
  const VERSION='editable-text-v1';
  const PROPS=['editableStickerId','editableStickerInstanceId','textArea','minFontSize','requestedFontSize','editableStickerStyle','role','publicSrc','assetId','slotId','slotMeta','isSlot','isTplBg'];
  const FONTS={'jf-openhuninn':{name:'可愛粉圓',url:'/static/fonts/jf-openhuninn-2.1.ttf'},'NotoSansTC':{name:'思源黑體',url:'/static/fonts/NotoSansTC.woff2'}};
  const loaded=new Map(),bound=new WeakSet();
  let coveragePromise=null;
  const uuid=()=>crypto.randomUUID();
  const isMember=o=>!!o?.editableStickerInstanceId;
  function area(a){
    if(!a||!['x','y','width','height'].every(k=>Number.isFinite(a[k])&&a[k]>=0&&a[k]<=1)||a.width<=0||a.height<=0||a.x+a.width>1.000001||a.y+a.height>1.000001)throw Error('文字安全區設定無效');
    return {...a};
  }
  async function font(family,text='文字'){
    if(!FONTS[family])throw Error('請使用站內字型（可愛粉圓／思源黑體）');
    if(!coveragePromise)coveragePromise=fetch('/static/fonts/editable-font-manifest.json').then(r=>{if(!r.ok)throw Error('字型契約無法載入');return r.json();}).catch(e=>{coveragePromise=null;throw e;});
    const coverage=await coveragePromise;
    const ranges=coverage[family]?.ranges;if(!ranges)throw Error('字型契約缺失');
    for(const character of String(text)){const n=character.codePointAt(0);let lo=0,hi=ranges.length;while(lo<hi){const mid=(lo+hi)>>1;if(ranges[mid][1]<n)lo=mid+1;else hi=mid;}if(![9,10,13].includes(n)&&!(ranges[lo]?.[0]<=n))throw Error('字型不支援部分字元，請更換字型或文字');}
    if(!loaded.has(family))loaded.set(family,(async()=>{
      const response=await fetch(FONTS[family].url+'?sha='+coverage[family].sha256);if(!response.ok)throw Error('字型載入失敗');const bytes=await response.arrayBuffer();
      const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');if(hash!==coverage[family].sha256)throw Error('字型版本不一致');
      const face=new FontFace(family,bytes,family==='NotoSansTC'?{weight:'100 900'}:{});
      await face.load();document.fonts.add(face);return face;
    })().catch(e=>{loaded.delete(family);throw Error('字型載入失敗，不能安全排版');}));
    await loaded.get(family);
    const result=await document.fonts.load('16px "'+family+'"',String(text||'文字'));
    if(!result.length)throw Error('字型尚未準備好');
  }
  function members(c,o){const id=typeof o==='string'?o:o?.editableStickerInstanceId;return c.getObjects().filter(x=>x.editableStickerInstanceId===id);}
  function pair(c,o){const list=members(c,o);return {bg:list.find(x=>x.role==='editable-sticker-bg'),text:list.find(x=>x.role==='editable-sticker-text')};}
  function fit(bg,t){
    const a=area(t.textArea),w=bg.width*a.width,h=bg.height*a.height,pad=Math.max(0,Number(t.strokeWidth)||0)*2+(t.fontStyle==='italic'?Number(t.requestedFontSize||t.fontSize)*.15:0);
    const max=Number(t.requestedFontSize||t.fontSize),min=Number(t.minFontSize||12);
    if(!(max>=min&&min>=1))throw Error('文字字級設定無效');
    let success=false;
    for(let size=max;size>=min;size=Math.max(min,size-1)){
      t.set({width:Math.max(1,w-pad),fontSize:size,splitByGrapheme:true});t.initDimensions();
      const lineWidth=Math.max(0,...t._textLines.map((_,i)=>t.getLineWidth(i)));
      if(t.height+pad<=h+.01&&lineWidth+pad<=w+.01){success=true;break;}
      if(size===min)break;
    }
    if(!success)throw Error('文字過多，請減少字數或換行');
    return t.fontSize;
  }
  function sync(bg,t){
    if(!bg||!t)throw Error('文字貼紙缺少成員');
    fit(bg,t);
    const a=t.textArea,m=bg.calcTransformMatrix(),p=fabric.util.transformPoint(new fabric.Point((a.x+a.width/2-.5)*bg.width,(a.y+a.height/2-.5)*bg.height),m);
    t.set({originX:'center',originY:'center',left:p.x,top:p.y,angle:bg.angle,scaleX:bg.scaleX,scaleY:bg.scaleY,flipX:bg.flipX,flipY:bg.flipY,opacity:bg.opacity,visible:bg.visible,
      lockMovementX:true,lockMovementY:true,lockScalingX:true,lockScalingY:true,lockRotation:true,hasControls:false});
    t.setCoords();bg.setCoords();
  }
  async function rehydrate(c){
    for(const o of c.getObjects().filter(isMember))o.role=o.type==='image'?'editable-sticker-bg':'editable-sticker-text';
    const texts=c.getObjects().filter(o=>o.role==='editable-sticker-text');
    await Promise.all(texts.map(o=>font(o.fontFamily,o.text)));
    for(const t of texts){const {bg}=pair(c,t);sync(bg,t);t.__lastValid=t.text;}
    bind(c);c.requestRenderAll();
  }
  function syncAll(c){for(const bg of c.getObjects().filter(o=>o.role==='editable-sticker-bg')){const {text}=pair(c,bg);sync(bg,text);}}
  function bind(c){
    if(!fabric.Object.prototype.__editableSerializer){
      const original=fabric.Object.prototype.toObject;
      fabric.Object.prototype.toObject=function(props){return original.call(this,isMember(this)?[...(props||[]),...PROPS]:props);};
      fabric.Object.prototype.__editableSerializer=true;
    }
    if(bound.has(c))return;bound.add(c);let removing=false;
    let hydrationQueued=false;
    c.on('object:added',({target})=>{if(!isMember(target)||hydrationQueued)return;hydrationQueued=true;queueMicrotask(async()=>{try{await rehydrate(c);}catch(e){if(typeof toast==='function')toast(e.message);}finally{hydrationQueued=false;}});});
    if(c.findTarget){const find=c.findTarget;c.findTarget=function(){const target=find.apply(this,arguments);return target?.role==='editable-sticker-text'&&!target.isEditing&&!target.__editableEntering?pair(c,target).bg:target;};}
    let ordering=false;
    for(const [name,delta] of [['bringForward',1],['sendBackwards',-1],['bringToFront','top'],['sendToBack','bottom'],['moveTo','index']]){
      const original=c[name];c[name]=function(o,index){
        if(ordering||!isMember(o))return original.apply(this,arguments);
        const {bg,text}=pair(c,o),objects=c.getObjects(),others=objects.filter(x=>x!==bg&&x!==text);
        const current=Math.min(objects.indexOf(bg),objects.indexOf(text));
        const target=Math.max(0,Math.min(others.length,delta==='top'?others.length:delta==='bottom'?0:delta==='index'?index:current+delta));
        const arranged=[...others.slice(0,target),bg,text,...others.slice(target)];ordering=true;
        try{arranged.forEach((object,i)=>c.moveTo(object,i));}finally{ordering=false;}
        c.requestRenderAll();return c;
      };
    }
    for(const event of ['object:moving','object:scaling','object:rotating','object:modified'])c.on(event,({target})=>{if(isMember(target)){const {bg,text}=pair(c,target);sync(bg,text);c.requestRenderAll();}});
    c.on('object:removed',({target})=>{if(!isMember(target)||removing)return;removing=true;members(c,target).forEach(o=>c.remove(o));removing=false;});
    c.on('mouse:dblclick',({target})=>{if(!isMember(target))return;const {text}=pair(c,target);text.__editableEntering=true;c.setActiveObject(text);text.enterEditing();text.__editableEntering=false;text.selectAll();c.requestRenderAll();});
    c.on('text:changed',({target})=>{if(!isMember(target))return;const {bg,text}=pair(c,target);try{sync(bg,text);text.__lastValid=text.text;}catch(e){text.text=text.__lastValid||'';sync(bg,text);if(typeof toast==='function')toast(e.message);}c.requestRenderAll();});
    c.on('text:editing:exited',({target})=>{if(isMember(target))c.fire('object:modified',{target});if(typeof recordHistory==='function'&&c===window.__editableFrontCanvas)recordHistory();});
    const select=({selected})=>{const o=selected?.[0];if(o?.role==='editable-sticker-text'&&!o.isEditing&&!o.__editableEntering){const {bg}=pair(c,o);c.setActiveObject(bg);}if(typeof window.bfEditableSelection==='function')window.bfEditableSelection(c,o);};
    c.on('selection:created',select);c.on('selection:updated',select);
  }
  async function add(c,asset){
    const a=area(asset.textArea),s={text:'輸入文字',fontFamily:'jf-openhuninn',fontSize:160,minFontSize:24,fill:'#604047',stroke:null,strokeWidth:0,textAlign:'center',charSpacing:0,lineHeight:1.2,fontWeight:'400',fontStyle:'normal',...(asset.defaultTextStyle||{})};
    await font(s.fontFamily,s.text);
    const bg=await new Promise((resolve,reject)=>fabric.Image.fromURL(asset.imageSrc,img=>img?.width?resolve(img):reject(Error('對話框圖片無法載入')),{crossOrigin:'anonymous'}));
    const instance=uuid(),common={editableStickerId:asset.id,editableStickerInstanceId:instance};
    bg.set({...common,assetId:asset.id,publicSrc:asset.imageSrc,role:'editable-sticker-bg',left:c.width/2,top:c.height/2,originX:'center',originY:'center',strokeWidth:0});
    bg.scaleToWidth(Math.min(200,c.width*.65));
    const t=new fabric.Textbox(s.text,{...s,...common,requestedFontSize:s.fontSize,minFontSize:s.minFontSize,textArea:a,role:'editable-sticker-text'});
    sync(bg,t);t.__lastValid=t.text;bind(c);c.add(bg,t);c.setActiveObject(bg);c.requestRenderAll();return {bg,text:t};
  }
  async function duplicate(c,o){
    const {bg,text}=pair(c,o);if(!bg||!text)throw Error('文字貼紙缺少成員');
    const clone=o=>new Promise(r=>o.clone(r,PROPS));
    const b=await clone(bg),t=await clone(text),id=uuid();
    b.set({editableStickerInstanceId:id,left:bg.left+18,top:bg.top+18});t.set('editableStickerInstanceId',id);sync(b,t);c.add(b,t);c.setActiveObject(b);c.requestRenderAll();return {bg:b,text:t};
  }
  async function update(c,o,props){
    const {bg,text}=pair(c,o);if(!text)throw Error('請選文字貼紙');
    const saved=text.toObject(PROPS);await font(props.fontFamily||text.fontFamily,props.text||text.text);
    text.set(props);if(props.fontSize!=null)text.requestedFontSize=Number(props.fontSize);
    try{sync(bg,text);text.__lastValid=text.text;}catch(e){text.set(saved);sync(bg,text);throw e;}
    c.requestRenderAll();return text;
  }
  async function serialize(c,context){
    await rehydrate(c);c.discardActiveObject();
    const data=c.toJSON(PROPS);delete data.clipPath;
    data.objects=data.objects.filter(o=>!['guide','slot-guide'].includes(o.role));
    const visit=(raw,obj)=>{
      if(raw.type==='image'){
        const el=obj.getElement();if(typeof el.src==='string'&&el.src.startsWith('data:image/png;base64,')){raw.src=el.src;return;}const source=document.createElement('canvas');source.width=el.naturalWidth||el.width;source.height=el.naturalHeight||el.height;
        if(!source.width||source.width*source.height>32_000_000)throw Error('原始素材尺寸無效');
        source.getContext('2d').drawImage(el,0,0);raw.src=source.toDataURL('image/png');source.width=source.height=1;
      }
      if(raw.objects)raw.objects.forEach((r,i)=>visit(r,obj._objects[i]));
    };
    const objs=c.getObjects().filter(o=>!['guide','slot-guide'].includes(o.role));data.objects.forEach((r,i)=>visit(r,objs[i]));
    const coverage=await coveragePromise;
    return {...data,render_contract_version:VERSION,fontHashes:Object.fromEntries(Object.entries(coverage).map(([key,value])=>[key,value.sha256])),logicalCanvas:{width:c.width,height:c.height},production:{printW:context.printW,printH:context.printH},modelId:context.modelId,styleId:context.styleId};
  }
  async function render(data,maskSrc,width,height){
    const c=new fabric.StaticCanvas(null,{width:data.logicalCanvas.width,height:data.logicalCanvas.height,enableRetinaScaling:false});
    try{
      const texts=[];const scan=o=>{if(['text','textbox','i-text'].includes(o.type))texts.push(o);(o.objects||[]).forEach(scan);};data.objects.forEach(scan);
      await Promise.all(texts.map(o=>font(o.fontFamily,o.text)));
      await new Promise(resolve=>c.loadFromJSON({version:data.version,background:data.background,objects:data.objects},resolve));await rehydrate(c);
      c.getObjects().forEach(o=>o.set('objectCaching',false));
      const image=await new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=()=>reject(Error('生產遮罩無法載入'));im.src=maskSrc;});
      const mask=BenfuwanPrintMask.normalizeMaskImage(image);
      const output=BenfuwanPrintMask.renderPrint(c,mask,width,height);
      return {png:output.toDataURL('image/png'),layouts:c.getObjects().filter(o=>o.role==='editable-sticker-text').map(o=>({id:o.editableStickerInstanceId,fontSize:o.fontSize,lines:o._textLines.map(a=>a.join(''))}))};
    }finally{c.dispose();}
  }
  window.BenfuwanEditableSticker={VERSION,PROPS,FONTS,area,font,fit,sync,syncAll,bind,add,duplicate,update,pair,isMember,rehydrate,serialize,render};
})();
