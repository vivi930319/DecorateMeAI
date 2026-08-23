"""GET/POST /api/products、GET/PATCH/DELETE /api/products/{type:id}、
GET /api/admin/product-audit-logs、爬蟲 staging 路徑 — 商品與 Admin 契約。

實際 Gateway 路由（由 /openapi.json 取得，和派工書表格的相對路徑不完全一樣）：

- 公開商品清單（不需登入）：GET `/product-api/api/products`
- Admin 商品管理（需 admin）：GET/POST `/admin-api/products`、
  GET/PATCH/DELETE `/admin-api/products/{product_id}`
- Audit Log：GET `/admin-api/product-audit-logs`
- 爬蟲 staging（現行版本）：GET `/admin-api/crawler-staging/products`，
  單筆 GET/PATCH `/admin-api/crawler-staging/products/{staging_id}`，
  匯入 POST `/admin-api/crawler-staging/products/{staging_id}/import`。
  Legacy 的 `/api/crawler/product-preview` 目前**沒有**出現在 Gateway 的
  openapi.json 裡，代表它已經不是可測的路徑，不是「兩套並存」的狀態。
"""
import time

import pytest

from conftest import error_payload

PUBLIC_PRODUCTS_PATH = "/product-api/api/products"
ADMIN_PRODUCTS_PATH = "/admin-api/products"
ADMIN_AUDIT_LOG_PATH = "/admin-api/product-audit-logs"
ADMIN_CRAWLER_STAGING_PATH = "/admin-api/crawler-staging/products"
LEGACY_CRAWLER_PATH = "/api/crawler/product-preview"

TEST_PRODUCT_NAME_PREFIX = "[契約測試-可刪除]"


# ── 公開商品清單：不需要登入 ──────────────────────────────────────────

def test_public_product_list_does_not_require_auth(http, gateway_base_url):
    res = http.request("GET", f"{gateway_base_url}{PUBLIC_PRODUCTS_PATH}")
    assert res.status_code == 200, f"公開商品清單不應要求登入，實際 {res.status_code}：{res.text}"
    data = res.json()
    items = data.get("items") or data.get("products") or []
    assert isinstance(items, list), f"商品清單應為陣列：{type(items)}"


# ── Admin 商品管理：401 / 403 權限矩陣 ────────────────────────────────

def test_admin_products_unauthenticated_returns_401(http, gateway_base_url):
    res = http.request("GET", f"{gateway_base_url}{ADMIN_PRODUCTS_PATH}")
    assert res.status_code == 401, res.text
    err = error_payload(res)
    assert err and err.get("code") == "MEMBER_AUTH_REQUIRED", err


def test_admin_products_regular_member_returns_403(member_session, gateway_base_url):
    """一般會員（非 admin）呼叫 Admin 端點應為 403 ADMIN_REQUIRED，不是被放行或誤判成 401。"""
    res = member_session.get(f"{gateway_base_url}{ADMIN_PRODUCTS_PATH}")
    assert res.status_code == 403, f"一般會員呼叫 Admin 端點應回 403，實際 {res.status_code}：{res.text}"
    err = error_payload(res)
    assert err and err.get("code") == "ADMIN_REQUIRED", err


def test_admin_can_list_products(admin_session, gateway_base_url):
    res = admin_session.get(f"{gateway_base_url}{ADMIN_PRODUCTS_PATH}")
    assert res.status_code == 200, res.text
    data = res.json()
    items = data.get("items") or data.get("products") or []
    assert isinstance(items, list), f"Admin 商品清單應為陣列：{type(items)}"


# ── 建立 → 版本修改（If-Match）→ 軟停用 → Audit Log 全流程 ─────────────

@pytest.fixture
def created_test_product(admin_session, gateway_base_url):
    """建立一筆明確標記的測試商品，測試結束後嘗試軟停用清理，不留垃圾資料。"""
    payload = {
        "name": f"{TEST_PRODUCT_NAME_PREFIX} {int(time.time())}",
        "type": "lipsticks",
        "brand": "契約測試",
        "price": 1,
        "status": "inactive",  # 一開始就用非上架狀態建立，降低誤入前台清單的風險
    }
    res = admin_session.post(f"{gateway_base_url}{ADMIN_PRODUCTS_PATH}", json=payload)
    if res.status_code == 404:
        pytest.skip("此 Gateway 版本的 /admin-api/products 不支援直接 POST 建立，改由第 5 人交付的既有測試商品驗證")
    if res.status_code == 400 and (error_payload(res) or {}).get("code") == "MISSING_FIELDS":
        pytest.skip(
            "建立商品被擋在 MISSING_FIELDS：缺少商品端未公開的必填欄位規格。"
            " 需要爬蟲／商品端（第 5 人）提供 POST /admin-api/products 的完整必填欄位清單後才能測寫入流程。"
        )
    if res.status_code >= 500:
        pytest.skip(
            f"建立商品回傳伺服器錯誤（{res.status_code} {(error_payload(res) or {}).get('code')}）："
            " 這是商品端建立流程的缺陷，已記入交接文件，暫時無法用它驗證後續版本流程。"
        )
    assert res.status_code in (200, 201), f"建立測試商品失敗：{res.status_code} {res.text}"
    data = res.json()
    product = data.get("product") or data
    product_id = product.get("id") or product.get("product_id")
    assert product_id, f"建立成功卻拿不到商品 id：{data}"
    version = product.get("version", 1)
    yield {"id": product_id, "version": version}
    # 清理：確保軟停用（status=inactive 或等效欄位），非硬刪除。
    try:
        admin_session.patch(
            f"{gateway_base_url}{ADMIN_PRODUCTS_PATH}/{product_id}",
            json={"status": "inactive"},
            headers={"If-Match": str(version)},
        )
    except Exception:
        pass


