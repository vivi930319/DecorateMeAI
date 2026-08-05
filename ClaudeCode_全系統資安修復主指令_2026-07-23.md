# Claude Code 全系統資安修復主指令

> 日期：2026-07-23  
> 實作者：Claude Code  
> 獨立驗收者：Codex  
> 範圍：`PythonProject12` 後端與 `web_frontend` 正式前端

## 0. 工作規則

1. 先讀兩個程式庫的 `git status`、未提交差異及最近提交，不得覆蓋、還原或遺失既有修改。
2. 可以修改程式與測試，但本輪不得自行 `commit`、`push`、開 PR、部署、輪替金鑰或變更雲端 IAM。
3. 不得使用 `git reset --hard`、`git checkout --`、刪除工作目錄或其他破壞性指令。
4. 不得讀取、輸出或寫入任何實際 API Key、Cookie、JWT、密碼、完整 Email、照片、完整分析包或完整 Prompt。
5. 錯誤訊息對使用者顯示繁體中文；內部錯誤碼可保留英文常數。
6. 商品頁維持一次呈現完整資料庫商品；不要重新加入 `limit=50`、分頁或虛擬清單。
7. Ollama 完整 Prompt 是目前專題紀錄的暫時例外：不要移除展示功能、不要改寫 Prompt 內容，但仍不得寫入一般 Log。
8. Demo 功能不得成為繞過登入、權限、資料最小化或正式資料隔離的後門。

## 1. 本輪必修：同瀏覽器跨分頁帳號混用

問題：同一瀏覽器的使用者分頁與 Admin 分頁共用 HttpOnly Cookie。任一分頁重新登入後，其他分頁可能仍保留舊 `profile`，造成收藏、渲染、點數或管理操作使用錯誤帳號。

必須做到：

- 登入與登出以 `BroadcastChannel('decorate-me-auth')` 通知其他分頁；沒有 BroadcastChannel 時仍靠伺服器驗證攔截。
- 每一個需要身分的寫入，在送出前以 `/auth/session` 驗證目前 Cookie 的 `sub` 與該分頁原本登入者一致。
- 驗證必須 fail closed：網路錯誤、401、缺少 `sub`、身分不一致都不得送出原寫入。
- Admin 修改其他會員時，比對的是「目前 Admin 操作者」，不是被修改會員的 Email。
- 最佳防線是在 Gateway 加入不含 Email 的 opaque actor：前端送 `X-Expected-Actor`，Gateway 在代理上游前比對目前 JWT actor；不一致回 `409 SESSION_OWNER_CHANGED`。
- 至少保護：收藏商品、妝容收藏新增／刪除、會員資料修改／刪除、點數、打卡、任務、主題、Face job、Render job、保留／刪除媒體，以及所有 Admin 寫入。
- 登出、401、409 或跨分頁換帳號時，取消進行中的請求／輪詢，清除記憶體中的圖片、檔案、分析包、結果與工作 ID，再清除該分頁 session。
- 加入可重現兩個分頁 A/B 帳號切換的自動測試，證明第一個寫入就被擋下，而不是等資料庫回錯才發現。

## 2. 本輪必修：私人媒體與會員刪除

- 檢查最新會員刪除提交。刪物件失敗或回傳 `false` 時不可刪除追蹤 job；需回傳失敗或留下可重試狀態。
- 妝前圖、妝後圖、暫存圖、永久圖、Face job、Render job、分析結果與工作紀錄均須有可重試的刪除流程。
- Gateway 不可在資料庫已刪、媒體刪除失敗時仍回報完整成功；設計 durable deletion job、狀態與重試界面，至少不得吞掉失敗。
- `retain` 必須同時成功保存妝前與妝後圖。任一失敗不得移除 TTL 或回報完整成功。
- `/render/media/sign`、`content`、`delete` 不可只相信呼叫者提供的 URL；必須依 job 所有權／opaque owner 驗證物件。
- 測試跨會員不能簽名、讀取或刪除另一位會員的物件。

## 3. 本輪必修：授權、Session 與權限撤銷

