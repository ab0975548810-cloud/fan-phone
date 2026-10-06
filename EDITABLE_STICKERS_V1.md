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
字型 bytes 以 SHA256 校驗；glyph coverage manifest 拒絕缺字，不會以 system font 補字。字型載入後清除 Fabric 的舊度量 cache，避免草稿還原曾量到 fallback 字型。
普通文字有固定相容 mapping：Arial→Arimo＋Noto Sans TC；黑體→Noto Sans TC；明體→Tinos＋Noto Serif TC；手寫→Caveat＋粉圓；Emoji→Noto Emoji 固定單色向量字型。所有字型均為站內 WOFF2、SHA256／coverage 驗證，前台與 production 同一份檔案。建立時選項明示固定字型，Emoji 建立時提示單色；還原 legacy 系統字型時在編輯階段提示確認排版，不在結帳才換字型。文字貼紙仍僅允許粉圓／思源黑體。

## 訂單與重建

只有含文字貼紙的設計附 `render_contract_version: editable-text-v1`。
保存 logicalCanvas、modelId/styleId、完整 Fabric objects（含 clipPath／slot 與文字參數）、production 寬高。
用原始 image element 輸出來源 PNG（不是 editor 截圖）；草稿／購物車保留本機原圖。送單前逐張 multipart POST `/api/design-sources`，SHA256 去重，PNG MIME／magic／bytes／pixel 驗證。來源位於既有 private bucket `design-temp/{expires}/{opaque-id}.png`；回傳簽名 opaque sourceRef，綁 HMAC client identity＋本次 sourceCheckout。訂單 JSON 只有 sourceRef／SHA256／原始尺寸，不含大 Base64。
單張最大 24MB，維持 Flask 36MB 不變；來源總量 70MB／64MP。結構 JSON 上限 1.5MB，原本 security 2MB gate 保留；前端也檢查 print／preview 合併 request 不超過 36MB。後端先驗所有 receipt、總量，再下載驗 hash／尺寸、promote 到訂單 private sources。同一 source hash 不重複上傳。
暫存約 24～25 小時過期，上傳時執行 bounded oldest-first janitor；可另排程 `design_sources.cleanup_expired(app)`，沒有新 DB table。完成、失敗、idempotent replay 都 release 暫存；create rollback 清 print／preview／sources／mask，包括 upload response 遺失。永久刪單清來源與重建 artifact，原有 ledger／finance 保留。retry fingerprint 使用已驗證來源 hash，排除每次重傳不同的 receipt／checkout token。
寫圖前保存私有 `design-cleanup` intent。DB commit 回覆遺失時先查是否已成立；DB 無法讀取則延後 cleanup，不猜測失敗。儲存刪除暫時失敗也保留 intent，janitor 確認訂單不存在後重試清理；已成立訂單僅清 intent，保留来源。正式部署可每小時排程既有 runtime 執行 cleanup 函式，以便無流量期間也清過期檔案；本 PR 未啟用 production 排程。
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
來源另有每張 32MP／總計 64MP／70MB 安全限制，不因此壓縮原圖或轉 JPEG。相同來源重用；content-addressed artifact 使用 atomic 本機寫入，Supabase 重送／回覆遺失僅在 bytes 完全一致時重用。
缺資源／不支援字型／geometry 更新／renderer 無法啟動 → PRODUCTION_REBUILD_FAILED；不 fallback 客戶 PNG。
舊訂單没有 render contract，仍讀既有 print_path。vendor payload／startPrint 安全規則未改。

## 部署前置（此 PR 不部署）

新依賴為 Playwright 1.63.0 及相符的 Chromium／系統依賴；Dockerfile 建置時安裝，沿用 gunicorn.conf.py 的所有 middleware，綁 PORT。
既有 Python buildpack 若繼續使用，必須另安裝 `python -m playwright install --with-deps chromium`，否則新版文字訂單會 fail closed。
字型與固定 Fabric 包含在 repo，無 runtime 外部字型／CDN 依賴；renderer 可用性先於開放新功能驗證。
不需 production DB 操作；不設定 vendor key、不啟用實體列印。
