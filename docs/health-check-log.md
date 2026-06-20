# Decorate Me Health Check Log

最後更新：2026-06-20

## 2026-06-20 實測

| Service | URL | 結果 | 備註 |
|---|---|---|---|
| Face BASIC | `http://127.0.0.1:8001/health` | `200 OK` | `status=ok`，jobs/limits 皆有回傳，但 live async result schema 與工作區最新程式碼不一致 |
| Face PRO | `http://127.0.0.1:8002/health` | `200 OK` | `status=ok`，`/health` 可用 |
| Text Suggestion | `http://127.0.0.1:8010/health` | `200 OK` | suggestion 服務可用，但內部仍回報 Ollama `127.0.0.1:11434` 不可達，現在靠 fallback |
| Member Database | `https://vegetation-arguments-final-inspiration.trycloudflare.com/health` | `failed` | DNS 無法解析，前端目前不應依賴此網址做整合測試 |

## 2026-06-20 補充

- `C:\Users\isach\PycharmProjects\PythonProject12\.venv\Scripts\python.exe -m py_compile Face_analyzer_BASIC.py Face_analyzer_PRO.py Ollama_suggestion.py backend_smoke_test.py ollama_suggestion_smoke_test.py`：通過。
- `C:\Users\isach\PycharmProjects\PythonProject12\.venv\Scripts\python.exe -m pip check`：通過，`requirements.txt` 目前沒有依賴衝突。
- `C:\Users\isach\PycharmProjects\PythonProject12\.venv\Scripts\python.exe ollama_suggestion_smoke_test.py`：通過。
- `node frontend_smoke_check.js`：通過。
- `node --check js/router.js js/api.js js/data.js`：通過。
- 目前監聽中的 `8001`、`8002`、`8010` 進程仍是系統 Python `C:\Users\isach\AppData\Local\Programs\Python\Python310\python.exe`，不是 `.venv\Scripts\python.exe`。
- `C:\Users\isach\PycharmProjects\PythonProject12\.venv\Scripts\python.exe backend_smoke_test.py`：未通過。
  - 失敗點在 BASIC `GET /v1/face/jobs/{jobId}/result`
  - live result 缺少 README / 同步 API 已有的 `臉部對稱性`
  - 代表目前對外服務很可能是舊進程或舊啟動環境，後端需要先清掉舊服務再重啟驗證
- 前端 `web_frontend` 現在已是獨立 Git repo，這項舊版控風險已解除。

## 2026-06-18 實測

| Service | URL | 結果 | 備註 |
|---|---|---|---|
| Face BASIC | `http://127.0.0.1:8001/health` | `200 OK` | `status=ok`，jobs/limits 皆有回傳；`backend_smoke_test.py` 今日同步分析與 async jobs 再次通過 |
| Face PRO | `http://127.0.0.1:8002/health` | `200 OK` | `status=ok`，jobs/limits 皆有回傳；`backend_smoke_test.py` 今日同步分析與 async jobs 再次通過 |
| Text Suggestion | `http://127.0.0.1:8010/health` | `200 OK` | suggestion 服務可用，但內部仍回報 Ollama `127.0.0.1:11434` 不可達，現在靠 fallback |
| Member Database | `https://vegetation-arguments-final-inspiration.trycloudflare.com/health` | `failed` | DNS 無法解析，前端目前不應依賴此網址做整合測試 |

## 2026-06-18 補充

- `C:\Users\isach\PycharmProjects\PythonProject12\.venv\Scripts\python.exe -m py_compile Face_analyzer_BASIC.py Face_analyzer_PRO.py Ollama_suggestion.py backend_smoke_test.py ollama_suggestion_smoke_test.py`：通過。
- `C:\Users\isach\PycharmProjects\PythonProject12\.venv\Scripts\python.exe -m pip check`：通過，`requirements.txt` 目前沒有依賴衝突。
- `C:\Users\isach\PycharmProjects\PythonProject12\.venv\Scripts\python.exe backend_smoke_test.py`：通過，今日自動選到 `data/basic_usable/raw_images/000007.jpg`。
- `C:\Users\isach\PycharmProjects\PythonProject12\.venv\Scripts\python.exe ollama_suggestion_smoke_test.py`：通過。
- `node frontend_smoke_check.js`：通過。
- `node --check js/router.js js/api.js js/data.js`：通過。
- 目前監聽中的 `8001`、`8002`、`8010` 進程皆由系統 Python `C:\Users\isach\AppData\Local\Programs\Python\Python310\python.exe` 啟動，不是 `.venv\Scripts\python.exe`；雖然今天仍可跑，但這是環境漂移風險。
- 前端 `ApiConfig.services` 與後端 port 仍一致：
  - BASIC：`8001`
  - PRO：`8002`
  - textSuggestion：`8010`

