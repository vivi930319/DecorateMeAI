# 會員資料庫服務：前端串接規格書

> 文件版本：`2026-07-v1-Draft`
> 適用服務：前端（web_frontend）↔ 會員資料庫 API（合作方維運，目前規劃透過 Cloudflare Tunnel 交付）
> 目前狀態：前端已經照這份規格在打 API，但目前這個網址連不上（DNS 無法解析），登入/註冊會直接 fallback 成本機模擬。這份文件同時記錄「現有前端已經在用的契約」跟「還缺的部分」，麻煩對照確認。

本文件定義前端與會員資料庫服務之間的正式對接規範，涵蓋帳號登入、註冊、OTP 驗證，以及後台管理需要新增的會員資料管理端點。

## 0. 現況總結（給忙碌版）

前端目前會打以下端點，全部都是 `POST` + `application/json`：

| 端點 | 用途 | 前端呼叫函式 |
| --- | --- | --- |
| `/api/login` | 登入 | `Api.login()` |
| `/api/register` | 註冊 | `Api.register()` |
| `/api/send-otp`（失敗會改打 `/api/register`） | 寄送註冊驗證碼 | `Api.sendOTP()` |
| `/api/verify-otp` | 驗證註冊驗證碼 | `Api.verifyOTP()` |

**現在缺的東西（這份文件主要要溝通的）：**

1. 會員資料需要多帶 `level`（會員等級）跟 `role`（角色）兩個欄位，見第 2 節。
2. 需要新增一個「管理員更新會員資料」的端點，讓後台可以把某個會員升級成 VIP、或停權，見第 3 節。
3. 目前完全沒有做任何連線認證（沒有帶 API Key / Token），如果正式環境需要驗證，麻煩先講一聲，前端這邊可以照 Ollama 那份串接的模式（`X-API-Key` header）比照辦理。

## 0.1 2026-07-08 後台權限收斂更新

前端這一輪已經改成：

- **PRO / render / admin 權限只看後端欄位**
- **登入後不再用 email 白名單覆寫 `role` / `level`**
- **後台 `GET /api/members` 已改回 `credentials: 'include'` 正式模式**

所以會員資料庫端現在必須把下面這批欄位視為**唯一權限來源**：

- `role`
- `level`
- `status`
- `allowedPages`
- 建議補 `vipRequested`
- 建議補 `renderQuota`

如果這些欄位缺漏、回舊值、或只有部分端點會回，前端畫面刷新後就會不一致。

## 1. 通訊與協議基本規則

| 項目 | 規格 |
| --- | --- |
| Protocol | HTTPS |
| Encoding | UTF-8 |
| Request Content-Type | `application/json` |
| Response Content-Type | `application/json; charset=utf-8` |
| 安全驗證 Header | 目前無，待確認是否需要（見第 0 節） |
| 欄位命名 | 現有欄位沿用 `snake_case`（`phone_number`），新欄位建議統一用這個慣例 |

## 2. 現有端點（前端已經在打，麻煩對照現況）

### 2.1 登入 `POST /api/login`

請求：

```json
{
  "email": "user@example.com",
  "password": "使用者輸入的密碼"
}
```

前端期待的成功回應（HTTP `200`）：

```json
{
  "member": {
    "name": "王小美",
    "email": "user@example.com",
    "phone_number": "0912345678",
    "age": 25,
    "level": "一般會員",
    "role": "member",
    "status": "active",
    "allowedPages": ["dashboard", "analysisBasic", "style", "products", "favorites", "history", "compare", "suggestion", "profile"],
    "vipRequested": false,
    "renderQuota": {
      "dailyLimit": 3,
      "remaining": 2,
      "resetAt": "2026-07-09T00:00:00+08:00"
    }
  }
}
```

**這裡是這次要溝通的重點**：前端現在會直接讀取並信任 `member.role`、`member.level`、`member.status`、`member.allowedPages`，並用它們決定 admin / PRO / render 顯示與頁面存取。麻煩資料庫那邊實際回傳這些欄位，且回傳當下該會員資料庫裡最新的值。

`level` 允許值：

- `一般會員`（預設，新註冊會員都是這個）
- `VIP會員`（可使用 PRO 進階分析功能，需由管理員在後台手動升級）
- `管理員`（不透過這個欄位判斷，管理員身分目前由前端 email 規則暫代，見第 4 節說明）

`role` 允許值：`member`、`admin`