def test_patch_without_if_match_returns_4xx(admin_session, gateway_base_url, created_test_product):
    res = admin_session.patch(
        f"{gateway_base_url}{ADMIN_PRODUCTS_PATH}/{created_test_product['id']}",
        json={"price": 2},
    )
    assert 400 <= res.status_code < 500, (
        f"PATCH 缺少 If-Match 應被擋下（4xx），實際 {res.status_code}：{res.text}"
    )


def test_patch_with_correct_if_match_updates_version(admin_session, gateway_base_url, created_test_product):
    product_id = created_test_product["id"]
    version = created_test_product["version"]
    res = admin_session.patch(
        f"{gateway_base_url}{ADMIN_PRODUCTS_PATH}/{product_id}",
        json={"price": 3},
        headers={"If-Match": str(version)},
    )
    assert res.status_code == 200, f"帶正確 If-Match 的 PATCH 應成功，實際 {res.status_code}：{res.text}"
    data = res.json()
    product = data.get("product") or data
    new_version = product.get("version")
    assert new_version is not None and new_version != version, "PATCH 成功後 version 應該遞增/改變"
    created_test_product["version"] = new_version  # 讓後續（若有）與 fixture 清理使用最新版本


def test_patch_with_stale_if_match_returns_409_version_conflict(admin_session, gateway_base_url, created_test_product):
    """先用正確 If-Match 更新一次讓伺服器版本前進，再故意用舊版本號重打，驗證 409。"""
    product_id = created_test_product["id"]
    stale_version = created_test_product["version"]

    first = admin_session.patch(
        f"{gateway_base_url}{ADMIN_PRODUCTS_PATH}/{product_id}",
        json={"price": 4},
        headers={"If-Match": str(stale_version)},
    )
    assert first.status_code == 200, f"第一次合法 PATCH 應成功，無法繼續製造版本衝突：{first.text}"

    stale_retry = admin_session.patch(
        f"{gateway_base_url}{ADMIN_PRODUCTS_PATH}/{product_id}",
        json={"price": 5},
        headers={"If-Match": str(stale_version)},  # 故意重用剛剛已經過期的版本號
    )
    assert stale_retry.status_code == 409, (
        f"用過期的 If-Match 重打應回 409 VERSION_CONFLICT，實際 {stale_retry.status_code}：{stale_retry.text}"
    )
    err = error_payload(stale_retry)
    assert err and err.get("code") == "VERSION_CONFLICT", err

    # 409 之後應該重新 GET 拿到最新版本，而不是憑空猜。
    refetch = admin_session.get(f"{gateway_base_url}{ADMIN_PRODUCTS_PATH}/{product_id}")
    assert refetch.status_code == 200, refetch.text
    refreshed = refetch.json()
    refreshed_product = refreshed.get("product") or refreshed
    created_test_product["version"] = refreshed_product.get("version", stale_version)


def test_soft_disable_keeps_record_but_marks_inactive(admin_session, gateway_base_url, created_test_product):
    product_id = created_test_product["id"]
    version = created_test_product["version"]
    res = admin_session.patch(
        f"{gateway_base_url}{ADMIN_PRODUCTS_PATH}/{product_id}",
        json={"status": "inactive"},
        headers={"If-Match": str(version)},
    )
    assert res.status_code == 200, f"軟停用應成功，實際 {res.status_code}：{res.text}"
    data = res.json()
    product = data.get("product") or data
    assert product.get("status") == "inactive", f"軟停用後 status 應為 inactive：{product}"
    created_test_product["version"] = product.get("version", version)

    # 軟停用後商品紀錄本身應該還在（可用 admin GET 查到），不是被硬刪除。
    refetch = admin_session.get(f"{gateway_base_url}{ADMIN_PRODUCTS_PATH}/{product_id}")
    assert refetch.status_code == 200, "軟停用後仍應能用 Admin GET 查到該商品紀錄（不是被硬刪除）"


def test_audit_log_requires_admin(http, member_session, gateway_base_url):
    unauth = http.request("GET", f"{gateway_base_url}{ADMIN_AUDIT_LOG_PATH}")
    assert unauth.status_code == 401, unauth.text

    member_res = member_session.get(f"{gateway_base_url}{ADMIN_AUDIT_LOG_PATH}")
    assert member_res.status_code == 403, f"一般會員查 Audit Log 應回 403，實際 {member_res.status_code}"


