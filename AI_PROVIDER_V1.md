# AI 摳圖 Provider V1

這版只延伸現有去背：兩種雲端模型、一個瀏覽器本機互動工具。
不切正式 provider、不部署、不修改 Supabase 資料或 migration。

## 手動 A/B 設定

| Server env | 行為 |
| --- | --- |
| `AI_REMOVE_PROVIDER=runpod`（未設定時預設） | 原 RunPod / BiRefNet；即使有新 key 也不切換 |
| `AI_REMOVE_PROVIDER=koukoutu` | 只用抠抠图，失敗回錯誤 |
| `AI_REMOVE_PROVIDER=auto` | 抠抠图優先，一次 RunPod fallback |
| `KOUKOUTU_API_KEY` | 僅 server；前端與結果下載不帶 key |

沒有新 key 時，原 RunPod 自動去背與本機工具照常；`auto` 可直接走 RunPod。
`koukoutu` 缺 key 則 fail closed。未啟用新 provider 的 `stamp` 回明確
`AI_MODE_NOT_AVAILABLE`，不把一般 BiRefNet 偽稱為專用印花模型。
`auto` 下印花失敗可退到一般 BiRefNet，回應 header 如實標記實際 provider/model。
正式環境變數仍由管理者另行設定；這個 PR 不做任何設定。

## API 與原圖

既有 `POST /api/ai/remove-background` 增加 form `mode=general|stamp`，缺省 general。
一般圖片仍先嘗試既有本機邊界連通去背／透明邊清理；這兩者不呼叫 backend、不扣 quota。
印花模式直接送自己的同源 API，server 決定 provider。

公開文件：[通用 multipart](https://doc.koukoutu.com/444674398e0)、
[印花 multipart](https://doc.koukoutu.com/444687820e0)、
[通用輪詢](https://doc.koukoutu.com/444686434e0)、
[印花輪詢](https://doc.koukoutu.com/444687824e0)。

- Server 送 `image_file`、`output_format=png`，`crop/border/stamp_crop=0`。
- create 成功取得 `task_id` 後輪詢 query，`state=0` 等待，`state=1` 下載 `result_file`。
- 下載只允許公開 HTTPS，逐個檢查 redirect、不傳 API key；stream 限制 14MB。
- 驗證可解碼 PNG、最大 3,200 萬像素、有透明區與非空主體。壞結果不替換圖片。
- 前端沿用現有 `compositeWithMask`：雲端圖片只提供 alpha，套回原始 source canvas；
  RGB、解析度、比例不裁切、不降 production 原圖像素。
- `X-AI-Provider` / `X-AI-Model` 表示實際結果；原 RunPod response headers 保持相容。

## 點選摳圖

`ai-interactive-core-v1.js` 抽取既有 same-origin MediaPipe 1.0.1 / MagicTouch
載入與筆刷 protocol。保留正向／負向，移除所有頭部 gate、bbox、裁切。
舊 `ai-head-*` scripts 不加入 runtime。

共用工具 dialog 讓使用者點／塗「保留」、「排除」，可撤銷一筆；取消或錯誤保留原圖。
pointer capture 與 `touch-action:none` 保護手機繪製。筆畫是完整圖片的 normalized 座標，
推論縮到最長邊 1536 僅節省本機運算，mask 全幅套回原圖，輸出保持原始 W/H。
MediaPipe ESM / WASM / model 維持既有同源 proxy，只有選用點選工具才載入。
CSP 加入 `wasm-unsafe-eval`，允許 WebAssembly；沒有新增 JS `unsafe-eval`。

前台／模板仍用原有 Fabric replacement，保留物件中心、顯示尺寸、旋轉、clipPath、slot、圖層。
前台草稿、編輯器座標、模板 geometry、720 DPI pipeline 都不改。

## Quota：一次操作只算一次

沿用 `ai_usage_events` 與所有既有 RPC、HMAC identity、rolling 24h、5/15/60、active 2。
無新增 table／migration。既有 `runpod_job_id` 是 text；新 provider 在同欄保存
`koukoutu:<task_id>`，原 RunPod ID 格式不改。

一次請求只 reserve 一次。第一個 provider 接受工作後 mark SUBMITTED 一次；
若 fallback，不再次 reserve/mark，同一個 active slot 保持到整個操作結束。
第一個 accepted ID 保留在帳本，失敗後仍 counted；沒有任何 accepted ID 才 release。
Quota RPC 故障時停止，不繼續 poll/fallback；RunPod 可 best-effort cancel。
抠抠图公開文件未提供取消 API，不能假造 cancel；已接受的工作可能仍在 provider 完成，
但不會在帳本失敗後繼續取得或使用結果。

`auto` 使用同一個總 timeout，前半保留給抠抠图，後半可做一次 fallback。
一次 logical quota 不代表只有一次供應商成本：兩個 provider 均接受時可能有兩筆費用。
沒有取消 API 的抠抠图 timeout 也可能繼續完成；A/B 前需確認 vendor 的費率與帳單。

## Regression

- `test_ai_remove_provider.py`：公開 model keys、PNG/crop 欄位、query 契約、timeout/5xx/
  malformed/opaque、fallback、single count、quota fail closed、key 不出 browser、URL 安全。
- 既有 `test_ai_quota.py` RunPod lifecycle 全部保留。
- `.github/tests/test_ai_provider_browser.py`：WebKit / Chromium 真正按鈕、touch tap、
  pointer drag，正負筆畫、mask alpha、2400×1800 原圖、Fabric geometry/slot/clip/layer 保留；
  雲端和推論 SDK fixture 可重現，不接付費 vendor。檢查實際 WASM CSP compile。
- 本機另外用真正公開 MediaPipe SDK / MagicTouch，在 Chromium 與 WebKit 推論
  Hero 圖：960×1026 透明 PNG、正負筆畫正常，不呼叫 backend。
- Smoke / Commerce / Print Center / 完整 WebKit / Chromium CI 保留。

付費抠抠图／RunPod integration 本輪沒有實際呼叫；正式切換前另做受控 A/B。