`status` 允許值：`active`、`suspended`

`allowedPages` 建議至少支援：

- `dashboard`
- `analysisBasic`
- `analysisPro`
- `style`
- `products`
- `favorites`
- `history`
- `compare`
- `suggestion`
- `profile`
- `admin`
- `unlimitedRender`

`vipRequested` 建議值：

- `false`
- `true`

`renderQuota` 若後端暫時還沒做真正會員綁定配額，可先不回；但**不要讓前端自己報真實剩餘次數**。如果要回，格式建議固定如下：

```json
{
  "dailyLimit": 3,
  "remaining": 2,
  "resetAt": "2026-07-09T00:00:00+08:00"
}
```

若登入失敗（帳密錯誤 / 帳號不存在），請回傳非 `2xx` 狀態碼，前端會捕捉例外並嘗試本機模擬（僅原型階段行為，正式上線後這個 fallback 會拿掉）。

### 2.2 註冊 `POST /api/register`

請求：

```json
{
  "phone_number": "0912345678",
  "name": "王小美",
  "email": "user@example.com",
  "password": "使用者輸入的密碼",
  "age": 25
}
```

前端目前不解析這支 API 的回應內容，只看 HTTP 狀態碼是否成功。**新註冊的會員請一律存成 `level: 一般會員`**（前端這邊已經把預設值從 `VIP會員` 改回 `一般會員` 了，麻煩後端也統一）。

### 2.3 寄送註冊驗證碼 `POST /api/send-otp`

請求：

```json
{ "email": "user@example.com" }
```

前端會先打 `/api/send-otp`，失敗的話會改打 `/api/register` 當作備援（原型階段的權宜設計，正式串接後建議只保留一個正確的端點，跟我們說要用哪一個）。

### 2.4 驗證註冊驗證碼 `POST /api/verify-otp`

請求：

```json
{ "email": "user@example.com", "otp": "使用者輸入的驗證碼" }
```

### 2.5 管理員會員清單 `GET /api/members`

這支端點現在是前端 admin 後台的正式資料來源。前端已經不再接受公開讀取或 demo fallback 模式。

回應（HTTP `200`，**只允許 admin session**）：

```json
{
  "members": [
    {
      "name": "王小美",
      "email": "user@example.com",
      "phone_number": "0912345678",
      "age": 25,
      "level": "一般會員",
      "role": "member",
      "status": "active",
      "allowedPages": ["dashboard", "analysisBasic", "style", "products", "favorites", "history", "compare", "suggestion", "profile"],
      "vipRequested": false,
      "renderQuota": {
        "dailyLimit": 3,
        "remaining": 2,
        "resetAt": "2026-07-09T00:00:00+08:00"
      }
    }
  ]
}
```

注意：

- 未登入不可回會員清單
- 一般會員不可回會員清單
- 這支不應再公開暴露全站會員資料
- 前端目前已固定使用 `credentials: 'include'` 讀這支，不能再假設匿名讀取

## 3.（新增需求）管理員更新會員資料端點

目前後台管理頁面（`/admin`）已經做好「把某會員升級成 VIP、停權/啟用」的介面，但因為沒有這支 API，現在這些操作只能存在管理員自己瀏覽器的 localStorage，**不會真的同步到會員本人的帳號**。麻煩協助新增以下端點：

建議端點：`PATCH /api/members/{email}`

請求：

```json
{
  "level": "VIP會員",
  "status": "active",
  "role": "member",
  "allowedPages": ["dashboard", "analysisBasic", "analysisPro", "style", "products", "favorites", "history", "compare", "suggestion", "profile"],
  "vipRequested": false,
  "renderQuota": {
    "dailyLimit": 10,
    "remaining": 7,
    "resetAt": "2026-07-09T00:00:00+08:00"
  }
}
```

欄位規則：

- `status` 允許值：`active`、`suspended`
- `role` 允許值：`member`、`admin`
- `allowedPages` 建議視為完整覆蓋寫入，不要做模糊 merge
- `vipRequested` 若你們決定保留升級申請流程，就應由後端正式存這個欄位
- `renderQuota` 若你們決定把會員配額存在 member database，`PATCH` 應能回傳最新 quota；若不放在 member database，也至少要在回應裡給前端最新可顯示值

停權建議：**被停權帳號應直接無法登入**；若你們選擇允許登入再由前端擋頁面，也請明確告知，但不建議。

回應（HTTP `200`）：

