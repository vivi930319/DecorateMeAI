# Gateway 安全代理與 Ollama 專題展示說明

> 更新日期：2026-07-19  
> 專案：Decorate Me  
> 用途：專題展示、系統維護與專題結束後的安全收尾提醒  
> 注意：本文件不得記錄 API key、JWT、密碼、完整 email、照片、完整分析包或完整生成提示。

---

## 一、Gateway 到底是什麼？

Gateway 可以理解成「前端與後端服務中間的安全櫃台」。

使用者在瀏覽器操作 Decorate Me 時，前端不直接拿著 API key 呼叫 Face、Render、Ollama 或會員資料庫，而是先把請求送給 Gateway。Gateway 確認會員是否登入、路徑是否允許、請求是否太頻繁，再使用伺服器端保存的憑證呼叫真正的服務。

可以把整個流程想成餐廳：

- 前端是客人，只負責點餐。
- Gateway 是櫃台，負責確認客人、檢查訂單及把訂單送到正確廚房。
- Face、Render、Ollama、會員資料庫是廚房。
- API key、Cloud Run IAM 與 session secret 是廚房鑰匙，只能由櫃台保管，不能交給客人。

```text
使用者瀏覽器
     │
     │ 登入 session + 功能請求
     ▼
AI Gateway
     │
     ├── Face Basic / Face Pro
     ├── Render
     ├── Ollama 文字建議
     └── 會員資料庫
```

Gateway 不是單純把 API 換一個網址。它的工作還包括：

- 驗證登入會員。
- 檢查管理員權限。
- 限制允許呼叫的 API 路徑。
- 限制登入嘗試次數與請求大小。
- 統一處理 CORS、錯誤代碼與逾時。
- 保管上游服務金鑰。
- 避免瀏覽器偽造 email、role 或管理員身分。

---

## 二、為什麼 API key 不能放在前端？

`config.local.js`、HTML、CSS 和 JavaScript 都會被使用者的瀏覽器下載。只要開啟瀏覽器開發者工具，就能查看這些檔案。

因此以下內容不能放在前端：

- Face API key。
- Render API key。
- Ollama／文字建議 API key。
- OpenAI、Replicate 或其他模型權杖。
- Gateway session secret。
- 管理員資料庫金鑰。
- `.env` 檔案內容。
- JWT、登入密碼或 OTP。

前端可以公開的內容只有：

- Firebase Hosting 網址。
- Gateway 公開路徑。
- 公開商品圖片與商品資料網址。
- 不含秘密的功能開關。

目前正式前端使用相同網域的 Gateway 路徑：

```text
/auth/**
/admin-api/**
/face-basic/**
/face-pro/**
/render-service/**
/text-suggestion/**
/member-database/**
```

---

## 三、目前已完成的正式部署

- [x] Face Basic 與 Face Pro 已改用 Secret Manager 金鑰。
- [x] Render 已改用 Secret Manager 金鑰。
- [x] 舊前端 Face／Render key 已失效。
- [x] AI Gateway 已部署至 Cloud Run。
- [x] Gateway 使用 `member-session-only` 驗證方式。
- [x] Firebase Hosting 已改成 Gateway-only 前端。
- [x] 線上 `config.local.js` 不含 Face、Render 或文字建議 API key。
- [x] Gateway `/health` 回傳 `status: ok`。
- [x] Firebase Hosting 正式網址已發布：<https://decorate-me.web.app>

正式資料流：

```text
decorate-me.web.app
        │
        ▼
Firebase Hosting rewrite
        │
        ▼
ai-gateway（Cloud Run）
        │
        ├── 私有 Face Basic
        ├── 私有 Face Pro
        ├── 私有 Render
        └── 會員資料服務
```

---

## 四、Ollama 專題展示期間的暫時規則

目前 Ollama 文字建議需要讓專題展示人員觀察提示與回應，所以保留「展示模式」設計。但這不是永久商用設定。

程式已準備以下明確開關：

```text
GATEWAY_ALLOW_EXTERNAL_TEXT_UPSTREAM=true
```

這個開關的意義是：管理者明確知道文字建議會送往外部服務，才允許 Gateway 啟用該路徑。預設必須保持關閉。

目前正式 Gateway 沒有把會員分析資料送到 `trycloudflare.com`。原因是公開 Tunnel 是臨時網址，無法當成永久受信任的正式資料出口。

