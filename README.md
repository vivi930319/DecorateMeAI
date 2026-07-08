# Decorate Me - Face Analysis API

本分支負責 **臉部分析模組**。此模組需要獨立成 API，讓網頁版前端與未來 iOS App 都能共用同一套臉部分析能力。

---

## 2026-07-08 資安收尾（本輪）

- **render 服務加 API key 保護**：`replicate_render_api.py` 的 `/render` 需帶 `X-API-Key`（環境變數 `RENDER_API_KEY`），擋掉直接掃 Cloud Run URL 無限燒 Replicate 錢的濫用。實測未帶/錯 key 回 `401`、`/health` 回 `api_key_required: true`。前端 `config.local.js` 帶 `renderApiKey`，Cloud Run 已設同值環境變數。
- **前端管理員身分收斂**：`AdminStore.isAdminProfile()` 移除「任何 `admin@` 開頭 email 都算管理員」的寬鬆規則，改以資料庫回傳的 `role`/`level` 為準（保留明確白名單當快取）。
- **`config.local.js` 移出版控**：加入 `.gitignore`、新增 `config.local.example.js` 範本，避免 API 金鑰進 git 歷史。
- **收藏頁臨時網址提示**：舊版收藏若圖片是 `replicate.delivery` 臨時網址，卡片上顯示「可能已失效」。
- 完整體檢見 `專案體檢與缺口報告.md`；資料庫端待辦見 `00_資料庫整合_請先讀我_READ_FIRST.md`。

## 2026-07-08 自動檢查摘要

- 重新讀取本機 `README.md`、`TODO.txt` 與前端 `C:\Users\isach\OneDrive\桌面\web_frontend\README.md`。
- 後端程式碼與設定檔目前仍包含：
  - BASIC / PRO `/health`
  - BASIC / PRO `/v1/face/analyze/*`
  - BASIC / PRO 非同步 jobs API
  - BASIC `/v1/face/pose`
  - `Dockerfile` / `.dockerignore` / `docker-compose.yml`
- `.venv` 重新檢查：
  - `python -m py_compile Face_analyzer_BASIC.py Face_analyzer_PRO.py Ollama_suggestion.py backend_smoke_test.py ollama_suggestion_smoke_test.py analysis_package.py replicate_render.py replicate_render_api.py job_store.py`：通過
  - `python -m pip check`：通過
- 前端重新檢查：
  - `node --check js/api.js js/data.js js/router.js`：通過
  - `node frontend_smoke_check.js`：通過
- `docker compose config`：可正常解析
- 今日 live / cloud 狀態：
  - `GET http://127.0.0.1:8001/health`：連線被拒
  - `GET http://127.0.0.1:8002/health`：連線被拒
  - `GET http://127.0.0.1:8010/health`：連線被拒
  - `GET https://face-basic-258021445391.asia-east1.run.app/health`：`200 OK`
  - `GET https://face-pro-258021445391.asia-east1.run.app/health`：`200 OK`
  - `GET https://replicate-render-258021445391.asia-east1.run.app/health`：`200 OK`
  - `GET https://morning-deeper-kick-medium.trycloudflare.com/health`：`403 Forbidden`
  - `POST https://morning-deeper-kick-medium.trycloudflare.com/suggest`（帶 `X-API-Key`）可到達，但最小測試因 payload 不完整回 `400`
  - `GET https://purpose-violin-conflict-header.trycloudflare.com/health`：`200 OK`
  - `POST https://purpose-violin-conflict-header.trycloudflare.com/recommend-products`（帶 LAB 測試資料）：`200 OK`
  - `POST https://purpose-violin-conflict-header.trycloudflare.com/api/login`：`400`
- 這次確認到的主要差異：
  - 前端 `config.local.js` 現在實際使用的 `memberDatabaseUrl` / `productUrl` 是 `https://purpose-violin-conflict-header.trycloudflare.com`，昨日文件中仍引用舊的 `div-oct-deposits-acer` 已過時
  - `memberDatabase` / `product` 目前不是 DNS 失敗，而是可到達狀態；阻塞點回到註冊 csrf 與後續正式串接
  - `textSuggestion` 仍不是整條服務掛掉，而是公開 `/health` 需要權限；帶 key 的 `/suggest` 可以到達
  - `job_store.py` 仍是 Firestore 共用 job store；正式多 worker / queue 仍未落地
- 目前新的主要阻塞：
  - 本機 `8001` / `8002` / `8010` 今天都沒有常駐服務，展示前必須先用 `.venv` 或 `start_full_stack_local.bat` 重啟
  - `backend_smoke_test.py` 仍失敗在 BASIC `/v1/face/pose`，原因是本機 `8001` 沒有服務
  - `textSuggestion` 對外 `/health` 目前不可直接拿來當 team health check 基準，文件需改成以 `/suggest` 實測或請組員補開放健康檢查
  - Redis / Celery / RQ 或其他正式 queue 方案仍未落地
- 目前版本控制狀態：
  - `PythonProject12` 是 Git repo，今天沒有新的未追蹤專案檔
  - `web_frontend` 是獨立 Git repo，不是桌面 repo；目前只有 `js/api.js` 有未提交修改

---

## 2026-07-07 自動檢查摘要