```json
{
  "member": {
    "email": "user@example.com",
    "level": "VIP會員",
    "role": "member",
    "status": "active",
    "allowedPages": ["dashboard", "analysisBasic", "analysisPro", "style", "products", "favorites", "history", "compare", "suggestion", "profile"],
    "vipRequested": false,
    "renderQuota": {
      "dailyLimit": 10,
      "remaining": 7,
      "resetAt": "2026-07-09T00:00:00+08:00"
    }
  }
}
```

這支 API 應該要有權限檢查（只有管理員帳號能呼叫），而且**必須回傳更新後完整 member**，不要只回 `{ ok: true }` 或只回 patch 片段；否則前端只能暫時拼湊畫面，刷新後就會不穩。

### 3.1 管理員刪除會員資料 `DELETE /api/members/{email}`

後台會員管理提供「刪除會員」操作，前端會呼叫：

```text
DELETE /api/members/{email}
```

安全與資料一致性要求：

- 只有已驗證的管理員 session／Bearer token 可以呼叫；一般會員不可刪除任何會員。
- 禁止刪除目前登入中的管理員帳號；後端也必須再次驗證，不能只依賴前端按鈕停用。
- 請明確定義關聯資料處理方式：會員收藏、點數交易、購物車、分析歷史可採 cascade delete，或依隱私／稽核需求做匿名化；不可留下無主資料。
- 成功回 `200 {"ok": true}` 或 `204 No Content`；失敗回標準錯誤 JSON，前端只有收到 2xx 才會從畫面與本機快取移除會員。
- 建議寫入管理員 audit log，至少包含操作者、被刪除 email、時間與結果；刪除不可透過前端自行修改 localStorage 取代後端授權。

## 4.（2026-07-06 更新）管理員身分判斷改為完全依賴資料庫

**現況已變更**：前端原本有兩個管理員身分的暫時性繞過，這次已經拿掉：

1. 前端原本寫死一組管理員帳密（`admin@decorateme.local` / 固定密碼），登入時直接比對字串放行，完全不打 API。**已移除**，這組帳號現在必須跟一般會員一樣，真的呼叫 `/api/login` 給你們驗證。
2. 前端原本邏輯：只要 email 開頭是 `admin@`，不管資料庫回傳什麼都視為管理員。**這個規則麻煩你們也視為即將移除**（目前前端會先跟你們確認，可能近期會拿掉），改成完全只看第 2 節登入回應裡的 `member.role === "admin"` 或 `member.level === "管理員"`。

拿掉這兩個繞過之後，代表**管理員身分完全交給你們資料庫決定**，前端不再有任何自己判斷的邏輯。這樣一來有一個雞生蛋問題需要你們處理：

### 4.1 第一個管理員帳號怎麼來（麻煩你們決定並告知）

前端這邊沒有任何管理員帳號的建立/授權介面（第 3 節的 `PATCH /api/members/{email}` 需要「已經是管理員」的人才能呼叫），所以**第一個管理員帳號沒辦法透過一般流程產生**。麻煩你們選一種方式並告知我們：

- **方案 A（建議）**：直接在資料庫後台/資料庫 migration script 手動插入一筆帳號，`role` 設為 `admin`，帳密由你們自訂，安全地告知我們即可（不要透過前端網頁，也不要寫進任何前端會讀到的檔案）。
- **方案 B**：資料庫服務啟動時讀取環境變數（例如 `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD`），第一次啟動時自動建立這個帳號，環境變數只存在你們的伺服器環境裡，不會被前端看到。

不管哪種方案，麻煩提供一組實際能登入、且 `/api/login` 回應會帶 `role: "admin"` 的帳號給我們測試。

### 4.2 驗收方式

請用你們建立的管理員帳號實際打一次 `/api/login`，回應應該長這樣（對照第 2.1 節格式）：

```json
{
  "member": {
    "name": "管理員顯示名稱",
    "email": "你們設定的管理員 email",
    "phone_number": "...",
    "age": 0,
    "level": "管理員",
    "role": "admin"
  }
}
```

我們收到範例後會實測前端登入這組帳號，確認後台管理頁面能不能正常開啟。

## 5. 錯誤處理與 CORS / Session 要求

### 5.1 `GET /api/members` / `PATCH /api/members/{email}` 的安全要求

這兩支 members 管理端點現在都應滿足：