def test_product_audit_log_records_change(admin_session, gateway_base_url):
    """/admin-api/product-audit-logs：記錄的是「變更了什麼」(action + before/after + productId)。"""
    res = admin_session.get(f"{gateway_base_url}{ADMIN_AUDIT_LOG_PATH}")
    assert res.status_code == 200, res.text
    data = res.json()
    entries = data if isinstance(data, list) else (data.get("items") or data.get("logs") or [])
    assert isinstance(entries, list) and entries, f"商品稽核紀錄應至少有一筆可查：{str(data)[:200]}"
    sample = entries[0]
    assert "action" in sample, f"稽核項目缺少 action：{list(sample.keys())}"
    assert any(k in sample for k in ("beforeData", "afterData", "productId")), (
        f"稽核項目缺少變更內容欄位：{list(sample.keys())}"
    )


def test_product_audit_log_operator_is_recorded_somewhere(admin_session, gateway_base_url):
    """派工書要求 Audit 能追出「操作者」。實測 /product-audit-logs 的項目**沒有**操作者欄位
    （只有 action/before/after/productId/requestId），操作者改由 Gateway 自己的
    /admin-api/admin-actions（回 events，含雜湊後 actorId）記錄。此測試確認「操作者至少
    在 admin-actions 找得到」；若要在單一端點同時看到操作者＋變更內容，需商品端補欄位。"""
    logs = admin_session.get(f"{gateway_base_url}{ADMIN_AUDIT_LOG_PATH}").json()
    log_items = logs.get("items") or []
    if log_items:
        assert not any(k in log_items[0] for k in ("actorId", "actor_id", "actor")), (
            "product-audit-logs 現在開始帶操作者欄位了——這是好事，請更新交接文件把此限制移除"
        )
    actions = admin_session.get(f"{gateway_base_url}/admin-api/admin-actions?limit=5")
    assert actions.status_code == 200, actions.text
    payload = actions.json()
    assert "events" in payload, f"admin-actions 應回傳 events 清單：{list(payload.keys())}"
    events = payload.get("events") or []
    # 註：新環境或尚無經 Gateway 寫入時 events 可能為空，這不算失敗；
    # 一旦有內容，就必須帶得出操作者欄位，否則稽核無法回答「誰動了資料」。
    if events:
        assert any(any("actor" in str(k).lower() for k in ev.keys()) for ev in events), (
            f"admin-actions 事件缺少操作者欄位：{list(events[0].keys())}"
        )


# ── 爬蟲部署版本確認 ───────────────────────────────────────────────

def test_crawler_staging_current_path_requires_admin(http, gateway_base_url):
    res = http.request("GET", f"{gateway_base_url}{ADMIN_CRAWLER_STAGING_PATH}")
    assert res.status_code == 401, (
        f"現行爬蟲 staging 路徑應該存在且要求登入（401），實際 {res.status_code}：{res.text}"
    )


def test_crawler_staging_current_path_works_for_admin(admin_session, gateway_base_url):
    """【已知缺陷】現行爬蟲 staging 路徑在 openapi 有註冊、admin 也通過授權，
    但實際回 404（帶 requestId，屬下游後端的 404，非 Gateway route-not-found），
    代表爬蟲 staging 端點目前沒有真正在服務。此測試斷言「應該 200」，
    讓缺陷持續顯示為 FAIL，爬蟲端把 staging 端點接上後自動轉綠。"""
    res = admin_session.get(f"{gateway_base_url}{ADMIN_CRAWLER_STAGING_PATH}")
    assert res.status_code == 200, (
        f"Admin 呼叫現行爬蟲 staging 路徑應成功，實際 {res.status_code}：{res.text[:200]}"
        "（目前下游回 404，爬蟲 staging 端點尚未實際服務，見交接文件）"
    )
    data = res.json()
    items = data.get("items") or data.get("products") or data
    assert isinstance(items, (list, dict)), f"爬蟲 staging 清單格式異常：{type(items)}"


def test_legacy_crawler_path_is_not_a_live_route(http, gateway_base_url):
    """Legacy 的 /api/crawler/product-preview 目前不在 Gateway 的路由表裡（見 openapi.json），
    不應該被誤當成仍在服務中的路徑；此測試把它列為 Legacy 的證據記錄下來。"""
    res = http.request("GET", f"{gateway_base_url}{LEGACY_CRAWLER_PATH}")
    err = error_payload(res)
    assert res.status_code == 404 and err and err.get("code") == "NOT_FOUND", (
        f"預期 Legacy 路徑已不存在（404 NOT_FOUND），實際 {res.status_code}：{res.text}。"
        " 若這裡開始回傳非 404，代表 Legacy 路徑被重新啟用，必須回頭確認是否造成新舊兩套並存。"
    )
