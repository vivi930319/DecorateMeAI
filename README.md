# 妝識你的美 - Decorate Me

[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.1.3-green.svg)](https://flask.palletsprojects.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18-blue.svg)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-7--alpine-red.svg)](https://redis.io/)
[![Docker](https://img.shields.io/badge/Docker%20Compose-ready-2496ED.svg)](https://docs.docker.com/compose/)

> **妝識你的美（Decorate Me）** 是結合會員服務、彩妝商品管理、妝容紀錄與個人化推薦的 Web 平台。後端以 Flask 提供 API 與 Jinja 頁面，資料層使用 PostgreSQL 18 與 Redis，並透過 CIEDE2000 色彩距離、風格關鍵字與五官特徵進行可解釋的商品推薦。

---

## 快速開始（Getting Started）

### 1. 環境需求

- Docker Desktop（建議）或 Python 3.11+
- PostgreSQL 18
- Redis 7
- SMTP 寄信帳號及應用程式密碼（註冊／重設密碼 OTP 必要）

### 2. 設定環境變數

複製 Docker 環境範本：

```powershell
Copy-Item .env.docker.example .env
```

正式環境至少應設定：

```dotenv
SECRET_KEY=請改成高熵亂數
DB_PASSWORD=請改成安全密碼
SMTP_USER=寄件帳號
SMTP_PASS=寄件應用程式密碼
UPSTREAM_MEMBER_API_KEY=Gateway金鑰
GATEWAY_KEY_LOOSE_MODE=false
```

### 3. Docker 部署（推薦）

```powershell
docker compose up -d --build
docker compose ps
Invoke-WebRequest http://127.0.0.1:5000/health
```

預設服務埠：Flask API `5000`、PostgreSQL `5432`、Redis `6379`。

若主機上的 `5432` 或 `6379` 已被占用，可在 `.env` 調整 `DB_PORT_PUBLISHED` 或 `REDIS_PORT_PUBLISHED`；容器內服務埠不需改動。

### 4. 首次初始化資料庫

Docker Compose 會建立 PostgreSQL 18 容器與資料卷，但**不會自動匯入** `postgre.sql`。新資料卷需要先確認 SQL 檔版本後再初始化：

```powershell
Get-Content .\postgre.sql -Raw | docker compose exec -T db psql -U postgres -d empower_beauty
```

若 `.env` 使用不同帳號或資料庫名稱，請同步修改命令。既有正式資料庫不可直接重複匯入 dump；請先備份並使用 Migration 或經審核的 SQL。

### 5. 不使用 Docker 的本機啟動

先建立虛擬環境、安裝依賴，並由 `.env.example` 建立 `.env`：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python run_local_5000.py
```

本機模式必須自行準備 PostgreSQL、Redis 與資料庫 Schema。`.env.example` 的 `DATABASE_URL`／`DB_*`、Redis 和 SMTP 設定需依實際環境修改。

---

## 核心功能模組

### 1. 會員帳號與安全防護系統

- **驗證後才成為會員**：註冊資料會先保存在 `pending_registrations`；只有 OTP 驗證成功才寫入 `members`。
- **Email 網域檢查**：驗證格式、MX 記錄與一次性信箱黑名單；`admin@decorateme.local` 是唯一允許的非標準網域帳號。
- **OTP 防護與品牌 Email**：Redis 儲存有效期限、驗證嘗試與寄送時間窗；OTP HTML Email 使用 CID 內嵌 `static/brand/decorate-me-logo.jpg`，同時保留純文字備援內容。
- **密碼與登入**：以 Flask-Bcrypt 雜湊密碼；登入建立 PostgreSQL `member_sessions`，回傳 HttpOnly/Secure/SameSite Cookie 與 Bearer Token。
- **角色與授權**：使用者只能存取自己的資源；管理者可進行會員、商品與爬蟲資料管理。
- **請求安全**：CORS 僅允許設定來源；Cookie 驗證的寫入請求檢查 `Origin` 與 `Sec-Fetch-Site`；API 錯誤回應含 `code`、`message` 與 `requestId`。

### 2. 智慧色彩與風格推薦演算法

- **七種妝容風格**：Soft Baddie、千金、港風、韓系亞裔、病嬌、日雜清透、男士白開水。
- **CIEDE2000 色彩比對**：將 HEX 色票轉為 sRGB、XYZ(D65)、CIELAB，再以 ΔE00 取代舊 CIE76 色差。
- **風格與色系偏好**：使用 Jaccard 與 Recall；`avoidTags` 會檢查商品名稱、品牌、描述、規格、色號及標籤並扣分，`preferredColors` 命中則加分。
- **五官特徵評分**：以臉型、眼型、唇型及品類矩陣給予修飾分數。
- **品類動態權重**：底妝偏重色彩；眼妝與腮紅偏重風格；修容偏重臉部特徵。
- **伺服器端行為個人化**：登入會員的收藏、試妝紀錄與購物車會彙整為類別／品牌偏好；不把 Email、會員 ID、Token 或影像傳入演算法。
- **預算與品牌偏好**：前端可選擇傳送 `recommendationOptions` 的預算範圍、喜愛品牌與避免品牌；預算及喜愛品牌用於重排，`avoidedBrands` 則採硬性排除。
- **冷啟動保護**：匿名使用者或尚無互動紀錄的會員，維持內容式推薦；行為權重為 0，不會因資料不足而被扣分。
- **眉彩採風格導向**：眉彩絕不使用膚色比色。若有 `faceAnalysis.browLab`／`hairLab` 才使用 CIEDE2000；沒有眉色資料是正常路徑，仍會依風格與五官特徵排序並進入 `primary`，不回傳 `BROW_COLOR_UNAVAILABLE`。
- **新商品自動納入**：新商品通過商品契約且進入 `product_catalog` 後，會成為推薦候選；未知分類採預設權重，不會因未寫死分類被忽略。
- **資料庫檢索欄位與狀態**：以商品 `name`、`brand`、`description`、`specs`、`styleTags`／`tags` 與分類比對；只納入 `active`、`approved`、`in_stock`、`recommendation_ready` 全部成立的商品。
- **可重跑排序**：移除隨機微擾；相同分析資料與相同候選商品會得到相同排序，能重跑 Precision@K。
- **可解釋輸出**：每筆商品包含 `matchScore`、八項 `scoreBreakdown`、`matchedKeywords`、相容用文字 `matchReason`，以及含 `reasonCode`／`evidence` 的結構化 `matchReasons`。
- **粉底替代色**：`shadeRecommendation` 提供主推薦、較明亮與較深的替代色。資料庫尚無品牌正式 `depthIndex` 時使用 LAB 的 L* 近似，回應會附上說明，不宣稱是品牌定義的「淺一階／深一階」。
- **降級與覆蓋資訊**：回應提供 `fallbackReasons`、`skinToneLabReliable`、品類 `coverage`、每類一件的 `primary`、80 分以上的 `alternates` 與 `threshold: 0.80`。

#### 推薦流程圖

```mermaid
flowchart TD
    A[analysisPackage: style / faceAnalysis] --> B[契約驗證與風格別名正規化]
    B --> C[取得可售、已審核的商品候選]
    C --> D[CIEDE2000 色彩相似度；壞 LAB 自動降級]
    C --> E[標籤、偏好色與避雷詞比對]
    C --> F[臉型、眼型、唇型特徵矩陣]
    D --> G[品類動態權重計算內容分數]
    E --> G
    F --> G
    J[登入會員既有收藏／試妝／購物車] --> K[行為偏好重排，最高 15%]
    G --> K
    K --> H[去重與品類多樣化]
    H --> I[推薦商品、結構化理由、粉底替代色與 fallback]
```

### 3. 商品、收藏、試妝與會員服務

- 商品瀏覽、商品 CRUD、色票查詢及商品分類 API。
- 收藏新增、切換、刪除；購物車讀取、新增、更新、刪除。
- 試妝紀錄、保存妝容、分析歷史及推薦頁面。
- 每日簽到、點數、任務領取、主題兌換與推薦碼。

### 4. 爬蟲商品暫存與管理稽核

- 商品預覽 API 會驗證 URL、過濾不安全網路目標並解析商品資料，以降低 SSRF 風險。
- 爬蟲資料先寫入 `crawler_staging_products`，管理者才可核准或拒絕。
- 商品新增、修改、刪除與暫存審核均可留下產品／管理稽核紀錄。
- 管理者可查詢會員、更新會員、刪除會員、檢視稽核與產品紀錄。

---

## 技術棧（Technology Stack）

| 類別 | 技術 | 用途 |
|---|---|---|
| 後端 | Python 3.11、Flask 3.1.3、Gunicorn | API 與 Web 服務 |
| ORM | Flask-SQLAlchemy、SQLAlchemy 2、psycopg2-binary | ORM 與 PostgreSQL 連線 |
| 資料庫 | PostgreSQL 18 | 資料表、JSONB、Function、Trigger、View、Index |
| 快取 | Redis 7、redis-py | OTP、TTL、嘗試計數與限流 |
| 安全 | Flask-Bcrypt、Flask-Login、Flask-WTF、Flask-CORS、dnspython | 密碼、登入、表單、跨域與 MX 驗證 |
| 爬蟲/預覽 | requests、BeautifulSoup4、httpx、Playwright、Selenium | 商品頁解析與動態網頁支援 |
| 數值/影像 | NumPy、OpenCV-headless、Pillow | 色彩與影像處理 |
| 部署 | Docker、Docker Compose | Flask、PostgreSQL、Redis 容器化 |

> `qdrant-client`、`OLLAMA_HOST` 與 `SD_HOST` 目前僅作為可擴充介面；核心推薦不會呼叫 Qdrant、Ollama 或 Stable Diffusion。

---

## 資料庫模型總覽

### 會員與驗證

| 模型/資料表 | 說明 |
|---|---|
| `members` | 會員、角色、等級、Email 驗證、狀態與 Session 版本 |
| `pending_registrations` | 等待 Email OTP 驗證的註冊資料 |
| `otp_codes` | OTP 目的、雜湊、到期與嘗試狀態 |
| `member_sessions` | 雜湊 Session Token、到期、撤銷與來源識別 |
| `member_deletion_jobs` | 會員刪除作業狀態 |

### 商品、互動與稽核

`postgre.sql` 目前定義 **34 張資料表**，包括 `products`、`product_catalog`、八個商品分類表、`crawler_staging_products`、收藏、購物車、簽到、點數、任務、推薦碼、妝容／分析歷史與各類稽核表。

- **Function**：`enforce_product_contract`、`register_product_catalog_item`、`product_hex_to_lab`、簽到／收藏／會員等級相關函式。
- **Trigger**：商品契約檢查、新商品登錄全域商品目錄、簽到重複防護、收藏與會員等級歷程。
- **View**：`view_member_activity`、`view_member_dashboard`、`view_product_list`、`view_product_popularity`。
- **Index**：針對商品推薦狀態、爬蟲審核、會員 Session/OTP、稽核、點數、任務等高頻查詢建立索引。

---

## API 概覽

`app.py` 目前有 72 個 `@app.route` 宣告；部分路徑支援多個 HTTP 方法，提供超過 70 項操作。

| 類別 | 代表端點 |
|---|---|
| 健康 | `GET /health`、`GET /healthz` |
| 認證 | `POST /api/register`、`/api/send-otp`、`/api/verify-otp`、`/api/login`、`/api/logout`、`GET /api/me` |
| 會員 | `GET/PATCH/DELETE /api/members/<email>`、點數、任務、主題、推薦碼、稽核、統計 |
| 收藏/購物車 | 收藏 CRUD/toggle、歷史、`GET/PUT /cart`、購物車品項 CRUD |
| 商品/爬蟲 | 商品 CRUD、`GET /api/products` 篩選、`GET /api/products/<id>/similar`、色票、預覽、爬蟲暫存查詢/核准/拒絕、產品稽核 |
| 推薦/試妝 | `POST /recommend-products`、`POST /api/tryon/save` |

### 商品列表與相似商品

`GET /api/products` 支援下列查詢參數：

| 參數 | 說明 |
|---|---|
| `query` / `q` | 搜尋商品名稱、品牌、描述或銷售頁 ID |
| `category` / `type` | 依分類或前端品類名稱篩選，例如 `lip`、`lipsticks` |
| `brand` | 品牌完整名稱，不分英文字母大小寫 |
| `inStock` | `true`／`false`／`1`／`0` |
| `limit` | 每頁 1–100 筆；帶入後回傳游標分頁格式 |
| `cursor` | 上一頁的 `nextCursor` |

未傳 `limit` 時回傳 `{ "products": [...] }`；傳入 `limit` 時會額外回傳 `items`、`total` 與 `nextCursor`。

`GET /api/products/<id>/similar?limit=6` 回傳同品類的相似商品，`limit` 範圍為 1–20。每筆結果包含：

- `similarity` 與色彩、風格、品類、品牌、價格的 `similarityBreakdown`
- `relation`：`same_style_alt`、`lighter_variant`、`darker_variant`、`same_brand` 或 `budget_alt`
- `matchReason`：供前端顯示相似原因

### 個人化推薦

推薦請求範例：

```json
{
  "analysisPackage": {
    "id": "AN-001",
    "schemaVersion": "2026-08-v2",
    "style": "richGirl",
    "faceAnalysis": {
      "faceShape": "oval",
      "eyeShape": "almond",
      "lipShape": "full",
      "skinTone": {
        "lab": [65.2, 8.1, 18.4],
        "season": "warm",
        "level": "medium",
        "labReliable": true
      }
    },
    "generativeText": {
      "styleTags": ["luxury", "soft"],
      "preferredColors": ["champagne", "玫瑰"],
      "avoidTags": ["glitter"]
    }
  },
  "limit": 12,
  "recommendationOptions": {
    "preferredBrands": ["3CE", "heme"],
    "avoidedBrands": ["不想看到的品牌"],
    "pricePreference": {"min": 300, "max": 1200, "mode": "value"}
  }
}
```

`analysisPackage.faceAnalysis` 是必填物件；`limit` 必須是 1–50 的整數。`recommendationOptions` 為選填欄位，品牌陣列各最多 20 筆，`pricePreference.mode` 僅接受 `value`、`low`、`high`，且 `min` 不得大於 `max`。

請求的任何巢狀位置均不得放入 Email、姓名、會員 ID、電話、Token、Cookie、原始照片或 Base64 影像。會員身分與既有互動資料只由後端從有效 Session／Bearer Token 取得。

推薦回應中，商品的 `scoreBreakdown` 除了既有的 `colorScore`、`styleScore`、`featureScore`、`availabilityScore` 外，還包含：

| 欄位 | 用途 |
|---|---|
| `priceFit` | 與選填預算區間的契合程度；未設定預算時為中性值。 |
| `brandAffinity` | 與顯式喜愛／避免品牌的契合程度。 |
| `behaviorScore` | 後端從收藏、試妝、購物車彙整的類別／品牌偏好。 |
| `contentScore` | 色彩、風格、五官特徵、庫存與顯式偏好的內容分數。 |
| `personalization` | 回應層級欄位，說明是否套用個人化、互動筆數與行為權重（最高 `0.15`）。 |

其他重要輸出：

| 欄位 | 用途 |
|---|---|
| `matchReason` | 相容既有前端的中文推薦理由字串。 |
| `matchReasons` | 結構化理由陣列，包含 `priority`、`reasonCode`、`personalized`、`text` 與 `evidence`。 |
| `skinToneLabReliable` | 後端依 LAB 型別、三軸完整性及合法值域重新判定的可信狀態。 |
| `fallbackReasons` | 降級原因；壞或缺少膚色 LAB 且涉及底妝時包含 `SKIN_TONE_LAB_UNRELIABLE`。 |
| `shadeRecommendation` | 粉底主推薦及較明亮／較深替代色；無可用粉底 LAB 時為 `null`。 |

> `matchScore` 是排序分數，不是「商品適合度百分比」或模型準確率。準確率應以人工金標資料、Precision@K 等離線評估另行計算。

### 推薦錯誤契約

| 情況 | HTTP | code / 回應 |
|---|---:|---|
| JSON 語法錯誤或 body 不是物件 | 400 | `INVALID_REQUEST` |
| `limit` 不是整數或不在 1–50 | 400 | `INVALID_REQUEST` |
| 品牌陣列超過 20 筆、價格區間顛倒或 mode 無效 | 400 | `INVALID_REQUEST` |
| 缺少或無效 `analysisPackage` | 422 | `INVALID_ANALYSIS_PACKAGE` |
| 請求含身分、憑證或原始影像欄位 | 422 | `IDENTITY_DATA_NOT_ALLOWED` |
| 未知妝容風格 | 422 | `UNKNOWN_MAKEUP_STYLE` |
| 合法請求但查無可用商品 | 200 | `RECOMMENDATION_EMPTY`，`products: []` |
| 商品資料庫無法使用 | 502 | `PRODUCT_DB_UNAVAILABLE` |
| 商品資料庫查詢逾時 | 504 | `PRODUCT_DB_TIMEOUT` |

錯誤與空結果絕不產生虛構商品；前端應優先讀取 `analysisPackage.recommendations.products`。

---

## 專案目錄結構

```text
Backend database/
├── app.py                    # Flask 路由、驗證、會員/商品/推薦整合
├── models.py                 # SQLAlchemy ORM 模型
├── recommendation.py         # CIEDE2000、偏好分數、理由、粉底替代色與排序
├── makeup_keywords.py        # 七種風格關鍵字與別名
├── postgre.sql               # PostgreSQL 18 schema、Function、Trigger、View、Index
├── otp_utils.py / OTP.py     # OTP、Redis、SMTP 輔助
├── static/brand/              # OTP Email 內嵌 Decorate Me Logo
├── crawler_preview.py        # 商品預覽與 SSRF 防護
├── config.py / forms.py      # 設定與表單驗證
├── docker-compose.yml        # Flask + PostgreSQL 18 + Redis
├── Dockerfile                # API 映像建置
├── wait_for_services.py      # 容器啟動等待 DB / Redis
├── templates/                # Jinja 網頁模板
├── tests/recommendation/     # Precision@K 評估與 13 項推薦契約測試
├── backups/                  # 升級前資料庫備份
└── test_*.py、*_test.py      # 開發診斷腳本，非正式服務核心
```

---

## 測試、限制與安全提醒

```powershell
python -m py_compile app.py recommendation.py
python -m unittest tests.recommendation.test_recommendation_contract -v
python tests\recommendation\evaluate_precision_at_k.py gold.json predictions.json
docker compose ps
```

- `test_recommendation_contract.py` 現有 13 項測試，涵蓋 styleId／顯示名稱相容、未知風格、停用商品排除、結果確定性、眉彩正常路徑、預算／品牌／行為分數、壞 LAB 降級、品牌硬排除、避雷詞差異、偏好約束及巢狀敏感欄位阻擋。
- 路由層還應在可連線的 PostgreSQL／Redis 環境驗證商品過濾、相似商品、502 `PRODUCT_DB_UNAVAILABLE` 與 504 `PRODUCT_DB_TIMEOUT`。純演算法單元測試不會模擬資料庫離線。
- 評估工具可計算 Precision@5/10、重複率、停用商品率與幻覺商品率；尚未建立人工金標集前，不宣稱準確率數字。
- 不可提交 `.env`、SMTP 密碼、Gateway/Bearer Key、真實個資、正式資料庫 dump 或 Docker Volume。
- `backups/` 是 PostgreSQL 升級前還原點；先做異地加密備份，再考慮清理。
- 正式上線應設定固定 HTTPS 網域、`GATEWAY_KEY_LOOSE_MODE=false`、由 Gateway 傳送 `X-Gateway-Key`，並執行權限、CORS、OTP、備份還原與資安測試。
- 協同過濾、Learning-to-Rank、MDP／強化學習與完整曝光／點擊／購買事件表仍是未來擴充項目；目前正式使用的是可重現、可解釋的內容式＋有限行為重排推薦。

---