- Gateway 的會員清單端點只能由已驗證 Admin 使用，不可只依賴上游資料庫補做授權。
- Admin 的 role/status 不可在 JWT 兩小時內永久沿用；`/auth/session` 或敏感 Admin 操作要向可信來源重驗，停權／降權應立即生效。
- Session 登出、停權、刪除帳號後必須撤銷；加入 session/token version 或等價機制的接口與測試。
- Cookie 僅作同源 Gateway session。不得把可重用 Bearer Token 放進 localStorage/sessionStorage 或回傳給瀏覽器 JavaScript。
- 保持 Gateway 為瀏覽器唯一正式 API 入口。

## 4. 本輪必修：XSS、URL 與前端資料殘留

- `showToast`、問候語、Avatar、商品、爬蟲預覽、管理員頁等所有外部／會員／API 資料不得直接插入 `innerHTML`。
- 優先使用 `textContent`、DOM API；需要 HTML 時集中使用可信 sanitizer，不可只處理少數欄位。
- URL 僅允許 `https:`（本機測試明確允許 `http://localhost`）；拒絕 `javascript:`、`data:` 及未知 scheme。
- 為 CSP 漸進式上線準備：移除 inline handler/inline script，先建立 Report-Only 或可測試政策；不得直接破壞 Demo。
- 登出、帳號刪除與 Session 過期時，清除該帳號在 localStorage 的 PII、分析回饋、妝容草稿、建議與圖片快取；不能誤刪同瀏覽器其他帳號的資料。
- 正式登入會員的點數、打卡、任務與主題不得在後端失敗時用 localStorage 假裝成功。Demo 離線資料必須明確隔離並標示。

## 5. 本輪必修：上傳、SSRF、資源耗盡與逾時

- 圖片在完整解碼前驗證 magic bytes、檔案大小與影像尺寸上限；避免解壓縮炸彈。
- 下載 Replicate／供應商輸出時使用允許網域、逐次驗證 redirect、串流讀取、Content-Length 與實際位元組雙重上限，阻擋私有 IP／metadata 位址。
- 不得對任意使用者 URL 提供伺服器端下載能力。
- Gateway 對登入、會員、商品、Face、Render、Ollama 使用不同且合理的 timeout；外部 Tunnel 不得佔用 600 秒連線。
- Rate limit 以可信的 actor + IP 組合與集中式儲存實作；不可退回單機記憶體後仍宣稱具備完整防護。
- Render quota 使用 Gateway 傳入的 opaque actor，不可錯用不存在的 Email header 或只靠 IP。

## 6. 本輪必修：Log、錯誤與隱私

- Log 不得包含照片、base64、完整 Email、權杖、Cookie、完整分析包、完整 Prompt 或完整請求／回應 body。
- 含 Email 的 URL path 會被平台 access log 記錄；新接口改用 `/me`、opaque member ID 或 body，並提供相容遷移，不只在應用 logger 遮罩。
- 錯誤回應不洩漏 exception、內部 URL、query、header、金鑰名稱或堆疊。
- 使用 request ID、固定錯誤碼、actorId 與狀態；稽核紀錄不得保存完整管理員 Email。

## 7. 本輪必修：供應鏈、權限與測試

- Pin Python 套件版本並產生可重現鎖定；Docker base image 規劃 digest pin。
- 新增 CI：語法檢查、單元測試、秘密掃描、依賴漏洞掃描、靜態安全掃描與部署前 smoke test。
- 不得把掃描器自動結果當成唯一 Code Review；人工檢查授權與資料流。
- 為 Face/Render/Gateway 拆分最小權限 service account 的雲端修改清單；本輪先改 IaC／文件，不直接改正式 IAM。
- 修正 Hosting HTML 快取，入口 HTML 使用 no-cache/no-store 或 revalidate；hash 靜態資產才使用 immutable。

## 8. 驗收方式

至少執行並回報：

1. 後端完整單元測試與新增安全測試。
2. 前端 `node --check`、既有 smoke test 與新增跨分頁／XSS 測試。
3. 秘密掃描只回報檔名與類型，不輸出秘密內容。
4. 列出修改檔、測試結果、未解決風險與需要其他端配合事項。
5. 不得用「測試未跑」或「可能可行」宣稱完成。

完成後停止，不提交、不推送、不部署，交由 Codex 逐檔審查與退件。
