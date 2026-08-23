"""POST /recommend-products（或 Gateway 現行路由）— recommendations.products 契約。

實際 URL 經 Gateway 同源代理：`/<gateway>/product-api/recommend-products`
（見 js/api.js `ApiConfig.services.product`）。

**已用真實請求驗證的落差**：`/product-api/{path}` 在 openapi.json 裡的
operationId 是 `public_product_proxy`，Gateway 對它整條前綴都不做登入
閘門檢查（跟 face-basic／face-pro／text-suggestion／render-service 用
的 `/{service}/{path}` 不同，那條會在轉發前先擋 401）。實測結果：
未登入打 `/product-api/recommend-products` 且缺少 faceAnalysis 時，
回傳的是 400 `INVALID_ANALYSIS_PACKAGE`（先驗證 body），不是 401。
派工書「未登入應為 401」的通則因此在這條路由不成立，需要跟推薦端
owner（第 3 人）確認這是刻意設計成公開端點，還是遺漏了登入檢查。
"""
import os

import pytest

from conftest import error_payload

RECOMMEND_PATH = "/product-api/recommend-products"
_MINIMAL_FACE_ANALYSIS = {"faceShape": "oval", "skinTone": {"L": 60, "a": 10, "b": 15}}


@pytest.fixture(scope="session")
def sample_style():
    return os.environ.get("DM_TEST_STYLE", "richGirl").strip() or "richGirl"


def test_unauthenticated_with_valid_body_is_not_gateway_auth_gated(http, gateway_base_url, sample_style):
    """記錄實際行為：product-api 前綴是 Public Product Proxy，Gateway 層不擋未登入請求。
    這裡不斷言「應該」401 或 200——只確認它不是被籠統地當成內部錯誤（500），
    並把「未登入到底能不能打通」的判定留給下面兩個更精確的案例。"""
    res = http.request(
        "POST", f"{gateway_base_url}{RECOMMEND_PATH}",
        json={"faceAnalysis": _MINIMAL_FACE_ANALYSIS, "style": sample_style},
    )
    assert res.status_code != 401, (
        "若這裡開始回 401，代表 Gateway 已經改成替 product-api 前綴加上登入閘門，"
        "本檔其餘「不需要登入」的假設要一併重新確認"
    )
    assert res.status_code < 500, f"不應該是未預期的伺服器錯誤：{res.status_code} {res.text}"


def test_unauthenticated_missing_face_analysis_returns_400_invalid_analysis_package(http, gateway_base_url, sample_style):
    res = http.request(
        "POST", f"{gateway_base_url}{RECOMMEND_PATH}",
        json={"style": sample_style},
    )
    # 2026-08-14：商品／推薦端把輸入驗證失敗統一改成 422（他們同批把
    # PRODUCT_VALIDATION_FAILED 也定為 422），語意上 422 比 400 更精確——
    # 請求本身格式正確，是內容不符合語意規則。
    #
    # 錯誤碼才是這個測試真正要守住的契約，狀態碼接受 400 或 422 兩種。
    assert res.status_code in (400, 422), (
        f"缺少 faceAnalysis 應回 400／422，實際 {res.status_code}：{res.text}"
    )
    err = error_payload(res)
    assert err and err.get("code") == "INVALID_ANALYSIS_PACKAGE", err


def test_missing_style_returns_4xx(member_session, gateway_base_url):
    res = member_session.post(
        f"{gateway_base_url}{RECOMMEND_PATH}",
        json={"faceAnalysis": _MINIMAL_FACE_ANALYSIS},
    )
    assert 400 <= res.status_code < 500, f"缺少 style 應回 4xx，實際 {res.status_code}：{res.text}"


def test_wrong_type_style_returns_4xx(member_session, gateway_base_url):
    res = member_session.post(
        f"{gateway_base_url}{RECOMMEND_PATH}",
        json={"faceAnalysis": _MINIMAL_FACE_ANALYSIS, "style": 12345},
    )
    assert 400 <= res.status_code < 500, f"style 型別錯誤應回 4xx，實際 {res.status_code}：{res.text}"


