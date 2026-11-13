# 母版跨型號適配 V1：架構審查、重現與驗收

基準：`e6b041f16121126635dd0cd10f094fe09c73b1ae`（2026-10-26 同步 main）。
所有寫入都在本機／GitHub CI 的隔離 JSON、SQLite、Storage 目錄進行；正式模板、訂單及設備未操作。

## 先重現，再改入口

原本 `index.html` 的安裝順序：base `applyTemplate` → universal → precision → normalized-v5 → front-multilayer → alignment-v6。

- Legacy universal：v6 最外層把 `template_version` 改為 0，實際繞過 precision / normalized / universal 的轉換。問題不是每次必定轉四次，而是各版本有不同規則、入口太多。
- v6 將物件中心分別乘 `dstW/srcW`、`dstH/srcH`，尺寸卻只乘兩者最小值。因此物件本身可能不變形，但相對距離改變；slot 也有相同問題。
- multilayer 的 `map()` 依 normalized width/height 分別映射兩軸；不同畫布比例會使照片框、圖案及字形拉伸。
- 後台 normalized-v5 儲存中心／尺寸比例；multilayer 儲存 `sourceCanvas` 及 normalized geometry。這些原始比例可以保留，不能把兩軸映射當作等比例構圖。
- 生產端 #71 的 deterministic renderer 已透過 multilayer `prepareRender()` 重建 normalized layers；若只改客戶畫布、不改授權的 target geometry，固定圖層會被拒絕，或生產圖與編輯器不同。

真實尺寸重現：iPhone 13 的 78.87 × 152.15 mm → iPhone 17 Pro 的 71.63 × 149.61 mm。
舊 rx = 0.90820337、ry = 0.98330595；兩軸相差 8.269%。100 source px 的垂直間距變成 98.3306，而物件高度只變成 90.8203，間距相對物件失衡 7.5103 px。
此數值案例在 `test_reproduces_old_spacing_and_multilayer_stretch` 中保留，另使用四個正式公開刀模衍生 fixture 做實際 Fabric 對照。

## 單一新引擎與相容邊界

`template_adaptation.py` 是 `master-v1` 唯一轉換／碰撞引擎。後台預覽、批次另存、前台授權、伺服器固定圖層驗證都讀同一結果，不在前台追加另一層幾何 wrapper。

- 母版使用 `adaptation_contract_version: master-v1`，保留原始 `objects_json`、source canvas、source print dimensions、model/style reference。
- 新後台入口先從現有多圖層編輯器擷取原始母版，保留素材、圖層、文字、照片框與權限。舊版模板可由現有編輯器確認後另存母版；不自動改寫正式舊模板。
- `scale = min(targetWidth / sourceWidth, targetHeight / sourceHeight)`；以來源／目標畫布中心建立一組仿射轉換。所有普通元素共用同一 scale 與 translation。
- target logical canvas 精確對應現有 `Math.round(mm × 3)`；引擎回傳 admin units = customer units / 1.5，不更動 editor 或 720 DPI 的尺寸規則。
- normalizedGeometry 為來源真值，避免再乘已被 Fabric 兩位小數截短的 raw scale。生成的新裁切欄位也遵守既有 Fabric 序列化精度，未放寬 locked-layer 驗證。
- 背景只有明確標記 `background-crop` 才做 source viewport 的等比例 cover 裁切。未標記主體、文字、slot 與裝飾不拉伸、不逐物件亂搬。字型、fontSize、Textbox width、行距等保持原始內容，不重新排字來塞空間。新母版停用 Fabric 的中間 object bitmap cache，與既有 deterministic renderer 一樣直接繪製原始字型與素材；舊模板行為不變。
- 舊 precision / normalized-v5 不再在前台下載／安裝；legacy v1/v2 仍由現有 alignment-v6 單次相容轉換。既有多圖層、沒有 master 契約的模板保持原路徑。

策略欄位 `adaptationRole`：保留構圖、主視覺、重要文字、可裁切背景、可移動裝飾。裝飾可由店主逐型號單獨位移；其他元素維持整組比例。

## 刀模、安全區與失敗處理

- 讀取 model × style 已配置的完整 print mask source frame，保留相機孔及所有透明區；不改 PNG、不用 alpha bbox 重定義 editor geometry。
- bounded 分析 mask 長邊 384 sample pixels，alpha ≥224，以保守 min-pooling 確保高解析細孔不被平均掉，再向內保守縮 2 sample pixels。這是程式保守安全邊界，並非實體刀模校準或保證印刷公差。
- 旋轉後完整物件矩形 footprint 做碰撞檢查；對透明裝飾採保守外接範圍，可能需要人工微調，避免誤判安全。
- 預設先保持構圖；若有碰撞，依距離由小到大嘗試 1% 格點、最多各軸 4% 的整組位移。不拉伸、不自動改文字大小、不猜主體。
- 超出可表示 geometry、碰孔、碰安全邊界皆為 `needs-adjustment`；缺檔／無法讀取為失敗，無 generic safe box fallback。
- 無法安全適配的版本不能批次發布，也不能在前台當作成功套用。店主可對單一型號調整構圖位置／等比例大小，或微調標記裝飾，再重新檢查。
- 素材／字型載入失敗不生成成功預覽；API 故障不改模板。圖片遮罩按 URL 最多快取 32 項、60 秒，失敗不快取；正式素材沿用不可變資產 URL。

