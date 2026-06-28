# Decorate Me - Face Analysis API

本分支負責 **臉部分析模組**。此模組需要獨立成 API，讓網頁版前端與未來 iOS App 都能共用同一套臉部分析能力。

## 2026-06-25 渲染服務完成（flux-kontext-pro）

### 新增服務：replicate-render（Cloud Run）

- **`replicate_render.py`**：核心渲染模組，使用 `black-forest-labs/flux-kontext-pro` via Replicate SDK，支援從 data URL、HTTP URL、本機路徑載入圖片，`build_render_prompt()` 以自然語言格式組裝 prompt（flux-kontext-pro 不接受 tag-list 格式）。
- **`replicate_render_api.py`**：FastAPI 服務，提供 `GET /health` 與 `POST /render`，回傳格式與前端 API contract 一致（`status`, `afterImageUrl`, `error`）。
- **`Dockerfile.render`**：獨立 Docker image，和 face-basic / face-pro 的主 Dockerfile 分開，不影響現有後端。
- **`requirements.render.txt`**：`fastapi`, `uvicorn`, `replicate`, `requests`, `python-dotenv`。
- **Cloud Run 部署**：`replicate-render` 服務（`asia-east1`），`REPLICATE_API_TOKEN` 設為 Cloud Run 環境變數，不寫入 Git。

**更新 render 服務：**
```bat
docker build -f Dockerfile.render -t asia-east1-docker.pkg.dev/decorate-me/beauty-backend/replicate-render:latest .
docker push asia-east1-docker.pkg.dev/decorate-me/beauty-backend/replicate-render:latest
gcloud run deploy replicate-render --image=asia-east1-docker.pkg.dev/decorate-me/beauty-backend/replicate-render:latest --region=asia-east1 --project=decorate-me
```

### 前端改動（web_frontend）

- **`pages/compare.html`**：新增「AI 渲染妝容」按鈕（`#compareRenderBtn`）與渲染狀態顯示、英文 prompt 預覽區（`#comparePromptPreview`）。移除渲染前後照片字條（舊的 `comparePhotoLabel`）。
- **`js/router.js`**：
  - `setCompareImage()` 改用 inline style 設定 `backgroundSize: contain` 等，修正 `.compare-stage.before`（2 個 class） CSS 特異性覆蓋 `.compare-stage`（1 個 class）導致手機版照片被裁切的問題。
  - Compare render 按鈕使用 `buildRenderPrompt(pkg?.faceAnalysis, Router.selectedStyleId, pkg?.generativeText?.suggestion || '')` 組裝 prompt。
- **`js/api.js`**：完整重寫 `buildRenderPrompt()`，臉部分析欄位（臉型、眼型、眉型、鼻型、嘴唇、膚色四季型）以中英字典映射為英文描述，並將 Ollama suggestion 前 300 字作為 makeup reference。50 個妝容中文詞彙 → 英文關鍵詞字典。Ollama 的 `renderPromptEn` 不再使用，prompt 完全由前端自行組裝。

### 修正的 Bug

| Bug | 原因 | 修正方式 |
|-----|------|---------|
| 手機版照片被裁切 | `.compare-stage.before`（2 class）優先級高於 `.compare-stage`（1 class），`background` shorthand 重設了 `background-size` | 改用 inline style |
| 「AI 渲染妝容」按鈕不存在 | 按鈕只在 `router.js` inline template，實際頁面用的是 `pages/compare.html`，沒有同步 | 補進 `pages/compare.html` |
| `'str' object is not callable` | replicate SDK 1.0.7 的 `output.url` 是字串屬性，舊程式把它當 method 呼叫 | `url_val() if callable(url_val) else str(url_val)` |
| 網站卡在 intro 動畫 | `api.js` 同一函式內重複宣告 `const faceParts` 造成 SyntaxError | 移除重複宣告 |
| Ollama 生出亂格式英文指令 | 把 `renderPromptEn` 交給 Ollama 自動翻譯，它會生出「Apply deep optimized individual layout for requested 千金妝」 | 前端改用內建關鍵詞字典自行組裝，不依賴 Ollama |

### 服務架構（更新後）

| 服務 | URL | 狀態 | 跑在哪 |
|------|-----|------|--------|
| 前端 | https://decorate-me.web.app | ✅ 雲端 | Firebase Hosting |
| face-basic | https://face-basic-258021445391.asia-east1.run.app | ✅ 雲端 | Google Cloud Run |
| face-pro | https://face-pro-258021445391.asia-east1.run.app | ✅ 雲端 | Google Cloud Run |
| ollama_suggestion | Cloudflare URL（每次重啟更新） | ✅ Cloudflare | 黃姵錚 Mac |
| replicate-render | Cloud Run（asia-east1） | ✅ 雲端 | Google Cloud Run |
| member_database | — | ⏳ 等組員 | 組員部署後填入 |
| product_recommend | — | ⏳ 等組員 | 組員部署後填入 |

### 待辦

- 新增 Replicate 付款方式（目前 429 rate limit）：replicate.com/account/billing
- ollama_suggestion 組員需 git pull 後重啟才能取得 streaming 端點
- member_database / product_recommend URL 等組員提供

---

## 2026-06-28 自動檢查摘要

- 重新讀取本機 `README.md`、`TODO.txt` 與前端 `C:\Users\isach\OneDrive\桌面\web_frontend\README.md`。
- 後端程式碼與設定檔目前仍包含：
  - BASIC / PRO `/health`
  - BASIC / PRO `/v1/face/analyze/*`
  - BASIC / PRO 非同步 jobs API
  - BASIC `/v1/face/pose`
- `.venv` 重新檢查：
  - `python -m py_compile Face_analyzer_BASIC.py Face_analyzer_PRO.py Ollama_suggestion.py backend_smoke_test.py ollama_suggestion_smoke_test.py analysis_package.py`：通過
  - `python -m pip check`：通過
  - `python backend_smoke_test.py`：通過
  - `python ollama_suggestion_smoke_test.py`：通過
- 前端重新檢查：
  - `node --check js/api.js js/data.js js/router.js`：通過
  - `node frontend_smoke_check.js`：通過
- 今日 live / cloud 狀態：
  - `GET http://127.0.0.1:8001/health`：`200 OK`
  - `GET http://127.0.0.1:8002/health`：`200 OK`
  - `GET http://127.0.0.1:8010/health`：`200 OK`
  - `GET https://face-basic-258021445391.asia-east1.run.app/health`：`200 OK`
  - `GET https://face-pro-258021445391.asia-east1.run.app/health`：`200 OK`
- 這次修正的小問題：
  - `Dockerfile` 已移除對不存在 `replicate_render.py*` 的 `COPY`，避免預設 backend image 和 optional `replicate_render` 未交付狀態互相矛盾
- 目前新的主要阻塞：
  - 監聽中的 `8001`、`8002`、`8010` 進程仍是系統 Python `C:\Users\isach\AppData\Local\Programs\Python\Python310\python.exe`，不是 `.venv\Scripts\python.exe`
  - Suggestion `/health` 仍回報本機 Ollama `127.0.0.1:11434` 不可達，而且 `fallbackEnabled=false`
  - 前端 `config.local.js` 的 `textSuggestionUrl` `https://possibly-polyester-bargains-transcript.trycloudflare.com/health` 今天仍 DNS 無法解析
  - 前端 `memberDatabase` 仍指向 `https://vegetation-arguments-final-inspiration.trycloudflare.com/health`，今天仍 DNS 無法解析
- 目前版本控制狀態：
  - `PythonProject12` 是 Git repo，本次檢查前工作樹乾淨；本輪新增的本機文件更新尚未提交
  - 前端 `web_frontend` 是獨立 Git repo，目前只有 `dev_server.py` 未追蹤

---

## 2026-06-27 自動檢查摘要

- 重新讀取本機 `README.md`、`TODO.txt` 與前端 `C:\Users\isach\OneDrive\桌面\web_frontend\README.md`。
- 後端程式碼與設定檔仍維持一致：
  - BASIC / PRO `/health`
  - BASIC / PRO `/v1/face/analyze/*`
  - BASIC / PRO 非同步 jobs API
  - BASIC `/v1/face/pose`
  - Dockerfile / `.dockerignore` / `docker-compose.yml`
