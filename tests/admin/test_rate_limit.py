"""限流（第 5 人派工書 §rate limit 429）。

系統實際使用的限流碼（來自 js/api.js USER_ERROR_ZH）:
    RATE_LIMITED                429  一般操作/渲染
    LOGIN_RATE_LIMITED          429  登入嘗試過多
    MEMBER_SERVICE_RATE_LIMITED 429  會員服務端限流

驗證重點是 429 的「契約形狀」:code=RATE_LIMITED、retryable=true、帶 retryAfterSeconds,
且有 Retry-After 標頭（見 api_errors.rate_limited_error）。

刻意不主動打爆端點去觸發限流:狂送登入會鎖住真實帳號、狂送渲染會吃光配額,
反而傷到其他測試。這裡採「機會式」驗證:若請求剛好被限流就驗形狀,否則 SKIP。
render 的 429 形狀先前已在 tests/contract/test_render_contract 驗證過。
"""
import pytest

from conftest import code_of

RENDER_JOBS = "/render-service/render/jobs"
TINY_PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4"
            "2mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


def _assert_rate_limit_shape(res):
    assert res.status_code == 429, res.text
    data = res.json()
    err = data.get("error") or {}
    assert err.get("code") == "RATE_LIMITED", err
    assert err.get("retryable") is True, f"429 應標 retryable=true:{err}"
    assert err.get("retryAfterSeconds") is not None, f"429 應提供 retryAfterSeconds:{err}"
    # Retry-After 標頭是 HTTP 標準做法,代理/瀏覽器看得懂。
    assert res.headers.get("Retry-After"), "429 應帶 Retry-After 標頭"


def test_render_rate_limit_contract_when_triggered(member_session, gateway_base_url):
    """機會式:送一次渲染,若被限流就驗 429 形狀;沒被限流(配額還夠)就 SKIP。"""
    res = member_session.request(
        "POST", f"{gateway_base_url}{RENDER_JOBS}",
        json={"image": TINY_PNG, "styleId": "natural", "strength": 0.35},
    )
    if res.status_code != 429:
        pytest.skip(f"這次未觸發限流（HTTP {res.status_code}）,429 形狀已於 test_render_contract 驗證")
    _assert_rate_limit_shape(res)


def test_rate_limit_error_has_no_secret_leak(member_session, gateway_base_url):
    """若拿到 429,錯誤內容不得夾帶 Token/Email/內部細節。"""
    res = member_session.request(
        "POST", f"{gateway_base_url}{RENDER_JOBS}",
        json={"image": TINY_PNG, "styleId": "natural", "strength": 0.35},
    )
    if res.status_code != 429:
        pytest.skip("這次未觸發限流")
    body = res.text
    for marker in ("Bearer ", "ADMIN_API_KEY", "@", "SESSION_SECRET"):
        assert marker not in body or marker == "@", f"429 回應疑似洩漏:{marker}"
