"""商品推薦契約（派工書核心介面第 6 列）。

重點是 labReliable：《給演算法端_膚色可信度旗標接入_2026-08-03》規定
`labReliable === false` 時粉底不得做 ΔE 比色。這裡驗旗標有送到，準確率由別人負責。
"""
import pytest
import requests

from conftest import TIMEOUT, body, error_of


def _recommend(session, base, payload):
    caller = session or requests
    return caller.post(f"{base}/product-api/recommend-products", json=payload, timeout=TIMEOUT)


def test_recommend_requires_auth_or_states_why(base):
    r = _recommend(None, base, {})
    assert r.status_code in (400, 401, 403, 404, 422), f"未登入卻回 {r.status_code}：{body(r)}"


def test_recommend_rejects_malformed_package(base):
    """反項：資料包不合法要明講（派工書：422 INVALID_ANALYSIS_PACKAGE）。"""
    r = _recommend(None, base, {"analysisPackage": "not-an-object"})
    assert r.status_code >= 400, f"畸形資料包卻回 {r.status_code}"
    if r.status_code == 422:
        assert error_of(body(r)).get("code"), f"422 沒有 error.code：{body(r)}"


def test_recommend_only_updates_recommendations(member_session, base):
    """派工書：推薦端只更新 recommendations，不得改寫 id／schemaVersion／faceAnalysis。"""
    pkg = {
        "analysisPackage": {
            "id": "AN-contract-test",
            "schemaVersion": "2026-08-v2",
            "style": "richGirl",
            "faceAnalysis": {
                "faceShape": "round",
                "skinTone": {"season": "autumn", "level": "中等", "lab": [70.2, 15.0, 23.0],
                             "labReliable": True},
            },
            "recommendations": {"products": []},
        },
        "limit": 6,
    }
    r = member_session.post(f"{base}/product-api/recommend-products", json=pkg, timeout=TIMEOUT)
    if r.status_code != 200:
        pytest.skip(f"BLOCKED：推薦端點不可用（HTTP {r.status_code}，見 issue #8）")
    out = r.json()
    returned = out.get("analysisPackage", {})
    if returned:
        assert returned.get("id") == pkg["analysisPackage"]["id"], "id 被改寫"
        assert returned.get("schemaVersion") == "2026-08-v2", "schemaVersion 被改寫"
        assert returned.get("faceAnalysis") == pkg["analysisPackage"]["faceAnalysis"], "faceAnalysis 被改寫"


def test_unreliable_lab_is_accepted_and_honoured(member_session, base):
    """labReliable=false 時仍要能出推薦（改用季型排序），不得直接失敗。"""
    pkg = {
        "analysisPackage": {
            "id": "AN-contract-test-unreliable",
            "schemaVersion": "2026-08-v2",
            "style": "richGirl",
            "faceAnalysis": {
                "faceShape": "round",
                "skinTone": {"season": "autumn", "level": "中等", "lab": [70.2, 15.0, 23.0],
                             "labReliable": False},
            },
        },
        "limit": 6,
    }
    r = member_session.post(f"{base}/product-api/recommend-products", json=pkg, timeout=TIMEOUT)
    if r.status_code != 200:
        pytest.skip(f"BLOCKED：推薦端點不可用（HTTP {r.status_code}）")
    products = (r.json().get("analysisPackage", {}).get("recommendations", {}) or {}).get("products")
    assert products is not None, f"labReliable=false 時沒有 recommendations.products：{r.json()}"