- `.venv` 重新檢查：
  - `python -m py_compile Face_analyzer_BASIC.py Face_analyzer_PRO.py Ollama_suggestion.py backend_smoke_test.py ollama_suggestion_smoke_test.py analysis_package.py`：通過
  - `python -m pip check`：通過
  - `python backend_smoke_test.py`：通過
  - `python ollama_suggestion_smoke_test.py`：通過
- 前端重新檢查：
  - `node --check js/api.js js/data.js js/router.js`：通過
  - `node frontend_smoke_check.js`：通過
- 今日 live 狀態：
  - `GET http://127.0.0.1:8001/health`：`200 OK`
  - `GET http://127.0.0.1:8002/health`：`200 OK`
  - `GET http://127.0.0.1:8010/health`：`200 OK`
  - `backend_smoke_test.py` 今日再次完整通過，BASIC `/v1/face/pose`、同步分析與 async jobs 目前都可用
  - 前端 `config.local.js` 內的 Cloud Run `faceBasic` / `facePro` 也都回 `200 OK`
- 目前新的主要阻塞：
  - 監聽中的 `8001`、`8002`、`8010` 進程仍是系統 Python
    `C:\Users\isach\AppData\Local\Programs\Python\Python310\python.exe`
    不是 `.venv\Scripts\python.exe`
  - Suggestion `/health` 仍回報本機 Ollama `127.0.0.1:11434` 不可達，而且 `fallbackEnabled` 現在是 `false`；若直接打 live `8010` `/suggest`，沒有可用 Ollama 時應視為正式阻塞，不再是可接受的 fallback 狀態
  - 前端 `config.local.js` 的 `textSuggestionUrl` Cloudflare 網址
    `https://possibly-polyester-bargains-transcript.trycloudflare.com/health`
    今天已 DNS 無法解析
  - 前端 `memberDatabase` 仍指向 `https://vegetation-arguments-final-inspiration.trycloudflare.com/health`，今天仍是 DNS 無法解析
- 目前版本控制狀態：
  - `PythonProject12` 是 Git repo，工作樹目前乾淨
  - 前端 `web_frontend` 仍是獨立 Git repo，目前只有 `dev_server.py` 未追蹤

---

## 2026-06-26 自動檢查摘要

- 重新讀取本機 `README.md`、`TODO.txt` 與前端 `C:\Users\isach\OneDrive\桌面\web_frontend\README.md`。
- 後端程式碼與設定檔仍維持一致：
  - BASIC / PRO `/health`
  - BASIC / PRO `/v1/face/analyze/*`
  - BASIC / PRO 非同步 jobs API
  - BASIC `/v1/face/pose`
  - Dockerfile / `.dockerignore` / `docker-compose.yml`
- `.venv` 重新檢查：
  - `python -m py_compile Face_analyzer_BASIC.py Face_analyzer_PRO.py Ollama_suggestion.py backend_smoke_test.py ollama_suggestion_smoke_test.py analysis_package.py`：通過
  - `python -m pip check`：通過
  - `python backend_smoke_test.py`：通過
  - `python ollama_suggestion_smoke_test.py`：通過
- 前端重新檢查：
  - `node --check js/api.js js/data.js js/router.js`：通過
  - `node frontend_smoke_check.js`：通過
- 今日 live 狀態：
  - `GET http://127.0.0.1:8001/health`：`200 OK`
  - `GET http://127.0.0.1:8002/health`：`200 OK`
  - `GET http://127.0.0.1:8010/health`：`200 OK`
  - `backend_smoke_test.py` 今日再次完整通過，BASIC `/v1/face/pose`、同步分析與 async jobs 目前都可用
- 目前新的主要阻塞：
  - 監聽中的 `8001`、`8002`、`8010` 進程仍是系統 Python
    `C:\Users\isach\AppData\Local\Programs\Python\Python310\python.exe`
    不是 `.venv\Scripts\python.exe`
  - Suggestion `/health` 仍回報本機 Ollama `127.0.0.1:11434` 不可達，因此文字建議目前仍以 fallback 為主
  - 前端 `memberDatabase` 仍指向 `https://vegetation-arguments-final-inspiration.trycloudflare.com/health`，今天仍是 DNS 無法解析
- 目前版本控制狀態：
  - `PythonProject12` 是 Git repo
  - `analysis_package.py` 已被 Git 追蹤，不再是未追蹤檔案
  - `docker-compose.yml` 目前有未提交變更：已把 `replicate_render` 改成 `profiles: ["optional"]`，避免組員尚未交付 `replicate_render.py` 時跟著預設 `docker compose up` 啟動
  - 前端 `web_frontend` 仍是獨立 Git repo，但目前還有 `frontend_smoke_check.js` 未提交變更與 `dev_server.py` 未追蹤

---

## 2026-06-25 更新摘要

### 前端

- **亮度調整改為 Gamma 校正**：舊版用 CSS `filter: brightness(x)` 線性相乘，皮膚亮部容易過曝、JPEG 雜訊被放大。新版改為逐像素 Gamma 校正（`output = 255 * (input/255)^gamma`），暗部提亮多、亮部幾乎不動，輸出品質從 94% 提升至 97%。
- **亮度滑桿改為 -100 到 +100**：和 Lightroom / Snapseed 相同的操作邏輯，中間 0 = 原圖，右側提亮，左側調暗，自動偵測暗照並設建議值。移除舊版「原圖 / 自動 / 手動」三模式選項。
- **調色後照片送往後端**：分析前強制 flush debounce，確保 `Router.selectedFile` 一定是調色後版本，後端膚色計算結果才能反映調亮後的真實膚色。
- **Auth 改為 sessionStorage**：關閉分頁即自動登出，不再跨分頁保留登入狀態。
- **訪客資料清除**：頁面載入時若無登入 session，自動清除 `beautyAnalysisDraft`、`beautyFav`、`beautyCart`、`beautyHistory`、`beautySuggestions`，確保每次訪客都從乾淨狀態開始。
- **`renderPromptEn` 自動組裝**：Ollama 建議完成後，前端根據 `faceAnalysis`（臉型、眼型、膚色）與選定風格，用 JavaScript 在毫秒內拼裝英文 Replicate 渲染提示詞，存入 `analysisPackage.generativeText.renderPromptEn`，不需要額外 AI 呼叫。

### 後端 / 部署

- **`analysis_package.py` 加入**：後端資料包正規化工具，把中文臉部分析輸出轉為前後端共用的英文欄位格式（`faceShape: "oval"` 等），包含 `normalize_face_analysis()`、`build_analysis_package()`、`set_suggestion()`、`set_render_result()`。
- **`docker-compose.yml` 新增 `replicate_render` 服務**（port 8020）：等組員交付 `replicate_render.py` 後啟用，現可先將該 service 區塊保留但不啟動。
- **`.env` 新增**：存放 `REPLICATE_API_TOKEN`、`OLLAMA_BASE_URL`、`OLLAMA_MODEL`，docker-compose 自動讀取，不寫入 Git。
- **Google Cloud Run 部署完成**：
  - 專案：`decorate-me`（project ID：258021445391）
  - 區域：`asia-east1`（台灣最近節點）
  - Image：`asia-east1-docker.pkg.dev/decorate-me/beauty-backend/backend:latest`
  - face-basic：`https://face-basic-258021445391.asia-east1.run.app` ✅
  - face-pro：`https://face-pro-258021445391.asia-east1.run.app` ✅
  - 規格：memory 2Gi、CPU 2、timeout 300s、allow-unauthenticated
  - `config.local.js` 已更新 `faceBasicUrl`、`faceProUrl` 指向 Cloud Run
  - 本機 8001、8002 不再需要啟動

- **前端部署至 Firebase Hosting**：`https://decorate-me.web.app`，使用 Google Cloud 專案 `decorate-me`，更新只需 `firebase deploy --only hosting`，不再依賴本機 dev_server。

