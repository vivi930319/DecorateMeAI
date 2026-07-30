# AI Gateway · 技術細節完整版

**基準日：** 2026-07-31
**對應程式：** `ai_gateway.py`（約 1900 行）
**Cloud Run 服務：** `ai-gateway`（asia-east1，唯一開放 `allUsers` 的服務）

> Gateway 是整個系統**唯一對外的入口**。face-basic／face-pro／render-service
> 的 IAM 只綁 `ai-gateway@decorate-me.iam.gserviceaccount.com`，
> 外面直接打服務網址會在 IAM 層就被擋掉，連 API key 都碰不到。

---

## 一、它到底負責什麼

| 責任 | 為什麼放在 Gateway 而不是各服務 |
| --- | --- |
| 驗證會員 session | 上游服務不需要知道「誰是會員」，只需要知道「這個請求被授權了」 |
| CSRF 防護 | 只有 Gateway 面對瀏覽器，上游收到的是伺服器對伺服器的呼叫 |
| 跨帳號隔離（actor）| 同一個瀏覽器可能登入多個帳號，選哪一個是入口層的事 |
| 持有上游金鑰 | 前端永遠拿不到 `FACE_API_KEY` 或 Replicate token |
| 路徑白名單 | 上游新增端點時必須顯式放行，預設關閉 |
| 逾時與流量上限 | 每個上游各自的 timeout，防止一個慢上游拖垮整個 Gateway |

---

## 二、Session 設計：為什麼塞在一個 cookie 裡

### 2.1 Firebase Hosting 的限制

```python
SESSION_COOKIE = "__session"
```

**Firebase Hosting 的 CDN 只會把名為 `__session` 的 cookie 轉發給後端，
其餘一律在 CDN 就丟掉。**

這造成過一個很難查的 bug（S56）：瀏覽器明明有送 cookie，
但 Cloud Run 收到的請求裡沒有——因為 CDN 在中間丟掉了。

所以 session 的兩個部分必須**共用同一個名字**：

```
__session = <Gateway JWT>|<Fernet 封裝的上游 cookie>
```

分隔符用 `|` 的理由寫在註解裡：

> Gateway access token 是 JWT（base64url 加點），封裝過的上游 jar 是 Fernet token
> （base64 加 padding）。**兩種字母表都不含 `|`**，所以它能明確分隔。

### 2.2 多帳號：槽位設計

一個瀏覽器只有一份 `__session`，但使用者可能在不同分頁登入不同帳號。
做法是把多組 `(JWT, 封裝的上游 cookie)` 存成**槽位**：

```python
MULTI_SESSION_PREFIX = "v2."
MAX_SESSION_SLOTS = max(1, min(int(os.getenv("GATEWAY_MAX_SESSION_SLOTS", "4")), 8))
MAX_SESSION_COOKIE_BYTES = max(1024, min(..., 4000))
```

每個分頁用 `X-Expected-Actor` 標頭選槽位——那是一個**不含 email 的 opaque 識別碼**。

**cookie 大小是硬限制。** 瀏覽器約 4KB 上限，每個槽位是一個 JWT 加一份 Fernet 密文，
所以 `MAX_SESSION_COOKIE_BYTES` 決定同時能存在幾個帳號，超過就從最舊的開始淘汰。

> **旗標關掉時（`GATEWAY_MULTI_SESSION` 未設）行為與單帳號完全一樣**——
> 只有一個槽位，選擇邏輯照樣能用，因為它只是看到一個槽位而已。
> 這是刻意的：新功能預設不改變既有行為。

### 2.3 上游 cookie 為什麼要封裝

會員資料庫回的 cookie 直接存進 `__session` 的話，等於把上游憑證明文交給瀏覽器。
用 Fernet 對稱加密封裝：

```python
def _member_cookie_cipher() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(SESSION_SECRET.encode("utf-8")).digest())
    return Fernet(key)
```

金鑰由 `SESSION_SECRET` 派生。瀏覽器拿到的是密文，只有 Gateway 解得開。

---

## 三、CSRF：double-submit cookie

```python
CSRF_COOKIE = "dm_csrf"
CSRF_HEADER = "x-csrf-token"
```

**刻意不是 HttpOnly**——前端 JavaScript 必須讀得到它才能放進標頭。

流程：
1. `/auth/session` 發一個隨機 token，同時寫進 cookie
2. 前端寫入類請求時把同一個值放進 `x-csrf-token` 標頭
3. Gateway 比對 cookie 與標頭是否相同

**為什麼這樣就安全：** 跨站攻擊者可以讓瀏覽器**送出** cookie，但**讀不到**它
（同源政策），所以填不出正確的標頭。

### 3.1 CSRF 與 X-Expected-Actor 擋的是不同的東西

程式註解寫得很清楚：

> 先前只有 `X-Expected-Actor` 在擋跨帳號寫入——**它擋的是「寫到別人的資料上」，
> 不是「這個請求是不是使用者本人發起的」。**

| 機制 | 擋什麼 |
| --- | --- |
| `X-Expected-Actor` | A 帳號的分頁不能寫到 B 帳號的資料 |
| CSRF token | 惡意網站不能用你的 cookie 幫你發請求 |

