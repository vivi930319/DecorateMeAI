# 全系統資安 Code Review 驗收紀錄

> 日期：2026-07-23  
> 實作：Claude Code  
> 獨立驗收：Codex  
> 部署狀態：**已依使用者指示上線（2026-07-23）。** P0-R1～R9 與 item 6／7／8 全數修畢、前後端測試全綠並已 commit 與部署：
> - 後端 commit `9bc61ef`（分支 `Isa`）；gateway 映像 `ai-gateway:p0-actor-iso-20260723`，Cloud Run revision `ai-gateway-00039-nzc`（100% 流量）。
> - 前端 commit `e51c4a2`（資安）＋`d17c24a`（資產），分支 `dev_makeup`；Firebase 版本 `20260723-212540`。
> - 上線後驗證：商品代理 `200`、登入 `401`（連得到會員庫，非 503）、`js/api.js` 已含 `_protectedFetch`。
> - 本次上線在無 Codex 逐檔驗收的情況下由使用者直接指示執行，以全綠測試為品質關卡。仍待外部資料庫端／Ollama 端與 IAM／Secret 端配合項目（見文末）。
>
> **第三輪（純我方剩餘項目）全部完成並上線（2026-07-23）：** 登入限流加帳號維度、Render SSRF＋串流限制、依賴鎖版、CI（測試＋秘密＋漏洞掃描）、登出清 localStorage 臉圖 PII、IAM 已確認最小權限。
> - 後端 commit `de75b7f`＋`eefca40`（分支 `Isa`，已 push）；gateway 映像 `ai-gateway:login-account-limit-20260723` → revision `ai-gateway-00040-7cs`；render 映像 `replicate-render:ssrf-guard-20260723` → revision `replicate-render-00049-fgz`（維持 IAM 私有，直連 403）。
> - 前端 commit `1b90969`＋`d686073`（分支 `dev_makeup`，已 push）；Firebase 版本 `20260723-231345`，`js/api.js` 已含 `clearAccountLocalPII`。
> - 47 個後端測試＋前端 smoke 全綠。**我方項目至此全部完成並上線**；剩餘僅：模型訓練、外部組對接（資料庫 S7／S55／會員刪除／sessionVersion、Ollama S5 金鑰輪換、爬蟲後端 SSRF、演算法服務內資料最小化）。

## 驗收規則

- Claude Code 負責實作；Codex 只做差異審查、測試、退件與文件整理。
- 未經本紀錄標示「通過」前，不 commit、不 push、不部署、不變更正式 IAM／Secret。
- 不得在文件、Log 或測試輸出保存實際 Email、照片、Token、Cookie、金鑰、完整分析包或完整 Prompt。
- 商品維持一次載入完整資料；Ollama Prompt 展示保留到使用者另行確認。

## 第一輪測試結果

| 項目 | 結果 |
|---|---|
| `ai_gateway_test.py` | 27 tests，通過 |
| `render_api_test.py` | 13 tests，通過 |
| `node --check js/api.js` | 通過 |
| `node --check js/router.js` | 通過 |
| `node frontend_smoke_check.js` | **失敗**：`deleteMember` 未經 actor 防線 |
| Claude 自動執行 | 額度於收尾時用完，台北時間 08:40 重置 |

## P0 退件：跨分頁帳號隔離仍未完成

### P0-R1 Gateway 缺少 actor header 時仍放行

位置：`ai_gateway.py` 的 `enforce_expected_actor`。

目前只在 header 存在且不相符時回 409；header 缺少時直接放行。這使舊前端、漏加 header 的新方法或惡意呼叫者仍可在 Cookie 被另一分頁取代後寫入。

修正要求：

- 僅對 `POST/PATCH/PUT/DELETE` 的受保護路由強制 header。
- 寫入缺少 header 也要在呼叫上游前回 `409 SESSION_OWNER_CHANGED` 或固定的 `EXPECTED_ACTOR_REQUIRED`。
- `GET/HEAD` 不要求 header，避免讀取及健康檢查被破壞。
- 測試必須從「缺 header 放行」改成「缺 header 不得呼叫上游」。

### P0-R2 前後端沒有真正使用 actor contract

位置：`ai_gateway.py` `/auth/session`、`js/api.js` `loginToGateway`、`validateSession`。

- Gateway 回傳欄位為 `actor`，主規格要求 `actorId`；必須統一名稱。
- `validateSession()` 目前丟棄 actor 欄位，只回 `sub/role/status`。
- `loginToGateway()` 沒有在登入後重驗 `/auth/session`，也沒有把 actor 固定在該分頁的 sessionStorage。
- 登入成功通知 BroadcastChannel 早於 actor 固定，無法形成伺服器端寫入保護。

修正要求：登入成功後立即重驗 session；`sub` 必須等於登入帳號且 `actorId` 必須存在，才可回報登入成功。把 `actorId` 存在 sessionStorage，登出／過期時清除。

### P0-R3 `assertSessionOwner` 仍 fail open