### 組員規格書

- 新增 `replicate_接入規格書.md`（位於 `web_frontend/`）：提供給負責 Replicate 渲染的組員，說明服務架構、完整程式碼、Cloudflare Tunnel 設定、前後端資料格式。

### 服務架構（目前）

| 服務 | URL | 狀態 | 跑在哪 |
|------|-----|------|--------|
| 前端 | https://decorate-me.web.app | ✅ **雲端** | Firebase Hosting |
| face-basic | https://face-basic-258021445391.asia-east1.run.app | ✅ **雲端** | Google Cloud Run |
| face-pro | https://face-pro-258021445391.asia-east1.run.app | ✅ **雲端** | Google Cloud Run |
| ollama_suggestion | Cloudflare URL（每次重啟更新） | ✅ Cloudflare | 黃姵錚 Mac |
| member_database | — | ⏳ 等組員 | 組員部署後填入 |
| product_recommend | — | ⏳ 等組員 | 組員部署後填入 |
| replicate_render | — | ⏳ 等組員 | 組員 Cloud Run |

本機 5500、8001、8002 已不再需要啟動。前端更新只需跑 `firebase deploy --only hosting`。

### 更新流程

**前端有改動：**
```bat
cd C:\Users\isach\OneDrive\桌面\web_frontend
firebase deploy --only hosting
```
約 30 秒，`https://decorate-me.web.app` 立即生效。

**後端有改動（`Face_analyzer_BASIC.py` / `Face_analyzer_PRO.py` 等）：**
```bat
cd C:\Users\isach\PycharmProjects\PythonProject12
docker build -t asia-east1-docker.pkg.dev/decorate-me/beauty-backend/backend:latest .
docker push asia-east1-docker.pkg.dev/decorate-me/beauty-backend/backend:latest
gcloud run deploy face-basic --image=asia-east1-docker.pkg.dev/decorate-me/beauty-backend/backend:latest --region=asia-east1
gcloud run deploy face-pro --image=asia-east1-docker.pkg.dev/decorate-me/beauty-backend/backend:latest --region=asia-east1
```
build 約 5 分鐘，push + deploy 約 2 分鐘，完成後 Cloud Run 自動換版本，URL 不變。

### analysisPackage 更新（`generativeText`）

```json
"generativeText": {
  "status": "pending | completed | failed",
  "provider": "ollama",
  "model": "gemma3 / llava",
  "suggestion": "中文妝容建議（5段）",
  "renderPromptEn": "luxury rich girl makeup, Asian woman with oval face...",
  "error": null,
  "fallbackUsed": false
}
```

新增欄位 `renderPromptEn`：前端自動組裝，供 Replicate 渲染用的英文 prompt。

---

## 2026-06-24 自動檢查摘要

- 重新讀取本機 `README.md`、`TODO.txt` 與前端 `C:\Users\isach\OneDrive\桌面\web_frontend\README.md`。
- 後端程式碼與設定檔仍維持一致：
  - BASIC / PRO `/health`
  - BASIC / PRO `/v1/face/analyze/*`
  - BASIC / PRO 非同步 jobs API
  - BASIC `/v1/face/pose`
  - Dockerfile / `.dockerignore` / `docker-compose.yml`
- `.venv` 重新檢查：
  - `python -m py_compile Face_analyzer_BASIC.py Face_analyzer_PRO.py Ollama_suggestion.py backend_smoke_test.py ollama_suggestion_smoke_test.py analysis_package.py`：通過
  - `python -m pip check`：通過
  - `python backend_smoke_test.py`：通過
  - `python ollama_suggestion_smoke_test.py`：通過
- 前端重新檢查：
  - `node frontend_smoke_check.js`：通過
  - `node --check js/api.js js/data.js js/router.js`：通過
- 今日 live 狀態和 2026-06-23 不同：
  - `GET http://127.0.0.1:8001/health`：`200 OK`
  - `GET http://127.0.0.1:8002/health`：`200 OK`
  - `GET http://127.0.0.1:8010/health`：`200 OK`
  - `backend_smoke_test.py` 已再次完整通過，BASIC `/v1/face/pose`、同步分析與 async jobs 目前都可用
- 目前新的主要阻塞：
  - 監聽中的 `8001`、`8002`、`8010` 進程仍是系統 Python
    `C:\Users\isach\AppData\Local\Programs\Python\Python310\python.exe`
    不是 `.venv\Scripts\python.exe`
  - Suggestion `/health` 仍回報本機 Ollama `127.0.0.1:11434` 不可達，因此文字建議目前仍以 fallback 為主
  - 前端 `memberDatabase` 仍指向 `https://vegetation-arguments-final-inspiration.trycloudflare.com/health`，今天仍是 DNS 無法解析
- 目前版本控制狀態：
  - `PythonProject12` 是 Git repo
  - 這次有重要未追蹤檔案：`analysis_package.py`
  - `.gitignore` 已新增白名單但尚未提交，代表 `analysis_package.py` 與 `後端功能與BASIC臉部分析說明.md` 目前仍只存在工作樹

## 2026-06-23 自動檢查摘要

- 重新讀取本機 `README.md`、`TODO.txt` 與前端 `C:\Users\isach\OneDrive\桌面\web_frontend\README.md`。
- 後端程式碼與設定檔仍維持一致：
  - BASIC / PRO `/health`
  - BASIC / PRO `/v1/face/analyze/*`
  - BASIC / PRO 非同步 jobs API
  - BASIC `/v1/face/pose`
  - Dockerfile / `.dockerignore` / `docker-compose.yml`
- `.venv` 重新檢查：
  - `python -m py_compile Face_analyzer_BASIC.py Face_analyzer_PRO.py Ollama_suggestion.py backend_smoke_test.py ollama_suggestion_smoke_test.py`：通過
  - `python -m pip check`：通過
  - `python ollama_suggestion_smoke_test.py`：通過
- 前端重新檢查：
  - `node frontend_smoke_check.js`：通過
  - `node --check js/api.js js/data.js js/router.js`：通過
- 今日 live 狀態和 2026-06-22 相同：
  - `8001`、`8002`、`8010` 目前都**沒有監聽中的服務**
  - `GET http://127.0.0.1:8001/health`、`8002/health`、`8010/health` 全部是 connection refused
  - `backend_smoke_test.py` 仍在第一個 `/v1/face/pose` 就失敗，原因是沒有可連線的 BASIC 服務
- 前端 `memberDatabase` 仍指向 `https://vegetation-arguments-final-inspiration.trycloudflare.com/health`，今天仍是 DNS 無法解析。
- 目前版本控制狀態：
  - `PythonProject12` 是 Git repo，這次未發現重要未追蹤檔案
  - `C:\Users\isach\OneDrive\桌面\web_frontend` 也是獨立 Git repo
  - 前端目前只有 `docs/health-check-log.md` 有未提交變更，內容是 2026-06-22 健康檢查紀錄

## 2026-06-22 自動檢查摘要

- 重新讀取本機 `README.md`、`TODO.txt` 與前端 `C:\Users\isach\OneDrive\桌面\web_frontend\README.md`。
- 後端程式碼與設定檔仍維持一致：
  - BASIC / PRO `/health`
  - BASIC / PRO `/v1/face/analyze/*`
  - BASIC / PRO 非同步 jobs API
  - BASIC `/v1/face/pose`
  - Dockerfile / `.dockerignore` / `docker-compose.yml`
- `.venv` 重新檢查：
  - `python -m py_compile Face_analyzer_BASIC.py Face_analyzer_PRO.py Ollama_suggestion.py backend_smoke_test.py ollama_suggestion_smoke_test.py`：通過
  - `python -m pip check`：通過
  - `python ollama_suggestion_smoke_test.py`：通過
- 前端重新檢查：
  - `node frontend_smoke_check.js`：通過
  - `node --check js/api.js js/data.js js/router.js`：通過
