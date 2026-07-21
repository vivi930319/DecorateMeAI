# 給資料庫端：會員 Session 完整接口規格（Cline 執行版）

> 日期：2026-07-21
>
> 這份是 `給資料庫端_會員登入Session修復規格_2026-07-21.md` 的**擴充版**。前一份只規範了登入與 `/api/members/{email}` 兩條；這份補上**其餘 12 條端點**，因為實際故障發生在 `check-in`，不是登入。兩份衝突時以這份為準。
>
> 禁止寫入本文件、Log、Git 或訊息：真實密碼、完整 Cookie 值、API Key、JWT、完整會員 email、會員照片。

---

## 〇、給 Cline 的使用方式

把下面這段貼進 Cline 的輸入框，然後把本檔案一起加入 context：

```text
請閱讀 給資料庫端_會員Session完整接口規格_Cline版_2026-07-21.md。
這是外部 Gateway 對本服務的接口契約，本服務目前不符合，導致使用者登入後
幾秒內被登出。

請依照文件第五節的 TASK 1 到 TASK 6 逐項執行，一次只做一個 TASK。
每個 TASK 做完後：
1. 說明你改了哪些檔案、改了什麼
2. 執行該 TASK 底下的「驗收」指令並貼出結果
3. 停下來等我確認，再做下一個 TASK

硬性限制（違反就是錯的，寧可停下來問我）：
- 不可以移除或放寬任何身分驗證
- 不可以把端點改成公開或不檢查 Session
- 不可以信任請求裡的 email、role 欄位來決定身分
- 不可以為了讓測試過就回傳假資料或寫死 200
- 不確定就先問，不要自己猜規格
```

> Cline 用 DeepSeek 時，請務必維持「一次一個 TASK」。一次丟六個任務容易改到一半就偏掉。

---

## 一、一句話問題

會員登入成功後，Gateway 用同一個 Session Cookie 呼叫 `/api/members/{email}/check-in`，**收到 401**，於是前端整批背景請求被取消、跳回登入頁並顯示「登入狀態已失效」。

登入本身是成功的（`/auth/session` 預檢通過），所以問題**不在登入**，而在「登入後其他端點是否認得同一個 Session」。

---

## 二、系統怎麼串的

```text
瀏覽器（只認得 Gateway，沒有你的網址、也沒有任何金鑰）
  → https://decorate-me.web.app/member-database/api/members/xxx/check-in
  → AI Gateway（驗證自己的 HttpOnly session，取出封裝的上游 Cookie）
  → 你的服務 /api/members/xxx/check-in       ← 這裡回 401
```

重點：

1. 請求**不是**從瀏覽器直接來的，是 Cloud Run 伺服器對伺服器呼叫。
2. 因此**沒有** `Origin`、`Referer`，`User-Agent` 也不是瀏覽器。**不可以拿這些來判斷合法性。**
3. Gateway 會原樣送出登入時你給的 Cookie。
4. Gateway **不會**送 `Authorization` 標頭。

---

## 三、完整端點清單

Gateway 目前只允許以下路徑通過，其他一律 404 擋掉。`{email}` 是 URL-encode 過的（`a@b.com` → `a%40b.com`），請務必先 decode 再查。

| # | Method | 路徑 | 用途 | 需要 Session |
|---|---|---|---|---|
| 1 | POST | `/api/login` | 登入 | 否（這是入口） |
| 2 | GET | `/api/members` | 管理員：會員清單 | 是（且需 role=admin） |
| 3 | GET | `/api/members/{email}` | 讀取單一會員 | 是 |
| 4 | PATCH | `/api/members/{email}` | 更新會員 | 是 |
| 5 | DELETE | `/api/members/{email}` | 刪除會員 | 是 |
| 6 | GET | `/api/members/{email}/points` | 點數餘額與紀錄 | 是 |
| 7 | GET | `/api/members/{email}/check-in` | 查詢打卡狀態 | 是 |
| 8 | POST | `/api/members/{email}/check-in` | 執行打卡 | 是 |
| 9 | GET | `/api/members/{email}/tasks` | 任務清單 | 是 |
| 10 | POST | `/api/members/{email}/tasks/{taskId}/claim` | 領取任務獎勵 | 是 |
| 11 | POST | `/api/members/{email}/theme-shop/{themeId}/redeem` | 兌換主題 | 是 |
| 12 | GET | `/api/members/{email}/saved-looks` | 妝容收藏清單 | 是 |
| 13 | POST | `/api/members/{email}/saved-looks` | 新增妝容收藏 | 是 |
| 14 | DELETE | `/api/members/{email}/saved-looks/{id}` | 刪除單筆收藏 | 是 |
| 15 | POST | `/api/recommend/personal` | 個人化推薦 | 是 |
| 16 | POST | `/api/favorites/toggle` | 商品收藏切換 | 是 |

**第 3～16 條全部都必須接受同一個登入 Cookie。** 這是這次的核心問題：目前很可能只有第 3 條（或只有登入）是通的。

