# 前台貼紙 Load failed 修復

基於 main `44ed440afd521af6c68477953e6e56f262ba790d`，獨立分支 `fix/sticker-load-recovery`。

## 根因與實際證據

2026-11-13 使用 WebKit、390×844、觸控模式，唯讀正式站「iPhone 17 Pro Max／鏡頭底膜」，點選素材 `s_89ad5100393e`。

`addStickerImage()` 直接把素材外部網址交給 Fabric。圖片載入及解碼成功，畫布內已存在寬 489px 的貼紙。但自動存草稿的 `BenfuwanDraftStore.freezeImage()` 又對同一外部網址執行 `fetch()`。正式站 `connect-src 'self'` 不允許這個請求；WebKit 拋出 `TypeError: Load failed`，`warnSave()` 直接把英文錯誤顯示在黑色提示中。

失敗網址：`https://sazoqqgeabjiyzbihpdy.supabase.co/storage/v1/object/public/case-assets/stickers/97b1e5a9a6b8430d8bd55ff38407f4b7.png`。這次重現的根因是 **CSP 阻擋草稿下載**，不是這張圖片損壞，也不是 Fabric 沒有加入圖片。直接圖片載入的 CORS／解碼失敗則是同一路徑另外缺少防護的情境，一併修復並測試。

| 證據 | 修復前 | 修復後 |
|---|---|---|
| WebKit 畫面 | [黑色 Load failed](before-webkit.png) | [同一貼紙成功加入](after-webkit.png) |
| 請求及結果 | [CSP 拒絕、draftSaved=false](before-network.json) | [同源代理 HTTP 200、draftSaved=true](after-network.json) |

修復後證據使用瀏覽器本機覆寫本分支程式，讀取相同正式公開素材及現有代理 API；沒有部署正式站。所有正式站非 GET／HEAD／OPTIONS 請求均阻擋。補拍修復前提示時只顯示第一張貼紙，避免一次請求整個素材庫縮圖。畫布與資料保存僅在測試瀏覽器本機，沒有正式訂單。

## 修復契約

- 共用 `editor-image-loader.js`：外部網址走既有 `/api/public/asset_proxy`，保留代理來源限制及 CSP，不增加外部白名單。
- 先取得原始 PNG/JPEG/WebP 位元組並成功解碼，再把帶 data URL 的 Fabric 物件加入畫布；不改圖、不重新縮圖、不填白底。草稿及 Undo 不必再次下載外部素材。
- 舊版網址形式的草稿圖片也改走同一下載入口。原有 IndexedDB 原子寫入、衝突處理及購物車流程不變。
- 每次下載 8 秒，網路／逾時／429／5xx 最多重試一次；解碼最多 5 秒；整個貼紙加入操作最多 23 秒（含文字字型等待）。永久 HTTP 失敗、格式／解碼錯誤不無限重試。
- 顯示載入狀態，按鈕標記 busy；連點或多張同時加入只接受第一個進行中的操作。完成或失敗後恢復按鈕。
- 失敗不加入半成品、不更動畫布／Undo／已保存草稿；切換畫布、清除或離開編輯器後的延遲結果不加入。
- 照片貼紙與文字貼紙共用入口，文字背景和文字成員在載入完成後才加入；下載錯誤以繁體中文提示，草稿保存失敗明示原草稿保留。
- 縮圖延遲載入，避免開啟素材庫同時下載全部 452 張圖片。

## 回歸

新增 `.github/tests/test_sticker_loading.py`，接入原本 WebKit／Chromium CI 入口：

- 同樣 CSP 下舊版真正重現 Load failed；修復版不放寬 CSP 即可保存。
- 手機殼及鏡頭底膜、原始圖片 bytes 一致、透明 alpha、同源代理、真正跨來源無 CORS 回應。
- 404、損壞 PNG、斷網、實際 offline 模式、503 後成功、逾時、快速連點、離開編輯器後才回應。
- 失敗前後完整畫布 JSON、Undo index 與 IndexedDB 已保存草稿一致。
- 貼紙縮放、旋轉、移動、刪除、Undo／Redo；文字貼紙失敗恢復及成功成對加入。
- 頁面重載後恢復草稿、購物車保存與回編、720 DPI 生產 PNG、透明背景。
- 沿用完整瀏覽器套件的母版適配、照片框、文字貼紙、草稿衝突、受保護送單及生產圖一致性回歸。

最終 SHA、Smoke、Commerce（含 PostgreSQL）、Print Center、WebKit／Chromium 結果列於 Draft PR 說明。

未修改列印 W/H、X/Y、刀模 PNG、正式訂單、庫存或銳印流程。沒有正式寫入、合併或部署。WebKit 自動化不等於實體 iPhone Safari 驗收。
