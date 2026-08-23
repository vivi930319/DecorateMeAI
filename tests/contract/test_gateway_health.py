"""GET /health、GET /public-config — Gateway 自身與下游狀態，以及測試服務探活。"""


def test_health_returns_200(http, gateway_base_url):
    res = http.request("GET", f"{gateway_base_url}/health")
    assert res.status_code == 200, res.text


def test_health_response_is_json_with_service_identity(http, gateway_base_url):
    res = http.request("GET", f"{gateway_base_url}/health")
    assert res.headers.get("content-type", "").startswith("application/json"), res.headers
    data = res.json()
    assert data.get("service") == "ai-gateway", f"預期 service=ai-gateway，實際回傳：{data}"
    assert data.get("status"), f"health 回應缺少 status 欄位：{data}"


def test_public_config_ok_and_does_not_leak_upstream_urls(http, gateway_base_url):
    """/public-config 只能回同源相對路徑，不可外洩 Tunnel 網址、API Key 或任何 Secret。"""
    res = http.request("GET", f"{gateway_base_url}/public-config")
    assert res.status_code == 200, res.text
    data = res.json()
    body_text = res.text

    assert "trycloudflare.com" not in body_text, "public-config 洩漏了 Tunnel 網址"
    for forbidden in ("ADMIN_API_KEY", "apiKey", "api_key", "secret", "Secret", "faceApiKey", "renderApiKey"):
        assert forbidden not in body_text, f"public-config 疑似洩漏敏感欄位：{forbidden}"

    for key in ("memberDatabaseUrl", "productUrl", "crawlerUrl"):
        if key in data and data[key]:
            value = str(data[key])
            assert value.startswith("/") and not value.startswith("//"), (
                f"{key} 應該是同源相對路徑（以 / 開頭），實際為 {value}"
            )


def test_config_local_js_not_served_by_gateway(http, gateway_base_url):
    """本機開發用的 config.local.js 含金鑰，正式 Gateway／Hosting 都不應該公開它。"""
    res = http.request("GET", f"{gateway_base_url}/config.local.js")
    assert res.status_code != 200, "Gateway 不應該公開 config.local.js（可能外洩本機金鑰設定）"


def test_downstream_read_path_reachable_through_gateway(http, gateway_base_url):
    """統一走 Gateway：確認下游商品讀取路徑經 Gateway 同源代理可通（不直連 tunnel）。"""
    res = http.request("GET", f"{gateway_base_url}/product-api/api/products?limit=1")
    assert res.status_code == 200, f"商品讀取經 Gateway 應可通，實際 {res.status_code}：{res.text[:200]}"


def test_auth_backend_reachable_through_gateway(http, gateway_base_url):
    """會員驗證後端經 Gateway 可達：用假帳密登入應得到明確的 401 業務錯誤，
    而不是 502/503/逾時（那代表 Gateway 連不到會員後端）。"""
    res = http.request(
        "POST", f"{gateway_base_url}/auth/login",
        json={"email": "probe-not-real@example.com", "password": "x"},
    )
    assert res.status_code == 401, (
        f"會員後端應可經 Gateway 到達並回 401，實際 {res.status_code}：{res.text[:200]}"
    )
