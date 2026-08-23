"""爬蟲 SSRF 與現行流程（第 5 人派工書 §爬蟲／staging、§爬蟲安全）。

**重要現況（實測 + 前端註解確認）**:目前系統沒有任何「接收 URL 去抓取」的線上端點,
所以 SSRF 防護（擋 localhost／私網／Metadata IP、redirect 重驗、URL 長度…）**無從觸發測試**:

- 舊的即時抓取 `/crawler/search-preview` 已下線（js/router.js:4702「已下線」）→ 實測 404。
- 爬蟲自 2026-07-28 起「只寫 crawler_staging_products,不再即時擷取」(js/router.js:4914)。
- 現行 staging 端點 `/admin-api/crawler-staging/products` 實測回 404 NOT_FOUND（尚未實際服務,
  前端註解:「商品後端尚未回覆最終路徑」)。

因此 SSRF 的自動化測試在目前部署下只能 SKIP。真正要測 SSRF,需第 5 人／商品端提供一個
會接收 URL 的端點（新流程的擷取入口),屆時再補下方 _SSRF_TARGETS 的實測。
"""
import pytest

from conftest import code_of

SEARCH_PREVIEW = "/admin-api/crawler/search-preview"
STAGING = "/admin-api/crawler-staging/products"
LEGACY_PREVIEW = "/api/crawler/product-preview"

# 一旦有了「接收 URL 抓取」的端點,把 (method, path, body_key) 填進來,下面的 SSRF 測試就會啟用。
_SSRF_TARGETS: list = []


def test_legacy_realtime_crawl_endpoint_is_offline(admin_session, gateway_base_url):
    """即時抓取端點已下線:應為 404,不是還活著。"""
    res = admin_session.request(
        "POST", f"{gateway_base_url}{SEARCH_PREVIEW}",
        json={"url": "http://169.254.169.254/latest/meta-data/"},
    )
    assert res.status_code == 404, (
        f"預期 search-preview 已下線（404）,實際 {res.status_code}:若它復活,必須立刻補 SSRF 測試"
    )


def test_legacy_product_preview_is_gone(http, gateway_base_url):
    res = http.request("GET", f"{gateway_base_url}{LEGACY_PREVIEW}")
    assert res.status_code == 404 and code_of(res) == "NOT_FOUND", (
        f"Legacy /api/crawler/product-preview 應已移除（404 NOT_FOUND）,實際 {res.status_code}"
    )


def test_current_staging_endpoint_state(admin_session, gateway_base_url):
    """【已知缺陷】現行 staging 路徑管理員呼叫回 404、尚未實際服務。
    此測試斷言它應該 200,讓缺陷持續顯示為 FAIL,爬蟲/商品端接上後自動轉綠。"""
    res = admin_session.request("GET", f"{gateway_base_url}{STAGING}")
    assert res.status_code == 200, (
        f"現行爬蟲 staging 端點應可服務（200）,實際 {res.status_code} {code_of(res)}:"
        "端點尚未接上,見交接文件"
    )


@pytest.mark.skipif(not _SSRF_TARGETS,
                    reason="目前無任何『接收 URL 抓取』的線上端點,SSRF 無從觸發;"
                           "需第 5 人/商品端提供擷取入口後才能測")
@pytest.mark.parametrize("blocked_url", [
    "http://169.254.169.254/latest/meta-data/",  # GCP/AWS metadata
    "http://localhost/",
    "http://127.0.0.1/",
    "http://10.0.0.1/",
    "http://192.168.1.1/",
    "file:///etc/passwd",
    "gopher://127.0.0.1:6379/",
])
def test_ssrf_blocks_private_and_metadata(admin_session, gateway_base_url, blocked_url):
    """一旦有擷取端點:內網/保留/Metadata IP 與非 http(s) 協定都要被擋（422 PRIVATE_URL_BLOCKED）。"""
    method, path, body_key = _SSRF_TARGETS[0]
    res = admin_session.request(method, f"{gateway_base_url}{path}", json={body_key: blocked_url})
    assert res.status_code == 422, f"{blocked_url} 應被擋（422）,實際 {res.status_code}"
    assert code_of(res) in ("PRIVATE_URL_BLOCKED", "INVALID_URL"), code_of(res)