- 重新讀取本機 `README.md`、`TODO.txt` 與前端 `C:\Users\isach\OneDrive\桌面\web_frontend\README.md`。
- 後端程式碼與設定檔目前仍包含：
  - BASIC / PRO `/health`
  - BASIC / PRO `/v1/face/analyze/*`
  - BASIC / PRO 非同步 jobs API
  - BASIC `/v1/face/pose`
  - `Dockerfile` / `.dockerignore` / `docker-compose.yml`
- `.venv` 重新檢查：
  - `python -m py_compile Face_analyzer_BASIC.py Face_analyzer_PRO.py Ollama_suggestion.py backend_smoke_test.py ollama_suggestion_smoke_test.py analysis_package.py replicate_render.py replicate_render_api.py job_store.py`：通過
  - `python -m pip check`：通過
- 前端重新檢查：
  - `node --check js/api.js js/data.js js/router.js`：通過
  - `node frontend_smoke_check.js`：通過
- `docker compose config`：可正常解析
- 今日 live / cloud 狀態：
  - `GET http://127.0.0.1:8001/health`：連線被拒
  - `GET http://127.0.0.1:8002/health`：連線被拒
  - `GET http://127.0.0.1:8010/health`：連線被拒
  - `GET https://face-basic-258021445391.asia-east1.run.app/health`：`200 OK`
  - `GET https://face-pro-258021445391.asia-east1.run.app/health`：`200 OK`
  - `GET https://replicate-render-258021445391.asia-east1.run.app/health`：`200 OK`
  - `GET https://morning-deeper-kick-medium.trycloudflare.com/health`：`403 Forbidden`
  - `POST https://morning-deeper-kick-medium.trycloudflare.com/suggest`（帶 `X-API-Key`）可到達，最小測試回 `422 VALIDATION_ERROR`
  - `GET https://div-oct-deposits-acer.trycloudflare.com/health`：DNS 無法解析
- 這次確認到的主要差異：
  - `replicate-render` Cloud Run `/health` 現在已回 `storage_configured=true`，永久 `afterImageUrl` 的部署阻塞已解除
  - 前端 `memberDatabaseUrl` / `productUrl` 目前指向同一個 Cloudflare URL，但今天 DNS 無法解析，不能再視為可用整合基準
  - `textSuggestion` 仍不是整條服務掛掉，而是公開 `/health` 需要 API key；實際 `/suggest` 仍可到達
  - `job_store.py` 仍是 Firestore 共用 job store；正式多 worker / queue 仍未落地
- 目前新的主要阻塞：
  - 本機 `8001` / `8002` / `8010` 今天都沒有常駐服務，展示前必須先用 `.venv` 或 `start_full_stack_local.bat` 重啟
  - `memberDatabase` / `product` Cloudflare URL 今天 DNS 無法解析，會員 / 商品正式串接暫時無法驗證
  - `textSuggestion` 對外 `/health` 目前不可直接拿來當 team health check 基準，文件需改成以 `/suggest` 實測或請組員補開放健康檢查
  - Redis / Celery / RQ 或其他正式 queue 方案仍未落地
- 目前版本控制狀態：
  - `PythonProject12` 是 Git repo，今天沒有新的未追蹤專案檔；未提交變更包含 `.dockerignore`、`.gitignore`、`Dockerfile`、`Face_analyzer_BASIC.py`、`Face_analyzer_PRO.py`、`Ollama_suggestion.py`、`README.md`、`analysis_package.py`、`backend_smoke_test.py`、`docker-compose.yml`、`job_store.py`、`replicate_render.py`、`requirements.txt` 等
  - 前端 `web_frontend` 是獨立 Git repo，目前已有未提交修改 `config.local.js`、`css/main.css`、`firebase.json`、`js/api.js`、`js/router.js`、`pages/profile.html`，今天沒有新的未追蹤重要專案檔

---

## 2026-07-06 自動檢查摘要

- 重新讀取本機 `README.md`、`TODO.txt` 與前端 `C:\Users\isach\OneDrive\桌面\web_frontend\README.md`。
- 後端程式碼與設定檔目前仍包含：
  - BASIC / PRO `/health`
  - BASIC / PRO `/v1/face/analyze/*`
  - BASIC / PRO 非同步 jobs API
  - BASIC `/v1/face/pose`
  - `Dockerfile` / `.dockerignore` / `docker-compose.yml`
- `.venv` 重新檢查：
  - `python -m py_compile Face_analyzer_BASIC.py Face_analyzer_PRO.py Ollama_suggestion.py backend_smoke_test.py ollama_suggestion_smoke_test.py analysis_package.py replicate_render.py replicate_render_api.py job_store.py`：通過
  - `python -m pip check`：通過
- 前端重新檢查：
  - `node --check js/api.js js/data.js js/router.js`：通過
  - `node frontend_smoke_check.js`：通過
- 今日 live / cloud 狀態：
  - `GET http://127.0.0.1:8001/health`：連線被拒
  - `GET http://127.0.0.1:8002/health`：連線被拒
  - `GET http://127.0.0.1:8010/health`：連線被拒
  - `GET https://face-basic-258021445391.asia-east1.run.app/health`：`200 OK`
  - `GET https://face-pro-258021445391.asia-east1.run.app/health`：`200 OK`
  - `GET https://replicate-render-258021445391.asia-east1.run.app/health`：`200 OK`
  - `GET https://morning-deeper-kick-medium.trycloudflare.com/health`：`403 Forbidden`
  - `POST https://morning-deeper-kick-medium.trycloudflare.com/suggest`（帶 `X-API-Key`）可到達，最小測試回 `422 VALIDATION_ERROR`
  - `GET https://div-oct-deposits-acer.trycloudflare.com/health`：`200 OK`
  - `POST https://div-oct-deposits-acer.trycloudflare.com/recommend-products`：`400`，但已證明 endpoint 存在
  - `POST https://div-oct-deposits-acer.trycloudflare.com/recommend-products`（帶 LAB 測試資料）：`200 OK`，可回傳商品推薦清單
  - `POST https://div-oct-deposits-acer.trycloudflare.com/api/login`：`400 MISSING_CREDENTIALS`