---

## 四、Cookie 契約

### 4.1 登入回應

```http
POST /api/login
Content-Type: application/json

{"email": "demo@example.com", "password": "……"}
```

成功時必須**同時**具備：

```http
HTTP/1.1 200 OK
Set-Cookie: member_session=<高熵隨機值>; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=7200
Content-Type: application/json

{"success": true, "member": {"email": "demo@example.com", "role": "member", "status": "active"}}
```

- `member.email` 必須存在，且忽略大小寫後等於送進來的 email。
- Cookie 名稱可自訂，但**一定要有 `Set-Cookie`**。只回 JSON token 不算數。
- Cookie 值不可以是 email、密碼、流水號或任何可猜測的內容。

### 4.2 五條 Cookie 規則（這次踩到的坑都在這）

| 規則 | 說明 | 違反的後果 |
|---|---|---|
| R1 | Session 必須存在**跨程序共用的儲存區**（PostgreSQL／Redis），不可只放單一 Python process 記憶體 | 多 worker 或重啟後，登入和下一個請求落在不同程序 → 401 |
| R2 | 第 3～16 條端點都要能認得同一個 Cookie | 只有登入通、其他 401（**目前狀況**） |
| R3 | 一般成功回應**不要無故重發 `Set-Cookie`**。真的要輪替時，必須把**整組** session cookie 一起重發，不能只發其中一個 | Gateway 收到殘缺的 cookie 組合，下一個請求就掉線 |
| R4 | 成功回應裡**絕對不可以**出現 `Max-Age=0` 或空值的清除指令（那是登出才做的事） | Session 被當場清掉 |
| R5 | 驗證失敗一律回 `401`，權限不足回 `403`。**不可以回 500，也不可以回 302 轉登入頁** | Gateway 會判成服務故障，回 503 給使用者 |

> R3、R4 我們已經在 Gateway 端加了合併保護（`merge_upstream_cookies`），但資料庫端還是不該亂發。

### 4.3 Gateway 會送什麼標頭

```http
GET /api/members/demo%40example.com/check-in
Accept: application/json
Cookie: member_session=<登入時你給的值>
X-Forwarded-For: <使用者 IP>
```

- **沒有** `Authorization`
- **沒有** `Origin` / `Referer`
- 只有在我們設定了上游服務金鑰時才會多送 `X-API-Key`；目前**沒有設定，所以不會送**
- 如果你的端點需要服務金鑰，請告訴我們**標頭名稱**（金鑰本身放 Secret Manager，不要貼在訊息裡）

---

## 五、Cline 任務清單

### TASK 1：找出 Session 驗證的實作位置

**做什麼**

1. 在專案裡搜尋登入處理：關鍵字 `login`、`/api/login`、`set_cookie`、`session`
2. 在專案裡搜尋會員端點：關鍵字 `members`、`check-in`、`saved-looks`、`points`
3. 找出「驗證 Session 的那段程式」是用什麼方式（decorator、middleware、還是每個 handler 自己寫）

**驗收**：列出以下三項，不要改任何程式碼

- 登入 handler 的檔案與行號
- Session 驗證機制的檔案與行號
- 第三節表格 16 條端點，各自對應的 handler 位置；找不到的標成「缺少」

---

### TASK 2：確認 Session 存在哪裡（對應 R1）

**做什麼**

1. 找出 Session 目前存哪：Python dict？檔案？PostgreSQL？Redis？
2. 如果是**行程內記憶體**（例如全域 dict、`app.state` 裡的變數），這就是 bug，往下做
3. 如果已經在 PostgreSQL／Redis，跳過改動，直接做驗收

**怎麼改**

改成共用 Session Store，至少包含這些欄位：

| 欄位 | 用途 |
|---|---|
| `session_hash` | 只存 Session 值的 SHA-256 雜湊，**不存原始值** |
| `member_id` | 對應會員主鍵（不要用 email 當秘密） |
| `created_at` | 建立時間 |
| `expires_at` | 到期時間（建議 2 小時） |
| `revoked_at` | 登出／停權／刪除會員時填入 |

**驗收**：用同一個 Cookie 連續呼叫 `/api/members/{email}` 五次，全部 200。若服務有多個 worker，重複測到確定不會隨機 401。

---

### TASK 3：讓全部端點共用同一套驗證（對應 R2，**最重要**）

**做什麼**

把 TASK 1 找到的 Session 驗證，套用到第三節表格第 3～16 條**每一條**。

**注意**

- 不是「拿掉驗證」，是「把同一套驗證補上去」
- 目前 401 的是 `check-in`，但很可能 `points`、`tasks`、`saved-looks` 也一樣，**不要只修 check-in**
- 驗證通過後，還要檢查「這個 Session 的會員」是否等於「URL 裡的 {email}」；不相等且不是 admin 就回 403

**驗收**：用同一個 Cookie 依序呼叫下列每一條，全部不可以是 401：