位置：`js/api.js` 約第 1050 行。

目前 `session.sub` 缺少時回 `{ok:true, unverified:true}`。這與安全要求相反。

修正要求：網路錯誤、401、缺 `sub`、缺 `actorId`、本機 actor 缺少、Email 不一致、actor 不一致全部 fail closed，且不得執行原 write callback。

### P0-R4 沒有集中加入 `X-Expected-Actor`

位置：`js/api.js` `_fetchWithRelogin`、直接 `fetch` 的 Face／Render／Admin 方法。

目前新增的 `_protectedWrite` 只先做 Email preflight，沒有在實際請求加入 `X-Expected-Actor`；`_fetchWithRelogin` 也未處理 409。Gateway 的新防線因此沒有可用的前端配對。

修正要求：

- 建立單一受保護寫入 fetch wrapper，只對可信的同源 Gateway 路徑加入 actor header。
- 不得把 actor header 送到第三方網址。
- 409 必須觸發帳號已切換流程、取消請求且停止原操作。
- 新增測試讀取實際送出的 headers，而不只計算 fetch 次數。

### P0-R5 寫入覆蓋不完整

已知遺漏：

- `deleteMember` 完全沒有 `_protectedWrite`，現有 smoke test 已抓到。
- Face 分析／job 建立仍直接 `fetch`。
- Render 建立、retain、刪除仍需逐一確認。
- Admin 商品新增／修改／刪除、爬蟲預覽／匯入仍直接 `fetch`，未帶 actor。
- 會員與 Admin 的所有新增寫入若不走集中 wrapper，未來仍會再漏。

驗收測試須列出所有受保護寫入方法，並證明缺 actor 時目標 API 呼叫次數為 0。

### P0-R6 登出與記憶體清理未完成

- 登入已有 BroadcastChannel，登出尚未發通知。
- 401／409／換帳號時需停止 Face／Render polling。
- 除 sessionStorage 外，需清除 Router 記憶體中的 File、Blob、圖片、analysis package/result、job ID；不能只清 Auth profile。
- 不得誤刪同瀏覽器其他帳號的持久資料。

## P0 退件：私人媒體與會員刪除

### P0-R7 刪除物件失敗仍刪 job

位置：`replicate_render_api.py` `delete_member_render_artifacts`。

最新提交已改成先刪妝前／妝後物件、再刪 job，方向正確；但程式忽略 `delete_permanent_storage_url()` 的 `False`。物件不存在、URL 不合法或刪除失敗時，仍刪除 job 並增加 `jobsDeleted`，再次失去重試依據。

修正要求：兩張需要刪除的物件都成功或明確確認不存在後才刪 job；失敗則保留 job、記錄固定錯誤碼與可重試狀態。新增回傳 false／拋例外測試。

### P0-R8 retain 妝前圖失敗仍取消 TTL

位置：`replicate_render_api.py` `retain_render_job`。

目前妝前圖 retain 失敗只寫 Log，仍將 job 設為 retained 並移除 `expiresAt`。妝前圖繼續留在 `temporary/`，之後會被 Lifecycle 刪除，造成永久收藏只剩妝後圖。

修正要求：對有妝前圖的 job，妝前與妝後必須形成一致的 retain 結果。任一失敗不可回報完整成功或移除 TTL；需回 503／failed retaining 並可安全重試。不得在 Log 放 URL 或圖片資訊。

### P0-R9 legacy media 端點只驗 URL，不驗 owner

位置：`replicate_render_api.py` `/render/media/sign`、`/content`、`DELETE /render/media` 與 Gateway legacy saved-look 媒體流程。

目前只驗證 URL 是否屬於 bucket，沒有從 job／object owner 證明該 actor 擁有物件。若資料庫曾接受任意已知 URL，可能造成跨會員簽名、讀取或刪除。

修正要求：以 job ID + ownerId 作權限來源；legacy URL 只能經過受控 migration 對應到 owner，不接受單純 URL 作授權依據。新增 A 會員不能簽名／讀取／刪除 B 會員物件的測試。

## P1 後續批次

- XSS：`showToast`、問候語、Avatar、商品與爬蟲資料仍存在 `innerHTML` 注入面。
- 登出／刪除帳號時的 localStorage PII 與分析回饋清理。
- Admin role/status 的即時重驗與 Session 撤銷版本。
- 登入 rate limit 集中儲存與 actor + IP 維度。
- 圖片解壓縮炸彈、Replicate 輸出 SSRF／串流大小限制。
- Log URL 中的 Email 改用 `/me`／opaque member ID。
- 最小權限 service account、依賴鎖定、CI、秘密與漏洞掃描。
- Hosting 入口 HTML 快取修正。

## 外部端文件

- `給資料庫端_資安修復與驗收規格_2026-07-23.md`
- `給演算法端_資安修復與資料最小化規格_2026-07-23.md`
- `給爬蟲端_資安修復與SSRF防護規格_2026-07-23.md`
- `給Ollama端_資安修復與Prompt展示例外規格_2026-07-23.md`