### 展示期間只能送出的資料

- Demo 專用的假會員 ID。
- 經過縮短與去識別化的臉型摘要。
- 測試用風格名稱。
- 測試用色彩、季型或妝容偏好。
- 隨機產生的 `requestId`、階段、狀態與耗時。

### 展示期間不得送出或記錄的資料

- 真實照片或照片 base64。
- 真實會員完整 email。
- JWT、API key、登入密碼、OTP 或其他權杖。
- 完整臉部分析包。
- 原始完整生成 prompt。
- OpenAI、Replicate 或其他模型的秘密設定。
- 可直接辨識會員身分的完整工作紀錄。

### 建議教授看到的 Prompt 紀錄格式

```json
{
  "requestId": "REQ-DEMO-7C21",
  "stage": "text_suggestion",
  "status": "completed",
  "style": "natural",
  "promptSummary": "自然妝、暖色調、降低眼妝飽和度",
  "durationMs": 842,
  "sensitivePayload": "[not logged]"
}
```

不要顯示下面這種格式：

```json
{
  "email": "完整會員信箱",
  "photo": "data:image/...",
  "token": "完整權杖",
  "analysisPackage": "完整分析包",
  "prompt": "完整原始提示全文"
}
```

---

## 五、專題展示時怎麼講？

可以用下面這段話向教授說明：

> 使用者的瀏覽器不會直接取得 AI 服務金鑰。所有臉部分析、妝容渲染和會員資料請求會先經過 Gateway。Gateway 會確認登入身分、允許路徑和請求大小，再使用 Secret Manager 中的伺服器憑證呼叫後端。畫面上看到的 Prompt 與工作紀錄是去識別化的 Demo 摘要，不包含照片、email、完整分析包或權杖。

教授若問「為什麼多一層 Gateway」，可以回答：

> 因為瀏覽器不能保管秘密。Gateway 把 API key 留在伺服器端，同時集中處理登入、權限、限流、CORS 和錯誤管理，這是正式商用系統常見的架構。

教授若問「為什麼現在能看到 Ollama Prompt」，可以回答：

> 這是專題展示期間的除錯摘要，用來說明模型如何產生建議。正式版本會關閉完整提示紀錄，只保留 requestId、狀態和耗時。

---

## 六、常見錯誤與新手判斷

| 錯誤 | 意義 | 處理方式 |
|---|---|---|
| `401 MEMBER_AUTH_REQUIRED` | 尚未登入或沒有會員 session | 重新登入，不要把 API key 填回前端 |
| `401 MEMBER_AUTH_INVALID` | session 過期或簽章不一致 | 登出再登入，檢查 Gateway session secret |
| `401 Invalid or missing API key` | 仍呼叫到舊服務或舊 Gateway 模式 | 確認前端已使用 Gateway-only 設定 |
| `403` | 會員沒有管理員權限，或私有 Cloud Run 拒絕直連 | 檢查角色與 Gateway IAM |
| `503 NOT_CONFIGURED` | Gateway 找不到上游設定 | 檢查 Cloud Run 環境變數與 Secret Manager |
| `503 EXTERNAL_TEXT_UPSTREAM_DISABLED` | 外部 Ollama 展示路徑目前關閉 | 使用本機 Demo；不要改回前端直連 |
| `502 UPSTREAM_UNAVAILABLE` | 上游服務、Tunnel 或模型暫時無法使用 | 檢查服務健康狀態與 Tunnel 網址 |
| CORS 錯誤 | 前端網址不在允許清單 | 檢查 `CORS_ORIGINS` |

---

## 七、專題結束後一定要做的事

- [ ] 將 `GATEWAY_ALLOW_EXTERNAL_TEXT_UPSTREAM` 改成 `false`。
- [ ] 移除 `TEXT_SUGGESTION_URL` 的公開 Tunnel 設定。
- [ ] 將 Ollama 搬到可信任 Cloud Run、VPC 或其他私有服務。
- [ ] 刪除 Demo Prompt 全文，只留下摘要、狀態與耗時。
- [ ] 刪除 Demo 假會員產生的測試資料。
- [ ] 檢查 Firebase Hosting 前端仍然沒有任何 API key。
- [ ] 檢查 Cloud Run Secret Manager 權限是否只授予需要的服務帳號。
- [ ] 輪替專題展示期間曾使用過的臨時 key。
- [ ] 驗證會員刪除後，照片、渲染圖、分析結果、收藏及工作紀錄均同步清除。
- [ ] 更新本文件與歷史流程追蹤，把完成項目打勾。

