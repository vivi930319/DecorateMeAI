"""POST /v1/face/analyze/basic、POST /v1/face/analyze/pro — analysisPackage 契約。

Gateway 走同源代理：實際 URL 是 `/<gateway>/face-basic/v1/face/analyze/basic`
與 `/<gateway>/face-pro/v1/face/analyze/pro`（見 js/api.js 的 gatewayService()）。

合法測試圖片由第 2 人交付，本檔不內建任何真人臉部圖片。設定：

    $env:DM_TEST_FACE_IMAGE = "C:\\path\\to\\legit-face.jpg"

未設定時，只跑不需要真的完成分析的案例（未登入 401、缺檔案、錯型別）。
"""
import os

import pytest

from conftest import error_payload

BASIC_PATH = "/face-basic/v1/face/analyze/basic"
PRO_PATH = "/face-pro/v1/face/analyze/pro"

REQUIRED_PACKAGE_KEYS = {
    "id", "schemaVersion", "style", "faceAnalysis",
    "generativeText", "render", "recommendations",
}


@pytest.fixture(scope="session")
def test_face_image_path():
    path = os.environ.get("DM_TEST_FACE_IMAGE", "").strip()
    if not path or not os.path.isfile(path):
        pytest.skip("未設定 DM_TEST_FACE_IMAGE（或路徑不存在），略過需要合法臉部圖片的案例")
    return path


def _assert_analysis_package_shape(package):
    missing = REQUIRED_PACKAGE_KEYS - set(package.keys())
    assert not missing, f"analysisPackage 缺少必要欄位：{missing}（實際：{list(package.keys())}）"
    gen_text = package.get("generativeText") or {}
    assert "suggestion" in gen_text and "renderPromptEn" in gen_text, (
        f"generativeText 應同時保留 suggestion / renderPromptEn 兩個鍵（值可為 null）：{gen_text}"
    )
    recs = package.get("recommendations") or {}
    assert "products" in recs, f"recommendations 缺少 products 鍵：{recs}"


@pytest.mark.parametrize("path,label", [(BASIC_PATH, "BASIC"), (PRO_PATH, "PRO")])
def test_unauthenticated_returns_401(http, gateway_base_url, path, label):
    res = http.request("POST", f"{gateway_base_url}{path}", files={"file": ("x.jpg", b"not-a-real-image", "image/jpeg")})
    assert res.status_code == 401, f"{label} 未登入應回 401，實際 {res.status_code}：{res.text}"
    err = error_payload(res)
    assert err and err.get("code") == "MEMBER_AUTH_REQUIRED", err


@pytest.mark.parametrize("path,label", [(BASIC_PATH, "BASIC"), (PRO_PATH, "PRO")])
def test_missing_file_field_returns_4xx(member_session, gateway_base_url, path, label):
    """已登入但缺少必要的圖片欄位：應為明確的 4xx（缺欄位），不是 500。"""
    res = member_session.post(f"{gateway_base_url}{path}", files={})
    assert 400 <= res.status_code < 500, (
        f"{label} 缺檔案時應回 4xx，實際 {res.status_code}：{res.text}"
    )


@pytest.mark.parametrize("path,label", [(BASIC_PATH, "BASIC"), (PRO_PATH, "PRO")])
def test_wrong_content_type_field_returns_4xx(member_session, gateway_base_url, path, label):
    """檔案欄位帶非圖片內容：錯型別案例，應為明確 4xx 而非成功或 500。"""
    res = member_session.post(
        f"{gateway_base_url}{path}",
        files={"file": ("not-image.txt", b"hello world, this is not an image", "text/plain")},
    )
    assert 400 <= res.status_code < 500, (
        f"{label} 上傳非圖片內容時應回 4xx，實際 {res.status_code}：{res.text}"
    )


def test_basic_analysis_package_contract(member_session, gateway_base_url, test_face_image_path):
    with open(test_face_image_path, "rb") as fh:
        res = member_session.post(f"{gateway_base_url}{BASIC_PATH}", files={"file": fh})
    assert res.status_code == 200, f"BASIC 合法請求應成功，實際 {res.status_code}：{res.text}"
    data = res.json()
    package = data.get("analysisPackage")
    assert package, f"回應缺少 analysisPackage：{data}"
    _assert_analysis_package_shape(package)
    face_analysis = package.get("faceAnalysis")
    assert face_analysis, "BASIC 分析後 faceAnalysis 不應為空"


def test_pro_analysis_package_contract(member_session, gateway_base_url, test_face_image_path):
    with open(test_face_image_path, "rb") as fh:
        res = member_session.post(f"{gateway_base_url}{PRO_PATH}", files={"front": fh})
    assert res.status_code == 200, f"PRO 合法請求應成功，實際 {res.status_code}：{res.text}"
    data = res.json()
    package = data.get("analysisPackage")
    assert package, f"回應缺少 analysisPackage：{data}"
    _assert_analysis_package_shape(package)


def test_id_and_schema_version_and_face_analysis_not_rewritten_by_downstream(
    member_session, gateway_base_url, test_face_image_path
):
    """同一張圖打兩次 BASIC：id 理論上應各自獨立產生，但 schemaVersion 與 faceAnalysis
    的欄位結構（key 集合）不應該因為重跑而改變──代表下游沒有竄改分析結果本體。"""
    def _analyze():
        with open(test_face_image_path, "rb") as fh:
            res = member_session.post(f"{gateway_base_url}{BASIC_PATH}", files={"file": fh})
        assert res.status_code == 200, res.text
        return res.json()["analysisPackage"]

    first = _analyze()
    second = _analyze()
    assert first["schemaVersion"] == second["schemaVersion"], "schemaVersion 在兩次分析間不一致"
    assert set(first["faceAnalysis"].keys()) == set(second["faceAnalysis"].keys()), (
        "faceAnalysis 的欄位結構在兩次分析間不一致，懷疑被下游竄改"
    )