- 這次確認到的主要差異：
  - 前端目前的 `memberDatabaseUrl` / `productUrl` 已不是失效網址，兩者都指向同一個可達的 Cloudflare service
  - 前端已補上商品 API 回傳格式轉換：`imageUrl/category/brand/matchReason` 會轉成商品卡需要的 `img/cat/brand/desc`
  - 商品頁會優先顯示 `analysisPackage.recommendations.products`；若分析後尚未存到推薦商品，進商品頁時會自動補打一輪 `/recommend-products` 再刷新
  - 商品頁已移除前端內建假商品 demo fallback；商品 API 尚未回來時顯示載入骨架，API 無資料時顯示「目前沒有商品資料」
  - 首頁「為你精選」也改用商品 API 真資料；若商品有熱門度欄位就排序，沒有熱門度時直接取 API 回傳前幾筆
  - `textSuggestion` 目前不是 DNS 失敗，而是 `/health` 對外回 `403`；真正的 `/suggest` 仍可到達
  - `docker compose config` 可正常解析，`Dockerfile`、`.dockerignore`、`docker-compose.yml` 目前一致
  - `job_store.py` 仍是 Firestore 共用 job store；正式多 worker / queue 仍未落地
- 目前新的主要阻塞：
  - 本機 `8001` / `8002` / `8010` 今天都沒有常駐服務，展示前必須先用 `.venv` 或 `start_full_stack_local.bat` 重啟
  - `textSuggestion` 對外 `/health` 目前不可直接拿來當 team health check 基準，文件需改成以 `/suggest` 實測或請組員補開放健康檢查
  - `replicate-render` 目前 `storage_configured=false`，與「必須回保存後永久 `afterImageUrl`」的整合規則仍有落差
  - Redis / Celery / RQ 或其他正式 queue 方案仍未落地
- 目前版本控制狀態：
  - `PythonProject12` 是 Git repo，今天沒有新的未追蹤專案檔；未提交變更包含 `.dockerignore`、`.gitignore`、`Dockerfile`、`Face_analyzer_BASIC.py`、`Face_analyzer_PRO.py`、`Ollama_suggestion.py`、`README.md`、`analysis_package.py`、`backend_smoke_test.py`、`docker-compose.yml`、`job_store.py`、`replicate_render.py`、`requirements.txt` 等
  - 前端 `web_frontend` 是獨立 Git repo，目前已有未提交修改 `config.local.js`、`css/main.css`、`js/api.js`、`js/router.js`、`pages/profile.html`

---

## 2026-07-05 自動檢查摘要

- 重新讀取本機 `README.md`、`TODO.txt` 與前端 `C:\Users\isach\OneDrive\桌面\web_frontend\README.md`。
- 後端程式碼與設定檔目前仍包含：
  - BASIC / PRO `/health`
  - BASIC / PRO `/v1/face/analyze/*`
  - BASIC / PRO 非同步 jobs API
  - BASIC `/v1/face/pose`
- `.venv` 重新檢查：
  - `python -m py_compile Face_analyzer_BASIC.py Face_analyzer_PRO.py Ollama_suggestion.py backend_smoke_test.py ollama_suggestion_smoke_test.py analysis_package.py replicate_render.py replicate_render_api.py job_store.py`：通過
  - `python -m pip check`：通過
- 前端重新檢查：
  - `node --check js/api.js js/data.js js/router.js`：通過
  - `node frontend_smoke_check.js`：通過
- 今日 live / cloud 狀態：
  - `GET http://127.0.0.1:8001/health`：連線被拒
  - `GET http://127.0.0.1:8002/health`：連線被拒
  - `GET http://127.0.0.1:8010/health`：連線被拒
  - `GET https://face-basic-258021445391.asia-east1.run.app/health`：`200 OK`
  - `GET https://face-pro-258021445391.asia-east1.run.app/health`：`200 OK`
  - `GET https://replicate-render-258021445391.asia-east1.run.app/health`：`200 OK`
  - `GET https://ohio-gender-success-excerpt.trycloudflare.com/health`：DNS 無法解析
  - `GET https://vegetation-arguments-final-inspiration.trycloudflare.com/health`：DNS 無法解析
- 這次確認到的主要差異：
  - `backend_smoke_test.py` 已補成會自動從現有資料夾挑 smoke-test 圖片；今天重新執行後會先打到 BASIC `POST /v1/face/pose`，再因本機 `8001` 沒有常駐服務而失敗
  - `job_store.py` 仍是 Firestore 共用 job store；若沒有 Firestore 套件或憑證，才會退回記憶體 store
  - 前端 `config.local.js` 目前的 `textSuggestion` Cloudflare URL 今天也已 DNS 無法解析，`memberDatabase` 預設 fallback 仍是失效網址
  - `replicate-render` Cloud Run `/health` 仍明確回 `storage_configured=false`