## 下一輪順序

1. 先修 P0-R1 至 P0-R6，重跑前後端測試。
2. 再修 P0-R7 至 P0-R9，加入失敗／跨會員測試。
3. Codex 逐檔審查，不通過則再次退件。
4. P0 全部通過後才開始 P1；P0/P1 都完成後才通知使用者統一部署。

## 第二輪結果（2026-07-23）

### 測試

| 項目 | 結果 |
|---|---|
| `python -m unittest ai_gateway_test.py`（29 tests） | 通過 |
| `python -m unittest render_api_test.py`（16 tests） | 通過 |
| `node --check js/api.js`／`js/router.js` | 通過 |
| `node frontend_smoke_check.js` | 通過（含跨分頁 actor 防線、XSS 與外部 URL 守門） |

### P0 退件處理

- **R1～R6（跨分頁帳號隔離，前端）**：`enforce_expected_actor` 對寫入強制 header、缺 header 前置回 `409`；`/auth/session` 統一回 `actorId` 並由分頁固定在 sessionStorage；`assertSessionOwner` 全面 fail closed；受保護寫入統一走 `_protectedFetch`，`X-Expected-Actor` 只送同源 Gateway、不送第三方，`409` 觸發換帳號流程；`deleteMember`／`patchMember` 已納入統一入口。smoke test 逐項驗證缺 actor 時目標 API 呼叫次數為 0。
- **R7（刪物件失敗仍刪 job）**：`delete_member_render_artifacts` 忽略 `False` 的問題已修，改為刪除失敗即保留 job、標 `deletionStatus=failed` 並回 `503 MEMBER_ARTIFACT_DELETE_INCOMPLETE`。**新增測試** `test_member_deletion_keeps_job_when_object_delete_fails`。
- **R8（retain 妝前圖失敗仍取消 TTL）**：`retain_render_job` 對有妝前圖的 job，任一張失敗即回 `503 RETAIN_INCOMPLETE`、保留 `expiresAt`、標 `retainStatus=failed`，不回報完整成功。**新增測試** `test_retain_keeps_job_retryable_when_before_image_fails`。
- **R9（legacy media 只驗 URL 不驗 owner）**：三個 legacy 端點（sign／content／DELETE）統一經 `_require_legacy_media_owner`，以 job＋ownerId 為授權來源，非 owner 回 `404`，admin 才放行。**新增測試** `test_legacy_media_owner_blocks_cross_member_sign_read_delete`（含 sign 端點端對端）。

### 本輪其他項目

- **item 6（稽核／錯誤處理不留 PII）**：共用的 `api_errors._request_logging` 原本記錄完整 `request.url.path`，會員路徑帶 email。新增 `redact_log_path()`，把帶 email 的路徑段（含 `%40` 編碼）遮成 `<member>`，Gateway／Face／Render／Ollama 一次收斂。錯誤處理維持只回固定碼與通用訊息，不外洩內部細節、不記 token／cookie／照片／完整分析包／完整 prompt。**新增測試** `test_access_log_path_never_carries_a_member_email`。
- **item 7（前端 XSS 與 URL 驗證）**：`showToast`、儀表板問候語、Avatar（含 alt 與 src）、購物車與商品卡（name／price／cat／brand）全部改走 `escapeHtml`；Avatar 圖片改用 `lookImageSrc` 驗證 scheme；新增 `safeExternalUrl()`，商品來源頁 `href` 只接受 `http(s)`，擋掉 `javascript:` 等 scheme。smoke test 加入對應防回歸字串守門。
- **item 8（受保護 API 接統一 wrapper）**：`listProductAuditLogs`（`/admin-api`，GET）與 `recommendProducts` 改走 `_fetchWithRelogin`，統一 credentials、session signal 與 `401/403` 換帳號處理；換帳號或登出時背景請求一併取消。

### 仍需外部端配合（不在本工作樹）

- **S40／S46（#17）**：會員刪除與 Admin 刪收藏的完整欄位、權限與交易規格，待會員資料庫端實作；Gateway 的 `X-Expected-Actor` 與媒體刪除協定已就緒。
- **S55（#27）**：登入端點帳號枚舉（`USER_NOT_FOUND` vs `WRONG_PASSWORD`）待資料庫端統一為 `INVALID_CREDENTIALS`。
- **S5（#26）**：Ollama 金鑰輪換待 Ollama 端換發。
- **IAM／Secret**：統一部署前需確認 `ai-gateway` 服務帳號權限與 Secret（含避免 CRLF）狀態；本輪未變更任何正式 IAM／Secret。

### P1 後續（尚未進行）

Log 中 email 已於 item 6 收斂；其餘 P1（依賴鎖定、CI、秘密與漏洞掃描、圖片解壓炸彈、Replicate 輸出 SSRF／串流大小限制、Hosting 入口 HTML 快取）仍待後續批次。