- 今日新的實際阻塞與 2026-06-20 不同：
  - `8001`、`8002`、`8010` 目前都**沒有監聽中的服務**
  - `GET http://127.0.0.1:8001/health`、`8002/health`、`8010/health` 全部是 connection refused
  - `backend_smoke_test.py` 目前在第一個 `/v1/face/pose` 就失敗，不再是昨天的 live schema 漂移問題
- 前端 `memberDatabase` 仍指向 `https://vegetation-arguments-final-inspiration.trycloudflare.com/health`，今天仍是 DNS 無法解析。
- 目前版本控制狀態：
  - `PythonProject12` 是 Git repo，這次未發現重要未追蹤檔案
  - `C:\Users\isach\OneDrive\桌面\web_frontend` 也是獨立 Git repo，這次未發現重要未追蹤檔案

## 2026-06-19 自動檢查摘要

- 新增 `臉部對稱性` 分析（`get_face_symmetry()`）：score、eyeOpenRatio、noseDeviation、mouthSymmetry，已整合進 `export_json()` 輸出。
- PRO 側面輔助分析完成：`_analyze_side_supplementary()` 以 `strict_angle=False` 對側面照（約 10° yaw）分析膚色，並與正面照 LAB 平均，結果含 `LAB來源: 正面+側面平均`。
- `FaceAnalyzer.__init__` 新增 `strict_angle` 參數（預設 `True`），PRO 側面分析用 `False` 跳過角度驗證。
- `精細分析狀態` 已輸出真實狀態，不再是 "待實作"。
- `POST /v1/face/pose` 已上線，回傳 yaw / pitch / roll / captureRole / side / confidence，供前端 PRO 掃描流程即時姿態偵測。
- `captureRole` 閾值更新：`front`（abs_yaw ≤ 8° & pitch ≤ 12°）、`side`（abs_yaw ≥ 10°）、`angle45`（abs_yaw ≥ 6°）、`turning`（其餘）。
- `backend_smoke_test.py` 更新：新增 `臉部對稱性` 欄位驗證、PRO `精細分析狀態` 不含 "待實作" 斷言、`/v1/face/pose` 端點測試。
- `data/asian_faces/` 已放入亞洲人臉 sample 資料集（GitHub, 192 張）供後續模型訓練參考；完整資料集需聯繫論文作者。
- `frontend_smoke_check.js` 更新：驗證 `faceAnalysis` schema 新增欄位（symmetry、noseSide、sidePhotoUsed、proStatus）與 `fromRawFaceAnalysis()` 映射邏輯。

## 2026-06-20 自動檢查摘要

- 重新讀取本機 `README.md`、`TODO.txt` 與前端 `C:\Users\isach\OneDrive\桌面\web_frontend\README.md` 後，確認後端程式檔本身仍包含 `臉部對稱性`、`/v1/face/pose`、PRO 側面輔助分析與非同步 jobs API。
- `GET /health` 重新實測：
  - BASIC `http://127.0.0.1:8001/health`：`200 OK`
  - PRO `http://127.0.0.1:8002/health`：`200 OK`
  - Suggestion `http://127.0.0.1:8010/health`：`200 OK`
- Suggestion `/health` 仍回報本機 Ollama `127.0.0.1:11434` 不可達，因此目前文字建議仍以 fallback 為主。
- 前端 `memberDatabase` 目前的 Cloudflare URL `https://vegetation-arguments-final-inspiration.trycloudflare.com/health` 仍然 DNS 失敗。
- `.venv` 重新檢查：
  - `python -m py_compile Face_analyzer_BASIC.py Face_analyzer_PRO.py Ollama_suggestion.py backend_smoke_test.py ollama_suggestion_smoke_test.py`：通過
  - `python -m pip check`：通過，未發現 `requirements.txt` 依賴衝突
  - `ollama_suggestion_smoke_test.py`：通過
- 新發現的主要阻塞：
  - 目前對外監聽 `8001`、`8002`、`8010` 的 PID 仍是系統 Python
    `C:\Users\isach\AppData\Local\Programs\Python\Python310\python.exe`
    不是 `.venv\Scripts\python.exe`。
  - 因此目前 live port 回應的 BASIC async result schema 與工作區程式碼不一致：
    `backend_smoke_test.py` 在 `GET /v1/face/jobs/{jobId}/result` 階段失敗，缺少 README 已列出的 `臉部對稱性` 欄位。
  - 這代表目前埠上服務很可能是舊進程或舊啟動環境，部署 / 整合前必須先清乾淨並用 `.venv` 重啟。
- 前端版本控制狀態已更新：
  - `C:\Users\isach\OneDrive\桌面\web_frontend` 現在是獨立 Git repo（不是整個桌面 repo）
  - 本次檢查未發現未追蹤的重要專案檔

## 2026-06-18 自動檢查摘要

- 後端 `.venv` 重新實測通過：
  - BASIC `GET /health`
  - PRO `GET /health`
  - Suggestion `GET /health`
- `backend_smoke_test.py` 這次已直接通過：
  - 自動選到 `data/basic_usable/raw_images/000007.jpg`
  - BASIC `/health`、同步分析、非同步 jobs 通過
  - PRO `/health`、同步分析、非同步 jobs 通過
- `ollama_suggestion_smoke_test.py` 再次通過。
- `.venv` 內 `pip check` 通過，這次沒有發現 `requirements.txt` 衝突。
- `python -m py_compile` 已再次通過 `Face_analyzer_BASIC.py`、`Face_analyzer_PRO.py`、`Ollama_suggestion.py`、`backend_smoke_test.py`、`ollama_suggestion_smoke_test.py`。
- `docker compose config` 可正常解析。
- 目前監聽中的 `8001`、`8002`、`8010` 進程仍是用系統 Python
  `C:\Users\isach\AppData\Local\Programs\Python\Python310\python.exe`
  啟動，不是 `.venv\Scripts\python.exe`，這仍是環境漂移風險。
- 目前真正仍卡住的外部依賴：
  - Ollama `127.0.0.1:11434` 不可達，`/suggest` 仍靠 fallback。
  - 前端 `memberDatabase` Cloudflare URL 仍無法解析。
  - 前端 `web_frontend` 仍不是獨立 Git repo，而是掛在 `C:\Users\isach\OneDrive\桌面`。

## 2026-06-17 自動檢查摘要

- 後端 `.venv` 重新實測通過：
  - BASIC `GET /health`
  - PRO `GET /health`
  - Suggestion `GET /health`
- `ollama_suggestion_smoke_test.py` 再次通過。
- `backend_smoke_test.py` 這次沒有直接通過：
  - 腳本一啟動就因缺少 smoke-test image 而中止
  - 目前訊息是 `No smoke-test image found. Run select_basic_usable_images.py first.`
  - 代表 API contract 仍在，但本機測試資產前置條件沒有補齊
- `.venv` 內 `pip check` 通過，這次沒有發現 `requirements.txt` 衝突。
- `python -m py_compile` 已再次通過 `Face_analyzer_BASIC.py`、`Face_analyzer_PRO.py`、`Ollama_suggestion.py`。
- `docker compose config` 可正常解析。
- 已修正 Docker build 設定：
  - 移除 `index.html` 殘留引用（`Dockerfile` / `.dockerignore`）
  - 移除 `Face_analyzer.py` 的 COPY（無人 import，空占映像層）
  - 補入 `dev_server_utils.py` COPY — 少了這個 Docker 容器啟動就立刻 `ModuleNotFoundError`
- 已修正 `requirements.txt`：補入 `pydantic`（Ollama_suggestion 頂層依賴）、`Pillow`、`tqdm`、`pandas`（資料工具腳本依賴）
- 已修正 `setup.bat`：`opencv-python` 改為 `opencv-python-headless`，避免與 `requirements.txt` 衝突。
- 已修正 `batch_basic_classify.py`：欄位名 `nose_shape` 改為 `nose_front`，與 `auto_label_basic_dataset.py` 和 `labels.csv` 一致。
- 目前真正仍卡住的外部依賴：
  - Ollama `127.0.0.1:11434` 不可達，`/suggest` 仍靠 fallback。
  - 前端 `memberDatabase` Cloudflare URL 仍無法解析。
  - 前端 `web_frontend` 仍不是獨立 Git repo，而是掛在 `C:\Users\isach\OneDrive\桌面`。

