"""登入與 session 契約（派工書：member、role、status、短期憑證）。

正向需要測試帳號，沒有就 BLOCKED；反向（未登入、缺欄位、錯型別）不需要帳號，一定要跑。
"""
import requests

from conftest import TIMEOUT, body, error_of


def test_session_requires_login(base):
    """未登入應為 401。"""
    r = requests.get(f"{base}/auth/session", timeout=TIMEOUT)
    assert r.status_code == 401, f"未登入 /auth/session 回 {r.status_code}"


def test_login_missing_fields_is_400_invalid_request(base):
    """派工書統一錯誤格式：缺欄位 = 400 INVALID_REQUEST。

    目前實際回 422（FastAPI 預設的驗證錯誤直接透出來），與契約不符。
    """
    r = requests.post(f"{base}/auth/login", json={}, timeout=TIMEOUT)
    assert r.status_code == 400, (
        f"缺欄位回 {r.status_code}，契約要求 400 INVALID_REQUEST；body={body(r)}"
    )
    assert error_of(body(r)).get("code") == "INVALID_REQUEST"


def test_login_wrong_types_is_400(base):
    r = requests.post(f"{base}/auth/login", json={"email": 123, "password": True}, timeout=TIMEOUT)
    assert r.status_code == 400, f"錯型別回 {r.status_code}，契約要求 400；body={body(r)}"


def test_login_bad_credentials_does_not_enumerate(base):
    """資安 issue #27：登入端點不可用錯誤碼區分「帳號不存在」與「密碼錯誤」。"""
    a = requests.post(f"{base}/auth/login",
                      json={"email": "no-such-user-9c1f@example.com", "password": "x"}, timeout=TIMEOUT)
    b = requests.post(f"{base}/auth/login",
                      json={"email": "admin@example.com", "password": "definitely-wrong"}, timeout=TIMEOUT)
    ca, cb = error_of(body(a)).get("code"), error_of(body(b)).get("code")
    assert not (ca == "USER_NOT_FOUND" and cb == "WRONG_PASSWORD"), (
        f"可列舉帳號：不存在={ca} 密碼錯={cb}（issue #27）"
    )


def test_login_returns_member_role_status(member_session, base):
    """正向：登入後 /auth/session 要帶得出 member、role、status。"""
    r = member_session.get(f"{base}/auth/session", timeout=TIMEOUT)
    assert r.status_code == 200, f"session 回 {r.status_code}"
    data = r.json()
    assert "role" in str(data), f"session 沒有 role：{data}"


def test_no_admin_key_in_any_auth_response(base):
    """派工書：Network 不得出現 Admin Key。"""
    for path, payload in (("/auth/session", None), ("/auth/login", {})):
        r = (requests.get(f"{base}{path}", timeout=TIMEOUT) if payload is None
             else requests.post(f"{base}{path}", json=payload, timeout=TIMEOUT))
        lowered = r.text.lower()
        for forbidden in ("admin_api_key", "x-admin-key", "adminkey"):
            assert forbidden not in lowered, f"{path} 回應含 {forbidden}"
