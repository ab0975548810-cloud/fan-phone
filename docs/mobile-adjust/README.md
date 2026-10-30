# 手機物件調整面板修復與驗收

基準：`main e6b041f16121126635dd0cd10f094fe09c73b1ae`。獨立分支 `fix/mobile-adjust-panel`，Draft PR #103。最終 HEAD 與 GitHub CI 結果以 PR 說明／Checks 為準。

## 操作與座標契約

- 調整面板改成畫布下方的精簡工具列，佔實際版面，不使用遮罩擋住畫布。預設提供大小、透明度、角度；X/Y、方向微調、翻轉、層級及形狀樣式收在「更多調整」。可收合／展開，原主工具列仍可操作。
- 大小為加入物件時的基準尺寸 100%，範圍 0.1～300%；模板會依可用空間進一步縮小範圍。兩軸使用同一倍率，保留既有比例。`bfScaleBaseX/Y` 隨歷史及草稿保存，不因開關面板／重新選取而重設。沒有這兩個欄位的舊設計，以首次載入時尺寸建立基準。
- 透明度 0～100%，旋轉 -180～180°；滑桿即時更新物件及數字。數字輸入以 Enter／確認／離開欄位提交，輸入途中不改物件。空值、非數字與越界值提示後恢復上一有效值。
- X/Y 是**畫布左上角原點、X 向右、Y 向下、物件中心位置，單位為邏輯 px**。一般物件中心範圍為各軸 -1～2 倍畫布尺寸；模板限於畫布內。與治具右下角原點的印刷 X/Y 完全不同。
- 滑桿連續預覽只在操作結束建立一筆 Undo；雙指縮放與旋轉共用同一交易。精度保存為 8 位小數，避免 Fabric 原本 2 位小數令 Undo 後比例漂移。
- 單指沿用 Fabric 移動；雙指與面板共用模板權限與使用者鎖定檢查。原有兩套雙指監聽器在新控制器啟用後讓出事件，避免同時修改物件。可編輯文字貼紙以整組底圖權限判斷複製等操作。
- 模板尺寸碰到邊界時，改用一個倍率限制兩軸，避免照片／文字／貼紙被分軸壓縮。
- `VisualViewport` 處理鍵盤縮小可視範圍及偏移；文字輸入使用 16px，減少 iOS 自動放大。縮小可視區時使用精簡列高，收鍵盤後恢復。只修改 CSS 顯示尺寸，Fabric 邏輯畫布尺寸及設計座標不改。

## 可重跑的驗證

新增 `.github/tests/test_adjust_panel.py`，接入現有 `.github/tests/test_ai_editor_webkit.py`；沒有修改 CI workflow 權限。

| 範圍 | 驗證內容 |
|---|---|
| WebKit／Chromium | 手機殼、獨立鏡頭底膜；375×667、390×844、844×390、1180×900；面板開合後完整畫布在保留區內 |
| 精確操作 | 數字確認前不修改、三組滑桿同步、非法值還原、中心 X/Y、每次微調 1px、文字大小不改字框／字級 |
| 歷史與手勢 | 連續滑桿與雙指操作只增加一筆；Undo/Redo 後基準保留；Chromium CDP 單指真實觸控輸入；雙引擎 DOM 雙指縮放／旋轉 |
| 權限 | 使用者鎖定、模板禁止移動／縮放／旋轉／編輯、鎖定照片框，直接派送事件仍不得繞過 |
| 鍵盤 | 模擬 visualViewport 440px 高與 offsetTop 12px，確認輸入欄可見、完整畫布不重疊；恢復後座標不變 |
| 輸出 | 手機殼 2126×4252、鏡頭底膜 1899×1332，均 720 DPI；面板開合／重排前後完整 production PNG 完全一致 |
| 既有回歸 | PR #82 模板／照片框／可編輯文字貼紙、#97 預覽與生產像素及透明度、#99 商品流程、#100 4K 相片縮放／形狀／字型／素材，沿用完整瀏覽器測試 |

執行：

```text
python smoke_test.py
python test_commerce.py
python test_print_center.py
python test_multilayer_templates.py
python .github/tests/test_ai_editor_webkit.py
BROWSER_ENGINE=chromium python .github/tests/test_ai_editor_webkit.py
```

本機 Smoke 通過；Commerce 29 項（2 項 PostgreSQL-only 由 CI 執行）、Print Center 90 項、模板契約 19 項通過。完整雙瀏覽器與最終 HEAD 的 PostgreSQL 17、Smoke、Commerce CI 證據列在 PR 說明。測試僅使用隔離本機／CI 資料、mock vendor；沒有正式送單或實體列印。

## 相同測資修復前後截圖

修復前由 `origin/main` 原始前端檔案重跑同一測資產生，沒有以修復版冒充舊版。

| 產品 | 修復前（WebKit） | 修復後（WebKit） |
|---|---|---|
| 手機殼 | [截圖](before-phone_case-webkit.png) | [截圖](after-phone_case-webkit.png) |
| 鏡頭底膜 | [截圖](before-camera_film-webkit.png) | [截圖](after-camera_film-webkit.png) |

另附 [Chromium 手機殼](after-phone_case-chromium.png)、[Chromium 鏡頭底膜](after-camera_film-chromium.png)、[WebKit 鍵盤可視區模擬](keyboard-phone_case-webkit.png)、[鏡頭底膜鍵盤模擬](keyboard-camera_film-webkit.png)。鍵盤圖下方空白代表被鍵盤佔用的可視區外空間，不是實體 iOS 鍵盤截圖。

## 邊界與剩餘驗收

沒有修改 `front-production-hq.js`、`front-print-mask.js`、商品型號 profile、印刷 W/H/X/Y、刀模 PNG、訂單、庫存、Print Center 或銳印設定。PR #102 的母版分支沒有修改／合併。

自動化 WebKit 並不等於實體 iPhone Safari；本輪沒有實機鍵盤／手感／實體 UV 印刷校準證據。實機確認仍需人工驗收。PR 保持 Draft，沒有合併或部署。
