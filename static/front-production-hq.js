/* 本福丸：送單前完成固定 720 DPI 生產圖；禁止低解析預覽圖進入購物車。 */
(function(){
  'use strict';
  if(window.__benfuwanProductionHQInstalled)return;
  window.__benfuwanProductionHQInstalled=true;
  const oldOpen=window.openPreview;
  const oldConfirm=window.confirmDesignToCart;
  const oldSubmit=window.submitOrder;
  const PPM=28.3464567; // 720 DPI / 25.4
  const MAX_PIXELS=18000000;
  let previewRun=null;

  function pixelsForMm(mm){return Math.round(Number(mm)*PPM)}

  function pngDensity(dataUrl){
    const binary=atob(dataUrl.split(',')[1]);
    const input=Uint8Array.from(binary,c=>c.charCodeAt(0));
    const chunk=new Uint8Array(21),v=new DataView(chunk.buffer);v.setUint32(0,9);chunk.set([112,72,89,115],4);v.setUint32(8,Math.round(PPM*1000));v.setUint32(12,Math.round(PPM*1000));chunk[16]=1;
    let crc=0xffffffff;for(const byte of chunk.subarray(4,17)){crc^=byte;for(let bit=0;bit<8;bit++)crc=(crc>>>1)^((crc&1)?0xedb88320:0)}v.setUint32(17,(crc^0xffffffff)>>>0);
    const parts=[input.subarray(0,33),chunk],src=new DataView(input.buffer);for(let p=33;p<input.length;){const end=p+src.getUint32(p)+12;if(!(input[p+4]===112&&input[p+5]===72&&input[p+6]===89&&input[p+7]===115))parts.push(input.subarray(p,end));p=end}
    const out=new Uint8Array(parts.reduce((s,a)=>s+a.length,0));let off=0;for(const a of parts){out.set(a,off);off+=a.length}const ss=[];for(let p=0;p<out.length;p+=32768)ss.push(String.fromCharCode(...out.subarray(p,p+32768)));return 'data:image/png;base64,'+btoa(ss.join(''));
  }

  function createGate(){
    let active=null;
    function begin(context,work){
      const record={context,status:'pending',promise:null,error:null};
      record.promise=Promise.resolve().then(work).then(value=>{record.status='ready';return value},error=>{record.status='failed';record.error=error;throw error});
      active=record;
      return record.promise;
    }
    function wait(context){
      if(!active||active.context!==context)return Promise.reject(new Error('請重新按「完成」產生高清生產圖。'));
      return active.promise;
    }
    function state(){return active?{context:active.context,status:active.status,error:active.error}:null}
    return {begin,wait,state};
  }

  const gate=createGate();

  async function rebuildHQ(target,context){
    const maskApi=window.BenfuwanPrintMask;
    if(!maskApi)throw new Error('高清生產圖元件尚未載入，請重新整理後再試。');
    const width=pixelsForMm(context.printW),height=pixelsForMm(context.printH);
    if(!(width>0&&height>0)||width*height>MAX_PIXELS)throw new Error('手機殼生產尺寸設定有誤，請聯絡店家。');
    const maskUrl=context.printLineUrl||'';
    if(!maskUrl)throw new Error('這個型號尚未設定可印範圍，請聯絡店家。');
    const state=await maskApi.ensureClip(target,maskUrl,true);
    if(canvas!==target||ctx!==context||context.printLineUrl!==maskUrl)throw new Error('型號或設計已切換，請重新按「完成」。');
    await new Promise(resolve=>requestAnimationFrame(resolve));
    const output=maskApi.renderPrint(target,state.mask,width,height);
    const data=pngDensity(output.toDataURL('image/png'));
    output.width=output.height=1;
    if(canvas!==target||ctx!==context||context.printLineUrl!==maskUrl)throw new Error('型號或設計已切換，請重新按「完成」。');
    context.printBase64=data;
    context.productionMeta={ppm:PPM,dpi:720,width,height,maskBounds:{...state.mask.bounds}};
    console.info('[PRINT] normalized 720 DPI production PNG ready',width,height,state.mask.bounds);
    return context.productionMeta;
  }

  function requireReady(context){
    return gate.wait(context).then(()=>{
      const meta=context&&context.productionMeta;
      if(!context?.printBase64||!meta||Math.abs(Number(meta.ppm)-PPM)>0.0001)throw new Error('高清生產圖尚未完成，請重新按「完成」。');
      return meta;
    });
  }

  window.openPreview=function(){
    if(previewRun)return previewRun;
    if(typeof canvas==='undefined'||!canvas||typeof ctx==='undefined'||!ctx)return;
    const target=canvas,context=ctx;
    context.productionMeta=null;
    const work=gate.begin(context,async()=>{
      const result=typeof oldOpen==='function'?await oldOpen.apply(this,arguments):undefined;
      if(canvas!==target||ctx!==context||!context.mockupBase64)throw new Error('預覽尚未完成，請再試一次。');
      context.printBase64=null;
      setBusy(true,'正在完成 720 DPI 高清生產圖...');
      await rebuildHQ(target,context);
      return result;
    });
    previewRun=work.catch(error=>{
      context.printBase64=null;
      context.productionMeta=null;
      console.error('[PRINT] HQ production render failed',error);
      toast('高清生產圖產生失敗：'+(error?.message||'請返回設計後再試一次'));
      return false;
    }).finally(()=>{previewRun=null;setBusy(false)});
    return previewRun;
  };

  window.confirmDesignToCart=async function(){
    const context=ctx;
    setBusy(true,'正在確認高清生產圖...');
    try{
      const meta=await requireReady(context);
      await oldConfirm.apply(this,arguments);
      if(!cartItem||cartItem.printBase64!==context.printBase64)throw new Error('購物車未能保存高清生產圖，請再試一次。');
      cartItem.productionMeta={...meta};
      await idbSet('cart',cartItem);
    }catch(error){
      console.error('[PRINT] cart blocked until HQ is ready',error);
      toast(error?.message||'高清生產圖尚未完成，請再試一次。');
    }finally{setBusy(false)}
  };

  window.submitOrder=async function(){
    if(!cartItem)cartItem=await idbGet('cart');
    const meta=cartItem&&cartItem.productionMeta;
    if(!cartItem?.printBase64||!meta||Math.abs(Number(meta.ppm)-PPM)>0.0001){
      toast('購物車內的生產圖不是 720 DPI 高清版本，請返回設計並重新加入購物車。');
      return;
    }
    return oldSubmit.apply(this,arguments);
  };

  window.BenfuwanProductionHQ=Object.freeze({
    PPM,
    DPI:720,
    pixelsForMm,
    createGate,
    begin:(context,work)=>gate.begin(context,work),
    whenReady:context=>requireReady(context),
    state:()=>gate.state()
  });
})();
