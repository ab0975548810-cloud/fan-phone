/* 本福丸後台：手機殼材質的「預設顏色 + 各型號覆蓋」 */
(function(){
  'use strict';
  if(window.__benfuwanModelColorsAdminInstalled)return;
  window.__benfuwanModelColorsAdminInstalled=true;

  const cleanList=v=>{
    const arr=Array.isArray(v)?v:String(v||'').split(/[,，]/);
    const out=[];
    arr.map(x=>String(x||'').trim()).filter(Boolean).forEach(x=>{if(!out.includes(x))out.push(x)});
    return out;
  };
  const getStyle=id=>id?(shopData.styles||[]).find(x=>String(x.id)===String(id)):null;

  function ensureStyles(){
    if(document.getElementById('bf-model-color-style'))return;
    const s=document.createElement('style');
    s.id='bf-model-color-style';
    s.textContent=`
      .bf-color-box{margin:12px 0 16px;border:1px solid #f1dfe6;border-radius:16px;background:#fffafb;overflow:hidden}
      .bf-color-head{padding:12px 13px;background:#fff2f6;display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}
      .bf-color-head b{font-size:13px;color:#d95680}.bf-color-head small{display:block;color:#958990;margin-top:3px;font-size:10px}
      .bf-color-search{width:min(260px,100%);border:1px solid #eadce1!important;border-radius:999px!important;padding:8px 12px!important;background:#fff!important}
      .bf-color-list{max-height:310px;overflow:auto;padding:6px 10px 10px}
      .bf-color-row{display:grid;grid-template-columns:minmax(150px,1fr) minmax(180px,1.4fr) auto;gap:8px;align-items:center;padding:8px 2px;border-bottom:1px solid #f5eaee}
      .bf-color-row:last-child{border-bottom:0}.bf-color-model{font-size:12px;font-weight:850}.bf-color-model small{display:block;color:#a09499;font-weight:600;margin-top:2px}
      .bf-color-input{width:100%;border:1px solid #eadce1;border-radius:11px;padding:9px 10px;background:#fff;font-size:12px}
      .bf-default-note{font-size:10px;color:#a09499;margin-top:5px}.bf-style-color-summary small{display:block;color:#9b8f95;margin-top:3px;font-size:10px}
      @media(max-width:680px){.bf-color-row{grid-template-columns:1fr}.bf-color-row .btn{justify-self:start}.bf-color-list{max-height:360px}}
    `;
    document.head.appendChild(s);
  }

  function ensureUI(){
    ensureStyles();
    const input=document.getElementById('style-colors');
    if(!input||document.getElementById('bf-model-color-box'))return;
    const field=input.closest('.field');
    const label=field?.querySelector('label');
    if(label)label.textContent='預設顏色（大部分型號使用）';
    input.placeholder='例如：白色, 黑色';
    const note=document.createElement('div');
    note.className='bf-default-note';
    note.textContent='某個型號沒有另外設定時，前台就使用這裡的預設顏色。';
    field?.appendChild(note);

    const box=document.createElement('div');
    box.id='bf-model-color-box';
    box.className='bf-color-box';
    box.innerHTML=`<div class="bf-color-head"><div><b><i class="fa-solid fa-mobile-screen-button"></i> 各手機型號顏色</b><small>只有不一樣的型號才要填；留空 = 使用上面的預設顏色。</small></div><input id="bf-model-color-search" class="bf-color-search" placeholder="搜尋型號，例如 iPhone 15"></div><div id="bf-model-color-list" class="bf-color-list"></div>`;
    field?.insertAdjacentElement('afterend',box);
    const modalBox=document.querySelector('#style-modal .box');
    modalBox?.classList.add('wide');
    document.getElementById('bf-model-color-search')?.addEventListener('input',filterRows);
  }

  function filterRows(){
    const q=String(document.getElementById('bf-model-color-search')?.value||'').trim().toLowerCase();
    document.querySelectorAll('#bf-model-color-list .bf-color-row').forEach(r=>{
      r.style.display=!q||String(r.dataset.search||'').includes(q)?'grid':'none';
    });
  }

  function renderModelColorRows(style){
    ensureUI();
    const list=document.getElementById('bf-model-color-list');
    if(!list)return;
    const overrides=(style&&style.model_colors&&typeof style.model_colors==='object')?style.model_colors:{};
    const defaults=cleanList(style?.colors||document.getElementById('style-colors')?.value||[]);
    const models=(shopData.models||[]).filter(m=>m.status!==false);
    if(!models.length){list.innerHTML='<div class="empty">目前沒有手機型號</div>';return}
    list.innerHTML='';
    models.forEach(m=>{
      const row=document.createElement('div');
      row.className='bf-color-row';
      row.dataset.search=`${m.brand||''} ${m.name||''}`.toLowerCase();
      const current=cleanList(overrides[m.id]||[]).join(', ');
      row.innerHTML=`<div class="bf-color-model">${esc(m.name||'')}<small>${esc(m.brand||'')}</small></div><div><input class="bf-color-input" data-model-id="${esc(m.id)}" value="${esc(current)}" placeholder="留空＝預設：${esc(defaults.join('、')||'不分顏色')}"></div><button type="button" class="btn alt mini">使用預設</button>`;
      row.querySelector('button').onclick=()=>{const inp=row.querySelector('.bf-color-input');inp.value='';inp.focus()};
      list.appendChild(row);
    });
    filterRows();
  }

  function collectOverrides(){
    const out={};
    document.querySelectorAll('#bf-model-color-list .bf-color-input').forEach(inp=>{
      const colors=cleanList(inp.value);
      if(colors.length)out[inp.dataset.modelId]=colors;
    });
    return out;
  }

  const originalOpenStyle=window.openStyleEditor;
  if(typeof originalOpenStyle==='function'){
    window.openStyleEditor=function(id=''){
      originalOpenStyle(id);
      const style=getStyle(id);
      renderModelColorRows(style||{colors:cleanList(document.getElementById('style-colors')?.value||[]),model_colors:{}});
      const search=document.getElementById('bf-model-color-search');if(search)search.value='';
    };
  }

  const originalRenderStyles=window.renderStyles;
  if(typeof originalRenderStyles==='function'){
    window.renderStyles=function(){
      originalRenderStyles();
      const rows=[...document.querySelectorAll('#styles-body tr')];
      const styles=shopData.styles||[];
      rows.forEach((row,i)=>{
        const s=styles[i];if(!s)return;
        const cell=row.children?.[2];if(!cell)return;
        const count=Object.keys(s.model_colors||{}).filter(k=>cleanList(s.model_colors[k]).length).length;
        cell.classList.add('bf-style-color-summary');
        const base=cleanList(s.colors||[]).join('、')||'不分顏色';
        cell.innerHTML=`<b>${esc(base)}</b>${count?`<small>另有 ${count} 個型號使用獨立顏色</small>`:'<small>所有型號使用預設顏色</small>'}`;
      });
    };
  }

  window.saveStyle=async function(){
    const id=document.getElementById('style-id').value;
    const prev=id?(shopData.styles||[]).find(x=>x.id===id):null;
    const data={
      ...(prev||{}),
      id:id||'style_'+Date.now(),
      name:document.getElementById('style-name').value.trim(),
      price:Number(document.getElementById('style-price').value)||390,
      colors:cleanList(document.getElementById('style-colors').value),
      model_colors:collectOverrides(),
      mask_img:document.getElementById('style-mask-url').value||'',
      print_x:Number(document.getElementById('style-x').value)||0,
      print_y:Number(document.getElementById('style-y').value)||0,
      print_w:Number(document.getElementById('style-w').value)||80,
      print_h:Number(document.getElementById('style-h').value)||160,
      status:true
    };
    if(!data.name)return alert('請填材質名稱');
    try{
      if(id){const i=shopData.styles.findIndex(x=>x.id===id);shopData.styles[i]=data}else shopData.styles.push(data);
      await saveShop();
      renderStyles();
      closeModal('style-modal');
    }catch(e){alert('儲存失敗：'+(e.message||e))}
  };

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ensureUI,{once:true});else ensureUI();
  console.info('[ADMIN] per-model case colors enabled');
})();