1. 只有 admin session 可讀 / 可寫
2. 前端使用 `credentials: 'include'`
3. 後端回 `Access-Control-Allow-Credentials: true`
4. `Access-Control-Allow-Origin` 必須是前端實際網域，**不能是 `*`**
5. session cookie 需可跨站送出，通常要：
   - `SameSite=None`
   - `Secure`
6. 若有 `OPTIONS` preflight，也要回上面兩個 CORS header

若這些沒同時成立，前端後台會出現兩種症狀：

- `GET /api/members` 直接讀不到會員列表
- `PATCH /api/members/{email}` 後端即使有處理，瀏覽器仍可能把回應擋掉

### 5.2 一般錯誤回應格式

現況：前端對「登入」這支 API 已經改成**任何非 `2xx` 都直接擋下、不放行**（不管是連不上還是帳密錯誤，都不再 fallback 成本機模擬登入），這是刻意的安全性修正，不是原型行為了。其餘幾支 API（註冊、OTP）目前還保留原型階段的本機 fallback，之後也會陸續拿掉，屆時再另外通知。正式串接建議至少回傳：

```json
{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "帳號或密碼錯誤"
  }
}
```

實際的 `error.code` 清單麻煩你們定義後補進這份文件，我們再對應前端錯誤訊息顯示。

## 6. 前端設定

前端目前透過 `config.local.js` 設定會員資料庫網址：

```js
window.DECORATE_ME_CONFIG = {
    memberDatabaseUrl: '<你們的 Cloudflare Tunnel 網址>'
};
```

網址每次重啟 tunnel 若會變動，麻煩比照 Ollama 那邊的做法，重啟後把新網址告知，我們這邊更新即可（如果能申請具名/固定 tunnel 網址最好，就不用每次重貼）。

---

> 以下第 7、8 節是 `2026-07-06` 補充的需求，起因是前端後台管理頁面（`/admin`）目前很多操作都只存在管理員自己瀏覽器的 localStorage，沒有真的寫回資料庫。麻煩對照現況評估。

## 7.（新增需求）後台管理員權限與操作紀錄

### 7.1 現況說明

前端後台管理頁面（`pages/admin.html`，邏輯在 `js/router.js` 的 `AdminStore`）目前能做到：

- 搜尋／篩選會員
- 修改會員角色（`member` / `admin`）
- 修改會員等級（`一般會員` / `VIP會員`）
- 停權／啟用
- 勾選細部功能權限（`allowedPages`：這個會員可以用哪些頁面/功能）

但這些操作目前**只存在管理員自己瀏覽器的 localStorage**，換一台電腦或換瀏覽器登入後台就看不到別人做過的修改。第 3 節已經定義的 `PATCH /api/members/{email}` 目前只接受 `level` 和 `status` 兩個欄位，還缺 `role` 和 `allowedPages`，麻煩擴充。

### 7.2 擴充 `PATCH /api/members/{email}`

請求（在原本 `level` / `status` 之外，新增兩個可選欄位）：

```json
{
  "level": "VIP會員",
  "status": "active",
  "role": "admin",
  "allowedPages": ["dashboard", "analysis", "admin"]
}
```

- `role` 允許值：`member`、`admin`（跟第 2 節登入回應的 `role` 定義一致）
- `allowedPages` 是這個會員被允許使用的功能頁面清單，建議值以第 2.1 節列的頁面代碼為準
- 建議把 `vipRequested` 與 `renderQuota` 也納入同一支管理 API 的完整回應，讓前端重新整理後不會失去最新狀態

回應（HTTP `200`）：

```json
{
  "member": {
    "email": "user@example.com",
    "level": "VIP會員",
    "status": "active",
    "role": "admin",
    "allowedPages": ["dashboard", "analysisBasic", "analysisPro", "style", "products", "favorites", "history", "compare", "suggestion", "profile", "admin"],
    "vipRequested": false,
    "renderQuota": {
      "dailyLimit": 10,
      "remaining": 7,
      "resetAt": "2026-07-09T00:00:00+08:00"
    }
  }
}
```

## 7.5 Admin 後台驗收清單（請修完後逐條自測）

1. 一般會員登入後不能進後台 `/admin`
2. admin 登入後可成功呼叫 `GET /api/members` 並看到會員列表
3. 修改 `role` / `level` / `allowedPages` / `status` 後重新整理，資料仍一致
4. 被設成 `suspended` 的帳號無法登入，或至少登入後立即被明確擋下
5. 跨站前端環境下（`decorate-me.web.app` 或實際前端網域），cookie 真的有隨 `credentials: 'include'` 一起送出

