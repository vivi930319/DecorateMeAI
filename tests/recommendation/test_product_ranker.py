"""排序:依分數排序、去重、排除停用/缺欄位/零分。"""
from recommendation.product_ranker import rank


def _p(pid, name, **extra):
    base = {"id": pid, "type": "lipsticks", "name": name, "status": "active"}
    base.update(extra)
    return base


def test_ranked_by_score_desc():
    products = [
        _p(1, "唇膏", description="奶茶"),          # 命中 1 次(desc)
        _p(2, "奶茶奶茶唇膏"),                       # 名稱命中(權重高)
    ]
    out = rank(products, ["奶茶"], limit=10)
    assert [o["id"] for o in out] == ["lipsticks:2", "lipsticks:1"]
    assert out[0]["matchScore"] == 1.0  # 最高分正規化為 1


def test_dedup_by_type_id():
    products = [_p(1, "奶茶唇膏"), _p(1, "奶茶唇膏")]
    out = rank(products, ["奶茶"], limit=10)
    assert len(out) == 1


def test_disabled_and_missing_fields_excluded():
    products = [
        _p(1, "奶茶唇膏", status="inactive"),   # 停用
        _p(2, ""),                              # 缺 name
        {"id": 3, "name": "奶茶唇膏"},           # 缺 type
        _p(4, "奶茶唇膏"),                       # 合格
    ]
    out = rank(products, ["奶茶"], limit=10)
    assert [o["id"] for o in out] == ["lipsticks:4"]


def test_zero_score_not_returned():
    out = rank([_p(1, "玫瑰唇膏")], ["奶茶"], limit=10)
    assert out == []


def test_limit_respected():
    products = [_p(i, f"奶茶唇膏{i}") for i in range(20)]
    out = rank(products, ["奶茶"], limit=5)
    assert len(out) == 5


def test_output_has_contract_fields():
    out = rank([_p(1, "奶茶唇膏", brand="Za", price=390)], ["奶茶"], limit=1)
    item = out[0]
    for f in ("id", "type", "name", "brand", "price", "matchScore", "matchedKeywords"):
        assert f in item
