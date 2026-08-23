"""第 5 人（Admin／商品／爬蟲／後台驗收）自動化測試共用設定。

只驗證「這裡自動做得了」的三塊:會員軟刪除、爬蟲 SSRF、限流。
商品 CRUD／版本衝突／Audit 已由第 1 人的 tests/contract 覆蓋,不重複。

帳密只從環境變數讀取,不寫進程式或報告:
    $env:DM_GATEWAY_BASE_URL = "https://ai-gateway-258021445391.asia-east1.run.app"
    $env:DM_MEMBER_EMAIL / DM_MEMBER_PASSWORD   一般會員
    $env:DM_ADMIN_EMAIL  / DM_ADMIN_PASSWORD    管理員
    # 破壞性的「實刪測試會員」需要一個可拋棄帳號,預設不跑:
    $env:DM_DISPOSABLE_MEMBER_EMAIL = "<可被刪除的測試會員>"

受保護寫入(DELETE/PATCH…)會自動帶 X-Expected-Actor + X-CSRF-Token(見 js/api.js
_protectedFetch),已登入 session 一律照這個契約送。
"""
import os

import pytest
import requests

DEFAULT_GATEWAY = "https://ai-gateway-258021445391.asia-east1.run.app"
TIMEOUT = float(os.environ.get("DM_HTTP_TIMEOUT", "20"))
_WRITE = {"POST", "PUT", "PATCH", "DELETE"}


def _env(name, default=""):
    return os.environ.get(name, default).strip()


@pytest.fixture(scope="session")
def gateway_base_url():
    return _env("DM_GATEWAY_BASE_URL", DEFAULT_GATEWAY).rstrip("/")


def _wrap(original, actor, csrf):
    def req(method, url, **kw):
        kw.setdefault("timeout", TIMEOUT)
        if str(method).upper() in _WRITE:
            h = dict(kw.get("headers") or {})
            h.setdefault("X-Expected-Actor", actor)
            if csrf:
                h.setdefault("X-CSRF-Token", csrf)
            kw["headers"] = h
        return original(method, url, **kw)
    return req


@pytest.fixture(scope="session")
def http():
    s = requests.Session()
    orig = s.request
    s.request = lambda m, u, **k: orig(m, u, **{**k, "timeout": k.get("timeout", TIMEOUT)})
    return s


def _login(base, email, password):
    s = requests.Session()
    r = s.post(f"{base}/auth/login", json={"email": email, "password": password}, timeout=TIMEOUT)
    if not r.ok:
        pytest.skip(f"登入失敗（HTTP {r.status_code}）,略過需要登入的測試:{r.text[:150]}")
    actor = str((r.json() or {}).get("actorId") or "")
    csrf = s.cookies.get("dm_csrf", "")
    s.request = _wrap(s.request, actor, csrf)
    s.dm_email = email
    return s


@pytest.fixture(scope="session")
def gateway_healthy(http, gateway_base_url):
    try:
        r = http.request("GET", f"{gateway_base_url}/health", timeout=10)
    except requests.RequestException as e:
        pytest.skip(f"Gateway 連不上:{e}")
    if r.status_code != 200:
        pytest.skip(f"Gateway /health HTTP {r.status_code}")
    return r


@pytest.fixture(scope="session")
def member_session(gateway_healthy, gateway_base_url):
    e, p = _env("DM_MEMBER_EMAIL"), _env("DM_MEMBER_PASSWORD")
    if not e or not p:
        pytest.skip("未設定 DM_MEMBER_EMAIL / DM_MEMBER_PASSWORD")
    return _login(gateway_base_url, e, p)


@pytest.fixture(scope="session")
def admin_session(gateway_healthy, gateway_base_url):
    e, p = _env("DM_ADMIN_EMAIL"), _env("DM_ADMIN_PASSWORD")
    if not e or not p:
        pytest.skip("未設定 DM_ADMIN_EMAIL / DM_ADMIN_PASSWORD")
    return _login(gateway_base_url, e, p)


def code_of(response):
    try:
        err = (response.json() or {}).get("error")
    except ValueError:
        return None
    return err.get("code") if isinstance(err, dict) else None
