# 重新編輯測試模式交付狀態

本分支從 main 的 d1484cc 建立。正式資料庫無 Migration。獨立編輯服務將設計副本、修改版、測試製作單及假設備收據寫入自己的私有磁碟。

## 憑證核對

店主使用平常的 Passkey 重新登入。登入安全頁會在實際通過 WebAuthn 驗證的註冊紀錄標示「本次登入驗證的憑證」並顯示 SHA-256 指紋。請核對建立時間、最後使用時間及完整指紋。名稱相同的其他憑證有不同指紋。同步同一筆 Passkey 的裝置共用這個身分。店主另外確認後，才可將完整指紋加入 ADMIN_REEDIT_TEST_CREDENTIAL_SHA256。現階段名單保持空白。

## 停用與回退

先在私有 QA 服務的掛載磁碟執行 `python private_reedit_wsgi.py revoke`。這會持久停用匯入並清除工作階段和待兌換交接。再把正式端 ADMIN_REEDIT_TEST_ENABLED 設為 false，輪換 ADMIN_REEDIT_GENERATION，使舊簽章永久失效。檢查已開啟分頁、私有圖片、儲存與完成製作都回絕後，回退至變更前記錄的正式 Railway deployment ID。正常訂單及印務服務持續運作。隔離環境的停用紀錄應保留；再次啟用需經核准，使用新的授權世代與全新空白磁碟。

## 隔離服務設定

使用獨立 HTTPS 主機、服務及掛載點 `/private-reedit`。啟動命令是 `gunicorn -c private_reedit_gunicorn.py private_reedit_wsgi:app`。正式服務原有的 Gunicorn 設定會啟動正式交接背景工作，切勿拿來啟動私有編輯服務。獨立服務只需要自己的 PRIVATE_REEDIT_SESSION_SECRET、專用 ADMIN_REEDIT_TRANSFER_KEY、兩端固定的 HTTPS 來源 ADMIN_REEDIT_SOURCE_ORIGIN 與 ADMIN_REEDIT_PRIVATE_ORIGIN。配對密鑰透過 Railway 私密變數設定，不提供給瀏覽器。限制隔離出口到正式授權回查與貼紙清單指定的公共素材儲存來源。

正式端使用相同的私有站網址及配對密鑰、獨立的授權世代、經店主確認的完整指紋及預設關閉的開關。現有共用密碼 QA 主機不可當作目的地。測試部署需先驗證正式站和隔離站各自使用 host-only Cookie。正式編輯開關、真實設備帳密及客戶 Session 金鑰不傳到隔離站。

## 測試資料與保存期限

正式端只投影設計欄位並讀取同訂單的原圖、預覽、封存刀模與素材。隔離端驗證傳輸簽章與每份檔案雜湊。瀏覽器會自動回到來源站驗證本次 Passkey 和隔離站的隨機挑戰。一次性交接 45 秒，權限自 Passkey 驗證起最長 15 分鐘。相同授權世代、管理員及未變動來源設計，可重新由訂單列表進入相同工作區。操作紀錄只留測試工作區、管理員代碼、操作與時間。

隔離服務在啟動時並每分鐘清理滿七天的工作區。到期當下即拒絕私有請求。可另行執行 `python private_reedit_wsgi.py cleanup`。設計 JSON、圖片、暫存上傳、工作副本、B/C、假設備收據皆在同一個到期目錄。部署時確認私有磁碟的備份、外部日誌、APM 及快照留存政策，避免將圖檔、請求本文或交接資料另行保存。從備份回復時，先隔離網路、清除過期資料及舊工作階段，再依新核准重建環境。

## 可重跑驗收與上線關卡

`python test_passkey_auth.py` 驗證註冊、實際 WebAuthn 驗證、錯誤來源、未列名憑證、單次兌換、撤權、關閉開關、服務失聯、匯入失敗的原子性、七天刪除及來源檔案逐位元一致。專用的 `.github/tests/test_private_reedit_browser.py` 在兩個本機 HTTPS 來源實際操作後台列表與前台編輯器，分別以 BROWSER_ENGINE=webkit、chromium 執行。真實收到的付款、扣庫存與設備端點未掛載於測試服務。

部署前需另行確認私有服務的磁碟、記憶體上限、存取日誌與回退版本。單一交接限制在 96 MiB，每個正式工作程序最多同時匯出一單；PNG 解碼和快照打包仍需額外記憶體。若 Railway 配額或網路無法在驗證期限內完成，操作會拒絕，應先在相同規格測試服務量測。正式來源唯讀盤點與隔離測試結果須分別解讀；真實正式列表的交接及實體 iPhone 驗收須另行部署核准後才能執行。