### 7.3 操作紀錄 audit log（新增端點）

建議端點：`GET /api/members/{email}/audit-log`（實際路徑可依你們資料庫設計調整，麻煩告知最終定案）

用途：記錄每一次管理員異動（誰、何時、改了什麼、改成什麼），方便之後追查問題或防止誤操作。

回應：

```json
{
  "logs": [
    {
      "actorEmail": "admin@example.com",
      "targetEmail": "user@example.com",
      "action": "level_change",
      "before": "一般會員",
      "after": "VIP會員",
      "timestamp": "2026-07-06T10:00:00Z"
    }
  ]
}
```

`action` 建議值：`level_change`、`status_change`、`role_change`、`permission_change`、`points_adjust`。這支端點的權限應比照第 3 節，只有管理員能查。

### 7.4 商品管理 CRUD（新增資源，目前完全沒有規格）

現況：後台「商品管理」（`pages/admin.html` 的商品區塊）目前是純前端 localStorage（`AdminStore.addProduct` / `updateProduct`），跟正式要推播給使用者看的商品清單完全脫節，重新整理或換裝置資料就消失。

建議端點：

| Method | 路徑 | 用途 |
| --- | --- | --- |
| GET | `/api/products` | 取得商品清單 |
| POST | `/api/products` | 新增商品 |
| PATCH | `/api/products/{id}` | 編輯商品 |
| DELETE | `/api/products/{id}` | 下架／刪除商品 |

商品欄位（對應現有後台表單）：

```json
{
  "id": "prod-xxxx",
  "name": "柔霧粉底液",
  "cat": "底妝",
  "price": "NT$980",
  "img": "https://...",
  "desc": "商品描述文字",
  "shades": ["#3A241C", "#C99070", "#B5654A"]
}
```

這塊建議先跟「商品推薦」的組員確認是不是同一個資料庫/服務，避免兩邊各自建一份商品資料，之後商品推薦結果對不起來。

## 8.（新增需求）點數 Ledger 點數紀錄系統

這是會員成長系統（簽到、推薦、任務、點數商店）的核心資料表，之後所有加點/扣點都要寫進這裡，方便對帳跟防作弊稽核。這次先麻煩建好核心資料表跟查詢/手動調整這兩支端點，簽到/推薦/兌換/任務相關的端點會之後陸續再發規格書。

### 8.1 資料表建議：`points_transactions`

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `id` | string/int | 交易識別碼 |
| `member_email` | string | 會員 email |
| `delta` | int | 正數為加點，負數為扣點 |
| `balance_after` | int | 交易後的餘額 |
| `reason` | string | 見下方允許值 |
| `ref_id` | string，可選 | 關聯的簽到/推薦/兌換/任務 id |
| `created_at` | datetime | 交易時間 |

`reason` 允許值：`check_in`（每日打卡）、`streak_bonus`（連續簽到獎勵）、`referral`（推薦人獎勵）、`redeem`（兌換點數商店商品）、`task_reward`（任務獎勵）、`admin_adjust`（管理員手動調整）

### 8.2 端點

`GET /api/members/{email}/points`

回應：

```json
{
  "balance": 320,
  "transactions": [
    {"delta": 10, "reason": "check_in", "balance_after": 320, "created_at": "2026-07-06T09:00:00Z"},
    {"delta": -50, "reason": "redeem", "balance_after": 310, "created_at": "2026-07-05T14:00:00Z"}
  ]
}
```

`POST /api/members/{email}/points/adjust`（管理員專用，用於後台手動調整點數）

請求：

```json
{ "delta": 100, "reason": "admin_adjust", "note": "活動獎勵補發" }
```

回應（HTTP `200`）：

```json
{ "balance": 420 }
```

這支端點應該要有管理員權限檢查，同第 3 節。

### 8.3 之後會依賴這張表的功能（先告知，這次不必一起做）

- 每日打卡集點、連續簽到獎勵
- 推薦碼集點
- 點數商店兌換
- 任務中心獎勵

這些之後會陸續發規格書給你們，這次只需要先把 `points_transactions` 核心資料表跟查詢/手動調整這兩支端點建好即可。

## 9.（2026-07-07 新增需求）收藏妝容對比圖：紀錄存資料庫

### 9.1 背景