## 後台批次另存

多圖層編輯器新增「母版跨型號適配」。一次列出 active 且有完整有效 W/H/X/Y/angle、preview/print mask 的手機殼 model × style；鏡頭底膜及未配置型號排除。

1. 原始母版及元素策略先顯示。
2. 依序取得所有型號預覽，顯示成功／需要微調／失敗。
3. 每個型號可獨立微調，重新預覽；未通過者不能儲存。
4. 店主確認後，使用同一 `templates` JSON 與 revision CAS 一次另存新母版＋所選型號版本。原模板完全保留；重複 click / stale version 不能重複提交。
5. 型號版本保存 master ID/hash、target model/style、profile/mask hash、override 及碰撞報告。禁止拿型號版本再做二次適配。
6. 前台有已確認的 exact variant 時優先顯示；新增有效型號沒有 variant 時可從原始母版即時計算。刀模或設定已變更的 exact variant fail closed，須重新預覽。已確認版本另有 content hash；直接修改幾何不能沿用舊的成功報告，須從母版重新驗證。
7. 新儲存 endpoint invalidates `/api/templates`；UI 從 server reload，錯誤與 CAS conflict 留在對話框，不吞掉。

新 API 僅沿用既有資料來源，無 DB schema/migration：

- admin-only `GET /api/admin/template-adaptation/targets`
- admin-only `POST /api/admin/template-adaptation/preview`
- admin-only `POST /api/admin/template-adaptation/save`
- public legacy master application `GET /api/template_adaptation/<id>`
- multilayer 沿用 `/api/template_contract/<id>`，新增 target geometry hash 綁定。固定圖層檢查以相同 target geometry 作 authority，customer 不能調整權限或偽造 target transform。

## 實際對照與量測

2026-10-26 唯讀查核正式公開 catalog，實際有 **19 組有效手機殼 model × style**（含晶彩／鏡面及 17/18 Pro Max）。已下載各組公開 print mask 並衍生離線 fixture；沒有登入或寫入 production DB。來源 URL、原始尺寸、SHA256 與完整 W/H/X/Y/angle 均保留於 [fixture catalog](../../.github/tests/fixtures/current_case_profiles/catalog.json)，production 數值原封不動。

**目前正式 19 組 × 五種構圖 = 95 組／引擎**，WebKit、Chromium 都用真實 Fabric 繪製。這五份保守母版各 95 組均通過；額外負向測試仍會正確回「需要人工微調」。此結果不代表任意母版都能安全通過。

每列五張圖，依正式 catalog 順序各呈現四組（最後三組），同頁為舊分軸映射／新統一引擎：

| 構圖 | 1–4 | 5–8 | 9–12 | 13–16 | 17–19 |
|---|---|---|---|---|---|
| 單張滿版 | [對照 1](current-full-image-1.png) | [對照 2](current-full-image-2.png) | [對照 3](current-full-image-3.png) | [對照 4](current-full-image-4.png) | [對照 5](current-full-image-5.png) |
| 多照片框 | [對照 1](current-photos-1.png) | [對照 2](current-photos-2.png) | [對照 3](current-photos-3.png) | [對照 4](current-photos-4.png) | [對照 5](current-photos-5.png) |
| 文字＋貼紙 | [對照 1](current-text-sticker-1.png) | [對照 2](current-text-sticker-2.png) | [對照 3](current-text-sticker-3.png) | [對照 4](current-text-sticker-4.png) | [對照 5](current-text-sticker-5.png) |
| 主視覺＋重要文字 | [對照 1](current-subject-title-1.png) | [對照 2](current-subject-title-2.png) | [對照 3](current-subject-title-3.png) | [對照 4](current-subject-title-4.png) | [對照 5](current-subject-title-5.png) |
| 29 層＋可編輯文字貼紙 | [對照 1](current-mixed-1.png) | [對照 2](current-mixed-2.png) | [對照 3](current-mixed-3.png) | [對照 4](current-mixed-4.png) | [對照 5](current-mixed-5.png) |

[Chromium 95 組逐層量測](chromium-current-metrics.json)／[WebKit 95 組逐層量測](webkit-current-metrics.json)。另外保留四款歷史公開素材的 20 組相容矩陣，避免更新 fixture 掩蓋先前案例。

當前明顯比例差案例：17 Pro 晶彩 71.63 × 149.61 mm 與鏡面 71.88 × 102.53 mm，不能把 x/y 各自拉滿；新引擎維持整組比例，背景才使用明確裁切策略。

