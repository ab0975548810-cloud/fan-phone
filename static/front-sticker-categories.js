/* 前台貼紙分類完全跟隨後台分類名稱；後台新增/刪除後前台同步 */
(function(){
  'use strict';
  if(window.__benfuwanStickerCategoriesInstalled)return;
  window.__benfuwanStickerCategoriesInstalled=true;

  function adminCategories(){
    const raw=Array.isArray(assetsData?.categories)?assetsData.categories:[];
    return ['全部',...raw.filter((c,i)=>c&&c!=='全部'&&raw.indexOf(c)===i)];
  }

  window.stickerCategories=adminCategories;
  window.renderStickerCats=function(){
    const box=document.getElementById('sticker-cats');if(!box)return;
    box.innerHTML='';
    adminCategories().forEach((c,i)=>{
      const b=document.createElement('button');
      b.className='pill'+(i===0?' active':'');
      b.textContent=c;
      b.onclick=()=>{
        box.querySelectorAll('.pill').forEach(x=>x.classList.remove('active'));
        b.classList.add('active');
        renderStickers(c);
      };
      box.appendChild(b);
    });
  };

  function resetScroll(){
    const sheet=document.getElementById('sheet-sticker');
    if(!sheet)return;
    sheet.scrollTop=0;
    const body=sheet.querySelector('.sheet-body');if(body)body.scrollTop=0;
  }
  const render=window.renderStickers;
  window.renderStickers=function(){const r=render.apply(this,arguments);resetScroll();return r;};
  const open=window.openStickerSheet;
  window.openStickerSheet=function(){const r=open.apply(this,arguments);resetScroll();requestAnimationFrame(resetScroll);return r;};
  // Also covers the existing editable-text sticker category.
  document.getElementById('sticker-cats')?.addEventListener('click',()=>{resetScroll();requestAnimationFrame(resetScroll);});

  console.info('[FRONT] sticker category names now follow admin settings');
})();