## 完全新手先看這裡

這個專案現在在做一件事：

```txt
使用者上傳一張臉部照片
→ 後端分析臉型、眉型、眼型、鼻型、嘴型、膚色
→ 前端拿到分析結果
→ 之後再接文字建議、妝後圖片、商品推薦、會員紀錄
```

你可以把它想成一條流水線：

```txt
照片
→ 臉部分析
→ 文字建議
→ 妝後圖片
→ 商品推薦
→ 儲存紀錄
```

目前我已經先把「臉部分析」這一段做起來，而且前端也已經可以用非同步方式呼叫它。

如果你只想知道進度，先看根目錄的：

```txt
TODO.txt
```

如果你只想知道 BASIC 圖片資料集怎麼標註，先看：

```txt
data/basic_usable/README.md
data/basic_usable/LABELING_GUIDE.md
data/basic_usable/dataset_report.md
```

最簡單的人話版本：

- BASIC：只看正面照，先判斷比較穩的臉部特徵。
- PRO：以後要看正面、45 度、側面，做更細的判斷。
- analysisPackage：前端、後端、隊友 API 共用的一包資料。
- 非同步 jobs：照片丟出去後，不用卡在同一個請求裡等結果，前端可以一直查進度。
- smoke test：快速確認「服務有沒有活著、API 能不能跑」的小測試。

目前分支：

```txt
GitHub repo: vivi930319/new_poject.git
branch: Isa
```

## 目前狀態

已完成：

- BASIC 臉部分析 API
- PRO 多角度分析 API 入口
- Ollama `/suggest` 本機轉接 / mock API 第一版
- BASIC / PRO 程式拆分
- Dockerfile 修正（補 `dev_server_utils.py`、移除 `Face_analyzer.py` 與 `index.html` 殘留）
- requirements 補齊（`pydantic`、`Pillow`、`tqdm`、`pandas`）
- setup.bat 修正（opencv 套件名統一）
- batch_basic_classify.py 欄位名修正（`nose_shape` → `nose_front`）
- 鼻型 BASIC 邏輯保守化
- PRO 多角度欄位預留
- BASIC / PRO `GET /health`
- BASIC / PRO `/v1/face/analyze/*` 相容入口
- `MAX_IMAGE_SIZE` 可用環境變數調整，預設 2048
- `numpy<2` 與 `mediapipe==0.10.21` 相容設定
- BASIC / PRO 非同步 jobs API 第一版
- BASIC / PRO jobs 已加入 timeout、保留時間與記憶體數量上限
- Docker Compose 同時啟動 BASIC 與 PRO 服務
- Docker Compose 可啟動 Ollama 文字建議本機轉接服務
- ONNX 模型檔以 Docker volume 掛載
- CelebA 第一批 BASIC 可用正面圖已篩選 500 張，輸出到 `data/basic_usable/raw_images`
- BASIC 眉型與臉型分類閾值校正（修正彎月眉 94% 偏差、長形臉幾乎不出現的問題）
- 臉部對稱性分析（`get_face_symmetry()`）：score / eyeOpenRatio / noseDeviation / mouthSymmetry
- `FaceAnalyzer` 新增 `strict_angle` 參數（PRO 側面分析用 `False`）
- PRO 側面輔助分析：膚色雙角度 LAB 平均（`LAB來源: 正面+側面平均`）
- PRO `精細分析狀態` 輸出真實狀態
- BASIC `POST /v1/face/pose` 輕量姿態偵測 API
- `captureRole` 閾值校正（8°/10°/6°）

目前主要檔案：

```txt
Face_analyzer_BASIC.py          BASIC 正面照分析 API（已部署）
Face_analyzer_PRO.py            PRO 多角度分析 API 入口（已部署）
Ollama_suggestion.py            Ollama 文字建議本機轉接 / mock 服務（已部署）
dev_server_utils.py             本機啟動共用工具（port 衝突偵測）
Dockerfile                      Docker 部署設定
docker-compose.yml              同時啟動三個服務
requirements.txt                Python 依賴
backend_smoke_test.py           BASIC / PRO health、同步、非同步 API 測試
ollama_suggestion_smoke_test.py 文字建議 prompt / fallback 測試

# 以下為舊版原型，不在 Docker 內，僅供參考
Face_analyzer.py                中間版原型（有 eyelid 邏輯、無 jobs API）
Face_test.py                    最舊原型（無 InsightFace）
```

補充：

- `127.0.0.1:8001` 本質上還是後端 BASIC API。
- 現在它的根路徑 `/` 會自動導向前端 `http://127.0.0.1:5500`，避免你誤看到舊版頁面。
- 前端資料夾需另行啟動（預設由 Live Server 提供 `http://127.0.0.1:5500`）。

## API 目標

臉部分析模組不應只服務網頁前端，而是應該成為獨立服務：

```txt
Web Frontend
iOS App
    ↓
Face Analysis API
    ↓
analysisPackage
    ↓
Ollama 文字建議 / Replicate 渲染 / 商品推薦 / PostgreSQL 紀錄
```

前端與 iOS 不需要知道後端內部使用 MediaPipe、InsightFace 或未來訓練模型，只需要依照 API contract 呼叫。

## 環境建立（第一次）

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

> 請一律用 `.venv` 內的 Python 啟動，不要用系統 Python，否則可能缺 `uvicorn`、`onnxruntime`、`insightface`。

## 快速啟動

**正式環境（face-basic / face-pro 已上 Cloud Run，不需要本機跑後端）：**

只開前端即可：

```bat
start_full_stack_local.bat
```

前端會自動從 `config.local.js` 讀取 Cloud Run URL，不需要本機 8001 / 8002。

---

**本機開發 / 測試用（需要完整本機環境）：**

```bat
.venv\Scripts\python.exe Face_analyzer_BASIC.py    # port 8001
.venv\Scripts\python.exe Face_analyzer_PRO.py      # port 8002
.venv\Scripts\python.exe Ollama_suggestion.py      # port 8010
```

> 本機測試時需把 `config.local.js` 的 `faceBasicUrl`、`faceProUrl` 暫時改回 `http://127.0.0.1:8001`、`http://127.0.0.1:8002`，或直接拿掉這兩行讓它 fallback 到 localhost。

**更新 Cloud Run（程式碼有改動時）：**

```bat
docker build -t asia-east1-docker.pkg.dev/decorate-me/beauty-backend/backend:latest .
docker push asia-east1-docker.pkg.dev/decorate-me/beauty-backend/backend:latest
gcloud run deploy face-basic --image=asia-east1-docker.pkg.dev/decorate-me/beauty-backend/backend:latest --region=asia-east1
gcloud run deploy face-pro   --image=asia-east1-docker.pkg.dev/decorate-me/beauty-backend/backend:latest --region=asia-east1
```

> Port 衝突時程式會直接提示，不會只丟 bind error。

## 啟動方式

### BASIC API

```bash
uvicorn Face_analyzer_BASIC:app --host 0.0.0.0 --port 8001
```

API：

```txt
POST http://127.0.0.1:8001/analyze
POST http://127.0.0.1:8001/v1/face/analyze/basic
POST http://127.0.0.1:8001/v1/face/jobs/basic
GET  http://127.0.0.1:8001/v1/face/jobs/{jobId}
GET  http://127.0.0.1:8001/v1/face/jobs/{jobId}/result
GET  http://127.0.0.1:8001/health
POST http://127.0.0.1:8001/v1/face/pose
```

`/v1/face/pose`：輕量姿態偵測，回傳 yaw/pitch/roll 與 captureRole，供前端 PRO 掃描流程判斷正面/側面。

```txt
Content-Type: multipart/form-data
file: image

Response:
{
  "yaw": -8.3,
  "pitch": 2.1,
  "roll": 0.5,
  "captureRole": "front",   // front | side | angle45 | turning
  "side": "left",           // left | right
  "confidence": 0.97
}
```

captureRole 閾值：

