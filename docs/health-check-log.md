# Decorate Me Health Check Log

最後更新：2026-06-15

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
