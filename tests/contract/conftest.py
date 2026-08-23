"""
AI Gateway 契約測試共用設定。

## 一律走 Gateway

本測試組不直連任何下游服務（會員、商品、爬蟲、臉部、Ollama、渲染），
全部經由正式 AI Gateway 的同源代理路徑呼叫——這跟正式前端（js/api.js）
的行為一致：瀏覽器只認得 Gateway，上游網址與金鑰只留在伺服器端。
派工書早期列的 Quick Tunnel 直連網址已不使用。

## 執行前準備

測試帳密、Base URL 一律只從本機環境變數讀取，不寫進程式或報告。
PowerShell 設定範例：

    $env:DM_GATEWAY_BASE_URL = "https://ai-gateway-258021445391.asia-east1.run.app"
    $env:DM_MEMBER_EMAIL     = "<一般會員帳號>"
    $env:DM_MEMBER_PASSWORD  = "<...>"
    $env:DM_ADMIN_EMAIL      = "<管理員帳號>"
    $env:DM_ADMIN_PASSWORD   = "<...>"
    # 需要跑 BASIC/PRO 完整分析時再設定合法臉部圖片路徑：
    $env:DM_TEST_FACE_IMAGE  = "C:\\path\\to\\legit-face.jpg"

沒設定帳密的服務會讓對應測試以 SKIPPED（不是 FAILED）結束，
確保整批測試在任何環境都能重跑，也能一眼看出「還缺什麼才能測」。

## Bearer Token 契約

Gateway 目前採「session-only」模式：登入後身分只靠 HttpOnly cookie 維持，
瀏覽器端沒有可讀取的 Bearer Token（見 js/api.js 的 `_getGatewaySessionToken`
恆傳回空字串）。派工書列的 `Authorization: Bearer <短期 Token>` 是後端對後端
或行動端另一套整合方式，不是這個 Gateway 對瀏覽器的實際契約；本測試組因此
以 requests.Session 的 cookies 作為登入態的唯一依據。
"""
import os

import pytest
import requests

DEFAULT_GATEWAY = "https://ai-gateway-258021445391.asia-east1.run.app"
TIMEOUT = float(os.environ.get("DM_HTTP_TIMEOUT", "20"))

# Network、localStorage、前端 JS bundle 都不得出現的敏感標頭／字面值。
FORBIDDEN_HEADER_NAMES = {"x-admin-key"}
FORBIDDEN_BODY_LITERALS = ("ADMIN_API_KEY", "X-Admin-Key")


def _env(name, default=""):
    return os.environ.get(name, default).strip()


@pytest.fixture(scope="session")
def gateway_base_url():
    return _env("DM_GATEWAY_BASE_URL", DEFAULT_GATEWAY).rstrip("/")


def _timeout_wrapper(original_request):
    def wrapped(method, url, **kwargs):
        kwargs.setdefault("timeout", TIMEOUT)
        return original_request(method, url, **kwargs)
    return wrapped


@pytest.fixture(scope="session")
def http():
    session = requests.Session()
    session.request = _timeout_wrapper(session.request)
    return session


@pytest.fixture(autouse=True)
def _http_stays_anonymous(http):
    """每個測試開始前清掉 `http` 的 cookie，確保它真的是「未登入的瀏覽器」。

    2026-08-14 抓到的實際事故：`http` 是 session scope（整批共用一個
    `requests.Session`），而其中有測試會用它成功登入一次——那次的 `__session`
    cookie 就留在 jar 裡，**後面每一個「未登入應回 401」的測試都變成已登入**。

    症狀非常有誤導性：沒設管理員帳密時整批是綠的（登入失敗，cookie 沒種下去），
    一旦設了帳密就冒出九個失敗，看起來像「帶了帳密反而把系統測壞」。
    實際上壞的是測試自己，而且它掩蓋的正是最該守住的那條線——未登入的人拿不拿得到資料。

    修法選擇：不改成 function scope，是因為 `gateway_healthy` 等 session scope 的
    fixture 依賴它（session scope 不能依賴 function scope）。清 cookie 就足夠，
    而且改動最小、不影響既有呼叫端。
    """
    http.cookies.clear()
    yield
    http.cookies.clear()


