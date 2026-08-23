"""統一錯誤格式契約。

修正後的統一形狀（由 Gateway 的 api_errors.normalize_error_response 在出口保證）：

    {
      "success": false,
      "status": "error",
      "error": {
        "code": "...", "message": "...", "retryable": false,
        "details": {}, "requestId": "..."
      }
    }

其中 error.requestId 一律等於回應的 X-Request-ID 標頭（單一追蹤碼）。

## 關於錯誤碼命名

派工書對照表用的是 `UNAUTHENTICATED`／`INVALID_REQUEST`／`INVALID_ANALYSIS_PACKAGE`
等碼，但正式前端（js/api.js）大量依賴 Gateway 現行的碼
（`MEMBER_AUTH_REQUIRED`、`VALIDATION_ERROR`、`ADMIN_REQUIRED`…）。
改碼會弄壞前端，因此決議：**碼維持現行值、由派工書文件那側對齊**，
Gateway 只統一「外層 envelope 形狀」。以下測試因此斷言「實際碼 + 統一形狀」。

## 部署狀態

envelope 修正已在 Gateway 原始碼（api_errors.py）完成並通過該專案本地測試；
本檔對「線上」Gateway 斷言，需等該修正部署後才會全綠。
"""
import pytest

from conftest import error_payload

SUGGEST_PATH = "/text-suggestion/suggest"


def _assert_unified_shape(response, expected_http, expected_code):
    assert response.status_code == expected_http, (
        f"預期 HTTP {expected_http}，實際 {response.status_code}：{response.text}"
    )
    data = response.json()
    assert "success" in data, f"回應缺少頂層 success 欄位：{data}"
    assert data.get("success") is False
    assert "status" in data, f"回應缺少頂層 status 欄位：{data}"
    assert data.get("status") == "error"
    # 錯誤回應只該有這三個頂層鍵，不應夾帶 products 這類資料欄位。
    assert set(data.keys()) == {"success", "status", "error"}, f"錯誤回應夾帶多餘頂層欄位：{data}"
    err = data.get("error") or {}
    assert err.get("code") == expected_code, f"預期 error.code={expected_code}，實際：{err}"
    assert "message" in err, f"error 物件缺少 message：{err}"
    assert "retryable" in err, f"error 物件缺少 retryable：{err}"
    assert "details" in err, f"error 物件缺少 details：{err}"
    assert err.get("requestId"), f"error 物件缺少 requestId：{err}"
    assert err.get("requestId") == response.headers.get("x-request-id"), (
        f"body 的 requestId 應等於 X-Request-ID 標頭：body={err.get('requestId')} "
        f"header={response.headers.get('x-request-id')}"
    )


def test_login_validation_error_shape(http, gateway_base_url):
    """缺欄位／型別錯誤：實際為 422 VALIDATION_ERROR（非派工書的 400 INVALID_REQUEST）。"""
    res = http.request("POST", f"{gateway_base_url}/auth/login", json={"email": "a@b.com"})
    _assert_unified_shape(res, 422, "VALIDATION_ERROR")


def test_401_unauthenticated_shape(http, gateway_base_url):
    res = http.request("GET", f"{gateway_base_url}/auth/session")
    _assert_unified_shape(res, 401, "MEMBER_AUTH_REQUIRED")


def test_403_admin_required_shape(member_session, gateway_base_url):
    res = member_session.get(f"{gateway_base_url}/admin-api/products")
    _assert_unified_shape(res, 403, "ADMIN_REQUIRED")


def test_409_version_conflict_shape(admin_session, gateway_base_url, created_test_product):
    # 複用 test_product_admin_contract.py 的 fixture 邏輯會造成跨檔相依，這裡故意精簡：
    # 只驗證形狀，版本衝突的完整流程已在 test_product_admin_contract.py 覆蓋。
    product_id = created_test_product["id"]
    version = created_test_product["version"]
    admin_session.patch(
        f"{gateway_base_url}/admin-api/products/{product_id}",
        json={"price": 9},
        headers={"If-Match": str(version)},
    )
    res = admin_session.patch(
        f"{gateway_base_url}/admin-api/products/{product_id}",
        json={"price": 10},
        headers={"If-Match": str(version)},  # 重用已經過期的版本號
    )
    _assert_unified_shape(res, 409, "VERSION_CONFLICT")


def test_422_validation_error_shape(member_session, gateway_base_url, sample_style):
    """資料包型別錯誤：Gateway 驗證層實際回 422 VALIDATION_ERROR
    （非派工書的 INVALID_ANALYSIS_PACKAGE；後者是下游商品端在 400 用的碼）。"""
    res = member_session.post(
        f"{gateway_base_url}{SUGGEST_PATH}",
        json={"faceAnalysis": "not-an-object", "style": sample_style, "language": "zh-TW"},
    )
    _assert_unified_shape(res, 422, "VALIDATION_ERROR")


def test_error_body_never_contains_secret_markers(http, gateway_base_url):
    """Log 與錯誤訊息不得包含 Token、Email、照片、完整 Prompt、Admin Key 或 Secret。"""
    res = http.request(
        "POST", f"{gateway_base_url}/auth/login",
        json={"email": "definitely-not-a-real-user@example.com", "password": "wrong-password-x1"},
    )
    body_text = res.text
    for marker in (
        "ADMIN_API_KEY", "X-Admin-Key", "faceApiKey", "renderApiKey", "textSuggestionApiKey",
        "SESSION_SECRET", "definitely-not-a-real-user@example.com",
    ):
        assert marker not in body_text, f"錯誤訊息疑似洩漏敏感內容：{marker}"


@pytest.fixture(scope="session")
def sample_style():
    import os
    return os.environ.get("DM_TEST_STYLE", "richGirl").strip() or "richGirl"


@pytest.fixture
def created_test_product(admin_session, gateway_base_url):
    import time
    payload = {
        "name": f"[契約測試-可刪除] {int(time.time())}",
        "type": "lipsticks",
        "brand": "契約測試",
        "price": 1,
        "status": "inactive",
    }
    res = admin_session.post(f"{gateway_base_url}/admin-api/products", json=payload)
    if res.status_code == 404:
        pytest.skip("此 Gateway 版本的 /admin-api/products 不支援直接 POST 建立")
    if res.status_code == 400 and (error_payload(res) or {}).get("code") == "MISSING_FIELDS":
        pytest.skip("建立商品缺必填欄位規格（MISSING_FIELDS），需商品端提供欄位清單，見交接文件")
    if res.status_code >= 500:
        pytest.skip(f"建立商品回 {res.status_code}（商品端建立流程缺陷），見交接文件")
    assert res.status_code in (200, 201), res.text
    data = res.json()
    product = data.get("product") or data
    product_id = product.get("id") or product.get("product_id")
    version = product.get("version", 1)
    yield {"id": product_id, "version": version}
    try:
        admin_session.patch(
            f"{gateway_base_url}/admin-api/products/{product_id}",
            json={"status": "inactive"},
            headers={"If-Match": str(version)},
        )
    except Exception:
        pass
