"""推薦服務契約與反向測試(用 monkeypatch 假商品,不打網路)。"""
import pytest

from recommendation import product_search, recommendation_service
from recommendation.recommendation_service import RecommendationError, recommend

_FAKE = {
    "lipsticks": [{"id": 10, "type": "lipsticks", "name": "奶茶色唇膏", "status": "active",
                   "brand": "Za", "price": 390}],
    "blushes": [{"id": 20, "type": "blushes", "name": "裸粉腮紅", "status": "active"}],
    "eyeshadows": [{"id": 30, "type": "eyeshadows", "name": "大地色眼影", "status": "active"}],
}


@pytest.fixture
def fake_db(monkeypatch):
    monkeypatch.setattr(product_search, "fetch_products",
                        lambda cat, **kw: list(_FAKE.get(cat, [])))
    # recommendation_service 是 `from . import product_search` 再呼叫,故 patch 模組屬性即可。


def _pkg(style="richGirl"):
    return {"id": "AN-1", "style": style, "faceAnalysis": {}}


def test_happy_path_shape(fake_db):
    out = recommend(_pkg(), limit=12)
    assert out["success"] is True
    recs = out["analysisPackage"]["recommendations"]
    assert recs["style"] == "千金"
    assert isinstance(recs["products"], list)
    for p in recs["products"]:
        assert {"id", "type", "name", "matchScore", "matchedKeywords"} <= set(p)


def test_accepts_style_id_and_display_name(fake_db):
    assert recommend(_pkg("richGirl"))["analysisPackage"]["recommendations"]["style"] == "千金"
    assert recommend(_pkg("千金"))["analysisPackage"]["recommendations"]["style"] == "千金"


def test_unknown_style_raises_422(fake_db):
    with pytest.raises(RecommendationError) as e:
        recommend(_pkg("notAStyle"))
    assert e.value.code == "UNKNOWN_MAKEUP_STYLE" and e.value.http == 422


def test_missing_package_raises_422(fake_db):
    with pytest.raises(RecommendationError) as e:
        recommend({"faceAnalysis": {}})  # 缺 style
    assert e.value.code == "INVALID_ANALYSIS_PACKAGE"


@pytest.mark.parametrize("bad_limit", [0, -1, 101, "5", None])
def test_invalid_limit_raises_400(fake_db, bad_limit):
    with pytest.raises(RecommendationError) as e:
        recommend(_pkg(), limit=bad_limit)
    assert e.value.code == "INVALID_REQUEST" and e.value.http == 400


def test_empty_result_is_not_error(fake_db, monkeypatch):
    monkeypatch.setattr(product_search, "fetch_products", lambda cat, **kw: [])
    out = recommend(_pkg())
    recs = out["analysisPackage"]["recommendations"]
    assert recs["products"] == [] and recs.get("code") == "RECOMMENDATION_EMPTY"


def test_db_failure_maps_to_502(fake_db, monkeypatch):
    def boom(cat, **kw):
        raise product_search.ProductDbError("商品服務回 503")
    monkeypatch.setattr(product_search, "fetch_products", boom)
    with pytest.raises(RecommendationError) as e:
        recommend(_pkg())
    assert e.value.code == "PRODUCT_DB_UNAVAILABLE" and e.value.http == 502
