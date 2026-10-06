# Multi-layer Template V1

沿用 templates JSON／objects_json、Fabric 5.3.1、現有模板 editor lazy loading、圖層面板與 #71 私有原圖／deterministic 720 DPI renderer。無 DB migration。

## 契約

模板保留 `template_version >= 2`，另外標示 `layer_contract_version: "multilayer-v1"`。objects_json 每個物件是獨立 Fabric layer，不儲存合成模板 PNG 作為生產來源。thumb_url 仍只是列表預覽。

每層包含：layerId、templateLayerId、layerInstanceId、layerName、role、assetId／src、normalizedGeometry、angle、opacity、zIndex、locked、canMove、canScale、canRotate、canDelete、canDuplicate、canEdit。保留原 Fabric 字型／fill／stroke／flip／clip／slot／editable sticker metadata。

normalizedGeometry 的 x/y 為物件**中心**相對 logical canvas 的比例；width/height 為未旋轉可見尺寸比例（包含實際 stroke）。全部 0～1。angle 單獨保存，不用旋轉後 bbox 重寫來源幾何。每種 target canvas 都以此重建中心與 X/Y scale，包含 reset／draft／history／production，避免 Fabric 預設兩位小數導致尺寸漂移。

templateLayerId 在不同客戶套用間不變。每次套用有 server-issued application UUID；原 layerInstanceId 為 applicationId:templateLayerId。複製保留 source identity、產生新 instance UUID，duplicateOf 指向原 instance。editable sticker 仍為獨立 Image／Textbox、共用自己的 pair instance UUID，textArea 比例不變。

## 後台

新建模板預設啟用多圖層，背景為獨立 locked layer。舊模板預設原流程，只有作者明確勾选才轉成新契約；已保存的多圖層不得靜默降級。

加入 PNG 圖層支援多檔，每個原始 PNG 獨立上傳、載入與編輯。新增 source_contract flag 沿用既有 admin upload API，保留原始 PNG bytes，不經模板預覽的 WebP／縮圖最佳化；僅此 flag 分支改變。原始素材上限 10MB／32MP，模板合計 70MB／64MP。

圖層列表包含名称、類型、客人鎖定、顯示／隱藏、上移／下移、六種編輯權限。作者可調整鎖定物件；鎖定規則只限制客人。文字貼紙兩個成員權限一起更新。普通文字使用 #71 固定站內字型；保存仍走 templatesVersion／expected_version／STALE_DATA。列表不載入 heavy Fabric stack，點建立／編輯才 lazy-load。

## 前台與恢復

新契約走 normalized mapping；舊 v1/v2/v3 沒有 marker 則走原 adaptation。

locked layer selectable/evented=false，不能攔截下方物件點擊，也不提供刪除、複製、移動或其他修改。unlocked 依權限開放 native Fabric 單指／控制點、雙指縮放／旋轉、翻轉、複製、圖層順序及文字編輯。雙指輸入只對多圖層 Canvas 接管，不更動舊手勢。

恢復原模板使用 immutable initial state，只替換本次 application 的原 layer／duplicate／slot photo；客人另外加入的照片／素材保留。照片框使用獨立 placeholder，換照保留完整原圖與 native crop；reset 回 placeholder。sourceSize 是原始 intrinsic size，Fabric width/height 可為裁切 viewport；#71 仍驗原始 bytes／尺寸／裁切範圍。

草稿／history 保存 current layers＋initial state。購物車／order 去掉 reset snapshot，保存 current normalized layers、empty slot manifest 和 template binding，走原 HQ cart gate。sources 仍先逐張上傳 private storage，design_json 不塞原圖 Base64。

## Server authority／Print

只讀 GET `/api/template_contract/<id>?model_id=...&style_id=...` 核對 catalog 後回傳模板與 binding（模板 hash、model/style、application UUID、簽名 ticket），綁定現有 client identity，24h 有效。恢復／加入購物車會重新核對版本與取得新 ticket；模板已更新則 fail closed，不偷偷改客人排版。

Admin 保存時驗 canonical layer IDs、geometry、權限與 original PNG pixel hash。建單再次依 server templates JSON 核對 ticket、原圖、鎖定／各權限、必要原 layer、duplicate identity、順序與內容。不能把 client locked=false 當權限。新訂單存 server authority snapshot 及 order-bound HMAC seal；Print Center 使用歷史 sealed contract，不依賴日後模板內容。

720 DPI renderer 使用原 #71 隔離 Chromium／相同字型／Fabric／print mask shared crop：normalized layers＋original source＋z-order＋文字＋opacity／rotation／flip 重建。locked 只是 UX 權限，不影響輸出。修改 seal／素材缺失／字型版本不符皆 fail closed，不改用 screenshot 或低解析 preview。

需要穩定 FLASK_SECRET_KEY（沿用現有 production 前置）；更換 secret 會使既有 signed layer contract 無法驗證，需先規劃金鑰輪替。此 PR 不設定正式環境，不部署、不 merge、不實體列印。

## 測試

後端測試：canonical schema／CAS／legacy、權限／identity／geometry／source tamper、private source snapshot、native slot crop、歷史 seal、原始 PNG 保存、30-layer 720 DPI rebuild。

Browser：真實 Admin 建立 30 layers，locked hit-through、拖曳、雙指、duplicate/delete、hide/order、ordinary text／editable text、slot／reset、draft reload、三種 iPhone normalized mapping、390／768／1180、原 HQ preview/cart。Chromium 用 CDP multi-touch；WebKit 用帶 touches 的 DOM Event 經公開輸入 handler（Linux WebKit 不允許 Touch constructor，Playwright WebKit 無 CDP），不直接設定 transform 假測手勢。實機 Safari 驗收仍應另做。

無多選／新 Group／吸附／自動對齊／協作編輯。