- 目前新的主要阻塞：
  - 本機 `8001` / `8002` / `8010` 今天都沒有常駐服務，展示前必須先用 `.venv` 或 `start_full_stack_local.bat` 重啟
  - `memberDatabase` 仍指向失效 Cloudflare URL，今天仍 DNS 無法解析
  - `product` 正式 API 仍未填入前端設定
  - `replicate-render` 目前 `storage_configured=false`，與「必須回保存後永久 `afterImageUrl`」的整合規則仍有落差
- 目前版本控制狀態：
  - `PythonProject12` 是 Git repo，今天沒有新的未追蹤專案檔；未提交變更包含 `.dockerignore`、`.gitignore`、`Dockerfile`、`Face_analyzer_BASIC.py`、`Ollama_suggestion.py`、`README.md`、`analysis_package.py`、`docker-compose.yml`、`job_store.py`、`requirements.txt` 等
  - 前端 `web_frontend` 是獨立 Git repo，目前未追蹤的重要檔案是 `membership_flowchart.drawio`

---

## 2026-07-03 自動檢查摘要

- 重新讀取本機 `README.md`、`TODO.txt` 與前端 `C:\Users\isach\OneDrive\桌面\web_frontend\README.md`。
- 後端程式碼與設定檔目前仍包含：
  - BASIC / PRO `/health`
  - BASIC / PRO `/v1/face/analyze/*`
  - BASIC / PRO 非同步 jobs API
  - BASIC `/v1/face/pose`
- `.venv` 重新檢查：
  - `python -m py_compile Face_analyzer_BASIC.py Face_analyzer_PRO.py Ollama_suggestion.py backend_smoke_test.py ollama_suggestion_smoke_test.py analysis_package.py replicate_render.py replicate_render_api.py job_store.py`：通過
  - `python -m pip check`：通過
- 前端重新檢查：
  - `node --check js/api.js js/data.js js/router.js`：通過
  - `node frontend_smoke_check.js`：通過
- 今日 live / cloud 狀態：
  - `GET http://127.0.0.1:8001/health`：連線被拒
  - `GET http://127.0.0.1:8002/health`：連線被拒
  - `GET http://127.0.0.1:8010/health`：連線被拒
  - `GET https://face-basic-258021445391.asia-east1.run.app/health`：`200 OK`
  - `GET https://face-pro-258021445391.asia-east1.run.app/health`：`200 OK`
  - `GET https://replicate-render-258021445391.asia-east1.run.app/health`：`200 OK`
  - `GET https://ohio-gender-success-excerpt.trycloudflare.com/health`：`200 OK`
  - `GET https://vegetation-arguments-final-inspiration.trycloudflare.com/health`：DNS 無法解析
- 這次確認到的主要差異：
  - `backend_smoke_test.py` 今天失敗在 BASIC `POST /v1/face/pose`，原因是本機 `8001` 沒有常駐服務，不是 Python 語法或套件衝突
  - `job_store.py` 仍是 Firestore 共用 job store；舊文件裡的純記憶體 `_jobs dict` 不應再當現況
  - 前端 `config.local.js` 已改用新的 `textSuggestion` Cloudflare URL，而且今天 `/health` 可達；README 舊的 DNS 失敗描述已過時
  - `replicate-render` Cloud Run `/health` 仍明確回 `storage_configured=false`
- 目前新的主要阻塞：
  - 本機 `8001` / `8002` / `8010` 今天都沒有常駐服務，展示前必須先用 `.venv` 或 `start_full_stack_local.bat` 重啟，再重跑 `backend_smoke_test.py`
  - `memberDatabase` 仍指向失效 Cloudflare URL，今天仍 DNS 無法解析
  - `product` 正式 API 仍未填入前端設定
  - `replicate-render` 目前 `storage_configured=false`，與「必須回保存後永久 `afterImageUrl`」的整合規則仍有落差
- 目前版本控制狀態：
  - `PythonProject12` 是 Git repo，今天沒有新的未追蹤專案檔；既有未提交變更仍包含本機 `README.md` 與 `docker-compose.yml`
  - 前端 `web_frontend` 是獨立 Git repo，目前有已修改的 `config.local.js`、`js/api.js` 與未追蹤 `dev_server.py`

---

## 2026-07-01 自動檢查摘要

- 重新讀取本機 `README.md`、`TODO.txt` 與前端 `C:\Users\isach\OneDrive\桌面\web_frontend\README.md`。
- 後端程式碼與設定檔目前仍包含：
  - BASIC / PRO `/health`
  - BASIC / PRO `/v1/face/analyze/*`
  - BASIC / PRO 非同步 jobs API
  - BASIC `/v1/face/pose`
- `.venv` 重新檢查：
  - `python -m py_compile Face_analyzer_BASIC.py Face_analyzer_PRO.py Ollama_suggestion.py backend_smoke_test.py ollama_suggestion_smoke_test.py analysis_package.py replicate_render.py replicate_render_api.py job_store.py`：通過
  - `python -m pip check`：通過
  - `python ollama_suggestion_smoke_test.py`：通過
  - `python backend_smoke_test.py`：通過
- 前端重新檢查：
  - `node --check js/api.js js/data.js js/router.js`：通過
  - `node frontend_smoke_check.js`：通過