```txt
front    abs_yaw ≤ 8° & abs_pitch ≤ 12°
side     abs_yaw ≥ 10°
angle45  abs_yaw ≥ 6°
turning  其餘
```

Request：

```txt
Content-Type: multipart/form-data
file: image
```

Response 範例：

```json
{
  "分析版本": "BASIC",
  "臉型": "鵝蛋臉",
  "眉型": "彎月眉",
  "眼型": "桃花眼",
  "鼻型": "標準鼻",
  "嘴型": "微笑唇",
  "膚色": {
    "四季型": "春季",
    "膚色分級": "白皙自然色",
    "LAB": {
      "L": 70,
      "a": 10,
      "b": 14
    }
  },
  "嘴唇_LAB": {
    "L": 40,
    "a": 20,
    "b": 10
  },
  "臉部對稱性": {
    "score": 82,
    "eyeOpenRatio": 0.95,
    "noseDeviation": 0.02,
    "mouthSymmetry": 0.98
  }
}
```

### 後端 Smoke Test

先啟動 BASIC 與 PRO：

```bash
uvicorn Face_analyzer_BASIC:app --host 127.0.0.1 --port 8001
uvicorn Face_analyzer_PRO:app --host 127.0.0.1 --port 8002
```

再執行：

```bash
python backend_smoke_test.py
```

已在本機完成驗證：

```txt
BASIC GET /health: ok
BASIC GET /health jobs/limits: ok
BASIC POST /v1/face/analyze/basic: ok
BASIC POST /v1/face/jobs/basic + poll + result: ok
PRO GET /health: ok
PRO GET /health jobs/limits: ok
PRO POST /v1/face/analyze/pro: ok
PRO POST /v1/face/jobs/pro + poll + result: ok
```

目前 Web Frontend 已改用上述 async jobs 流程送出 BASIC / PRO 分析，並會將 `jobId`、`progress`、`stage` 寫入 `analysisPackage.async`。

已完成前端瀏覽器 smoke test：

```txt
Web visitor login: ok
BASIC upload -> async job -> result display: ok
PRO front upload -> async job -> result display: ok
analysisPackage.async.jobId/progress/stage: ok
```

### Ollama 文字建議 API

這個服務不是正式的 Ollama 模型端。

它在這個專案裡的定位是：

- 本機整合用的 `/suggest` 轉接層
- 前端串接時先固定 request / response 格式
- 隊友正式服務尚未接上前的 mock / fallback

真正的 Ollama 模型推論與訓練端是其他組員的分工；這裡先保留同樣的 API 介面，方便前端與整體流程先接起來。

前端不要直接連：

```txt
http://127.0.0.1:11434
```

前端應該呼叫：

```txt
POST http://127.0.0.1:8010/suggest
GET  http://127.0.0.1:8010/health
```

啟動方式：

```bash
uvicorn Ollama_suggestion:app --host 0.0.0.0 --port 8010
```

Request 範例：

```json
{
  "style": "日常自然妝",
  "faceAnalysis": {
    "faceShape": "oval",
    "browShape": "curved",
    "eyeShape": "peach_blossom",
    "noseFront": "standard",
    "lipShape": "smile",
    "skinTone": {
      "season": "spring",
      "level": "白皙自然色"
    }
  }
}
```

Response 範例：

```json
{
  "status": "completed",
  "provider": "ollama",
  "model": "gemma3",
  "fallbackUsed": false,
  "createdAt": "...",
  "suggestion": "文字建議內容"
}
```

如果正式 Ollama 服務還沒接上，或本機沒有連到可用的 Ollama，展示階段可以先使用 fallback：

```txt
OLLAMA_ALLOW_FALLBACK=true
```

這樣 `/suggest` 仍會回傳中文妝容建議，不會讓前端 demo 卡死。

已完成測試：

```txt
ollama_suggestion_smoke_test.py: ok
GET /health: ok
POST /suggest: ok，未接到正式 Ollama 服務時 fallback 可用
```

### PRO API

```bash
uvicorn Face_analyzer_PRO:app --host 0.0.0.0 --port 8002
```

API：

```txt
POST http://127.0.0.1:8002/analyze-pro
POST http://127.0.0.1:8002/v1/face/analyze/pro
POST http://127.0.0.1:8002/v1/face/jobs/pro
GET  http://127.0.0.1:8002/v1/face/jobs/{jobId}
GET  http://127.0.0.1:8002/v1/face/jobs/{jobId}/result
GET  http://127.0.0.1:8002/health
```

Request：

```txt
Content-Type: multipart/form-data
front: image required
left45: image optional
right45: image optional
side: image optional
```

目前 PRO 狀態：

- `front` 必填（正面照，完整 BASIC 分析）
- `side` 正式 PRO 側面照（約 10° yaw，用於膚色雙角度平均）
- `left45` / `right45` 保留欄位（未來展望）

PRO Response 範例（正面 + 側面照）：

```json
{
  "分析版本": "PRO",
  "臉型": "鵝蛋臉",
  "眉型": "彎月眉",
  "眼型": "桃花眼",
  "鼻型": "標準鼻",
  "嘴型": "微笑唇",
  "膚色": {
    "四季型": "春季",
    "膚色分級": "白皙自然色",
    "LAB": { "L": 70.1, "a": 10.2, "b": 14.3 },
    "LAB來源": "正面+側面平均"
  },
  "嘴唇_LAB": { "L": 40, "a": 20, "b": 10 },
  "臉部對稱性": {
    "score": 82,
    "eyeOpenRatio": 0.95,
    "noseDeviation": 0.02,
    "mouthSymmetry": 0.98
  },
  "精細分析狀態": {
    "多角度照片": "已接收，膚色已雙角度平均",
    "臉部對稱性": "已計算",
    "鼻型精細分類": "需 70-90° 側面輪廓照才能分類翹鼻/鷹鉤鼻/塌鼻，目前側面角度（約 10°）不足，保留為未來展望"
  },
  "精細分析備註": "PRO 流程採正面照 + 單側側面照。側面照目前約 10° yaw，用於膚色雙角度平均與對稱性輔助；側面鼻型等深度特徵需 70-90° 輪廓照，保留為未來展望。"
}
```

## BASIC / PRO 分工

### BASIC

BASIC 只處理正面照可相對穩定判斷的特徵：

```txt
臉型
眉型
眼型
鼻型正面寬窄
嘴型
膚色
唇色 LAB
```

BASIC 鼻型目前只建議輸出：

```txt
標準鼻
寬鼻
窄鼻
```

不建議 BASIC 用正面照判斷：

```txt
鷹勾鼻
塌鼻
朝天鼻
翹鼻
高鼻樑 / 低鼻樑
```

這些需要側面照、45 度照或深度資訊，應留給 PRO。

### PRO

PRO 預計處理正面照看不出來的精細分類：

```txt
鷹勾鼻
塌鼻
朝天鼻
翹鼻
高鼻樑 / 低鼻樑
側臉輪廓
下巴前突 / 後縮
臉部立體度
```

PRO 資料應以同一個人的多角度照片成組：

```txt
subject_0001/
  front.jpg
  left45.jpg
  right45.jpg
  side.jpg
  label.json
```

## 非同步機制規劃

目前同步與非同步 API 並存：

- **同步**：`POST /analyze`、`POST /v1/face/analyze/basic`，直接回傳結果，適合單人測試。
- **非同步**：`POST /v1/face/jobs/basic`，立即回傳 `jobId`，前端輪詢查進度，適合多人同時使用。

多人並發時使用同步 API 的風險：

- 圖片分析耗時
- Ollama 文字建議耗時
- Replicate 圖片渲染耗時
- 多人同時請求可能佔滿 worker

目前非同步 Job API 使用 FastAPI `BackgroundTasks` 與記憶體 job 狀態，後續正式部署時再升級 Redis + Celery/RQ。

目前記憶體 job 狀態已有展示階段保護：

```txt
FACE_JOB_TIMEOUT_SECONDS=180       單一 job 超過 180 秒會標成 failed / timeout
FACE_JOB_RETENTION_SECONDS=3600    completed / failed job 保留 1 小時
FACE_JOB_MAX_COUNT=200             記憶體最多保留 200 筆 job
```

