"""POST /auth/login、GET /auth/session — 登入與短期憑證契約。

注意：實測發現 Gateway 目前是 session-only 模式（見 conftest.py 開頭說明），
瀏覽器端不會拿到可讀取的 Bearer Token，登入態完全靠 HttpOnly cookie 維持。
以下測試以此為準；「短期憑證」的驗證重點因此落在 HttpOnly cookie 與
/auth/session 的身分回傳，而不是派工書字面上的 Authorization: Bearer。
"""
from conftest import assert_no_admin_key_leak, error_payload


def test_unauthenticated_session_check_returns_401(http, gateway_base_url):
    res = http.request("GET", f"{gateway_base_url}/auth/session")
    assert res.status_code == 401, res.text
    err = error_payload(res)
    assert err and err.get("code") == "MEMBER_AUTH_REQUIRED", err


def test_login_missing_password_returns_422_validation_error(http, gateway_base_url):
    res = http.request("POST", f"{gateway_base_url}/auth/login", json={"email": "someone@example.com"})
    assert res.status_code == 422, res.text
    err = error_payload(res)
    assert err and err.get("code") == "VALIDATION_ERROR", err
    fields = err.get("fields") or []
    assert any("password" in f.get("field", "") for f in fields), f"驗證錯誤沒有指出缺少的欄位：{err}"


def test_login_missing_email_returns_422_validation_error(http, gateway_base_url):
    res = http.request("POST", f"{gateway_base_url}/auth/login", json={"password": "x"})
    assert res.status_code == 422, res.text
    err = error_payload(res)
    assert err and err.get("code") == "VALIDATION_ERROR", err


def test_login_wrong_type_email_returns_422(http, gateway_base_url):
    """email 傳數字而非字串：型別錯誤案例。"""
    res = http.request("POST", f"{gateway_base_url}/auth/login", json={"email": 12345, "password": "x"})
    assert res.status_code == 422, res.text
    err = error_payload(res)
    assert err and err.get("code") == "VALIDATION_ERROR", err


def test_login_wrong_credentials_returns_401_invalid_credentials(http, gateway_base_url):
    res = http.request(
        "POST", f"{gateway_base_url}/auth/login",
        json={"email": "definitely-not-a-real-user@example.com", "password": "wrong-password-x1"},
    )
    assert res.status_code == 401, res.text
    err = error_payload(res)
    assert err and err.get("code") == "INVALID_CREDENTIALS", err


def test_login_response_has_x_request_id_header(http, gateway_base_url):
    """requestId 目前只出現在回應 header（x-request-id），不在 body 的 error.requestId 裡；
    此測試記錄的是「header 有沒有」，body 缺 requestId 的落差另外記在 test_gateway_errors.py。"""
    res = http.request(
        "POST", f"{gateway_base_url}/auth/login",
        json={"email": "definitely-not-a-real-user@example.com", "password": "wrong-password-x1"},
    )
    assert res.headers.get("x-request-id"), "登入錯誤回應缺少 x-request-id header，事故無法追蹤"