@pytest.fixture(scope="session")
def gateway_healthy(http, gateway_base_url):
    """所有測試的前置：Gateway 自身要先探活，否則整批沒有意義。"""
    try:
        res = http.request("GET", f"{gateway_base_url}/health", timeout=10)
    except requests.RequestException as exc:
        pytest.skip(f"AI Gateway 無法連線（{gateway_base_url}）：{exc}")
    if res.status_code != 200:
        pytest.skip(f"AI Gateway /health 回傳 HTTP {res.status_code}，服務目前異常（{gateway_base_url}）")
    return res


@pytest.fixture(scope="session")
def member_credentials():
    email = _env("DM_MEMBER_EMAIL")
    password = _env("DM_MEMBER_PASSWORD")
    if not email or not password:
        pytest.skip("未設定 DM_MEMBER_EMAIL / DM_MEMBER_PASSWORD，略過需要一般會員登入的測試")
    return email, password


@pytest.fixture(scope="session")
def admin_credentials():
    email = _env("DM_ADMIN_EMAIL")
    password = _env("DM_ADMIN_PASSWORD")
    if not email or not password:
        pytest.skip("未設定 DM_ADMIN_EMAIL / DM_ADMIN_PASSWORD，略過需要管理員登入的測試")
    return email, password


# 受保護寫入的真實契約（見 js/api.js `_protectedFetch`）：
# 瀏覽器對同源 Gateway 送出的 POST/PUT/PATCH/DELETE 必須同時帶
#   - X-Expected-Actor：登入回應給的 actorId，把這次寫入綁在正確身分上
#   - X-CSRF-Token：與 dm_csrf cookie 相同值的 double-submit token
# 少任一個，Gateway 會回 409 EXPECTED_ACTOR_REQUIRED 或 403 CSRF_TOKEN_INVALID。
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _protected_request_wrapper(original_request, actor_id, csrf_token):
    def wrapped(method, url, **kwargs):
        kwargs.setdefault("timeout", TIMEOUT)
        if str(method).upper() in _WRITE_METHODS:
            headers = dict(kwargs.get("headers") or {})
            headers.setdefault("X-Expected-Actor", actor_id)
            if csrf_token:
                headers.setdefault("X-CSRF-Token", csrf_token)
            kwargs["headers"] = headers
        return original_request(method, url, **kwargs)
    return wrapped


def _login_session(gateway_base_url, email, password):
    session = requests.Session()
    res = session.post(
        f"{gateway_base_url}/auth/login",
        json={"email": email, "password": password},
        timeout=TIMEOUT,
    )
    if not res.ok:
        pytest.skip(
            f"測試帳號登入失敗（HTTP {res.status_code}），略過需要登入的測試。"
            f" 回應片段：{res.text[:200]}"
        )
    body = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
    actor_id = str(body.get("actorId") or "")
    csrf_token = session.cookies.get("dm_csrf", "")
    # 讓已登入的 session 在寫入時自動補上 CSRF／Expected-Actor，複製正式前端的行為。
    session.request = _protected_request_wrapper(session.request, actor_id, csrf_token)
    session.dm_actor_id = actor_id
    session.dm_csrf_token = csrf_token
    return session


@pytest.fixture(scope="session")
def member_session(gateway_healthy, gateway_base_url, member_credentials):
    """一般會員（非 admin）的已登入 requests.Session，共用 HttpOnly cookie。"""
    email, password = member_credentials
    return _login_session(gateway_base_url, email, password)


@pytest.fixture(scope="session")
def admin_session(gateway_healthy, gateway_base_url, admin_credentials):
    """管理員的已登入 requests.Session。"""
    email, password = admin_credentials
    return _login_session(gateway_base_url, email, password)


def assert_no_admin_key_leak(response):
    """驗證這一來一回完全沒有出現 Admin Key：不在請求標頭、不在回應內容字面值中。"""
    for name in response.request.headers:
        assert name.lower() not in FORBIDDEN_HEADER_NAMES, f"請求帶了不該出現的 {name} header"
    body_text = response.text or ""
    for literal in FORBIDDEN_BODY_LITERALS:
        assert literal not in body_text, f"回應內容疑似洩漏了 {literal}"


def error_payload(response):
    """回傳 error 物件本體；解不出 JSON 就回 None，交給呼叫端決定要不要當成失敗。"""
    try:
        data = response.json()
    except ValueError:
        return None
    return data.get("error") if isinstance(data, dict) else None
