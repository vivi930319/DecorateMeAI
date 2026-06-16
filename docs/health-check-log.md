# Decorate Me Health Check Log

最後更新：2026-06-16

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