`GET /health` 會回傳目前 jobs 統計與 limits，方便 demo 前確認服務狀態。

### 非同步 API 草案

```txt
POST /v1/face/jobs/basic
POST /v1/face/jobs/pro
GET  /v1/face/jobs/{jobId}
GET  /v1/face/jobs/{jobId}/result
```

流程：

```txt
Web / iOS
  ↓
POST /v1/face/jobs/basic
  ↓
Response: { jobId, status: "queued" }
  ↓
前端輪詢 GET /v1/face/jobs/{jobId}
  ↓
completed 後取得 analysisPackage
```

Job 狀態格式：

```json
{
  "jobId": "JOB-xxx",
  "analysisPackageId": null,
  "status": "queued | processing | completed | failed",
  "progress": 0,
  "stage": "upload | front_analysis | side_analysis | done | failed | timeout",
  "createdAt": "...",
  "startedAt": "...",
  "completedAt": "...",
  "error": null
}
```

PRO job stage 流程：

```txt
upload (queued, 0%)
  → front_analysis (processing, 30%)
  → side_analysis  (processing, 65%)
  → done           (completed, 100%)
```

實作階段：

```txt
第 1 階段：保留同步 API，加 timeout / fallback（已保留同步 API）
第 2 階段：FastAPI BackgroundTasks + 記憶體 job 狀態（已完成第一版，已加 timeout / cleanup）
第 3 階段：Redis + Celery/RQ + PostgreSQL job 狀態
第 4 階段：圖片改 object storage，API 只傳 imageId/url
```

### 多執行緒 / 多 worker TODO

- 優先在後端處理多 worker 或背景工作佇列，而不是只放在前端。
- 臉部分析主要耗時點在 `FaceAnalyzer(...).export_json()`，包含 OpenCV、MediaPipe、InsightFace、ONNXRuntime 等 CPU/模型推論流程。
- 展示階段可先用同步 API；多人同時上傳或分析時間變長時，改成 job queue 流程，避免單一請求長時間佔住 API worker。
- 可評估啟動多個 Uvicorn workers，或導入 Redis + Celery/RQ，把臉部分析任務交給背景 worker 執行。
- 前端 Web Worker 主要用來改善圖片壓縮、轉檔、資料包封裝時的 UI 卡頓；真正影響分析吞吐量的部分仍以後端 worker 為主。

## analysisPackage 資料包格式

`analysisPackage` 是所有端共同交換的核心資料格式。

臉部分析端輸出 `faceAnalysis`，Ollama 寫入 `generativeText`，Replicate 寫入 `render`，商品端寫入 `recommendations`，資料庫端儲存紀錄。

```json
{
  "id": "AN-xxx",
  "schemaVersion": "2026-06-v1",
  "mode": "BASIC",
  "client": "web | ios",
  "userId": null,
  "status": "completed",
  "createdAt": "...",
  "updatedAt": "...",
  "images": {
    "front": {
      "originalName": "photo.jpg",
      "originalType": "image/jpeg",
      "originalSize": 1234567,
      "compressedImageUrl": null,
      "compressedDataUrl": "base64-for-package",
      "compressedWidth": 1024,
      "compressedHeight": 1024
    }
  },
  "faceAnalysis": {
    "version": "BASIC",
    "faceShape": "oval",
    "browShape": "curved",
    "eyeShape": "peach_blossom",
    "noseFront": "standard",
    "lipShape": "smile",
    "skinTone": {
      "season": "spring",
      "level": "白皙自然色",
      "lab": { "L": 70, "a": 10, "b": 14 },
      "labSource": "正面+側面平均"
    },
    "lipLab": { "L": 40, "a": 20, "b": 10 },
    "symmetry": {
      "score": 82,
      "eyeOpenRatio": 0.95,
      "noseDeviation": 0.02,
      "mouthSymmetry": 0.98
    },
    "noseSide": null,
    "sidePhotoUsed": true,
    "proStatus": {
      "多角度照片": "已接收，膚色已雙角度平均",
      "臉部對稱性": "已計算",
      "鼻型精細分類": "需 70-90° 側面輪廓照"
    },
    "raw": {
      "臉型": "鵝蛋臉",
      "眉型": "彎月眉",
      "眼型": "桃花眼",
      "鼻型": "標準鼻",
      "嘴型": "微笑唇",
      "膚色": { "四季型": "春季", "膚色分級": "白皙自然色", "LAB": {}, "LAB來源": "正面+側面平均" },
      "嘴唇_LAB": {},
      "臉部對稱性": {},
      "精細分析狀態": {}
    }
  },
  "generativeText": {
    "status": "pending | completed | failed",
    "provider": "ollama",
    "model": "gemma3 / llava",
    "suggestion": null,
    "error": null
  },
  "render": {
    "status": "pending | completed | failed",
    "provider": "replicate",
    "replicateTempUrl": null,
    "afterImageUrl": null,
    "savedImageId": null,
    "error": null
  },
  "recommendations": {
    "products": [],
    "tips": [],
    "ads": []
  }
}
```

## 各端串接責任

| 端點 / 組別 | 接誰的 API | 輸入 | 輸出 |
|---|---|---|---|
| Web 前端 | Face API、Ollama API、Render API、Product API、DB API | 照片、使用者操作、analysisPackage | 畫面顯示、收藏、歷史紀錄 |
| iOS App | 同 Web，共用 Face API | 照片、使用者操作 | App 畫面、analysisPackage |
| Face Analysis API | 可獨立，也可後續接 Package Builder | front / left45 / right45 / side | faceAnalysis JSON / analysisPackage |
| Ollama 文字建議端 | 接 analysisPackage 或 faceAnalysis | faceAnalysis、style、userNote | generativeText.suggestion |
| Replicate 渲染端 | 接 analysisPackage | compressedImage、faceAnalysis、generativeText、style | render.afterImageUrl |
| 商品推薦端 | 接 analysisPackage 或 faceAnalysis + style | faceAnalysis、skinTone、style、suggestion | recommendations.products |
| PostgreSQL API | 接前端或後端紀錄 | user、favorite、analysisPackage、generatedImage metadata | 資料庫 id / 查詢結果 |

## 使用者流程

```txt
使用者開啟 Web / iOS
→ 登入 / 註冊 / 訪客模式
→ 選 BASIC 或 PRO
→ 上傳照片 / 拍照
→ 送出分析
→ 等待分析狀態 queued → processing → completed
→ 顯示臉部分析結果
→ 選擇妝容風格
→ 取得 Ollama 文字建議
→ 送 Replicate 產生妝後圖片
→ 顯示妝容建議 + 渲染後照片 + 商品推薦
→ 收藏商品 / 儲存分析紀錄 / 查看歷史紀錄
```

## 系統流程

```txt
使用者
  ├─ Web Frontend
  └─ iOS App
       ↓
Face Analysis API
  ├─ BASIC：正面照分析
  ├─ PRO：多角度照片入口
  └─ 產生 faceAnalysis JSON
       ↓
Package Builder
  └─ 建立 analysisPackage
       ├─ Ollama Suggestion API
       │    └─ 回傳 generativeText.suggestion
       ├─ Replicate Render API
       │    └─ 回傳 render.afterImageUrl
       ├─ Product Recommendation API
       │    └─ 回傳 recommendations.products
       └─ PostgreSQL API
            └─ 儲存會員、收藏、分析紀錄、生成圖片 metadata
```

## BASIC 資料集與後續模型

BASIC 先集中在正面照。

目前已從 CelebA `celeba_raw/img_align_celeba/img_align_celeba` 先篩出 500 張 BASIC 可用正面圖：