- 今日 live / cloud 狀態：
  - `GET http://127.0.0.1:8001/health`：`200 OK`
  - `GET http://127.0.0.1:8002/health`：`200 OK`
  - `GET http://127.0.0.1:8010/health`：`200 OK`
  - `GET https://face-basic-258021445391.asia-east1.run.app/health`：`200 OK`
  - `GET https://face-pro-258021445391.asia-east1.run.app/health`：`200 OK`
  - `GET https://replicate-render-258021445391.asia-east1.run.app/health`：`200 OK`
  - `GET https://router-identification-compatible-tolerance.trycloudflare.com/health`：DNS 無法解析
- 這次確認到的主要差異：
  - `backend_smoke_test.py` 今天再次完整通過，BASIC `/v1/face/pose`、BASIC / PRO sync 與 async result 都仍符合目前 contract
  - BASIC / PRO async job 狀態仍是 `job_store.py` 的 Firestore 共用實作，不是舊文件裡提到的純記憶體 `_jobs dict`
  - `start_full_stack_local.bat` 已固定使用 `.venv\Scripts\python.exe`，但目前監聽 `8001`、`8002`、`8010` 的實際進程仍是系統 Python `C:\Users\isach\AppData\Local\Programs\Python\Python310\python.exe`
  - `replicate-render` Cloud Run `/health` 仍明確回 `storage_configured=false`
- 目前新的主要阻塞：
  - 本機三支 live port 雖可用，但目前不是由 `.venv` 進程提供服務；展示前仍應先清掉舊進程，再用 `start_full_stack_local.bat` 或 `.venv` 明確重啟
  - Suggestion `/health` 仍回報本機 Ollama `127.0.0.1:11434` 不可達，而且 `fallbackEnabled=false`
  - 前端 `config.local.js` 目前指向的 `textSuggestion` Cloudflare URL 今天已 DNS 無法解析，展示時不能把它當可用正式位址
  - 前端 `memberDatabase` 仍指向 `https://vegetation-arguments-final-inspiration.trycloudflare.com/health`，今天仍 DNS 無法解析
  - `replicate-render` 目前 `storage_configured=false`，與「必須回保存後永久 `afterImageUrl`」的整合規則仍有落差
- 目前版本控制狀態：
  - `PythonProject12` 是 Git repo，本輪除了本機文件外，既有未提交變更還包含 `docker-compose.yml`
  - 前端 `web_frontend` 是獨立 Git repo，目前只有 `dev_server.py` 未追蹤

---

## 2026-06-30 自動檢查摘要

- 重新讀取本機 `README.md`、`TODO.txt` 與前端 `C:\Users\isach\OneDrive\桌面\web_frontend\README.md`。
- 後端程式碼與設定檔目前仍包含：
  - BASIC / PRO `/health`
  - BASIC / PRO `/v1/face/analyze/*`
  - BASIC / PRO 非同步 jobs API
  - BASIC `/v1/face/pose`
- `.venv` 重新檢查：
  - `python -m py_compile Face_analyzer_BASIC.py Face_analyzer_PRO.py Ollama_suggestion.py backend_smoke_test.py ollama_suggestion_smoke_test.py analysis_package.py`：通過
  - `python -m pip check`：通過
  - `python ollama_suggestion_smoke_test.py`：通過
  - `python backend_smoke_test.py`：通過
- 前端重新檢查：
  - `node --check js/api.js js/data.js js/router.js`：通過
  - `node frontend_smoke_check.js`：通過
- 今日 live / cloud 狀態：
  - `GET http://127.0.0.1:8001/health`：`200 OK`
  - `GET http://127.0.0.1:8002/health`：`200 OK`
  - `GET http://127.0.0.1:8010/health`：`200 OK`
  - `GET https://face-basic-258021445391.asia-east1.run.app/health`：`200 OK`
  - `GET https://face-pro-258021445391.asia-east1.run.app/health`：`200 OK`
  - `GET https://replicate-render-258021445391.asia-east1.run.app/health`：`200 OK`
  - `GET https://router-identification-compatible-tolerance.trycloudflare.com/health`：`200 OK`
- 這次確認到的主要差異：
  - BASIC / PRO async job 狀態已不是純記憶體 `_jobs dict`，目前改由 `job_store.py` 使用 Firestore 共用
  - 監聽中的 `8001`、`8002`、`8010` 進程仍是系統 Python `C:\Users\isach\AppData\Local\Programs\Python\Python310\python.exe`，不是 `.venv\Scripts\python.exe`
  - `replicate-render` Cloud Run `/health` 仍明確回 `storage_configured=false`
- 目前新的主要阻塞：
  - PRO live async job 在 `/health` 正常時仍可能卡住或回應過慢，展示前要先清掉舊進程並用 `.venv` 重啟後重跑 `backend_smoke_test.py`
  - Suggestion `/health` 仍回報本機 Ollama `127.0.0.1:11434` 不可達，而且 `fallbackEnabled=false`
  - 前端 `memberDatabase` 仍指向 `https://vegetation-arguments-final-inspiration.trycloudflare.com/health`，今天仍 DNS 無法解析
  - `replicate-render` 目前 `storage_configured=false`，與「必須回保存後永久 `afterImageUrl`」的整合規則仍有落差
- 目前版本控制狀態：
  - `PythonProject12` 是 Git repo，本輪有本機文件更新
  - 前端 `web_frontend` 是獨立 Git repo，目前只有 `dev_server.py` 未追蹤

---

## 2026-06-29 自動檢查摘要

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
  - `GET https://replicate-render-258021445391.asia-east1.run.app/health`：`200 OK`
  - `GET https://router-identification-compatible-tolerance.trycloudflare.com/health`：`200 OK`
