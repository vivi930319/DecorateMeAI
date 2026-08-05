"""Gateway 與下游可達性（派工書核心介面第 1 列）。

派工書寫著「Quick Tunnel 重啟會換網址，測試前先呼叫 GET /health」——所以下游
連不上時要判 BLOCKED 並指出網址過期，不能報成服務壞掉。
"""
import requests

from conftest import TIMEOUT, body


def test_gateway_health(gateway):
    r = requests.get(f"{gateway}/health", timeout=TIMEOUT)
    assert r.status_code == 200, f"Gateway /health 回 {r.status_code}: {body(r)}"


def test_public_config_shape(base):
    """前端啟動時讀這支決定要打哪裡；缺欄位會讓整個前端沒有下游可用。"""
    r = requests.get(f"{base}/public-config", timeout=TIMEOUT)
    assert r.status_code == 200
    cfg = r.json()
    for key in ("apiMode", "memberDatabaseUrl", "productUrl", "crawlerUrl"):
        assert key in cfg, f"public-config 缺 {key}：{cfg}"


def test_public_config_carries_no_secret(base):
    """派工書：前端不可含 ADMIN_API_KEY 或 X-Admin-Key。"""
    text = requests.get(f"{base}/public-config", timeout=TIMEOUT).text
    lowered = text.lower()
    for forbidden in ("admin_api_key", "x-admin-key", "adminkey", "secret", "password"):
        assert forbidden not in lowered, f"public-config 疑似外洩 {forbidden}"


def test_downstream_reachable_or_reported(base):
    """逐一記錄下游狀態。這支不判失敗，它的用途是讓報告寫得出 BLOCKED 的對象。"""
    results = {}
    for name, path in (("member-database", "/member-database/health"),
                       ("product-api", "/product-api/api/products"),
                       ("text-suggestion", "/text-suggestion/health"),
                       ("render-service", "/render-service/health")):
        try:
            results[name] = requests.get(f"{base}{path}", timeout=TIMEOUT).status_code
        except Exception as exc:
            results[name] = f"連不上: {type(exc).__name__}"
    print("\n下游狀態：")
    for k, v in results.items():
        print(f"  {k:<18} {v}")
    assert results, "沒有取得任何下游狀態"