## 2026-06-17 實測

| Service | URL | 結果 | 備註 |
|---|---|---|---|
| Face BASIC | `http://127.0.0.1:8001/health` | `200 OK` | 直接 `Invoke-WebRequest` 一度逾時，但 `backend_smoke_test.py` 隨後可正常通過 BASIC health、同步分析與 async jobs，表示服務最終仍可用 |
| Face PRO | `http://127.0.0.1:8002/health` | `200 OK` | `/health` 直接回 `status=ok`，sync / async 也隨 `backend_smoke_test.py` 通過 |
| Text Suggestion | `http://127.0.0.1:8010/health` | `200 OK` | suggestion 服務可用，但內部仍回報 Ollama `127.0.0.1:11434` 不可達，現在靠 fallback |
| Member Database | `https://vegetation-arguments-final-inspiration.trycloudflare.com/health` | `failed` | DNS 無法解析，前端目前不應依賴此網址做整合測試 |

## 2026-06-17 補充

- `C:\Users\isach\PycharmProjects\PythonProject12\.venv\Scripts\python.exe -m py_compile Face_analyzer_BASIC.py Face_analyzer_PRO.py Ollama_suggestion.py backend_smoke_test.py`：通過。
- `C:\Users\isach\PycharmProjects\PythonProject12\.venv\Scripts\python.exe -m pip check`：通過，`requirements.txt` 目前沒有依賴衝突。
- `C:\Users\isach\PycharmProjects\PythonProject12\.venv\Scripts\python.exe backend_smoke_test.py`：通過。
- `node frontend_smoke_check.js`：通過。
- `node --check js/router.js js/api.js js/data.js`：通過。
- 目前監聽中的 `8001`、`8002`、`8010` 進程皆由系統 Python `C:\Users\isach\AppData\Local\Programs\Python\Python310\python.exe` 啟動，不是 `.venv\Scripts\python.exe`；雖然今天仍可跑，但這是環境漂移風險。
- 桌面另有 `C:\Users\isach\OneDrive\桌面\makeup-ai-v2\face_analysis` 舊後端副本，內容仍是單檔 `/analyze` 原型，不能當成目前正式 Face Analysis backend 狀態。

## 2026-06-16 實測

| Service | URL | 結果 | 備註 |
|---|---|---|---|
| Face BASIC | `http://127.0.0.1:8001/health` | `200 OK` | 服務預設未常駐；用 `.venv` 啟動後可正常回 `status=ok` |
| Face PRO | `http://127.0.0.1:8002/health` | `200 OK` | 服務預設未常駐；用 `.venv` 啟動後可正常回 `status=ok` |
| Text Suggestion | `http://127.0.0.1:8010/health` | `200 OK` | 服務預設未常駐；用 `.venv` 啟動後可用，但 Ollama `127.0.0.1:11434` 仍不可達，現在靠 fallback |
| Member Database | `https://vegetation-arguments-final-inspiration.trycloudflare.com/health` | `failed` | DNS 無法解析，前端目前不應依賴此網址做整合測試 |

## 2026-06-16 補充

- `C:\Users\isach\PycharmProjects\PythonProject12\.venv\Scripts\python.exe backend_smoke_test.py`：通過。
- `C:\Users\isach\PycharmProjects\PythonProject12\.venv\Scripts\python.exe ollama_suggestion_smoke_test.py`：通過。
- `node frontend_smoke_check.js`：通過。
- `node --check js/router.js js/api.js js/data.js`：通過。

## 2026-06-15 實測

| Service | URL | 結果 | 備註 |
|---|---|---|---|
| Face BASIC | `http://127.0.0.1:8001/health` | `200 OK` | `status=ok`，jobs/limits 皆有回傳 |
| Face PRO | `http://127.0.0.1:8002/health` | `200 OK` | `status=ok`，jobs/limits 皆有回傳 |
| Text Suggestion | `http://127.0.0.1:8010/health` | `200 OK` | suggestion 服務可用，但 Ollama `127.0.0.1:11434` 不可達，目前靠 fallback |
| Member Database | `https://vegetation-arguments-final-inspiration.trycloudflare.com/health` | `failed` | DNS 無法解析，前端目前不應依賴此網址做整合測試 |

## 補充

- 2026-06-15 已執行 `python backend_smoke_test.py`，BASIC / PRO 同步與非同步 jobs 都通過。
- 2026-06-15 已執行 `python ollama_suggestion_smoke_test.py`，mock / fallback 流程通過。
- 若組員更換 IP、port 或 Cloudflare tunnel，需同步更新 `js/api.js` 與本檔。