---

## 八、每次部署前的安全檢查

```text
[ ] 前端沒有 API key、JWT、密碼或 OTP
[ ] config.local.js 只有公開設定
[ ] Gateway health 為 status: ok
[ ] Face 與 Render 不能被匿名直接呼叫
[ ] GCS bucket 不是公開狀態
[ ] 圖片使用短效 signed URL
[ ] Log 不含照片、email、token、完整分析包或完整 prompt
[ ] Demo 模式與正式模式有明確開關
[ ] 會員刪除會同步清除所有相關資料
[ ] Firebase Hosting 部署完成後重新檢查線上 config.local.js
```

---

## 九、最後提醒

只要秘密仍出現在瀏覽器，就不能算完成 Gateway 安全改造。

真正完成的判斷方式是：

1. 前端只知道 Gateway 路徑。
2. 上游 API key 只存在 Secret Manager。
3. Gateway 會驗證會員 session 和權限。
4. Log 只保留去識別化摘要。
5. Ollama 外部展示模式可以明確關閉。
6. 專題結束後能按照本文件逐項收尾。

---

## 十、金鑰與環境變數完整對照

> 安全原則：本節只記錄「金鑰名稱與用途」，不得填入實際值。實際秘密只能存在 Google Secret Manager 或受保護的 Cloud Run 環境中。

### 10.1 目前正式使用的 Secret Manager 秘密

| Secret Manager 名稱 | Gateway 環境變數 | 上游服務環境變數 | 用途 | 實際值 |
|---|---|---|---|---|
| `decorate-me-face-upstream-key` | `UPSTREAM_FACE_API_KEY` | Face Basic／Pro 的 `FACE_API_KEY` | Gateway 呼叫臉部分析服務 | 禁止寫入文件 |
| `decorate-me-render-upstream-key` | `UPSTREAM_RENDER_API_KEY` | Render 的 `RENDER_API_KEY` | Gateway 呼叫妝容渲染服務 | 禁止寫入文件 |
| `decorate-me-gateway-session-secret` | `GATEWAY_SESSION_SECRET` | 無 | 簽署與驗證會員短效 session | 禁止寫入文件 |

這三個秘密已在 2026-07-19 建立或輪替。Face、Render 與 Gateway 透過服務帳號直接讀取 Secret Manager，不需要將實際值寫入前端或部署文件。

### 10.2 其他可能看到的金鑰名稱

| 名稱 | 所屬服務 | 用途 | 是否能放前端 |
|---|---|---|---|
| `OPENAI_API_KEY` | Render／模型服務 | 呼叫 OpenAI 模型 | 不可以 |
| `REPLICATE_API_TOKEN` | Render | 呼叫 Replicate | 不可以 |
| `SUGGESTION_API_KEY` | Ollama 文字建議 | 保護文字建議 API | 不可以 |
| `SUGGESTION_SERVICE_API_KEY` | Render | Render 呼叫文字建議服務 | 不可以 |
| `PRODUCT_ADMIN_API_KEY` | Gateway／商品資料服務 | 管理員商品新增、修改、刪除 | 不可以 |
| `GATEWAY_FACE_API_KEY` | 舊 Gateway 模式 | 舊版瀏覽器第二層 key | 不應再放前端 |
| `GATEWAY_RENDER_API_KEY` | 舊 Gateway 模式 | 舊版瀏覽器第二層 key | 不應再放前端 |

目前正式 Gateway 已使用 `GATEWAY_SESSION_ONLY=true`，因此前端不需要 `GATEWAY_FACE_API_KEY` 或 `GATEWAY_RENDER_API_KEY`。即使 Cloud Run 還保留舊欄位，也不能再把它們加入 `config.local.js`。

### 10.3 不是秘密、但仍要管理的設定

