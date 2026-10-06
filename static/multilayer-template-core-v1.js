/* Layer contract shared by authoring, customer editor and the isolated #71 renderer. */
(function(){
  'use strict';if(window.BenfuwanMultilayer)return;
  const VERSION='multilayer-v1';
  const FLAGS=['locked','canMove','canScale','canRotate','canDelete','canDuplicate','canEdit'];
  const PROPS=['layerId','templateLayerId','layerInstanceId','templateApplicationId','layerName','assetId','duplicateOf','normalizedGeometry','zIndex',...FLAGS,'sourceSize','cropX','cropY','templateSlot','slotId','slotMeta','isSlot','isTplBg','templateState','layer_contract_version'];
  const uid=()=>crypto.randomUUID(),clone=v=>structuredClone(v);
  const text=o=>['text','textbox','i-text'].includes(o.type);
  const core=()=>window.BenfuwanEditableSticker;
  const freeze=v=>{if(v&&typeof v==='object'){Object.values(v).forEach(freeze);Object.freeze(v);}return v;};
  const dimensions=o=>({w:(Number(o.width)||0)+(o.strokeUniform?0:Number(o.strokeWidth)||0),h:(Number(o.height)||0)+(o.strokeUniform?0:Number(o.strokeWidth)||0)});
  function geometry(o,c){const p=o.getCenterPoint();return {x:p.x/c.width,y:p.y/c.height,width:o.getScaledWidth()/c.width,height:o.getScaledHeight()/c.height};}
  function validGeometry(g){if(!g||!['x','y','width','height'].every(k=>Number.isFinite(g[k])&&g[k]>=0&&g[k]<=1)||!g.width||!g.height)throw Error('圖層位置／尺寸需在模板畫布範圍內（0～1）');return g;}
  function map(o,g,c){validGeometry(g);const d=dimensions(o),stroke=o.strokeUniform?Number(o.strokeWidth)||0:0;
    o.set({originX:'center',originY:'center',left:g.x*c.width,top:g.y*c.height,scaleX:(g.width*c.width-stroke)/Math.max(.0001,d.w),scaleY:(g.height*c.height-stroke)/Math.max(.0001,d.h)});o.setCoords();}
  function defaults(o){const locked=o.locked??Boolean(o.isTplBg||o.role==='template-bg');return Object.fromEntries(FLAGS.map(k=>[k,k==='locked'?locked:locked?false:o[k]??true]));}
  function name(o){return o.layerName||o.originalName||o.text?.slice(0,18)||(o.isSlot?'照片框':o.isTplBg?'背景':o.type==='image'?'圖片':'素材');}
  function decorate(o,c){
    if(!o.stroke)o.strokeWidth=0;
    if(!o.layerId||c.getObjects().some(other=>other!==o&&other.layerId===o.layerId))o.layerId=uid();
    if(!o.layerInstanceId||c.getObjects().some(other=>other!==o&&other.layerInstanceId===o.layerInstanceId))o.layerInstanceId=uid();
    o.assetId=o.assetId||o.stickerId||o.layerId;
    Object.assign(o,defaults(o));o.layerName=name(o);o.role=o.role||(o.isSlot?'template-photo-slot':o.isTplBg?'template-bg':text(o)?'template-text':'template-sticker');
    if(o.isSlot)o.templateSlot=true;
    return o;
  }
  function policy(c,o){return c.templateState?.initial?.find(r=>r.templateLayerId===o.templateLayerId)||o;}
  function allowed(c,o,flag){if(!o?.templateLayerId)return true;const p=policy(c,o);return !p.locked&&p[flag]!==false;}
  function permissions(c,o,admin=false){
    if(admin){o.set({selectable:true,evented:true,lockMovementX:false,lockMovementY:false,lockScalingX:false,lockScalingY:false,lockRotation:false,editable:true,hasControls:true});return;}
    const p=policy(c,o);FLAGS.forEach(k=>o[k]=p[k]);
    o.set({selectable:!p.locked,evented:!p.locked,lockMovementX:p.locked||!p.canMove,lockMovementY:p.locked||!p.canMove,lockScalingX:p.locked||!p.canScale,lockScalingY:p.locked||!p.canScale,lockRotation:p.locked||!p.canRotate,editable:!p.locked&&p.canEdit,hasControls:!p.locked&&(p.canScale||p.canRotate)});
    o.setControlsVisibility?.({tl:!!p.canScale,tr:!!p.canScale,bl:!!p.canScale,br:!!p.canScale,mtr:!!p.canRotate,mt:false,mb:false,ml:false,mr:false});
    if(o.role==='slot-guide'){o.selectable=false;o.evented=!p.locked&&p.canEdit;}
    if(o.role==='editable-sticker-text'){o.lockMovementX=o.lockMovementY=o.lockScalingX=o.lockScalingY=o.lockRotation=true;o.hasControls=false;}
  }
  function update(c){if(c.layer_contract_version!==VERSION)return;core()?.syncAll(c);
    c.getObjects().forEach((o,i)=>{if(o.templateLayerId){const g=geometry(o,c);if(g.x<0||g.x>1||g.y<0||g.y>1||g.width>1.000001||g.height>1.000001)constrain(o,c);o.normalizedGeometry=geometry(o,c);o.zIndex=i;permissions(c,o);}});
  }
  function constrain(o,c){const d=dimensions(o),center=o.getCenterPoint();o.setPositionByOrigin(new fabric.Point(Math.max(0,Math.min(c.width,center.x)),Math.max(0,Math.min(c.height,center.y))),'center','center');
    o.set({scaleX:Math.min(Math.max(.001,o.scaleX),c.width/Math.max(1,d.w)),scaleY:Math.min(Math.max(.001,o.scaleY),c.height/Math.max(1,d.h))});o.setCoords();}
  async function fonts(c){await core()?.textFonts(c);}
  function exportTemplate(c){
    const rows=c.getObjects().filter(o=>o.role!=='guide');rows.forEach(o=>decorate(o,c));
    const data=c.toJSON([...PROPS,...(core()?.PROPS||[])]);delete data.clipPath;delete data.templateState;
    data.layer_contract_version=VERSION;data.sourceCanvas={width:c.width,height:c.height};
    data.objects=rows.map((o,i)=>{const raw=o.toObject([...PROPS,...(core()?.PROPS||[])]);raw.normalizedGeometry=validGeometry(geometry(o,c));raw.layerId=o.layerId;raw.templateLayerId=o.layerId;raw.zIndex=i;raw.sourceSize=o.type==='image'?{width:o.getElement().naturalWidth||o.getElement().width,height:o.getElement().naturalHeight||o.getElement().height}:undefined;
      raw.role=o.isSlot?'template-photo-slot':o.role;
      delete raw.templateState;delete raw.templateApplicationId;
      if(o.type==='image'){raw.src=o.publicSrc||raw.src;raw.publicSrc=raw.src;if(!raw.src||/^(data:|blob:)/.test(raw.src))throw Error('圖層圖片需先保存站內素材');}
      return raw;
    });return data;
  }
  async function enliven(rows){return new Promise((resolve,reject)=>{try{fabric.util.enlivenObjects(clone(rows),resolve);}catch(e){reject(e);}});}
  async function apply(c,tpl,binding,admin=false){
    const raw=typeof tpl.objects_json==='string'?JSON.parse(tpl.objects_json):tpl.objects_json;
    if(raw?.layer_contract_version!==VERSION)throw Error('多圖層模板契約缺失');
    const objects=await enliven(raw.objects);if(objects.length!==raw.objects.length||objects.some((o,i)=>!o||(o.type==='image'&&!o.width)))throw Error('模板圖層素材無法載入');
    c.clear();c.layer_contract_version=VERSION;c.selection=false;c.backgroundColor=raw.background||'transparent';
    const application=uid(),pairs=new Map();
    for(const [i,o] of objects.entries()){
      const saved=raw.objects[i];o.set({layerId:saved.layerId,templateLayerId:saved.layerId,layerInstanceId:(binding?.applicationId||application)+':'+saved.layerId,templateApplicationId:binding?.applicationId||application});Object.assign(o,defaults(saved));
      map(o,saved.normalizedGeometry,c);o.zIndex=i;
      if(o.editableStickerInstanceId){if(!pairs.has(o.editableStickerInstanceId))pairs.set(o.editableStickerInstanceId,uid());o.editableStickerInstanceId=pairs.get(o.editableStickerInstanceId);}
      if(!admin&&o.templateSlot){o.set({role:'slot-guide',fill:'rgba(255,255,255,.25)',stroke:'#ff6f9a',strokeWidth:1.5,strokeUniform:true,strokeDashArray:[5,4]});map(o,saved.normalizedGeometry,c);}
      c.add(o);
    }
    await core()?.rehydrate(c);
    objects.forEach((o,i)=>{o.normalizedGeometry=geometry(o,c);o.zIndex=i;});
    const initial=objects.map(o=>o.toObject([...PROPS,...(core()?.PROPS||[])]));
    c.templateState=freeze({version:VERSION,id:tpl.id,applicationId:binding?.applicationId||application,binding:clone(binding||{}),initial});
    for(const o of objects)permissions(c,o,admin);c.requestRenderAll();return objects;
  }
  async function reset(c){const state=c.templateState;if(!state)throw Error('目前沒有可恢復的模板');
    const initial=await enliven(state.initial);const extra=c.getObjects().filter(o=>o.templateApplicationId!==state.applicationId);
    c.getObjects().filter(o=>o.templateApplicationId===state.applicationId).forEach(o=>c.remove(o));
    for(const [i,o] of initial.entries()){map(o,o.normalizedGeometry,c);c.insertAt(o,i,false);permissions(c,o);}
    await core()?.rehydrate(c);extra.forEach(o=>{if(!c.getObjects().includes(o))c.add(o);});update(c);c.discardActiveObject();c.requestRenderAll();return initial;
  }
  function hydrate(c){if(c.layer_contract_version!==VERSION)return;
    if(c.templateState)c.templateState=freeze(clone(c.templateState));
    c.selection=false;c.getObjects().filter(o=>o.templateLayerId).forEach(o=>{map(o,o.normalizedGeometry,c);permissions(c,o);});
  }
  async function serialize(c,ctx){update(c);const data=await core().serialize(c,ctx);data.layer_contract_version=VERSION;data.templateBinding=clone(c.templateState.binding);data.emptyTemplateSlots=c.getObjects().filter(o=>o.templateSlot&&o.role==='slot-guide').map(o=>o.toObject(PROPS));data.objects.forEach((o,i)=>o.zIndex=i);delete data.templateState;return data;}
  async function prepareRender(c,data){if(data.layer_contract_version!==VERSION)return;c._objects.sort((a,b)=>(a.zIndex??0)-(b.zIndex??0));for(const o of c.getObjects()){if(o.templateLayerId){map(o,o.normalizedGeometry,c);o.setCoords();}}await core()?.rehydrate(c);}
  function serializer(){if(!window.fabric?.Object||fabric.Object.prototype.__multiSerializer)return;const previous=fabric.Object.prototype.toObject;fabric.Object.prototype.toObject=function(props){return previous.call(this,(this.layerId||this.templateLayerId)?[...(props||[]),...PROPS]:props);};fabric.Object.prototype.__multiSerializer=true;}
  const bound=new WeakSet();function bind(c,admin=false){serializer();if(bound.has(c))return;bound.add(c);
    // Existing image effects replace Image objects. Carry layer identity across
    // that synchronous remove/insert, without changing those effects' algorithms.
    const removed=[];let clearing=false;
    c.on('object:removed',({target})=>{if(admin||!target?.templateLayerId)return;removed.push(target);if(!clearing){clearing=true;queueMicrotask(()=>{removed.length=0;clearing=false;});}});
    c.on('object:added',({target})=>{if(admin||target?.templateLayerId||target?.type!=='image')return;const old=removed.find(o=>o.type==='image'&&o.role===target.role&&Math.abs(o.getCenterPoint().x-target.getCenterPoint().x)<1&&Math.abs(o.getCenterPoint().y-target.getCenterPoint().y)<1);if(!old)return;
      for(const key of PROPS)if(old[key]!==undefined&&!['sourceSize','cropX','cropY','templateState','layer_contract_version'].includes(key))target[key]=clone(old[key]);
      if(old.templateSlot&&old.sourceSize?.width===(target.getElement().naturalWidth||target.width)&&old.sourceSize?.height===(target.getElement().naturalHeight||target.height))target.set({width:old.width,height:old.height,cropX:old.cropX,cropY:old.cropY,scaleX:old.scaleX,scaleY:old.scaleY});
      permissions(c,target);update(c);
    });
    for(const evt of ['object:moving','object:scaling','object:rotating'])c.on(evt,({target})=>{if(!admin&&c.layer_contract_version===VERSION&&target?.templateLayerId){constrain(target,c);core()?.syncAll(c);}});
    c.on('object:modified',()=>{if(!admin)update(c);});
  }
  window.BenfuwanMultilayer={VERSION,PROPS,FLAGS,uid,clone,freeze,geometry,validGeometry,map,name,decorate,defaults,policy,allowed,permissions,constrain,update,fonts,exportTemplate,apply,reset,hydrate,serialize,prepareRender,bind};
  if(core())core().PROPS.push(...PROPS.filter(k=>!core().PROPS.includes(k)));
})();
