/* 本福丸後台：把 admin.html 的 global lexical visualCanvas 暴露給外掛補丁。
   admin.html 用 let visualCanvas 宣告，所以 window.visualCanvas 原本會是 undefined。
   模板 AI / 描邊外掛需要同一個 Fabric canvas，這裡只做 getter bridge，不建立第二張畫布。 */
(function(){
  'use strict';
  if(window.__benfuwanCanvasBridgeInstalled)return;
  window.__benfuwanCanvasBridgeInstalled=true;

  function getLexicalCanvas(){
    try{return (typeof visualCanvas!=='undefined')?visualCanvas:null}catch(e){return null}
  }

  try{
    const current=Object.getOwnPropertyDescriptor(window,'visualCanvas');
    if(!current||current.configurable){
      Object.defineProperty(window,'visualCanvas',{
        configurable:true,
        enumerable:false,
        get:getLexicalCanvas
      });
    }
  }catch(e){console.warn('[ADMIN] canvas bridge install warning',e)}

  // 讓後載入的模組能收到畫布已建立的變化。
  let last=null;
  setInterval(()=>{
    const c=getLexicalCanvas();
    if(c&&c!==last){
      last=c;
      try{window.dispatchEvent(new CustomEvent('benfuwan:template-canvas-ready',{detail:{canvas:c}}))}catch(e){}
    }
  },250);

  console.info('[ADMIN] lexical visualCanvas bridge enabled');
})();