- 這次確認到的主要差異：
  - 前端 `config.local.js` 的 `textSuggestionUrl` 已不是舊的 `possibly-polyester-bargains-transcript`，目前新 Cloudflare URL 可正常回 `200 OK`
  - `replicate-render` Cloud Run `/health` 已可達，但明確回 `storage_configured=false`
  - `docker-compose.yml` 的 optional `replicate_render` 已對齊 `Dockerfile.render`，目前會啟動 `replicate_render_api:app`
- 目前新的主要阻塞：
  - 監聽中的 `8001`、`8002`、`8010` 進程仍是系統 Python `C:\Users\isach\AppData\Local\Programs\Python\Python310\python.exe`，不是 `.venv\Scripts\python.exe`
  - Suggestion `/health` 仍回報本機 Ollama `127.0.0.1:11434` 不可達，而且 `fallbackEnabled=false`
  - 前端 `memberDatabase` 仍指向 `https://vegetation-arguments-final-inspiration.trycloudflare.com/health`，今天仍 DNS 無法解析
  - `replicate-render` 目前 `storage_configured=false`，與「必須回保存後永久 `afterImageUrl`」的整合規則仍有落差
- 目前版本控制狀態：
  - `PythonProject12` 是 Git repo，本輪只有本機文件更新
  - 前端 `web_frontend` 是獨立 Git repo，目前只有 `dev_server.py` 未追蹤

---

## 專題剩餘工作與時程估算

### 目前完成狀態

| 模組 | 狀態 |
|------|------|
| 臉部分析 BASIC API（Cloud Run） | ✅ 完成並部署 |
| 臉部分析 PRO API（Cloud Run） | ✅ 完成並部署 |
| Ollama 文字建議服務（組員 Mac + Cloudflare） | ✅ 運作中（依賴組員電腦開著） |
| AI 渲染服務 replicate-render（Cloud Run, flux-kontext-pro） | ✅ 完成並部署 |
| 前端 Web App（Firebase Hosting） | ✅ 完成並部署 |
| 妝容對比頁渲染流程（AI 渲染妝容按鈕） | ✅ 完成 |
| 會員資料庫串接 | ⏳ 等組員提供 URL |
| 商品推薦串接 | ⏳ 等組員提供 URL |

### 剩餘工作清單

**我自己要做：**

1. **Replicate 加付款方式**（0.5 hr）
   - 前往 replicate.com/account/billing 新增信用卡
   - 解除 429 rate limit 後才能實測 AI 渲染效果

2. **實測 AI 渲染品質並調整**（0.5 天）
   - 測試 flux-kontext-pro 渲染是否正確保留人物特徵
   - 視結果調整 prompt 參數（guidance、關鍵詞字典）

3. **Backend BASIC / PRO 分析邏輯調整**（1–3 天，視範圍）
   - 臉部特徵分類閾值微調（眉型、臉型、眼型等）
   - 若需重跑資料集驗證另加時間

4. **串接會員資料庫 + 商品推薦**（1 天，組員提供 URL 後）
   - 前端 `config.local.js` 填入組員 URL
   - 串接登入 / 收藏 / 歷史紀錄 API
   - 串接商品推薦 API

5. **端對端完整測試與 bug 修正**（1–2 天）
   - 完整跑過使用者流程：上傳 → 分析 → 文字建議 → 渲染 → 商品推薦 → 收藏
   - 修正串接後出現的問題

**等組員：**

6. **黃姵錚**：git pull 後重啟 Ollama 服務（streaming 端點）
7. **會員資料庫組員**：提供 Cloud Run / 伺服器 URL + API 規格
8. **商品推薦組員**：提供 Cloud Run / 伺服器 URL + API 規格

### 時程估算

| 工作 | 預估時間 | 依賴 |
|------|---------|------|
| Replicate 加信用卡 + 渲染測試 | 0.5 天 | 無 |
| Backend BASIC / PRO 調整 | 1–3 天 | 無 |
| 串接會員 + 商品資料庫 | 1 天 | 組員提供 URL |
| 端對端測試 + bug 修正 | 1–2 天 | 上述完成後 |
| **總計** | **3.5–6.5 天** | |

樂觀（BASIC/PRO 只是小改）：約 **4 天**。
保守（分析邏輯需重新校正）：約 **1 週**。

### 會員功能升級規劃與進度（2026-07-05）

目標是把目前的會員功能從「登入 / VIP 手動升級 / 本機資料」升級成完整的會員成長系統：簽到、點數、推薦、點數商店、任務中心、會員等級、PRO 付費解鎖與後台管理。

#### 預估工期

| 版本 | 範圍 | 預估時間 | 備註 |
|------|------|---------|------|
| Demo / 原型版 | 前端流程 + localStorage / mock API，可展示主要體驗，付費用模擬付款 | 3–5 天 | 不串正式金流、不做嚴格防作弊 |
| 可串接後端版 | API contract、資料表、前後端串接、後台審核，付款仍可先用 demo 訂單 | 6–9 天 | 需要會員資料庫服務可用 |
| 正式上線版 | 正式金流、自動開通、訂單狀態、權限驗證、防刷推薦、完整測試 | 10–15 天 | 若金流審核或外部 API 卡住會再增加 |

目前如果「全部都做，但付費功能只做 demo」，建議估 **1 週左右** 比較合理；若要正式金流上線版，仍建議抓 **2 週左右** 比較穩。

