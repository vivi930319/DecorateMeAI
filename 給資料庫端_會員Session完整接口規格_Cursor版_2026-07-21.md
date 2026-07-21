# 給資料庫端：會員 Session 完整接口規格（Cursor 執行版）

> 日期：2026-07-21
>
> 這份是 `給資料庫端_會員登入Session修復規格_2026-07-21.md` 的**擴充版**。前一份只規範了登入與 `/api/members/{email}` 兩條；這份補上**其餘 12 條端點**，因為實際故障發生在 `check-in`，不是登入。兩份衝突時以這份為準。
>
> 禁止寫入本文件、Log、Git 或訊息：真實密碼、完整 Cookie 值、API Key、JWT、完整會員 email、會員照片。

---

## 〇、給 Cursor 的使用方式

### 0.1 先建規則檔（做一次就好）

Cursor 的硬性限制放在規則檔比放在對話裡可靠——對話會被後面的訊息稀釋，規則檔每次都會自動帶進 context。

在專案根目錄建立 `.cursor/rules/member-session.mdc`：

```markdown
---
description: 會員 Session 接口修復的硬性限制
alwaysApply: true
---

修改會員驗證相關程式時，以下限制違反就是錯的，寧可停下來問人：

- 不可以移除或放寬任何身分驗證
- 不可以把端點改成公開或不檢查 Session
- 不可以信任請求 body / query / path 裡的 email、role 欄位來決定身分
- 不可以為了讓測試通過就回傳假資料或寫死 200
- 既有的 Flask-Login 與 Bearer JWT 驗證一律保留，只能「多接受一種身分」，
  不可以替換掉（iOS App 仍在用）
- 不確定規格就先問，不要自己猜
```

### 0.2 每個 TASK 的操作方式

用 `Ctrl+I`（Mac 是 `Cmd+I`）開 Agent，把本檔案用 `@` 帶進 context，一次只貼一個 TASK：

```text
@給資料庫端_會員Session完整接口規格_Cursor版_2026-07-21.md

這是外部 Gateway 對本服務的接口契約，本服務目前不符合，導致使用者登入後
幾秒內被登出。

請只做第五節的 TASK 0，不要動其他 TASK 的範圍。
做完後：
1. 說明你改了哪些檔案、改了什麼
2. 執行該 TASK 底下的「驗收」指令並貼出結果
3. 停下來等我確認
```

下一個 TASK 就把 `TASK 0` 換成 `TASK 1`，依此類推。

### 0.3 Cursor 專屬的四個注意事項

| 事項 | 說明 |
|---|---|
| **TASK 1 用 Ask 模式，不要用 Agent** | TASK 1 是純盤點、不該改任何程式。Agent 模式會忍不住順手改，用 Ask（唯讀）比較安全 |
| **不要按 Accept All** | Agent 會一次跨多檔改動。請逐檔看 diff 再 Accept；特別注意它有沒有偷偷把 `@login_required` 整行刪掉 |
| **開新 Chat 分隔 TASK** | 同一個 Chat 累積六個 TASK 會讓模型混淆前後文。每個 TASK 開新 Chat，規則檔會自動重新帶入 |
| **驗收指令自己跑** | 別讓 Agent 自己宣稱「測試通過」。第六節的 PowerShell 腳本請人工執行並貼回結果 |

> 模型建議用 Claude 或 GPT 系列的 thinking 模式。這份任務的重點在「不要改壞既有驗證」，推理能力比速度重要。

---

## 一、一句話問題

會員登入成功後，Gateway 用同一個 Session Cookie 呼叫 `/api/members/{email}/check-in`，**收到 401**，於是前端整批背景請求被取消、跳回登入頁並顯示「登入狀態已失效」。

登入本身是成功的（`/auth/session` 預檢通過），所以問題**不在登入**，而在「登入後其他端點是否認得同一個 Session」。

### 根因（2026-07-21 已由資料庫端釐清）

Session **不是**行程內記憶體，而是 PostgreSQL `member_sessions` 表，所以 R1 沒有問題。真正的原因是服務內同時存在三套身分機制，而各端點用的不是同一套：

| 機制 | 儲存位置 | Gateway 會送嗎 |
|---|---|---|
| `member_session` cookie | PostgreSQL `member_sessions` | ✅ 會 |
| Flask-Login 簽章 cookie | 瀏覽器 cookie | ❌ 不會 |
| Bearer JWT | 不存 server | ❌ 不會 |

- `/api/login` 建立 `member_session`；`/api/members/{email}` 與 `saved-looks` 用 `get_session_member()`／`authenticated_member()` 驗證 → Gateway 通得過。
- `check-in`、`tasks`、`points` 用 `@login_required` 與 `current_user`，只認 Flask session 或 Bearer → Gateway 兩者都沒有 → 固定 401／403。

所以本文件的重點是 **TASK 3**：讓第 3～16 條端點都認得 `member_session`。

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
| 15 | GET | `/api/recommend/personal` | 個人化推薦（**目前 app.py 缺這個端點，前端有在呼叫**） | 是 |
| 16 | POST | `/api/favorites/toggle` | 商品收藏切換 | 是 |

**第 3～16 條全部都必須接受同一個登入 Cookie。** 這是這次的核心問題：目前很可能只有第 3 條（或只有登入）是通的。

### 3.1 我們這邊的匿名實測（2026-07-21，Gateway 端直接對你的服務發的）