```txt
data/basic_usable/raw_images/          BASIC 可用圖
data/basic_usable/labels.csv           待人工標註欄位
data/basic_usable/label_map.json       標籤選項
data/basic_usable/split.csv            train 400 / val 100
data/basic_usable/selection_manifest.csv
data/basic_usable/rejected.csv
data/basic_usable/auto_labels_basic.csv   BASIC 規則預標註
data/basic_usable/auto_label_summary.json 預標註統計
data/basic_usable/needs_review.csv        預標註失敗/需人工複核清單
data/basic_usable/review_queue.csv        人工複核決策表
data/basic_usable/review_sheets/          人工複核預覽圖
data/basic_usable/LABELING_GUIDE.md       人工標註指南
data/basic_usable/dataset_report.md       資料集狀態報告
data/basic_usable/basic_usable_preview.jpg
```

最終資料策略：

```txt
dataset/
  basic/
    raw_images/
    images/
    labels.csv
    label_map.json
```

`labels.csv` 欄位：

```csv
image_id,file_path,face_shape,nose_front,eye_shape,brow_shape,lip_shape,quality,note
```

每類目標：

```txt
每個形狀至少 50 筆有效標籤
```

建議 raw images：

```txt
先收 500 張正面臉圖
```

因為會剔除：

```txt
模糊
側臉
遮臉
多人合照
過度美顏
低解析度
unknown
```

最終模型方向：

```txt
Input: 320x320 正面臉圖
Backbone: EfficientNet-B0 或 MobileNetV3
Outputs:
  face_shape head
  nose_front head
  eye_shape head
  brow_shape head
  lip_shape head
```

第一階段不急著訓練完整模型，先用標註資料校正目前規則法與 threshold。

## BASIC 分類閾值校正紀錄

### 問題發現（分析 basic_face_analysis.csv，3400 筆，2333 筆成功）

| 特徵 | 修正前分佈 | 問題 |
|------|-----------|------|
| 眉型 - 彎月眉 | 94.5% | 幾乎所有人都被判為彎月眉 |
| 眉型 - 標準眉 | 2.1% | 應為最大宗，實際卻幾乎沒有 |
| 眉型 - 一字眉 | 0% | 完全消失 |
| 臉型 - 長形臉 | 0.1%（3 筆） | 幾乎不出現 |
| 臉型 - 心形臉/菱形臉/梯形臉 | 0% | 條件過嚴，從未觸發 |

### 根本原因

**眉型（`get_eyebrow_shape`）**

`arch_ratio` = `(眉頭眉尾連線中點y − 眉峰y) / 眉毛寬度`

只要眉毛有任何弓形，`arch_ratio` 就很容易超過舊閾值 `0.120`，導致彎月眉條件幾乎把所有人吃掉，標準眉與一字眉幾乎無法出現。

**臉型（`get_face_shape`）**

長形臉有兩條判斷路徑，閾值不一致：

- `all_similar` 分支（額頭、顴骨、下顎寬度相近）：`hw >= 1.35` ← 合理
- **顴骨最寬分支（最常見）**：`hw >= 1.45` ← 比其他分支嚴 0.10，導致絕大多數臉型進到這裡後判不出長形臉

### 修正內容（`Face_analyzer_BASIC.py`，原始檔備份為 `.bak`）

**眉型閾值**

```python
# 修正前
if abs(tail_ratio) < 0.045 and arch_ratio < 0.080: return "一字眉"
if tail_ratio > 0.105:                             return "落尾眉"
if arch_ratio > 0.120 and abs(tail_ratio) < 0.110:  return "彎月眉"
return "標準眉"

# 修正後
if abs(tail_ratio) < 0.060 and arch_ratio < 0.095: return "一字眉"
if tail_ratio > 0.100:                            return "落尾眉"
if arch_ratio > 0.175 and abs(tail_ratio) < 0.115: return "彎月眉"
return "標準眉"
```

| 規則 | 閾值變化 | 目的 |
|------|---------|------|
| 一字眉 | `0.045/0.080` → `0.060/0.095` | 放寬，讓平眉可進入 |
| 落尾眉 | `> 0.105` → `> 0.100` | 微調 |
| **彎月眉** | **`arch > 0.120`** → **`arch > 0.175`** | 核心修正，只有明顯高弓眉才判 |

**臉型閾值**

```python
# 修正前（顴骨最寬分支）
if hw >= 1.45: return "長形臉"

# 修正後（與 all_similar 分支統一）
if hw >= 1.35: return "長形臉"
```

### 第二次校正（2026-06-19）—— 更換 Metric

第一次校正（閾值 0.120→0.175）無效，原因是：MediaPipe landmark **105/334** 是眉骨脊（brow ridge, 骨骼），不是實際眉毛的弓頂。對 CelebA 100 張量測發現，舊 arch_ratio 全部落在 [0.23, 0.31]，任何閾值都無法有效分類。

改用眉毛輪廓 5 點（`46/53/52/65/55` 左眉，`276/283/282/295/285` 右眉）的最高點（min-y）作為弓頂，並重新校正閾值：

```python
# 修正後（眉毛輪廓最高點 + 校正閾值）
if tail_ratio > 0.100:                               return "落尾眉"
if arch_ratio < 0.115 and abs(tail_ratio) < 0.080: return "一字眉"
if arch_ratio > 0.155 and abs(tail_ratio) < 0.115: return "彎月眉"
return "標準眉"
```

新 arch_ratio 分佈（CelebA 100 張）：[0.096, 0.192]，mean=0.139，Q1=0.125，Q3=0.154。

| 類別 | 閾值 | 預估比例 |
|------|------|------|
| 落尾眉 | tail > 0.100 | ~7% |
| 一字眉 | arch < 0.115 & abs(tail) < 0.080 | ~12% |
| 彎月眉 | arch > 0.155 & abs(tail) < 0.115 | ~22% |
| 標準眉 | 其餘 | ~60% |

**長形臉（hw）**：CelebA 對齊圖 hw 全部在 [1.08, 1.25]，長形臉閾值 1.35 超出資料集範圍，是資料集裁切對齊造成的特性，不修改閾值（閾值對真實使用者照片仍有效）。

### 預期效果

- 彎月眉從 ~95% 降至 ~22%，標準眉恢復為最大宗（~60%），一字眉恢復出現（~12%）
- 長形臉因 CelebA 資料集特性維持 0%，不影響生產環境判斷

## 後續優先順序

已完成：

- `/v1` Face Analysis API 命名固定
- `analysisPackage` v1 格式固定
- 同步 API 保留，非同步 jobs API 完成第一版
- 前端改為依 API contract 呼叫（async jobs 流程）
- BASIC 分類閾值校正（眉型、臉型）

待完成：

1. ~~將同一個 Docker image 以 `SERVICE_NAME=basic`、`pro` 部署成獨立 HTTPS API~~ **已完成**（Cloud Run face-basic / face-pro）。
2. 設定 `CORS_ORIGINS` 為正式 Web 前端網址；手機原生 App 仍使用相同 API，但需另外實作 token 安全儲存。
3. 建立 API Gateway 或 `api` 子網域，對外固定 `/v1` contract，內部再路由到 BASIC、PRO、suggestion。
4. Ollama 改為雲端可連線的模型端點，金鑰放 Secret Manager，不寫入 Git 或 App。
5. 會員登入改為 JWT / refresh token；會員、收藏、購物車、分析紀錄與照片中繼資料存入正式資料庫。
6. 圖片改存物件儲存，補上傳大小限制、格式驗證、刪除期限、隱私同意與資料刪除 API。
7. jobs 升級為 Redis + Celery/RQ，並加入 rate limit、監控、錯誤追蹤與正式環境 smoke test。
8. 重新對 `data/basic_usable/raw_images` 跑閾值校正後的分類，確認分佈是否改善。
9. PRO 側面鼻型精細分類需 70–90° 輪廓照，目前列為未來展望。

## API 最低規則

每個服務都必須提供：

```txt
GET /health
正式 endpoint
request 範例
response 範例
error response 範例
是否需要 token
圖片欄位格式說明
```

固定規則：

- 前端不直接連 PostgreSQL。
- 前端不直接連 Ollama 11434。
- Replicate 端不可只回臨時 URL，必須回保存後的永久 `afterImageUrl`。
- 所有 response 都要有 `status`。
- 錯誤 response 要有 `error.message`。
- 圖片欄位要明確說明是 File、base64、DataURL 還是 URL。