#### 會員分級權益（2026-07-07 定案並實作）

以「AI 渲染次數」作為分級主錨點（渲染是唯一每次使用都有實際 Replicate 成本的功能），PRO 分析（側臉鼻型）降為 VIP 附贈賣點：

| 權益 | 訪客 | 一般會員（免費註冊） | VIP 會員 |
|------|------|---------------------|----------|
| BASIC 臉部分析 / 妝容文字建議 | ✅ | ✅ | ✅ |
| AI 渲染 | ❌（點按會導向註冊） | 每日 3 次 | 每日 10 次 |
| 收藏 / 歷史紀錄 | ❌ | ✅ | ✅ |
| 點數 / 簽到 / 任務 / 推薦碼 | ❌ | ✅ | ✅ |
| PRO 分析（側臉鼻型） | ❌ | ❌ | ✅（附贈） |

設計原則：
- 銀卡／金卡（`MemberTier`，點數自動升級）是**活躍度徽章**，只給裝飾性獎勵，不是權益層；VIP 才是付費/核發的權益層。兩套系統並存不混用。
- VIP 刻意設「每日 10 次」而非不限次數，守住 Replicate 成本上限；管理員與後台單獨勾選 `unlimitedRender` 的帳號不受限（內部測試用）。
- 實作位置：`js/api.js` `AdminStore`（`_dailyRenderLimit: 3`、`_vipDailyRenderLimit: 10`、`getDailyRenderLimit()`、`canRender()` 擋訪客），`js/router.js` 對比頁渲染按鈕（訪客觸發 `promptGuestAuth`）與會員中心等級卡片文案。

#### 功能進度

| 功能 | 狀態 | 目前進度 | 下一步 |
|------|------|---------|--------|
| 會員登入 / 註冊 | 🟡 部分完成 | `memberDatabaseUrl` 已可達（`purpose-violin-conflict-header`，2026-07-07 更新；tunnel 網址組員重啟就會換），`/api/login` 錯誤處理正常；但 `/api/register` 一直回傳 `400 MISSING_FIELDS`，懷疑跟網頁表單的 `csrf_token` 有關 | 已整理問題訊息要問組員，回覆前無法實測完整註冊流程 |
| 管理員升級 VIP | 🟡 部分完成 | 前端後台已有介面概念；`MEMBER_DATABASE_INTEGRATION_SPEC.md` 第 3 節已定義 `PATCH /api/members/{email}`（level/status） | 後端補正式權限與資料庫寫入 |
| 每日打卡集點 | 🟢 Demo 完成 | `MemberRewards.checkin()`（`js/api.js`），前端 localStorage，每日 +10 點 | 之後接資料庫時把邏輯搬到後端 |
| 連續簽到獎勵 | 🟢 Demo 完成（2026-07-06） | 加入 streak 天數追蹤，3/7/14/30 天分別加碼 +5/+20/+40/+100，中斷自動歸零重算 | 之後接資料庫時把邏輯搬到後端 |
| 點數紀錄 ledger | 🟢 Demo 完成 + 🟡 正式規格已發 | 前端 `MemberRewards.ledger()` 已可用；`MEMBER_DATABASE_INTEGRATION_SPEC.md` 第 8 節已定義正式 `points_transactions` 表 | 等資料庫組員回覆或建好 |
| 推薦碼 / 推薦集點 | 🟢 Demo 完成（2026-07-06） | 註冊時自動綁定推薦人（`Referral.applyReferral()`），完成註冊即發 50 點給推薦人，會員中心顯示專屬推薦碼與已推薦人數 | 之後接資料庫時把邏輯搬到後端 |
| 推薦防刷 | ⚪ 未開始 | 目前只擋「自己推薦自己」和「同帳號重複套用」 | 擋重複帳號、同裝置異常等更嚴格的防刷規則 |
| 點數換主題 | ⚪ 未開始 | 目前只有流程圖設計 | 建立 redeem API、主題商品表與已解鎖清單 |
| 點數商店擴充 | ⚪ 未開始 | 尚未實作 | 增加頭像框、背景、功能券、PRO 折扣券 |
| 任務中心 | 🟢 Demo 完成（2026-07-06） | `Tasks` 模組（`js/api.js`）：新手任務（首次分析/收藏/推薦）+ 每日打卡任務，防重複領取 | 之後可再加每週任務；接資料庫時把邏輯搬到後端 |
| 會員等級 | 🟢 Demo 完成（2026-07-06） | `MemberTier` 模組：用累計點數自動判定一般/銀卡(100)/金卡(300)，VIP/管理員仍走後台手動核發 | 之後接資料庫時把邏輯搬到後端 |
| PRO 付費解鎖 Demo | 🟢 Demo 完成（2026-07-06） | `ProSubscription` 模組：月費/年費方案，`purchase()` 直接視為付款成功並自動開通 VIP，訂單寫入 `beautyProOrders` | 之後接資料庫時把邏輯搬到後端，接正式金流 |
| PRO 到期 / 續費 Demo | 🟢 Demo 完成（2026-07-06） | 到期日追蹤、續約會從現有到期日累加天數、`syncExpiry()` 到期自動退回一般會員 | 之後接資料庫時把邏輯搬到後端 |
| 後台會員管理 | 🟡 規格已發 | `MEMBER_DATABASE_INTEGRATION_SPEC.md` 第 7 節已補 role / allowedPages 擴充、操作紀錄 audit-log、商品管理 CRUD 規格 | 等資料庫組員回覆或建好，之後接回 `AdminStore` |

