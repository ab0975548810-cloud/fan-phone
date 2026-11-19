/* Private order-edit recovery. The saved server version remains authoritative. */
(() => {
  'use strict';
  const prefix = 'pixel-order-recovery:';
  async function access(mode, callback) {
    const db = await openIdb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, mode);
      const request = callback(tx.objectStore(IDB_STORE));
      tx.oncomplete = () => resolve(request.result);
      tx.onabort = () => reject(tx.error || Error('本機草稿交易中斷'));
      tx.onerror = () => reject(tx.error || Error('本機草稿存取失敗'));
    });
  }
  window.BenfuwanPixelRecovery = {
    read: order => access('readonly', store => store.get(prefix + order)),
    write: (order, value) => access('readwrite', store => store.put(value, prefix + order)),
    remove: order => access('readwrite', store => store.delete(prefix + order))
  };
})();