```text
GET  /api/members/{email}
GET  /api/members/{email}/points
GET  /api/members/{email}/check-in
GET  /api/members/{email}/tasks
GET  /api/members/{email}/saved-looks
```

---

### TASK 4：檢查 Set-Cookie 行為（對應 R3、R4）

**做什麼**

1. 搜尋所有 `set_cookie` / `Set-Cookie` 的呼叫位置
2. 確認**只有** `/api/login`（設定）和 `/api/logout`（清除）會發 Set-Cookie
3. 其他端點如果會發，把它拿掉；真的需要續期就整組一起發

**驗收**：呼叫 `GET /api/members/{email}/points`，檢查回應**沒有** `Set-Cookie` 標頭。

---

### TASK 5：統一錯誤狀態碼（對應 R5）

**做什麼**

| 情況 | 必須回 |
|---|---|
| 沒有 Cookie / Cookie 無效 / 已過期 / 已登出 | `401` |
| Cookie 有效但要存取別人的資料 | `403` |
| 會員不存在 | `404` |
| 帳號密碼錯誤 | `401` |

**絕對不可以**：回 `500`、回 `302` 轉登入頁、把驗證失敗回成 `200`。

**驗收**：用假 Cookie 呼叫 `/api/members/{email}/points`，必須是 401，且回應是 JSON 不是 HTML 登入頁。

---

### TASK 6：登出撤銷

**做什麼**

1. 登出時把 Session Store 裡對應紀錄的 `revoked_at` 填上
2. 回應清除 Cookie：`Set-Cookie: member_session=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0`

**驗收**：登出後用舊 Cookie 呼叫 `/api/members/{email}`，必須 401。

---

## 六、完整驗收腳本

把 `DB_BASE` 換成你目前的服務網址（Quick Tunnel 每次重啟都會換，先確認現在這一組是活的）。只用 Demo 測試帳號。

```powershell
$dbBase = 'https://<你目前的服務網址>'
$email  = 'DEMO_EMAIL'
$body   = @{ email = $email; password = 'DEMO_PASSWORD' } | ConvertTo-Json

# 1) 登入，必須 200 且有 Set-Cookie
$login = Invoke-WebRequest -Uri "$dbBase/api/login" -Method Post `
  -ContentType 'application/json' -Body $body -SessionVariable s
"login            : $($login.StatusCode)"
"has Set-Cookie   : $([bool]$login.Headers['Set-Cookie'])"

# 2) 同一個 Session 打過所有唯讀端點，全部不可以是 401
$e = [uri]::EscapeDataString($email.ToLowerInvariant())
foreach ($p in @(
    "/api/members/$e",
    "/api/members/$e/points",
    "/api/members/$e/check-in",
    "/api/members/$e/tasks",
    "/api/members/$e/saved-looks"
)) {
    try {
        $r = Invoke-WebRequest -Uri "$dbBase$p" -Method Get -WebSession $s
        "$p -> $($r.StatusCode)   setcookie=$([bool]$r.Headers['Set-Cookie'])"
    } catch {
        "$p -> $($_.Exception.Response.StatusCode.value__)  <== 失敗"
    }
}

# 3) 連續 5 次，檢查多 worker 有沒有隨機掉線
1..5 | ForEach-Object {
    $r = Invoke-WebRequest -Uri "$dbBase/api/members/$e" -Method Get -WebSession $s
    "round $_ -> $($r.StatusCode)"
}
```

**全部通過的標準**

- 登入 200，且有 `Set-Cookie`
- 五條唯讀端點全部 200（**沒有任何一條 401**）
- 除了登入以外，其他回應都**沒有** `Set-Cookie`
- 連續 5 次全部 200
- 假 Cookie → 401（JSON，不是 HTML）
- Log 裡沒有密碼、完整 Cookie、API Key、完整 email

---

## 七、不要做的事

- 不要為了通過驗收就把端點改成不驗證，或直接回 200
- 不要信任請求 body / query 裡的 `email`、`role` 來決定身分（那是使用者可控的）
- 不要因為「沒有 Origin」或「User-Agent 不是瀏覽器」就拒絕請求
- 不要讓前端保存資料庫 Cookie、JWT 或 API Key
- 不要把密碼、完整 Cookie、API Key、完整 email 寫進 Log
- 不要把測試帳密或金鑰提交到 GitHub

---

## 八、修好後請回覆這六項

只回非敏感資訊：

1. 目前服務基底網址
2. `/api/login` 是否有 `Set-Cookie`：有／沒有
3. 第六節腳本裡五條端點各自的狀態碼
4. Session 存在哪：PostgreSQL／Redis／簽章 Cookie／其他
5. Session 有效時間（分鐘）
6. 端點是否需要服務 API Key：需要的話只給**標頭名稱**，金鑰本身放 Secret Manager

這六項回來之後，我們才會在 Gateway 端跑正式端到端測試：登入 → 會員頁 → 點數 → 打卡 → 收藏 → 刪除妝容 → 刪除會員。
