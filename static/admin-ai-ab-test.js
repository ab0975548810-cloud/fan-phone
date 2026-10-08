(()=>{'use strict';
  const $=id=>document.getElementById(id);
  const form=$('ab-form'),input=$('ab-input'),run=$('ab-run'),message=$('ab-message');
  const rating=[...document.querySelectorAll('[data-choice]')];
  const ai=window.BenfuwanAiRemoveV2;
  const NORMALIZE_OPTIONS={maxEdge:4096,maxBytes:5.5*1024*1024,maxPixels:32000000};
  let originalUrl='',resultUrls=[],ratingToken='';

  const bytes=n=>{n=Number(n||0);return n>=1048576?(n/1048576).toFixed(2)+' MB':Math.round(n/1024)+' KB'};
  const duration=n=>Number.isFinite(Number(n))?(Number(n)/1000).toFixed(2)+' 秒':'—';
  function setMessage(text,error=false){message.textContent=text||'';message.classList.toggle('error',error)}
  function escapeHtml(value){const div=document.createElement('div');div.textContent=String(value??'');return div.innerHTML}
  function revokeResults(){resultUrls.forEach(url=>URL.revokeObjectURL(url));resultUrls=[]}
  function preview(prefix,src,text){
    const image=$(prefix+'-image'),box=image.parentElement,placeholder=box.querySelector('span');
    image.hidden=true;image.removeAttribute('src');placeholder.hidden=false;placeholder.textContent=text;
    if(src){
      image.onload=()=>{placeholder.hidden=true;image.hidden=false};
      image.onerror=()=>{image.hidden=true;placeholder.hidden=false;placeholder.textContent='結果圖片無法顯示'};
      image.src=src;
    }
  }
  function providerMeta(prefix,result){
    const box=$(prefix+'-meta');
    if(!result){box.innerHTML='';return}
    if(!result.ok){box.innerHTML=`<dt>狀態</dt><dd>失敗</dd><dt>處理時間</dt><dd>${duration(result.elapsed_ms)}</dd><dt>說明</dt><dd>${escapeHtml(result.error||'測試失敗')}</dd>`;return}
    const final=result.final;
    box.innerHTML=`<dt>處理時間</dt><dd>${duration(result.elapsed_ms)}</dd><dt>Raw 輸出尺寸</dt><dd>${result.width} × ${result.height}</dd><dt>Raw PNG 大小</dt><dd>${bytes(result.bytes)}</dd><dt>Final 輸出尺寸</dt><dd>${final?`${final.width} × ${final.height}`:'重建失敗'}</dd><dt>Final PNG 大小</dt><dd>${final?bytes(final.bytes):'—'}</dd><dt>Final 有效透明 alpha</dt><dd>${final&&final.valid_alpha?'是':'否'}</dd><dt>實際 provider</dt><dd>${escapeHtml(result.provider)}</dd><dt>模型</dt><dd>${escapeHtml(result.model)}</dd>${result.final_error?`<dt>重建錯誤</dt><dd>${escapeHtml(result.final_error)}</dd>`:''}`;
  }
  function summary(stats){if(!stats)return;$('sum-k-win').textContent=stats.koukoutu_wins;$('sum-r-win').textContent=stats.runpod_wins;$('sum-tie').textContent=stats.ties;$('sum-k-time').textContent=duration(stats.koukoutu_average_ms);$('sum-r-time').textContent=duration(stats.runpod_average_ms)}
  async function json(url,options){const response=await fetch(url,{cache:'no-store',...options});let data={};try{data=await response.json()}catch{}if(!response.ok||data.status!=='success')throw new Error(data.msg||`HTTP ${response.status}`);return data}
  async function loadSummary(){try{summary((await json('/api/admin/ai-ab-test/summary')).stats)}catch(error){setMessage(error.message,true)}}
  function rawPngBlob(result){
    const binary=atob(String(result.png_base64||''));
    const bytesOut=new Uint8Array(binary.length);
    for(let i=0;i<binary.length;i+=1)bytesOut[i]=binary.charCodeAt(i);
    return new Blob([bytesOut],{type:'image/png'});
  }
  function loadOriginal(file){
    if(originalUrl)URL.revokeObjectURL(originalUrl);
    originalUrl=URL.createObjectURL(file);
    const image=$('original-image'),placeholder=image.parentElement.querySelector('span');
    image.hidden=true;placeholder.hidden=false;placeholder.textContent='載入原圖中…';
    return new Promise((resolve,reject)=>{
      image.onload=()=>{placeholder.hidden=true;image.hidden=false;resolve(image)};
      image.onerror=()=>{image.hidden=true;placeholder.hidden=false;placeholder.textContent='原圖無法顯示';reject(new Error('原圖無法解碼'))};
      image.src=originalUrl;
    });
  }
  async function productionEquivalent(result,sourceImage){
    if(!result?.ok)return result;
    try{
      const finalBlob=await ai.compositeWithMask(sourceImage,rawPngBlob(result),{maxPixels:NORMALIZE_OPTIONS.maxPixels});
      const verified=await ai.validate(finalBlob);
      const url=URL.createObjectURL(finalBlob);resultUrls.push(url);
      return {...result,final:{url,width:verified.width,height:verified.height,bytes:finalBlob.size,valid_alpha:true}};
    }catch(error){
      return {...result,final:null,final_error:error?.message||'無法以原圖重建最終透明 PNG'};
    }
  }

  form.addEventListener('submit',async event=>{
    event.preventDefault();const file=input.files?.[0];if(!file)return;
    ratingToken='';rating.forEach(button=>button.disabled=true);run.disabled=true;revokeResults();
    preview('koukoutu','', '等待正式前台輸入準備…');preview('runpod','', '等待 A 完成…');providerMeta('koukoutu',null);providerMeta('runpod',null);
    try{
      if(!ai?.sourceBlobFromElement||!ai?.compositeWithMask)throw new Error('AI 圖片處理核心未載入');
      const sourceImage=await loadOriginal(file);
      const sourceSize=ai.elementSize(sourceImage);
      $('original-meta').innerHTML=`<dt>原始尺寸</dt><dd>${sourceSize.width} × ${sourceSize.height}</dd><dt>原始檔案大小</dt><dd>${bytes(file.size)}</dd><dt>AI 輸入</dt><dd>正在準備…</dd>`;
      setMessage('正在依正式前台規格準備 AI 輸入…');
      const normalized=await ai.sourceBlobFromElement(sourceImage,NORMALIZE_OPTIONS);
      $('original-meta').innerHTML=`<dt>原始尺寸</dt><dd>${sourceSize.width} × ${sourceSize.height}</dd><dt>原始檔案大小</dt><dd>${bytes(file.size)}</dd><dt>AI 輸入上限</dt><dd>4096px / 5.5 MB</dd><dt>正規化 PNG</dt><dd>${bytes(normalized.size)}</dd>`;
      setMessage('正在執行 A：Koukoutu。完成後才會執行 B：RunPod…');preview('koukoutu','', 'A 正在處理…');
      const body=new FormData();body.append('image',normalized,'ai-ab-normalized.png');
      const data=await json('/api/admin/ai-ab-test/run',{method:'POST',body});
      $('original-meta').innerHTML+=`<dt>Server AI 輸入尺寸</dt><dd>${data.original.width} × ${data.original.height}</dd>`;
      const a=await productionEquivalent(data.koukoutu,sourceImage);
      const b=await productionEquivalent(data.runpod,sourceImage);
      preview('koukoutu',a.final?.url||'',a.ok?(a.final?'載入最終結果中…':'最終結果重建失敗'):a.error);
      preview('runpod',b.final?.url||'',b.ok?(b.final?'載入最終結果中…':'最終結果重建失敗'):b.error);
      providerMeta('koukoutu',a);providerMeta('runpod',b);
      ratingToken=(a.final&&b.final&&data.rating_token)||'';
      rating.forEach(button=>button.disabled=!ratingToken);summary(data.stats);
      setMessage(data.stats_warning||(ratingToken?'兩張 production-equivalent final PNG 都完成，請進行人工評分。':'測試完成；只有兩邊最終結果都成功時才能評分。'),false);
    }catch(error){
      setMessage(error.message,true);preview('koukoutu','', '測試未完成');preview('runpod','', '測試未完成');
    }finally{run.disabled=false}
  });
  rating.forEach(button=>button.addEventListener('click',async()=>{if(!ratingToken)return;rating.forEach(item=>item.disabled=true);try{const data=await json('/api/admin/ai-ab-test/rate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({choice:button.dataset.choice,rating_token:ratingToken})});summary(data.stats);ratingToken='';setMessage('針對最終透明 PNG 的評分已記錄。')}catch(error){setMessage(error.message,true);rating.forEach(item=>item.disabled=false)}}));
  loadSummary();
})();