不需要帳密就能驗的部分我們先跑完了，結果如下。**好消息是錯誤碼與格式已經符合 R5，不用再花時間在 TASK 5。**

| 請求（無 Cookie） | 實測 | 判定 |
|---|---|---|
| `GET /health` | `200`，`{"service":"member-database","status":"ok"}` | ✅ 通道與服務是活的 |
| `GET /api/members/{email}` | `401` JSON | ✅ 符合 R5 |
| `GET /api/members/{email}/points` | `401` JSON | ✅ **已是 401**，先前記錄的 403 已不復現 |
| `GET /api/members/{email}/check-in` | `401` JSON | ✅ 符合 R5 |
| `GET /api/members/{email}/tasks` | `401` JSON | ✅ 符合 R5 |
| `GET /api/members/{email}/saved-looks` | `401` JSON | ✅ 符合 R5 |
| `GET /api/members` | `401` JSON | ✅ 符合 R5 |
| `POST /api/favorites/toggle` | `401` JSON | ✅ 符合 R5 |
| `GET /api/recommend/personal` | **`404`，而且是 HTML** | ❌ 端點確實不存在（第 15 條），前端有在呼叫 |
| 假 Cookie → `GET /api/members/{email}/points` | `401` JSON | ✅ TASK 5 驗收已通過 |
| 不存在帳號 `POST /api/login` | `401` JSON，無 `Set-Cookie` | ✅ 密碼錯誤回 401 正確 |

沒有任何一條回 `500`，也沒有 `302` 轉登入頁——**R5 這關你們已經過了**。

這代表：**剩下的問題百分之百集中在「帶著有效 Cookie 時會不會過」**，也就是 TASK 3。匿名 401 是對的，有效 Cookie 也 401 才是 bug，而這件事我們這邊測不出來——我們沒有 Demo 帳號密碼，需要你們自己跑第六節腳本。

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

## 五、Cursor 任務清單

### TASK 0：確認 `member_sessions` 在正式資料庫真的存在（最優先）

`postgres.sql` 裡沒有 `member_sessions` 的建表語句，目前靠 `db.create_all()` 動態建立。如果正式資料庫是從 `postgres.sql` 建的、而且沒跑過 `db.create_all()`，那麼**登入本身就會失敗**，後面所有 TASK 都是白做。

**做什麼**

1. 連到正式資料庫，確認資料表存在：

   ```sql
   SELECT to_regclass('public.member_sessions');
   ```

2. 回傳 `NULL` 就是不存在，把建表語句補進 `postgres.sql`，欄位對齊 `MemberSession` model：
   `session_hash`（PK）、`member_id`（FK → `members.phone_number`）、`created_at`、`expires_at`、`revoked_at`、`last_seen_at`。
3. 建議加索引：`expires_at`、`member_id`。

**驗收**：上面的 SQL 回傳 `member_sessions`，且登入後該表確實新增一列。

---

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

**怎麼改（重要：用「疊加」不要用「替換」）**

不要把 `@login_required` 直接換成 `get_session_member()`。iOS App 與資料庫自己的網頁可能仍在用 Flask-Login 或 Bearer JWT，直接替換會把它們一起打死。

正確做法是做一個統一解析器，三種都收，任一成立就放行：

```python
def resolve_member():
    """依序嘗試三種身分來源，回傳 member 或 None。"""
    member = get_session_member()          # Gateway 走這條
    if member:
        return member
    if current_user.is_authenticated:      # 既有網頁 / iOS
        return current_user
    return None                            # 交由呼叫端回 401
```

然後把第 3～16 條端點的 `@login_required` 換成用 `resolve_member()` 的裝飾器。這樣 Gateway 開始能通過，而現有用戶端一個都不會壞。

**注意**

- 不是「拿掉驗證」，是「多接受一種合法身分」
- 目前確認 401 的是 `check-in`、`tasks`、`points`，但請把第 3～16 條**逐條**檢查，不要只修這三個
- `member_id` 存的是 `phone_number`，但 URL 路徑用的是 email——比對擁有者時要確認兩邊是同一個欄位，不要拿 phone 去比 email
- 擁有者不符時回 `403`；但 `role=admin` 必須放行，Gateway 的管理員功能會用管理員身分存取其他會員的路徑
- `points` 的未登入回應先前記錄為 `403`，2026-07-21 實測已經是 `401`，這項不用再改（見 3.1）
- 第 15 條 `/api/recommend/personal` 實測 `404`，是**整條端點不存在**，不是驗證問題。請先確認要不要補；在補出來以前，前端呼叫它一定失敗

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

> **2026-07-21 更新：這個 TASK 我們已經替你們驗過了，目前全部通過（見 3.1）。**
> 匿名與假 Cookie 一律回 `401` JSON，沒有 `500`、沒有 `302`。
> 除非 TASK 3 改動時不小心破壞了錯誤碼，否則**這個 TASK 可以直接跳過**；
> 改完 TASK 3 後回頭跑一次下面的驗收確認沒有退步就好。

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

下面的網址是 2026-07-21 我們實測 `/health` 為 `200` 的那一組。Quick Tunnel 每次重啟都會換，如果你已經重開過服務，請換成新的並**同時通知我們**（Gateway 的環境變數要跟著改，不改的話線上會員功能全掛）。只用 Demo 測試帳號。

```powershell
$dbBase = 'https://programmers-planners-convenient-had.trycloudflare.com'
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