兩者都需要，缺一不可。

### 3.2 補發機制

已經登入但還沒有 CSRF cookie 的瀏覽器（例如這個功能上線前就登入的），
在下一次 `/auth/session` 補發一個，不必強制重新登入。

---

## 四、路徑白名單

```python
def is_path_allowed(upstream: Upstream, path: str) -> bool:
    return any(pattern.fullmatch(path) for pattern in upstream.allowed_paths)
```

**用 `fullmatch` 而非 `match`** —— `match` 只要開頭符合就過，
`v1/face/jobs/basic/../../etc` 這種路徑會被放行。

### 4.1 各上游的放行清單

| 上游 | 放行路徑 |
| --- | --- |
| `face-basic` | `health`、`v1/face/pose`、`v1/face/analyze/basic`、`v1/face/jobs/basic`、`v1/face/jobs/{id}`、`v1/face/jobs/{id}/result`、`v1/face/jobs/{id}/feedback` |
| `face-pro` | `health`、`v1/face/analyze/pro`、`v1/face/jobs/pro` |
| `render-service` | `health`、`render`、`render/jobs` |
| `text-suggestion` | `health`、`suggest` |
| `member-database` | `api/members/...` 等 13 條 |

**沒列進來的一律 404**，不是 403——不洩漏「這個端點存在但你沒權限」的資訊。

### 4.2 上游逾時各自獨立

```python
"face-basic": _timeout_env("AI_GATEWAY_FACE_TIMEOUT_SECONDS", 120)
```

臉部分析要跑 InsightFace + MediaPipe + 5 次 ONNX + 3 次 DINOv2，需要較長逾時；
文字建議走 Quick Tunnel，不穩定，逾時要短。**一個慢上游不該拖垮整個 Gateway。**

---

## 五、text-suggestion 預設 fail closed

```python
if service == "text-suggestion" and not ALLOW_EXTERNAL_TEXT_UPSTREAM:
    raise HTTPException(status_code=503, detail={"error": {
        "code": "EXTERNAL_TEXT_UPSTREAM_DISABLED", ...}})
```

文字建議服務走 **trycloudflare Quick Tunnel**，網址會變、也不在 GCP 的
IAM 保護範圍內。所以：

- 預設**關閉**，要顯式設環境變數才開
- `requires_upstream_api_key=False`——這條路**刻意不帶上游金鑰**，
  因為 tunnel 的另一端不在我們控制範圍，金鑰放上去等於外洩

> **這是一個安全上的權衡而不是疏漏：** 寧可這條路沒有金鑰保護、預設關閉，
> 也不要把金鑰送進一個不受控的通道。

---

## 六、啟動時的設定檢查

```python
for name, upstream in UPSTREAMS.items():
    if upstream.required_in_production and not upstream.base_url:
        missing.append(...)
    if upstream.requires_upstream_api_key and not upstream.api_key:
        missing.append(f"{name}.upstream_api_key")
```

**缺設定就拒絕啟動（fail closed）**，不是「先跑起來，等有人打了才 500」。

理由：一個「跑起來但上游全掛」的服務，從健康檢查看是正常的，
但每一個使用者請求都會失敗——**那比直接不啟動更難發現**。

---

## 七、實測驗證

```bash
# Gateway 自身健康檢查（公開）
curl https://ai-gateway-eu5pq7c53a-de.a.run.app/health
# {"status":"ok","service":"ai-gateway","privateUpstreamAuth":"cloud-run-iam",
#  "memberAuth":"short-lived-access-token","browserAuth":"member-session-only",
#  "externalTextUpstream":"enabled-for-demo"}

# 未登入時打上游 → 401，證明 session 驗證有效
curl https://ai-gateway-eu5pq7c53a-de.a.run.app/face-basic/health
# {"error":{"code":"MEMBER_AUTH_REQUIRED","message":"Member sign-in is required."}}
```

**注意第二個測試：連 `health` 都要登入。** 這是刻意的——
上游的存在與否本身也是資訊。

---

## 八、面試可能被問到的

**Q：為什麼不讓前端直接呼叫 face-basic？**
三個理由：(1) 金鑰會外洩到瀏覽器；(2) 沒有地方做 session／CSRF／actor 驗證；
(3) Cloud Run 服務要開 `allUsers` 才能被瀏覽器呼叫，等於完全公開。

**Q：JWT 存在 cookie 裡不是有 XSS 風險嗎？**
`__session` 是 HttpOnly，JavaScript 讀不到。CSRF token 才是可讀的，
但它只是隨機值，讀到也沒有用——攻擊者需要的是 session 本身。

**Q：為什麼 CSRF token 不做成 HttpOnly？**
double-submit 模式**必須**讓前端讀得到才能放進標頭。
安全性來自「跨站攻擊者讀不到你的 cookie」，不是來自 HttpOnly。

**Q：多帳號的槽位滿了會怎樣？**
從最舊的開始淘汰。`MAX_SESSION_COOKIE_BYTES = 3800` 是為了留在瀏覽器
4KB 上限之下——**超過的話整個 cookie 會被瀏覽器丟掉，等於全部登出**。
