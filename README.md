# 妝識你的美 — Decorate Me

[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.1.3-green.svg)](https://flask.palletsprojects.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18-blue.svg)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-7-red.svg)](https://redis.io/)

> Decorate Me 是結合彩妝商品目錄、會員帳號、OTP 驗證、試妝紀錄、爬蟲商品暫存與可解釋商品推薦的 Web 後端。服務採用 Flask、PostgreSQL 18、Redis 與 Docker Compose。

## 目錄

- 系統功能
- 技術架構
- 快速啟動
- 環境變數
- 商品資料流程
- 推薦演算法
- API 摘要
- 資料庫
- 專案檔案用途
- 測試與維護
- 限制與後續規劃

## 系統功能

### 本次文件同步重點（2026-09-17）

- 粉底推薦已改為「具官方數值色彩證據才可做使用者膚色嚴格匹配」；資料不足時會明確降級，不會把網頁色票當成實測結果。
- 商品詳情可取得以目前瀏覽粉底為基準的較淺、最相近、較深參考色；跨品牌結果只用於比較。
- 商品圖片可經由已發布的同源鏡像清單提供，保留原始來源網址，降低品牌網站防盜連或驗證頁直接出現在使用者畫面的風險。
- 已補齊色彩契約、色號鄰近、跨品牌、個人化、保存妝容與圖片鏡像的契約測試。

### 會員與帳號安全

- 註冊資料先保存於 pending_registrations；完成 Email OTP 驗證後才建立正式會員。
- 驗證 Email 格式、MX 記錄與一次性信箱網域
- OTP 具有效期限、寄送次數與驗證嘗試限制；Redis 用於 TTL 與限流。
- 密碼統一採 6～128 碼規則，使用 Bcrypt 雜湊。
- 登入後建立資料庫 Session，並支援 HttpOnly Cookie 與 Bearer Token。
- 使用者只能讀寫自己的會員資料、收藏、試妝、妝容、歷史與購物車；管理者才可管理商品及會員。
- 後端處理 CORS、Cookie 寫入來源檢查、Gateway 金鑰、管理端授權、SSRF 防護及稽核紀錄。

### 商品、會員活動與後台

- 商品目錄查詢、新增、修改、刪除與分類瀏覽。
- 收藏、購物車、試妝紀錄、分析歷史、保存妝容。
- 每日簽到、點數、任務、主題與推薦碼功能。
- 商品爬蟲暫存、預覽、核准、拒絕及正式匯入。
- 管理員會員管理、商品稽核與管理操作紀錄。
- 商品相似推薦與同品類商品查詢。
- 美元商品保留原始幣別，並提供揭露匯率與計算方式的新台幣顯示價格。
- 商品回應同時保留原始商品圖片來源與可用的鏡像網址；找不到已驗證鏡像時會安全地保留原網址，不會自行偽造圖片。

### 商品推薦

- 支援 Soft Baddie、千金、港風、韓系亞裔、病嬌、日雜清透、男士白開水七種風格。
- 粉底使用使用者膚色與商品色號的 CIEDE2000 色差進行嚴格比對。
- 唇彩、眼影、腮紅、修容、打亮、眉彩以風格、關鍵字、色系偏好及適用特徵排序。
- 登入會員可依既有收藏、試妝與購物車產生有限度的行為偏好重排。
- 回傳推薦理由、色差說明、色號替代選項、覆蓋狀態與降級原因。
- 色彩資料須有可追溯的官方數值證據才可用於粉底比色；透明商品、色盤、官方僅有色號名稱及未驗證色值會以不同方式標示，不會假裝是實體試色結果。

## 技術架構

~~~mermaid
flowchart LR
    FE["前端 Web／Gateway"] --> API["Flask API"]
    API --> PG["PostgreSQL 18"]
    API --> R["Redis 7"]
    API --> SMTP["SMTP OTP 郵件"]
    API --> PREVIEW["商品預覽與爬蟲暫存"]
    PG --> REC["推薦候選商品"]
    REC --> API
~~~

| 類別 | 使用技術 | 用途 |
|---|---|---|
| 後端 | Python 3.11、Flask、Gunicorn | HTTP API 與 Jinja 頁面 |
| 資料層 | PostgreSQL 18、SQLAlchemy、psycopg2 | 會員、商品、JSONB、Function、Trigger、View、Index |
| 快取 | Redis 7、redis-py | OTP、到期、寄送與驗證限制 |
| 安全 | Bcrypt、Flask-Login、Flask-CORS、dnspython | 密碼、登入、跨域與網域驗證 |
| 商品預覽 | requests、BeautifulSoup4 | 商品頁解析、URL 檢查與 SSRF 防護 |
| 色彩與影像 | NumPy、OpenCV、Pillow | CIELAB／CIEDE2000 色彩資料、圖片轉檔與鏡像處理支援 |
| 部署 | Docker、Docker Compose | Flask、PostgreSQL、Redis 容器服務 |

Qdrant、Ollama 與 Stable Diffusion 相關設定目前為預留整合；正式推薦流程不依賴它們。

## 快速啟動

### 需求

- Docker Desktop
- 或 Python 3.11、PostgreSQL 18、Redis 7
- SMTP 帳號與應用程式密碼（需要寄送 OTP 時）

### Docker 啟動

Docker PostgreSQL 對外預設使用主機埠 5433，避免與 Windows PostgreSQL 的 5432 衝突；API 對外預設使用 5001。

先啟動資料服務：

~~~powershell
docker compose up -d db redis
docker compose ps
~~~

API 容器需要 UPSTREAM_MEMBER_API_KEY。若本機已安裝 Google Cloud CLI 並可讀取 Secret Manager：

~~~powershell
.\scripts\start-member-service.ps1
~~~

由部署環境提供金鑰時：

~~~powershell
$env:UPSTREAM_MEMBER_API_KEY = "請由安全的秘密管理工具取得"
docker compose up -d --build app
docker compose ps
Invoke-WebRequest http://127.0.0.1:5001/health
Remove-Item Env:UPSTREAM_MEMBER_API_KEY
~~~

### 建立空白資料庫

postgre.sql 是 PostgreSQL custom-format 匯出檔，不是純文字 SQL；只可對全新空白資料庫使用 pg_restore：

~~~powershell
docker cp .\postgre.sql empower-beauty-db:/tmp/decorate-me.dump
docker compose exec -T db sh -lc 'pg_restore --verbose --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB" /tmp/decorate-me.dump'
~~~

不要對已有資料的資料庫重複還原完整 dump。正式變更應先備份，並以經審核的 migration 執行。

### 不使用 Docker 的本機啟動

~~~powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python run_local_5000.py
~~~

本機模式必須自行準備 PostgreSQL、Redis 及完整資料庫 schema。開發啟動器的 db.create_all() 無法建立完整 dump 內的 Function、Trigger、View 與索引，不能取代正式資料庫還原。

## 環境變數

| 變數 | 用途 |
|---|---|
| DATABASE_URL 或 DB_USER、DB_PASSWORD、DB_HOST、DB_PORT、DB_NAME | PostgreSQL 連線；DATABASE_URL 優先。 |
| SECRET_KEY | Flask Session 與安全設定；正式環境必須更換。 |
| JWT_SECRET、JWT_ISSUER、JWT_EXPIRES_IN | Bearer Token 簽章、簽發者與期限。 |
| REDIS_URL 或 REDIS_HOST、REDIS_PORT、REDIS_PASSWORD | OTP 與限流使用的 Redis。 |
| SMTP_USER、SMTP_PASS、SMTP_HOST、SMTP_PORT | OTP Email 寄送。 |
| OTP_EXPIRE_SECONDS、OTP_SEND_WINDOW_SECONDS、OTP_SEND_MAX_ATTEMPTS | OTP 期限與限流。 |
| CORS_ALLOWED_ORIGINS | 逗號分隔的允許前端來源。 |
| UPSTREAM_MEMBER_API_KEY | Gateway 與會員服務的安全通訊金鑰。 |
| GATEWAY_KEY_LOOSE_MODE | 過渡設定；正式環境應為 false。 |
| PRODUCT_ADMIN_API_KEY | 商品管理 API 金鑰。 |
| USD_TO_TWD_RATE、USD_TO_TWD_RATE_AS_OF | 美元商品的新台幣顯示匯率及資料時間。 |
| SAVED_LOOK_LIMIT、MEMBER_SESSION_TTL_SECONDS | 保存妝容上限及 Session 存活時間。 |
| CRAWLER_* | 商品預覽連線、大小、重新導向與限流設定。 |

不得提交實際密碼、SMTP 憑證、JWT／Gateway 金鑰或正式資料庫連線字串。

## 商品資料流程

~~~mermaid
flowchart TD
    A["商品來源／前端預覽"] --> B["crawler_staging_products"]
    B --> C{"管理員審核"}
    C -->|核准| D["正式商品分類表"]
    C -->|拒絕| E["保留審核狀態"]
    D --> F["product_catalog"]
    F --> G["可推薦候選商品"]
    G --> H["商品列表、相似商品、個人化推薦"]
~~~

新商品要進入推薦，應完成：

1. 寫入正確商品分類表。
2. 建立對應的 product_catalog 資料。
3. 狀態符合 active、approved、in_stock、recommendation_ready。
4. 提供名稱、品牌、價格、描述、分類、標籤與色彩資料。
5. 粉底另提供可用 LAB；同系列色階功能需要正確 series_id、depth_index 與正式排序來源。

### 色彩資料驗證

色彩資料由 color_contract.py 統一處理，避免把網頁圖片、色名或未驗證 HEX 當作實體顏色測量。

| 狀態／欄位 | 意義 |
|---|---|
| colorMatchReady | 官方數值色碼、SKU、來源網址與證據雜湊均可驗證時才為 true；只有此狀態可作為使用者膚色的嚴格粉底匹配依據。 |
| colorReferenceReady | 有完整單色 HEX 並可依統一 sRGB→CIELAB 公式換算；可用於商品間的參考比較，證據等級低於 colorMatchReady。 |
| colorEstimated | 有 HEX 但尚未通過完整官方數值驗證；可供目錄色票展示，不得宣稱為官方實測或使用者膚色正式匹配。 |
| colorRepresentation | 區分 single、palette、transparent、official_name_only。 |
| paletteComplete | 色盤每格都有可用官方色值時才為 true。 |
| colorWarning | 前端可直接顯示的色彩資料限制或警語。 |
| imageIdentityStatus | 圖片與商品色號核對狀態；若不符，後端不回傳該圖片供商品使用。 |

透明商品、色盤與官方僅提供色號名稱的商品仍可出現在目錄與風格推薦中，但不會拿來做使用者膚色的粉底 CIEDE2000 嚴格匹配。商品間色號參考也會回傳證據等級與警語。

## 推薦演算法

推薦主程式為 recommendation.py，API 為 POST /recommend-products。它是可重現、可解釋的規則式排序，而非黑盒深度學習模型。

### 輸入與資料最小化

~~~json
{
  "analysisPackage": {
    "style": "richGirl",
    "faceAnalysis": {
      "skinTone": {"lab": [65.2, 8.1, 18.4]},
      "faceShape": "oval",
      "browShape": "arched",
      "eyeShape": "almond",
      "lipShape": "full"
    },
    "generativeText": {
      "styleTags": ["luxury", "soft"],
      "preferredColors": ["champagne"],
      "avoidTags": ["glitter"]
    }
  },
  "limit": 12,
  "recommendationOptions": {
    "preferredBrands": ["3CE"],
    "avoidedBrands": ["Brand X"],
    "pricePreference": {"min": 300, "max": 1200, "mode": "value"}
  }
}
~~~

- limit 必須是 1～50。
- recommendationOptions 為選填；品牌陣列最多各 20 筆。
- pricePreference.mode 只接受 value、low、high。
- 分析封包不得含 Email、姓名、會員 ID、電話、Cookie、Token、Authorization、原始圖片或 Base64 圖片。
- 登入會員的行為偏好由後端從收藏、試妝、購物車取得，前端不需傳送會員識別資料。

### 色彩、風格與特徵規則

| 品類 | 主要排序依據 |
|---|---|
| 粉底 base | 使用者膚色 LAB 與商品 LAB 的 CIEDE2000 色差。 |
| 唇彩 lip | 妝容風格、關鍵字、色系偏好與唇型相關特徵；不以自然唇色 ΔE00 宣稱精準匹配。 |
| 眼影、腮紅、修容、打亮 | 妝容風格、關鍵字與色系偏好。 |
| 眉彩 | 妝容風格及眉型相關商品訊號；不以膚色、眉色或髮色進行色差排序。 |

粉底嚴格門檻：

~~~text
使用 CIEDE2000 計算 ΔE00
0 ≤ ΔE00 ≤ 2：正式匹配候選
ΔE00 > 2：不是正式匹配
~~~

若沒有符合 0～2 的粉底，系統會回傳一件最接近的可比較色號，並標記 FOUNDATION_CLOSEST_AVAILABLE，前端不得顯示為正式 MATCH。若膚色 LAB 或粉底 LAB 不可用，粉底不會偽造精準比色結果。

商品風格分數使用標籤 Jaccard 與 Recall：

~~~text
StyleScore = 0.4 × Jaccard + 0.6 × Recall
~~~

關鍵字會在商品名稱、品牌、描述、規格、色號與標籤中比對；preferredColors 命中會加分，avoidTags 命中會扣分。若沒有商品命中風格字典，回傳 STYLE_KEYWORD_NO_MATCH，但合格商品不會因此被永久排除。

### 分數與個人化

各品類採不同權重。粉底以色彩為主，其他主要品類以風格為主：

| 類別 | 色彩 | 風格 | 特徵 | 庫存 |
|---|---:|---:|---:|---:|
| 粉底 | 0.75 | 0.05 | 0.10 | 0.10 |
| 唇彩 | 0.00 | 0.75 | 0.15 | 0.10 |
| 眼影、腮紅、修容、打亮、眉彩 | 0.00 | 0.90 | 0.00 | 0.10 |

~~~text
CosmeticScore =
  colorWeight × ColorScore +
  styleWeight × StyleScore +
  featureWeight × FeatureScore +
  availabilityWeight × AvailabilityScore
~~~

預算與顯式品牌偏好存在時：

~~~text
PreferenceScore = (PriceFit + BrandAffinity) / 2
ContentScore = 0.90 × CosmeticScore + 0.10 × PreferenceScore
~~~

已登入會員的收藏、試妝與購物車會形成類別／品牌偏好：

~~~text
BehaviorScore = 0.60 × CategoryAffinity + 0.40 × BrandAffinity
BehaviorWeight = min(0.15, 0.03 × interactionCount)
FinalScore = (1 - BehaviorWeight) × ContentScore + BehaviorWeight × BehaviorScore
~~~

行為偏好最高只影響 15%，避免收藏或品牌偏好壓過色彩與風格相容性；沒有互動資料時，行為權重為 0。

### 排序與輸出

- 單次候選上限為 5,000 筆，排序複雜度約為 O(n log n)。
- 使用 candidateKey 去重，並優先讓不同品類都有曝光。
- primary 提供各品類主推；alternates 提供達 threshold 0.80 的替代商品。
- 粉底的較淺／較深參考先限制色相與彩度（冷暖）在合理範圍，再比 L* 明度；優先同品牌（不限系列），同品牌該方向沒有合格色號時才跨品牌，並以 `scope` 標明來源。
- 只有品牌自己公布色階順序（`depthIndexOfficial` 為 true）時才會使用「淺一階／深一階」字樣，並帶 `officialShadeLadder: true`；其餘一律是「較淺相近色／較深相近色」。
- foundationCrossBrandAlternatives 提供非主品牌的相近粉底，以供比較，不取代主推薦。
- 使用者膚色的正式粉底匹配只使用 `colorMatchReady`；色號鄰近比較另可使用 `colorReferenceReady`，並保留資料等級。遮瑕不會與粉底互相取代。
- 每筆商品提供 matchScore、scoreBreakdown、matchReason、matchReasons 與 recommendationPresentation。

粉底相關的主要輸出欄位：

| 欄位 | 前端用途 |
|---|---|
| foundationSkinMatch | 使用者膚色與該粉底色號的 ΔE00、嚴格 0～2 門檻及顯示狀態。 |
| foundationMatchStatus | 本次粉底是否 matched、closest_available、unavailable 或 not_requested。 |
| shadeRecommendation | 主推薦粉底與較淺／較深參考色；`selectionScope`、每支的 `scope` 與 `officialShadeLadder` 說明取自同品牌哪個範圍、是否為官方色階，`depthReferencePolicy` 揭露冷暖與明度門檻。 |
| foundationCrossBrandAlternatives | 相對於基準粉底的其他品牌比較色號；不等同使用者膚色匹配。 |
| recommendationPresentation | 供畫面直接使用的標題、推薦理由、警語、是否顯示匹配度與色差 QA。 |
| sourceImageUrl | 商品原始圖片來源；畫面用圖片可能已替換為同源鏡像，但來源資料不會被覆寫。 |

matchScore 是排序分數，不是模型準確率，也不是使用者一定會喜歡的百分比。

## API 摘要

服務包含健康檢查、認證、會員管理、商品、爬蟲暫存、推薦、點數、任務、收藏、購物車與 Jinja 頁面。常用端點如下：

| 類別 | 端點 |
|---|---|
| 健康檢查 | GET /health、GET /healthz |
| 認證 | POST /api/register、/api/send-otp、/api/verify-otp、/api/login、/api/logout、GET /api/me |
| 密碼 | POST /api/forgot-password、/api/reset-password、/api/change-password |
| 會員 | GET/PATCH/DELETE /api/members/<email>、會員稽核、點數、簽到、任務、主題、推薦碼 |
| 商品 | GET/POST /api/products、GET/PATCH/DELETE /api/products/<id>、GET /api/products/<id>/similar、GET /api/products/<id>/shade-matches |
| 爬蟲 | POST /api/crawler/product-preview、爬蟲暫存查詢、核准、拒絕與匯入 |
| 推薦 | POST /recommend-products、POST /api/tryon/save |
| 收藏／購物車 | 收藏清單與 toggle、購物車 GET/PUT、品項 POST/PATCH/DELETE |

推薦錯誤碼：

| HTTP | code | 意義 |
|---:|---|---|
| 400 | INVALID_REQUEST | JSON、limit 或偏好選項格式無效。 |
| 422 | INVALID_ANALYSIS_PACKAGE | 缺少或無效的臉部分析資料。 |
| 422 | IDENTITY_DATA_NOT_ALLOWED | 請求中含身分、憑證或原始影像資料。 |
| 422 | UNKNOWN_MAKEUP_STYLE | 不支援的妝容風格。 |
| 200 | RECOMMENDATION_EMPTY | 合法請求，但沒有可用商品。 |
| 502 | PRODUCT_DB_UNAVAILABLE | 商品資料庫暫時不可用。 |
| 504 | PRODUCT_DB_TIMEOUT | 商品資料庫查詢逾時。 |

## 資料庫

資料庫 schema 包含會員、OTP、Session、商品、商品目錄、商品分類、收藏、購物車、試妝、分析歷史、簽到、點數、任務、主題、推薦碼、爬蟲暫存與稽核資料表。

重要設計：

- product_catalog：統一各商品分類的公開商品 ID 與候選集合。
- 商品契約欄位：status、review_status、in_stock、recommendation_ready。
- Function：商品契約檢查、商品目錄登錄、色彩轉換、會員活動與統計。
- Trigger：商品新增目錄登錄、商品推薦狀態檢查、會員活動與稽核保護。
- View：會員活動、會員面板、商品清單、商品熱門度。
- Index：商品推薦狀態、粉底色階、OTP、Session、稽核與會員活動的常用查詢索引。

## 專案檔案用途

~~~text
Backend database/
├── app.py                         # Flask 路由、認證、商品、會員、推薦整合
├── models.py                      # SQLAlchemy ORM 模型
├── extensions.py                  # db、bcrypt、login_manager 共用實例
├── config.py                      # 環境變數與資料庫 URI 組裝
├── forms.py                       # Web 表單驗證
├── password_policy.py             # Web 與 JSON API 共用密碼規則
├── otp_utils.py                   # OTP、Redis、SMTP 輔助
├── recommendation.py              # 推薦、色彩、理由與色號替代規則
├── color_contract.py               # 官方色值證據、sRGB→CIELAB、CIEDE2000 與色彩資料警語契約
├── shade_neighbors.py             # 粉底色號鄰近色預先計算索引（同品牌不限系列、跨品牌）
├── makeup_keywords.py             # 妝容風格、別名與關鍵字字典
├── price_conversion.py             # 美元／新台幣顯示價與匯率揭露
├── crawler_preview.py             # 商品預覽、來源正規化與 SSRF 防護
├── product_image_mirror.py         # 讀取圖片鏡像 manifest，將可用圖片網址改為同源鏡像
├── mirror_product_images.py        # 下載、轉檔、驗證並發布商品圖片鏡像的維護工具
├── product_image_mirror.json       # 原始圖片網址與已發布鏡像路徑的對照資料
├── sql.py / seed_data.py          # 開發資料匯入工具
├── postgre.sql                    # PostgreSQL 18 custom-format 資料庫匯出檔
├── Dockerfile                     # API 映像建置
├── docker-compose.yml             # API、PostgreSQL、Redis 容器設定
├── Procfile                       # Procfile 平台的啟動命令
├── run_local_5000.py              # 本機開發啟動器
├── wait_for_services.py           # 等待 PostgreSQL、Redis 後啟動服務
├── scripts/                       # 啟動、資料比對與稽核輔助腳本
├── templates/                     # Jinja 網頁模板
├── tests/recommendation/          # 推薦、認證、商品、爬蟲、Session 契約測試
│   ├── test_cross_brand_shade_matches.py # 跨品牌粉底比較契約測試
│   ├── test_shade_neighbors.py    # 色號鄰近色索引、增量更新與商品頁比較測試
│   ├── test_foundation_shade_references.py # 較淺／較深參考、冷暖護欄與色彩證據測試
│   ├── test_personalization_regressions.py # MAC 主軸與個人化回歸測試
│   └── test_recommendation_contract.py # 粉底門檻、色差解釋與推薦回應測試
├── cleanup_invalid_product_images.py # 商品圖片資料清理工具
├── deploy_firebase_password_reset_fix.py # Firebase 密碼重設部署輔助
├── deploy_foundation_ladder_for_every_product.py # 商品詳情粉底色階前端部署輔助
├── deploy_before_makeup_baseline.py # 妝前顯示基準前端部署輔助
└── *_test.py、*_diagnostic.py 等  # 開發期手動測試與診斷工具
~~~

## 測試與維護

先做語法檢查：

~~~powershell
python -m py_compile app.py recommendation.py crawler_preview.py price_conversion.py password_policy.py
~~~

執行推薦與相關契約測試：

~~~powershell
$env:PYTHONPATH = "."
python tests\recommendation\test_recommendation_contract.py
python tests\recommendation\test_catalog_filters.py
python tests\recommendation\test_catalog_availability.py
python tests\recommendation\test_cross_brand_shade_matches.py
python tests\recommendation\test_shade_neighbors.py
python tests\recommendation\test_foundation_shade_references.py
python tests\recommendation\test_personalization_regressions.py
python tests\recommendation\test_saved_looks_contract.py
python tests\recommendation\test_product_image_mirror.py
python tests\recommendation\test_crawler_preview.py
python tests\recommendation\test_password_reset_contract.py
python tests\recommendation\test_session_ttl_contract.py
~~~

圖片鏡像與外部前端發布工具會連線至外部服務，僅應由具發布權限的人員在確認來源、帳號與目標環境後執行；一般測試不會發布任何內容。

推薦品質評估工具：

~~~powershell
python tests\recommendation\evaluate_precision_at_k.py gold.json predictions.json
~~~

在沒有人工標註的金標資料前，不應宣稱推薦準確率。推薦品質應以 Precision@K、商品覆蓋率、重複率、停用商品率與人工評估共同判定。

## 限制與後續規劃

- 目前是內容式與有限行為重排推薦，尚未建立完整曝光、點擊、購買事件資料集。
- 協同過濾、Learning-to-Rank、MDP／強化學習是後續擴充方向，不能在資料不足時宣稱已正式使用。
- 商品推薦品質依賴商品名稱、分類、標籤、色彩與庫存資料完整度。
- 粉底推薦只提供資料輔助；實際顏色受光線、螢幕與上妝方式影響，仍應以專櫃試色為準。
- 正式環境應固定 HTTPS 網域、限制 CORS、關閉 GATEWAY_KEY_LOOSE_MODE、使用秘密管理工具提供金鑰，並定期驗證 OTP、權限、商品審核與資料庫還原流程。
