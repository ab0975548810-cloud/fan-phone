# 可編輯文字貼紙 V1

此版本使用既有 assets JSON、templates.objects_json、orders.design_json；不新增資料表或 migration。

## 素材

`assets.editable_stickers[]`：`id/name/imageSrc/intrinsicSize/textArea/defaultTextStyle`。
安全區 `{x,y,width,height}` 全部相對原始 PNG、0～1、不可超出圖片。
預設樣式含 text/fontFamily/fontSize/minFontSize/fontWeight/fontStyle/fill/stroke/strokeWidth/textAlign/charSpacing/lineHeight。
fontSize/minFontSize 使用原圖座標單位，跟隨整組縮放。後台拖曳安全區、右下角調整大小，也可輸入比例。
保存沿用 assetsVersion / expected_version / STALE_DATA；普通 stickers 陣列不變。

## 物件與字型

每個實例包含 Image 與 Textbox，`editableStickerId` 識別款式、`editableStickerInstanceId` 識別配對。
角色為 editable-sticker-bg / editable-sticker-text；圖片為 transform authority。
文字中心使用圖片完整矩陣與 normalized textArea 計算；拖曳／縮放／旋轉／透明度同步。
點文字選整組，雙擊或「編輯文字」進 Textbox editing；刪任一成員整組刪除、複製生成新 instance ID。
文字工具 dock 是 editor 的 flex sibling，縮小可見 workspace，不覆蓋畫布。
文字先等站內 FontFace ready，再按字級逐 1 原图單位縮至 minFontSize，包含換行、字距、行距、描邊／斜體留白；仍不合則拒絕，保留最後有效內容。
兩個固定字型：jf-openhuninn 2.1（OFL）、Noto Sans TC（OFL，官方字型無損 WOFF2）。不接受任意字型 URL。
新版 structured 設計中的其他文字也須選上述站內字型，不能讓 production 默默使用系統字型。舊訂單與無文字貼紙設計保持原流程。

## 訂單與重建

只有含文字貼紙的設計附 `render_contract_version: editable-text-v1`。
保存 logicalCanvas、modelId/styleId、完整 Fabric objects（含 clipPath／slot 與文字參數）、production 寬高。
用原始 image element 輸出來源 PNG（不是 editor 截圖）；下單時每張原圖獨立保存於該訂單 private sources，JSON 改為來源路徑。
後端保存當時 server profile mask 與字型 SHA256；不相信客戶任意來源 URL。
compact／manifest fallback 不可刪除此契約；超容量明確阻擋，不偷偷改成不可重建的圖片。

Print Center prepare 對新版訂單：

1. 校驗完整結構、來源檔歸屬、字型 hash、生產尺寸。
2. 在隔離 Chromium 中載入固定 Fabric 5.3.1、共同 editable layout core 與既有 print mask core。
3. 字型 ready 後重新 fit Textbox，從向量文字與原始圖片渲染。
4. 沿用 #45 artwork/mask shared alpha-bounds crop、相機孔，輸出 720 DPI PNG。
5. 保存新 artifact；job.artwork_path 指向它，order.print_path 舊預覽／前端生產檔不覆寫。

Renderer 不接受 DOM screenshot；browser request 全數攔截，只有本機固定 JS／字型與本訂單來源 bytes 能載入。
每 process 同時最多一個 renderer，等待最多 5 秒、子程序最多 90 秒，最大輸出 18MP。
缺資源／不支援字型／geometry 更新／renderer 無法啟動 → PRODUCTION_REBUILD_FAILED；不 fallback 客戶 PNG。
舊訂單没有 render contract，仍讀既有 print_path。vendor payload／startPrint 安全規則未改。

## 部署前置（此 PR 不部署）

新依賴為 Playwright 1.63.0 及相符的 Chromium／系統依賴；Dockerfile 建置時安裝，沿用 gunicorn.conf.py 的所有 middleware，綁 PORT。
既有 Python buildpack 若繼續使用，必須另安裝 `python -m playwright install --with-deps chromium`，否則新版文字訂單會 fail closed。
字型與固定 Fabric 包含在 repo，無 runtime 外部字型／CDN 依賴；renderer 可用性先於開放新功能驗證。
不需 production DB 操作；不設定 vendor key、不啟用實體列印。
