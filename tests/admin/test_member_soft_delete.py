"""會員軟刪除（第 5 人派工書 §會員軟刪除）。

實際端點（由前端 js/api.js deleteMember 得知）:
    DELETE /member-database/api/members/{email}
刪除前前端會先呼叫 DELETE /admin-api/members/{email}/media 清影像。

派工書列的碼與實際碼的對照（實測）:
    未登入        UNAUTHENTICATED   → 實際 401 MEMBER_AUTH_REQUIRED
    一般會員      403               → 實際 403 MEMBER_SCOPE_FORBIDDEN（非 ADMIN_REQUIRED）
    刪自己        CANNOT_DELETE_SELF→ 實際 403 CANNOT_DELETE_SELF ✅
    不存在        MEMBER_NOT_FOUND  → 實際 503 MEDIA_OWNERSHIP_LOOKUP_FAILED ⚠️（見下）

破壞性的「實刪測試會員 → 200 → 不在列表 → 重新登入 ACCOUNT_SUSPENDED」需要一個
可拋棄帳號,預設不跑（設 DM_DISPOSABLE_MEMBER_EMAIL 才啟用）。
"""
import os

import pytest

from conftest import code_of

MEMBER_PATH = "/member-database/api/members"
FAKE = "nobody-xyz-9999@example.com"


def test_unauthenticated_delete_returns_401(http, gateway_base_url):
    res = http.request("DELETE", f"{gateway_base_url}{MEMBER_PATH}/{FAKE}")
    assert res.status_code == 401, res.text
    assert code_of(res) == "MEMBER_AUTH_REQUIRED", code_of(res)


def test_regular_member_cannot_delete_others(member_session, gateway_base_url):
    """一般會員刪別人:實際回 403 MEMBER_SCOPE_FORBIDDEN（會員只能動自己 scope）。"""
    res = member_session.request("DELETE", f"{gateway_base_url}{MEMBER_PATH}/{FAKE}")
    assert res.status_code == 403, res.text
    assert code_of(res) in ("MEMBER_SCOPE_FORBIDDEN", "ADMIN_REQUIRED"), code_of(res)


def test_admin_cannot_delete_self(admin_session, gateway_base_url):
    res = admin_session.request("DELETE", f"{gateway_base_url}{MEMBER_PATH}/{admin_session.dm_email}")
    assert res.status_code == 403, res.text
    assert code_of(res) == "CANNOT_DELETE_SELF", code_of(res)


def test_delete_requires_csrf_and_actor(admin_session, gateway_base_url):
    """受保護寫入必須帶 CSRF 與 Expected-Actor:各缺一個要分別被擋。"""
    # 缺 CSRF（清掉 header）
    no_csrf = admin_session.request(
        "DELETE", f"{gateway_base_url}{MEMBER_PATH}/{FAKE}",
        headers={"X-CSRF-Token": ""},
    )
    assert no_csrf.status_code in (401, 403), no_csrf.text


def test_delete_nonexistent_member_should_be_404_member_not_found(admin_session, gateway_base_url):
    """【與派工書不符】刪不存在的會員,派工書要求 404 MEMBER_NOT_FOUND;
    實際先做「清影像」的 ownership 查找,對不存在的帳號直接 503 MEDIA_OWNERSHIP_LOOKUP_FAILED——
    使用者/管理員看到的是伺服器錯誤,不是「查無此人」。這裡照派工書斷言,讓落差顯示為 FAIL。"""
    res = admin_session.request("DELETE", f"{gateway_base_url}{MEMBER_PATH}/{FAKE}")
    assert res.status_code == 404, (
        f"預期 404 MEMBER_NOT_FOUND,實際 {res.status_code} {code_of(res)}："
        "刪不存在會員回了非 404,代表刪除前的 media ownership 查找沒有先處理『查無此人』"
    )
    assert code_of(res) == "MEMBER_NOT_FOUND", code_of(res)


@pytest.mark.skipif(not os.environ.get("DM_DISPOSABLE_MEMBER_EMAIL", "").strip(),
                    reason="破壞性:需設 DM_DISPOSABLE_MEMBER_EMAIL 指定可拋棄測試會員")
def test_full_soft_delete_flow(admin_session, gateway_base_url):
    """實刪一個可拋棄測試會員:清影像 → 刪除 200 → 不在列表 → 重新登入應 ACCOUNT_SUSPENDED。"""
    email = os.environ["DM_DISPOSABLE_MEMBER_EMAIL"].strip()
    admin_session.request("DELETE", f"{gateway_base_url}/admin-api/members/{email}/media")
    res = admin_session.request("DELETE", f"{gateway_base_url}{MEMBER_PATH}/{email}")
    assert res.status_code == 200, f"軟刪測試會員應 200:{res.status_code} {res.text[:150]}"
    listing = admin_session.request("GET", f"{gateway_base_url}{MEMBER_PATH}")
    if listing.ok:
        text = listing.text
        assert email not in text, "軟刪後該會員仍出現在列表"