**2026-07-06 補充**：`member_database` 服務已上線，`config.local.js` 的 `memberDatabaseUrl` 與 `productUrl` 都指向這個網址（同一服務同時處理會員與商品推薦）。網址是 Cloudflare Tunnel，組員重啟後會變動，目前最新是 `https://purpose-violin-conflict-header.trycloudflare.com`（2026-07-07 更新；`threshold-commitments-jet-gabriel`、`div-oct-deposits-acer` 均已失效）。已針對後台管理與點數系統的缺口，在 `MEMBER_DATABASE_INTEGRATION_SPEC.md` 補上第 7、8 節規格書。目前卡點是 `/api/register` 一直回傳 `MISSING_FIELDS`，懷疑要 `csrf_token`，已整理問題待問組員，回覆前這條線的後續整合都無法真正實測。

#### 建議開發順序

1. **會員資料庫正式串接**：先讓登入、註冊、會員等級可真正同步。
2. **點數 ledger**：所有打卡、推薦、兌換、任務都依賴這個核心。
3. **每日打卡 + 連續簽到**：最快讓會員中心變得有互動。
4. **點數商店 + 主題解鎖**：讓點數有用途。
5. **推薦碼自動化**：先做自動綁定與發點，再補防刷。
6. **會員等級 + 任務中心**：把留存玩法整理成一套成長系統。
7. **PRO 付費 Demo 與自動開通**：先做模擬付款成功、訂單紀錄、PRO 權限開通；正式金流等展示後再接。

### 使用者完整流程（目標）

```
使用者開啟 https://decorate-me.web.app
→ 登入 / 訪客模式
→ 上傳照片（亮度調整）
→ 選 BASIC 或 PRO
→ 臉部分析（Cloud Run）→ 顯示臉型、眼型、膚色等
→ 選擇妝容風格
→ Ollama 文字建議（組員 Mac）
→ AI 渲染妝容（Replicate flux-kontext-pro）
→ 妝容前後對比
→ 商品推薦（組員 API）
→ 收藏 / 歷史紀錄（會員資料庫）
```

### 服務架構（現況）

| 服務 | URL / 位置 | 狀態 |
|------|-----------|------|
| 前端 | https://decorate-me.web.app | ✅ 雲端 |
| face-basic | https://face-basic-258021445391.asia-east1.run.app | ✅ 雲端 |
| face-pro | https://face-pro-258021445391.asia-east1.run.app | ✅ 雲端 |
| ollama_suggestion | Cloudflare Tunnel（黃姵錚 Mac） | ✅ 依賴組員電腦 |
| replicate-render | Cloud Run asia-east1 | ✅ 雲端 |
| member_database | 待定 | ⏳ 等組員 |
| product_recommend | 待定 | ⏳ 等組員 |

**Google Cloud 費用**：目前花費 $0（全部在免費額度內），預計試用期結束後每月 ~$0.21 USD。

---

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
- `MAX_IMAGE_SIZE` 可用環境變數調整，預設 1280；`INSIGHT_DET_SIZE` 預設 512
- `numpy<2` 與 `mediapipe==0.10.21` 相容設定
- BASIC / PRO 非同步 jobs API 第一版
- BASIC / PRO jobs 已加入 timeout、保留時間與記憶體數量上限
- Docker Compose 同時啟動 BASIC 與 PRO 服務
- Docker Compose 可啟動 Ollama 文字建議本機轉接服務
- BASIC/PRO 主流程不再需要 ONNX 眼皮模型
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

> 請一律用 `.venv` 內的 Python 啟動，不要用系統 Python，否則可能缺 `uvicorn`、`insightface`。

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

目前非同步 Job API 使用 FastAPI `BackgroundTasks` 觸發背景工作，job 狀態由 `job_store.py` 寫入 Firestore 共用；若缺少 Firestore 環境才退回單機記憶體描述已不再符合目前主流程。後續正式部署時仍規劃再升級 Redis + Celery/RQ。

目前 job 狀態已有展示階段保護：

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
第 2 階段：FastAPI BackgroundTasks + Firestore 共用 job 狀態（已完成第一版，已加 timeout / cleanup）
第 3 階段：Redis + Celery/RQ + PostgreSQL job 狀態
第 4 階段：圖片改 object storage，API 只傳 imageId/url
```

### 多執行緒 / 多 worker TODO

- 優先在後端處理多 worker 或背景工作佇列，而不是只放在前端。
- 臉部分析主要耗時點在 `FaceAnalyzer(...).export_json()`，包含 OpenCV、MediaPipe、InsightFace 等 CPU/模型推論流程。
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

## BASIC 分類標準

目前 BASIC 訓練資料以 `Group_yun` 為唯一標準，資料位於 `data/basic_full/grouped`。

- 臉型：心形臉、方形臉、長形臉、圓形臉、鵝蛋臉
- 眉型：一字眉、落尾眉、彎月眉
- 眼型：下垂眼、丹鳳眼、杏仁眼、桃花眼、細長眼、圓眼、瞇縫眼
- 鼻型：窄鼻、寬鼻、標準鼻
- 嘴型：花瓣唇、厚唇、微笑唇、薄唇、M型唇

舊分類、空分類與眼皮分類不再使用；資料整理工具遇到空標籤會跳過，不會建立 `_unknown`。

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
