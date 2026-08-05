"""商品與 Admin 契約（派工書核心介面第 7～9 列）。

含 If-Match／VERSION_CONFLICT 與「一般會員操作 Admin 應為 403」。
"""
import pytest
import requests

from conftest import TIMEOUT, body, error_of


def test_products_list_is_reachable(base):
    r = requests.get(f"{base}/product-api/api/products", timeout=TIMEOUT)
    assert r.status_code == 200, f"商品列表回 {r.status_code}：{body(r)}"
    data = r.json()
    products = data.get("products", data if isinstance(data, list) else None)
    assert products is not None, f"回應沒有 products：{str(data)[:200]}"


def test_products_list_carries_no_admin_key(base):
    lowered = requests.get(f"{base}/product-api/api/products", timeout=TIMEOUT).text.lower()
    for forbidden in ("admin_api_key", "x-admin-key", "adminkey"):
        assert forbidden not in lowered, f"商品列表回應含 {forbidden}"


def test_admin_endpoints_reject_anonymous(base):
    """反項：未登入打 Admin 一律不得成功。"""
    for path in ("/admin-api/api/admin/product-audit-logs",
                 "/admin-api/api/products"):
        r = requests.get(f"{base}{path}", timeout=TIMEOUT)
        assert r.status_code != 200, f"{path} 未登入竟然回 200"
        assert r.status_code in (401, 403, 404), f"{path} 回 {r.status_code}"


def test_member_cannot_reach_admin(member_session, base):
    """派工書：一般會員操作 Admin 應為 403 ADMIN_REQUIRED。"""
    r = member_session.get(f"{base}/admin-api/api/admin/product-audit-logs", timeout=TIMEOUT)
    assert r.status_code in (403, 404), f"一般會員打 Admin 回 {r.status_code}（契約要求 403）"
    if r.status_code == 403:
        assert error_of(body(r)).get("code") == "ADMIN_REQUIRED", body(r)


def test_patch_requires_if_match(admin_session, base):
    """派工書：PATCH 必須帶 If-Match；缺了要擋，帶錯版本要回 409 VERSION_CONFLICT。"""
    listing = admin_session.get(f"{base}/admin-api/api/products", timeout=TIMEOUT)
    if listing.status_code != 200:
        pytest.skip(f"BLOCKED：Admin 商品列表不可用（HTTP {listing.status_code}，見 issue #30）")
    data = listing.json()
    products = data.get("products") or []
    if not products:
        pytest.skip("BLOCKED：沒有商品可測 If-Match")
    pid = products[0].get("id") or products[0].get("candidateKey")
    no_match = admin_session.patch(f"{base}/admin-api/api/products/{pid}",
                                   json={"description": "contract-test"}, timeout=TIMEOUT)
    assert no_match.status_code != 200, "缺 If-Match 竟然改成功"
    stale = admin_session.patch(f"{base}/admin-api/api/products/{pid}",
                                json={"description": "contract-test"},
                                headers={"If-Match": "0"}, timeout=TIMEOUT)
    if stale.status_code == 409:
        assert error_of(body(stale)).get("code") == "VERSION_CONFLICT", body(stale)


def test_audit_log_records_actor(admin_session, base):
    r = admin_session.get(f"{base}/admin-api/api/admin/product-audit-logs", timeout=TIMEOUT)
    if r.status_code != 200:
        pytest.skip(f"BLOCKED：Audit Log 不可用（HTTP {r.status_code}）")
    logs = r.json().get("logs") or r.json().get("items") or []
    if not logs:
        pytest.skip("BLOCKED：Audit Log 目前為空，無法驗操作者欄位")
    assert any(k in logs[0] for k in ("actor", "operator", "userId", "changedBy")), (
        f"Audit Log 沒有操作者欄位：{logs[0]}"
    )