| 設定名稱 | 說明 | 注意事項 |
|---|---|---|
| `FACE_BASIC_URL` | Gateway 呼叫 Face Basic 的網址 | 可以記錄網址，但不要附上 key |
| `FACE_PRO_URL` | Gateway 呼叫 Face Pro 的網址 | 可以記錄網址，但不要附上 key |
| `RENDER_URL` | Gateway 呼叫 Render 的網址 | 可以記錄網址，但不要附上 key |
| `MEMBER_DATABASE_URL` | Gateway 呼叫會員資料服務的網址 | Tunnel 網址可能變動，仍不應公開散布 |
| `TEXT_SUGGESTION_URL` | Ollama 文字建議網址 | 正式環境不得指向未受控公開 Tunnel |
| `CORS_ORIGINS` | 允許呼叫 Gateway 的前端網域 | 正式環境只放實際網站網域 |
| `GATEWAY_SESSION_ONLY` | 是否只使用會員 session | 正式環境應為 `true` |
| `GATEWAY_ALLOW_EXTERNAL_TEXT_UPSTREAM` | 是否允許外部文字服務 | 預設及專題結束後必須為 `false` |

### 10.4 三種容易搞混的東西

#### API key

API key 是服務與服務之間使用的長期憑證，例如 Gateway 呼叫 Render。它不能放在瀏覽器，也不能寫進本文件。

#### 會員 session／JWT

會員登入後取得的短效憑證，只代表目前登入者。它會過期，也不能拿來取代上游 API key。Log 只能記錄 session 是否有效，不能記錄完整 token。

#### 服務網址

服務網址用來告訴 Gateway 應該呼叫哪一個服務。網址不一定是秘密，但仍可能透露系統架構。公開前端最好只保留相同網域的 Gateway 路徑。

### 10.5 如何安全確認秘密是否存在

推薦在 Google Cloud Console 操作：

1. 開啟 Google Cloud Console。
2. 選擇專案 `decorate-me`。
3. 進入「安全性」→「Secret Manager」。
4. 確認秘密名稱與最新版本狀態為 Enabled。
5. 查看權限時，只確認服務帳號和角色，不要截圖秘密值。

可以確認的資訊：

- 秘密名稱。
- 版本編號。
- 建立日期。
- 是否啟用。
- 哪些服務帳號具有 `Secret Accessor`。

不應記錄的資訊：

- Secret payload 實際值。
- 顯示秘密值的終端機畫面。
- 包含秘密的 PowerShell 歷史。
- 含 key 的截圖、報告或簡報。

### 10.6 如果真的需要查看實際值

只有在除錯或移轉服務時才應查看，而且必須在自己的私人終端機操作。查看後不要複製到聊天、Markdown、程式碼、Git、OneDrive 筆記或簡報。

```powershell
gcloud secrets versions access latest `
  --secret="秘密名稱" `
  --project="decorate-me"
```

這個指令會把秘密顯示在終端機，因此平常不要執行。大部分維護工作只需要把 Cloud Run 環境變數連到 Secret Manager，不需要知道實際值。

### 10.7 安全輪替流程

1. 建立新的 Secret Manager 版本。
2. 更新需要該秘密的 Cloud Run 服務。
3. 先測試 Gateway `/health`。
4. 測試 Face、Render 或管理員功能。
5. 確認新版正常後，停用舊秘密版本。
6. 檢查前端與 Git 歷史沒有實際秘密。
7. 在本文件只更新輪替日期，不填入秘密值。

輪替紀錄範例：

```text
秘密名稱：decorate-me-render-upstream-key
輪替日期：2026-07-19
目前版本：由 Secret Manager 管理
服務狀態：Gateway / Render 驗證完成
實際值：[禁止記錄]
```

### 10.8 金鑰外洩時怎麼辦

如果 key 曾出現在前端、GitHub、截圖、聊天或報告：

1. 立刻視為已外洩，不要只刪除檔案。
2. 產生新 key 或 Secret Manager 新版本。
3. 更新所有使用該 key 的後端服務。
4. 停用或撤銷舊 key。
5. 檢查存取紀錄是否有異常流量。
6. 確認前端只剩 Gateway 路徑。
7. 在歷史流程追蹤記錄事件與處理日期，但不得記錄實際 key。

### 10.9 維護人員檢查表

```text
[ ] 我知道秘密名稱，但文件裡沒有實際值
[ ] 實際秘密只存在 Secret Manager
[ ] Cloud Run 使用 secret reference，不使用前端明文
[ ] config.local.js 沒有 API key
[ ] Log 沒有 token 或完整 prompt
[ ] 舊 key 已停用
[ ] Secret Accessor 權限只給必要服務帳號
[ ] 本次輪替日期已記錄
```
