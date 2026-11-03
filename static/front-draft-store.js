/* Local guest designs. Each revision owns its blobs, so deletion is atomic. */
(function () {
  'use strict';
  const first = 'design-draft-v1';
  const range = IDBKeyRange.bound(first, first + ':\uffff');
  const prefix = 'draft-image:';
  let imageCache = new Map();

  async function list() {
    const db = await openIdb();
    return new Promise((resolve, reject) => {
      const rows = [];
      const req = db.transaction(IDB_STORE).objectStore(IDB_STORE).openCursor(range);
      req.onerror = () => reject(req.error);
      req.onsuccess = () => {
        const cursor = req.result;
        if (!cursor) return resolve(rows.sort((a,b) => b.updatedAt.localeCompare(a.updatedAt)));
        const {name, updatedAt, revision} = cursor.value;
        rows.push({key:cursor.key, name:name || '未命名設計', updatedAt:String(updatedAt || ''), revision});
        cursor.continue();
      };
    });
  }

  async function change(key, expected, update) {
    const db = await openIdb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, 'readwrite'), store = tx.objectStore(IDB_STORE);
      let conflict = false;
      store.get(key).onsuccess = event => {
        const previous = event.target.result;
        if ((previous?.revision || previous?.updatedAt || null) !== expected) {
          conflict = true;
          tx.abort();
          return;
        }
        const next = update(previous);
        if (next) store.put(next, key);
        else store.delete(key);
      };
      tx.oncomplete = resolve;
      tx.onabort = () => reject(Error(conflict ? '另一分頁已修改這份草稿，請重新開啟草稿。' : tx.error?.message || '草稿寫入失敗'));
      tx.onerror = () => reject(tx.error);
    });
  }

  async function walk(node, visit) {
    if (!node || typeof node !== 'object') return;
    await Promise.all(Object.entries(node).map(async ([key,value]) => {
      if (typeof value === 'string') node[key] = await visit(value,key);
      else await walk(value,visit);
    }));
  }
  async function freezeImage(src) {
    let blob;
    if (src.startsWith('data:')) {
      const comma = src.indexOf(','), header = src.slice(5,comma), body = src.slice(comma+1);
      const type = header.split(';')[0];
      blob = header.endsWith(';base64')
        ? new Blob([Uint8Array.from(atob(body), c => c.charCodeAt(0))],{type})
        : new Blob([decodeURIComponent(body)],{type});
    } else {
      const response = await fetch(src);
      if (!response.ok) throw Error('圖片無法保存，請確認連線後再試。');
      blob = await response.blob();
    }
    const bytes = new Uint8Array(await crypto.subtle.digest('SHA-256', await blob.arrayBuffer()));
    const ref = prefix + Array.from(bytes, b => b.toString(16).padStart(2,'0')).join('');
    return {ref,blob};
  }
  async function pack(draft) {
    const assets = {}, used = new Map();
    await walk(draft.canvasJson, async (value,key) => {
      if (!value || !(/^(data:image\/|blob:)/i.test(value) || key === 'src')) return value;
      let work = imageCache.get(value) || used.get(value);
      if (!work) work = freezeImage(value);
      used.set(value,work);
      const {ref,blob} = await work;
      assets[ref] = blob;
      return ref;
    });
    imageCache = used;
    return {...draft,assets};
  }
  async function unpack(raw) {
    if (!raw?.assets) return raw;
    const {assets,...draft} = raw, urls = new Map();
    await walk(draft.canvasJson, async value => {
      if (!value.startsWith(prefix)) return value;
      if (!assets[value]) throw Error('草稿缺少原始圖片，已保留草稿。');
      if (!urls.has(value)) urls.set(value,blobToDataURL(assets[value]));
      return urls.get(value);
    });
    return draft;
  }
  window.BenfuwanDraftStore = {list,change,pack,unpack,resetImages:()=>{imageCache=new Map();}};
})();