前端有「收藏妝容對比圖」功能：使用者完成臉部分析 → AI 渲染妝容 → 把「渲染前/渲染後照片 + 風格 + 分析摘要」存成一筆收藏。目前這些紀錄**只存在瀏覽器 localStorage**，換裝置或清瀏覽器資料就全部消失。

圖片本身的問題前端已經解決：渲染圖現在會自動存到我們的 GCS（`https://storage.googleapis.com/decorate-me-renders/...`），是**永久公開網址**，你們資料庫只需要存 URL 字串，不用碰圖片檔案本身。

### 9.2 資料表建議：`saved_looks`

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `id` | string/int | 紀錄識別碼 |
| `member_email` | string | 會員 email |
| `style` | string | 妝容風格名稱（例如「港風」） |
| `before_image_url` | text | 渲染前照片網址（可能是 data URL，較長，建議用 text 型別） |
| `after_image_url` | text | 渲染後照片的永久網址（GCS） |
| `analysis_summary` | json/text | 臉部分析摘要（臉型/眼型/膚色等，前端會給一包 JSON） |
| `created_at` | datetime | 收藏時間 |

### 9.3 端點

| Method | 路徑 | 用途 |
| --- | --- | --- |
| GET | `/api/members/{email}/saved-looks` | 取得該會員全部收藏（新到舊） |
| POST | `/api/members/{email}/saved-looks` | 新增一筆收藏 |
| DELETE | `/api/members/{email}/saved-looks/{id}` | 刪除一筆收藏 |

POST 請求範例：

```json
{
  "style": "港風",
  "beforeImageUrl": "data:image/jpeg;base64,...",
  "afterImageUrl": "https://storage.googleapis.com/decorate-me-renders/rendered/xxxx.jpg",
  "analysisSummary": { "faceShape": "鵝蛋臉", "eyeShape": "杏仁眼", "skinSeason": "春季" }
}
```

注意事項：

1. `beforeImageUrl` 可能是 base64 data URL（原始照片沒有上雲），單筆可能到數百 KB，欄位型別麻煩用能容納的（text/longtext）。如果你們覺得太大，告訴我們上限，前端可以只存壓縮版或乾脆只存渲染後那張。
2. 每個會員收藏數量建議上限 50 筆（超過時由你們拒絕或由我們前端擋都可以，說一聲用哪種）。
3. 權限：只有本人（登入 session 對應的 email）能讀寫自己的收藏。

### 9.4 完整資料流：渲染圖從哪來、哪個欄位要存（重要）

目前整條使用者流程的結果都只活在前端的 `analysisPackage`（前端記憶體 + localStorage），**資料庫完全沒有存到任何一步**，換裝置就全部消失。流程如下：

```
上傳照片 → 臉部分析(Cloud Run) → 妝容文字建議(Ollama)
        → AI 渲染妝容(Replicate) → 渲染圖上傳我方 GCS，拿到永久網址
        → 使用者按「收藏妝容對比圖」→（這一步之後才會呼叫你們的 POST /api/members/{email}/saved-looks）
```

前端 `analysisPackage.render` 物件在渲染完成後長這樣（你們只需要關心其中兩個欄位）：

```json
"render": {
  "status": "completed",
  "provider": "replicate",
  "afterImageUrl": "https://storage.googleapis.com/decorate-me-renders/rendered/xxxx.jpg",  ← 【要存這個】渲染後永久網址（我方 GCS，不會過期）
  "replicateTempUrl": "https://replicate.delivery/....",  ← 不要存這個，這是會過期的暫存網址
  "isPermanent": true   ← true 代表 afterImageUrl 已是永久網址；false 代表上傳 GCS 失敗、afterImageUrl 退回暫存網址
}
```

**關鍵對應**：`saved_looks.after_image_url` 要存的就是 `render.afterImageUrl`（永久網址），**不是** `replicateTempUrl`。前端送 POST 時已經幫你們挑好永久網址那個，你們照 9.3 的 `afterImageUrl` 欄位存即可。

觸發時機：**只有使用者按「收藏」才存一筆**（不是每次渲染都存，避免存一堆使用者根本沒要留的圖）。所以你們的 `POST /api/members/{email}/saved-looks` 只會在收藏當下被呼叫一次。

（附註：如果之後你們也想留「分析歷史」而不只是收藏，那是另一張表的事，這份規格先只處理收藏。要做再跟我們說。）