def test_login_success_returns_member_and_establishes_session(gateway_base_url, member_credentials, http):
    email, password = member_credentials
    res = http.request("POST", f"{gateway_base_url}/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    data = res.json()
    assert "member" in data, f"登入成功回應缺少 member 欄位：{data}"
    member = data.get("member") or {}
    assert member.get("email"), f"member 物件缺少 email：{member}"

    session_res = http.request("GET", f"{gateway_base_url}/auth/session", cookies=res.cookies)
    assert session_res.status_code == 200, session_res.text
    session_data = session_res.json()
    assert session_data.get("sub") or session_data.get("actorId"), (
        f"/auth/session 缺少可用的身分欄位（sub / actorId）：{session_data}"
    )


def test_login_does_not_leak_admin_key(gateway_base_url, member_credentials, http):
    email, password = member_credentials
    res = http.request("POST", f"{gateway_base_url}/auth/login", json={"email": email, "password": password})
    assert_no_admin_key_leak(res)


def test_login_sets_httponly_session_cookie(gateway_base_url, member_credentials, http):
    email, password = member_credentials
    res = http.request("POST", f"{gateway_base_url}/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    assert len(res.cookies) > 0, "登入成功卻沒有拿到任何 Cookie，前端將無法維持會員 session"
    raw_headers = res.raw.headers if res.raw is not None else None
    set_cookie_headers = (
        raw_headers.get_all("Set-Cookie") if raw_headers and hasattr(raw_headers, "get_all") else []
    ) or [res.headers.get("Set-Cookie", "")]
    assert any("HttpOnly" in (h or "") for h in set_cookie_headers), (
        f"Session cookie 未標示 HttpOnly，瀏覽器端 JavaScript 可讀取到憑證：{set_cookie_headers}"
    )


def test_admin_login_role_is_reflected_in_session(gateway_base_url, admin_credentials, http):
    email, password = admin_credentials
    res = http.request("POST", f"{gateway_base_url}/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    session_res = http.request("GET", f"{gateway_base_url}/auth/session", cookies=res.cookies)
    assert session_res.status_code == 200, session_res.text
    session_data = session_res.json()
    role = str(session_data.get("role", "")).lower()
    assert role == "admin", f"管理員帳號登入後 /auth/session 的 role 應為 admin，實際為：{role!r}（{session_data}）"


def test_logout_invalidates_session(gateway_base_url, member_credentials, http):
    email, password = member_credentials
    login_res = http.request("POST", f"{gateway_base_url}/auth/login", json={"email": email, "password": password})
    assert login_res.status_code == 200, login_res.text

    logout_res = http.request("POST", f"{gateway_base_url}/auth/logout", cookies=login_res.cookies)
    assert logout_res.status_code == 200, logout_res.text

    after_res = http.request("GET", f"{gateway_base_url}/auth/session", cookies=logout_res.cookies)
    assert after_res.status_code == 401, (
        f"登出後 /auth/session 應回 401，實際為 {after_res.status_code}：{after_res.text}"
    )


# ── OTP 與註冊契約（用假帳號驗證，不觸及真人信箱）─────────────────────

def test_send_otp_missing_email_returns_400(http, gateway_base_url):
    res = http.request("POST", f"{gateway_base_url}/auth/send-otp", json={})
    assert res.status_code == 400, f"send-otp 缺 email 應回 400，實際 {res.status_code}：{res.text}"
    err = error_payload(res)
    assert err and err.get("code") == "INVALID_EMAIL", err


def test_send_otp_for_non_pending_registration_returns_409(http, gateway_base_url):
    """對一個沒有進行中註冊的 email 要 OTP：屬業務衝突，應回 409，不是 200/500。"""
    res = http.request(
        "POST", f"{gateway_base_url}/auth/send-otp",
        json={"email": "fake-nobody-not-pending@example.com"},
    )
    assert res.status_code == 409, f"預期 409，實際 {res.status_code}：{res.text}"
    err = error_payload(res)
    assert err and err.get("code") == "REGISTRATION_NOT_PENDING", err


def test_send_otp_wrong_type_email_should_not_return_500(http, gateway_base_url):
    """【已知缺陷】email 傳非字串（型別錯）時，send-otp 目前直接回 500 INTERNAL_ERROR，
    代表後端缺少輸入型別驗證、把可預期的壞輸入變成未處理崩潰。正確行為應是 400/422。
    這個測試刻意斷言「不應該是 5xx」，讓缺陷持續顯示為 FAIL，修好後自動轉綠。"""
    res = http.request("POST", f"{gateway_base_url}/auth/send-otp", json={"email": 12345})
    assert res.status_code < 500, (
        f"email 型別錯誤應被當成 4xx 輸入驗證錯誤，不該讓後端崩成 {res.status_code}：{res.text}"
    )


def test_verify_otp_field_name_is_otp_not_code(http, gateway_base_url):
    """釐清欄位契約：驗證碼欄位名是 `otp`，不是 `code`。
    帶 otp 會走到「碼不存在或已逾時」(OTP_EXPIRED)；帶 code 反而被當成沒給碼
    (OTP_INVALID「不得為空」)。此測試把正確欄位名固定下來，避免下游用錯欄位。"""
    with_otp = http.request(
        "POST", f"{gateway_base_url}/auth/verify-otp",
        json={"email": "fake-nobody-not-pending@example.com", "otp": "000000"},
    )
    assert with_otp.status_code == 400, with_otp.text
    err = error_payload(with_otp)
    assert err and err.get("code") in ("OTP_EXPIRED", "OTP_INVALID"), err
    # 用錯的欄位名 code 時，後端會誤判成沒給碼——這正是我們要提醒下游別踩的坑。
    with_code = http.request(
        "POST", f"{gateway_base_url}/auth/verify-otp",
        json={"email": "fake-nobody-not-pending@example.com", "code": "000000"},
    )
    err2 = error_payload(with_code)
    # 2026-08-14：會員端把「沒給碼」與「碼不存在／逾時」合併成同一個 OTP_EXPIRED，
    # 於是這裡從 OTP_INVALID 變成 OTP_EXPIRED。
    #
    # 要守住的契約是「**用 code 這個欄位名不會被當成有效的驗證碼**」，不是「回哪一個錯誤碼」。
    # 先前寫死單一錯誤碼，等於把對方的訊息分類方式也綁進契約——那不是我們該管的範圍，
    # 對方合併兩個碼是合理的重構，卻會讓這個測試變紅。
    assert err2 and err2.get("code") in ("OTP_INVALID", "OTP_EXPIRED"), (
        f"帶 code 欄位時應該被拒絕（OTP_INVALID／OTP_EXPIRED 皆可）。"
        f"若這裡開始回成功或別的碼，代表 code 欄位被接受了，欄位契約已變更：{err2}"
    )


def test_register_missing_fields_returns_400(http, gateway_base_url):
    """缺必填欄位要回 4xx 並指出是輸入問題。

    2026-08-14 修正：原本送全空的 `{}`，而會員端**先驗 email 格式**，
    所以回的是 `INVALID_EMAIL` 而不是缺欄位相關的碼——測試因此變紅，
    但那其實是「測試沒問對問題」：空物件同時缺 email 又缺其他欄位，
    對方先報哪一個都合理。

    改成給一個**格式正確的 email**、其餘必填欄位留空，這樣才真的在測「缺欄位」。
    """
    res = http.request(
        "POST", f"{gateway_base_url}/auth/register",
        json={"email": "contract-test-nobody@example.com"},
    )
    assert res.status_code in (400, 422), (
        f"register 缺欄位應回 400／422，實際 {res.status_code}：{res.text}"
    )
    err = error_payload(res)
    assert err and err.get("code") in (
        "MISSING_FIELDS", "VALIDATION_ERROR", "INVALID_REQUEST", "REGISTER_VALIDATION_FAILED",
    ), err