def test_recommendation_response_shape(member_session, gateway_base_url, sample_style):
    res = member_session.post(
        f"{gateway_base_url}{RECOMMEND_PATH}",
        json={"faceAnalysis": _MINIMAL_FACE_ANALYSIS, "style": sample_style},
    )
    # 實測：即使帶了 faceAnalysis，最小骨架仍被以 400 INVALID_ANALYSIS_PACKAGE 拒絕，
    # 代表推薦端要的 faceAnalysis 欄位比這裡的骨架多。合法資料包需第 2／3 人交付。
    # 2026-08-14：推薦端把輸入驗證失敗從 400 改成 422（同批把 PRODUCT_VALIDATION_FAILED
    # 也定為 422）。這個 skip 判斷只認 400，改版後就不再觸發，測試變成硬失敗——
    # 但情況其實沒變：最小骨架仍然被拒絕。狀態碼兩種都要認。
    if res.status_code in (400, 422) and (error_payload(res) or {}).get("code") == "INVALID_ANALYSIS_PACKAGE":
        pytest.skip(
            "推薦端以 INVALID_ANALYSIS_PACKAGE 拒絕最小 faceAnalysis 骨架。"
            " 需要第 2／3 人交付合法的 faceAnalysis／analysisPackage 測試資料後才能測 happy-path。"
        )
    assert res.status_code == 200, f"合法請求應成功，實際 {res.status_code}：{res.text}"
    data = res.json()
    products = data.get("recommendations", {}).get("products") if "recommendations" in data else data.get("products")
    assert products is not None, f"回應找不到 recommendations.products（或頂層 products）：{list(data.keys())}"
    assert isinstance(products, list), f"products 應為陣列，實際型別：{type(products)}"
    for item in products[:5]:
        assert isinstance(item, dict), f"products 陣列元素應為物件：{item!r}"
        assert item.get("id") is not None, f"推薦商品缺少 id：{item}"


def test_recommendation_only_touches_recommendations_field(member_session, gateway_base_url, sample_style):
    """推薦端只該更新 recommendations；把同一包 analysisPackage 送進去，其餘欄位不應被改寫。"""
    package_probe = {
        "id": "AN-contract-probe",
        "schemaVersion": "2026-06-v1",
        "style": sample_style,
        "faceAnalysis": _MINIMAL_FACE_ANALYSIS,
        "generativeText": {"suggestion": None, "renderPromptEn": None},
        "render": {},
        "recommendations": {"products": []},
    }
    res = member_session.post(
        f"{gateway_base_url}{RECOMMEND_PATH}",
        json={"analysisPackage": package_probe, "faceAnalysis": _MINIMAL_FACE_ANALYSIS, "style": sample_style},
    )
    if res.status_code == 404:
        pytest.skip("此 Gateway 版本的 /recommend-products 不接受 analysisPackage 直傳，改用純 faceAnalysis+style 呼叫")
    # 2026-08-14：推薦端把輸入驗證失敗從 400 改成 422（同批把 PRODUCT_VALIDATION_FAILED
    # 也定為 422）。這個 skip 判斷只認 400，改版後就不再觸發，測試變成硬失敗——
    # 但情況其實沒變：最小骨架仍然被拒絕。狀態碼兩種都要認。
    if res.status_code in (400, 422) and (error_payload(res) or {}).get("code") == "INVALID_ANALYSIS_PACKAGE":
        pytest.skip("推薦端以 INVALID_ANALYSIS_PACKAGE 拒絕此資料包，需第 2／3 人交付合法測試資料")
    assert res.status_code == 200, res.text
    data = res.json()
    returned_package = data.get("analysisPackage")
    if not returned_package:
        pytest.skip("回應沒有回傳完整 analysisPackage，無法比對欄位是否被下游竄改")
    assert returned_package["id"] == package_probe["id"], "推薦端不該改寫 analysisPackage.id"
    assert returned_package["schemaVersion"] == package_probe["schemaVersion"], "推薦端不該改寫 schemaVersion"
    assert returned_package["faceAnalysis"] == package_probe["faceAnalysis"], "推薦端不該改寫 faceAnalysis"
    # 2026-08-14：商品端交付的契約是「保留 id／schemaVersion／faceAnalysis，只更新
    # recommendations」——**沒有承諾把 generativeText／render 原樣回傳**，實測它們確實
    # 不在回應裡（原本這裡直接 `returned_package["generativeText"]` 會 KeyError）。
    #
    # 前端不依賴這個回聲（它自己保有完整資料包，只讀 recommendations），
    # 所以不當成失敗；但「有回就不能被改掉」這條仍然要守，否則哪天開始回錯的值就沒人發現。
    for field in ("generativeText", "render"):
        if field in returned_package:
            assert returned_package[field] == package_probe[field], f"推薦端不該改寫 {field}"