以下歷史四個 model 的素材來源、尺寸與原始公開 URL 由既有 `.github/tests/fixtures/production_shop_data_mask_contract.json` 記錄：iPhone 13、14、14 Pro Max、17 Pro。沒有用另一個型號代替 fixture。

下圖為**實際 Fabric 舊分軸映射／新統一適配**，非設計示意稿或人工修圖；五種構圖 × 四個真實 mask = 20 組，兩個 browser engine 都執行。測試照片使用合成圖形，未使用客戶照片。

| 類型 | 對照圖 |
|---|---|
| 單張滿版圖片（明確允許背景裁切） | [full-image.png](full-image.png) |
| 多照片框 | [photos.png](photos.png) |
| 文字與貼紙 | [text-sticker.png](text-sticker.png) |
| 人物主視覺與重要文字 | [subject-title.png](subject-title.png) |
| 29 層混合構圖（含獨立文字貼紙配對） | [mixed.png](mixed.png) |

額外以左側、右側相機孔及無可用安全區的 mask 驗證碰撞／失敗分支，含 rotation、absolute clip、legacy slots 及裝飾 overrides。

實測 affine residual：最大長寬比誤差約 `1.78e-15`、相對距離誤差約 `2.85e-14` admin logical px；瀏覽器再逐層測量實際 Fabric 比例，不只信任 server 報告。完整每層來源／目標位置、尺寸、角度、碰撞及實際 Fabric 結果：

- [Chromium 20 組量測](chromium-metrics.json)
- [WebKit 20 組量測](webkit-metrics.json)

此外，以同一份 29 層母版逐一對目前正式 **19 組**設定完成隔離 source pre-upload、建單、Print Center 720 DPI 重建；各筆 Print Job 的 W/H/X/Y/angle 均與 fixture 保存的正式參數逐一相等。此 19 組生產矩陣使用 Chromium（正式 deterministic renderer 同引擎）；WebKit 對 19 組執行完整套版／量測，另測五種構圖的高解析前台→生產一致性。

逐型號重建亦重現並修復 Fabric 的浮點邊界雜訊（1 + 2e-16）。只有距離 0／1 小於 1e-12 的值會被正規化；未放寬真正越界驗證。24 筆 Chromium 生產結果（五種構圖＋19 型號）列於下方 JSON。

每種設計另實際走 #71 source pre-upload → 隔離 create_order → Print Center prepare → Chromium/Fabric 720 DPI 重建。iPhone 17 Pro 結果均為 **2030 × 4241 px / 720 DPI**；文字換行一致、位置誤差 <0.0002 logical px，相機孔中心兩份輸出 alpha 都是 0。

比較前台原有 HQ PNG 與重新重建 PNG 時，透明 RGB 值在瀏覽器間未定義，因此分開比較白底合成色彩與 alpha。另因 Linux WebKit／Chromium 原生文字邊緣渲染不同，文字以相同站內字型 hash、精確 fontSize、逐行內容與位置驗證；非文字區維持平均通道誤差 <0.75 / 255、整圖 alpha 平均誤差 <0.75 / 255。完整色彩誤差仍原樣記錄，不隱藏 native text raster 差異。Windows 本機可見平均誤差 <0.16 / 255、alpha <0.59 / 255；Linux CI 數值會由同一測試重新驗證。完整逐設計結果：

- [Chromium 生產一致性](chromium-production.json)
- [WebKit 生產一致性](webkit-production.json)

測試亦涵蓋批次 UI 真實按鈕、逐型號調整不改母版／其他型號、儲存失敗留在 modal、CAS、未登入 401、cache invalidation、固定圖層防竄改、profile 改變後舊 geometry 授權失效、390／768／1180 無水平溢出。

對照圖、逐層量測及 production 結果已隨 PR 收錄於本目錄；CI 從既有瀏覽器入口重跑相同專項，失敗會阻擋原有 job，無需修改 workflow 權限。完整既有 Smoke、Commerce、PostgreSQL、Print Center、WebKit／Chromium 回歸仍為 PR gate。

## 剩餘限制

- 無法由像素自動辨識臉或文字的重要性；店主需標記主視覺／重要文字。滿版可裁切背景可能包含人臉，需由店主判斷是否應改列主視覺。
- V1 不對群組、skew 做近似適配；保留為舊模板，提示另行整理。碰撞採保守矩形，可能產生需要微調的結果，並不保證任意母版適合任意手機。
- 實體 iPhone 的手感、實際 UV／刀模印刷公差尚未量測；不以程式數值取代店主視覺與真機驗收。
- 無正式模板遷移／改寫；既有模板需經後台另存及確認才啟用新契約。歷史訂單及既有 sealed 生產資料保持原樣。
- 正式發布需人工 review、備份既有模板資料與素材，部署程式後由店主用新入口確認另存；本 PR 未部署、未套 migration、未呼叫 vendor。
