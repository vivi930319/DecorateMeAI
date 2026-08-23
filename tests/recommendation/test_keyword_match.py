"""關鍵字計分:名稱/tags/描述/規格命中的加權。"""
from recommendation.keyword_loader import CATEGORIES, keywords_for, load_keywords
from recommendation.product_ranker import score_product


def test_example_whitelist_loads_and_has_seven_styles():
    wl = load_keywords()  # 退回 example 佔位
    assert len(wl) == 7
    for cats in wl.values():
        assert set(cats.keys()) == set(CATEGORIES)


def test_name_hit_scores_higher_than_description_hit():
    kw = ["奶茶"]
    by_name = {"id": 1, "type": "lipsticks", "name": "奶茶色唇膏", "description": ""}
    by_desc = {"id": 2, "type": "lipsticks", "name": "唇膏", "description": "奶茶調"}
    s_name, m_name = score_product(by_name, kw)
    s_desc, _ = score_product(by_desc, kw)
    assert s_name > s_desc > 0
    assert m_name == ["奶茶"]


def test_no_match_returns_zero():
    s, matched = score_product(
        {"id": 1, "type": "blushes", "name": "玫瑰腮紅", "description": ""}, ["奶茶", "大地色"])
    assert s == 0.0 and matched == []


def test_tags_field_counts():
    s, matched = score_product(
        {"id": 3, "type": "eyeshadows", "name": "眼影", "styleTags": ["大地色", "霧面"]},
        ["大地色"])
    assert s > 0 and "大地色" in matched


def test_keywords_for_missing_category_is_empty():
    wl = load_keywords()
    assert keywords_for(wl, "千金", "eyeshadows")           # 有
    assert keywords_for(wl, "不存在的妝容", "lipsticks") == []  # 無
