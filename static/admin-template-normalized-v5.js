/* 本福丸模板 v5：把每個物件的中心與實際尺寸存成相對座標，避免跨型號重複縮放。 */
(function(){
'use strict';
if(window.__bfTplNormV5Admin)return;window.__bfTplNormV5Admin=true;
function patch(){
  if(!window.fabric?.Object||fabric.Object.prototype.__bfNormV5)return;
  const old=fabric.Object.prototype.toObject;
  fabric.Object.prototype.toObject=function(props){
    const out=old.call(this,props);
    try{
      const cw=Math.max(1,Number(typeof tplW!=='undefined'?tplW:window.visualCanvas?.width)||1),ch=Math.max(1,Number(typeof tplH!=='undefined'?tplH:window.visualCanvas?.height)||1);
      const c=this.getCenterPoint?.();
      if(c&&Number.isFinite(c.x)&&Number.isFinite(c.y)){
        out.bfNormCX=c.x/cw;out.bfNormCY=c.y/ch;
        out.bfNormW=(this.getScaledWidth?.()||0)/cw;out.bfNormH=(this.getScaledHeight?.()||0)/ch;
        out.bfNormV=5;
      }
    }catch(e){}
    return out;
  };
  fabric.Object.prototype.__bfNormV5=true;
  console.info('[ADMIN] template normalized geometry v5 enabled');
}
function boot(){patch();let n=0;const t=setInterval(()=>{patch();if(++n>24||fabric?.Object?.prototype?.__bfNormV5)clearInterval(t)},500)}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();