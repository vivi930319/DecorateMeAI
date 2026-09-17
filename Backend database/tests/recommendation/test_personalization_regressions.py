from recommendation import recommend_products, get_dynamic_weights


def package(season="spring", style="hongKong", generated=None):
    return {"style": style, "faceAnalysis": {"skinTone": {
        "lab": [65, 12, 19], "season": season, "labReliable": True}},
        "generativeText": generated or {}}


def test_foundation_prefers_mac_when_color_evidence_is_available():
    rows = [{"id": i, "brand": brand, "name": "粉底液", "category": "base",
             "type": "foundations", "lab": lab, "inStock": True}
            for i, brand, lab in [(1, "MAC", [70, 12, 19]), (2, "Other", [65, 12, 19])]]
    result = recommend_products(package(), rows)
    assert result["colorDifferencePolicy"]["foundationAnchor"]["brand"] == "MAC"


def test_unverified_mac_never_bypasses_color_gate():
    rows = [{"id": 1, "brand": "MAC", "name": "粉底液", "category": "base",
             "type": "foundations", "lab": [65,12,19], "inStock": True,"colorMatchReady":False},
            {"id": 2, "brand": "Other", "name": "粉底液", "category": "base",
             "type": "foundations", "lab": [65,12,19], "inStock": True,"colorMatchReady":True}]
    result = recommend_products(package(), rows)
    assert result["colorDifferencePolicy"]["foundationAnchor"]["brand"] == "Other"
    assert result["colorDifferencePolicy"]["foundationAnchor"]["preferredBrandAvailable"] is False


def test_season_changes_ranking_with_explicit_catalog_evidence():
    rows = [{"id": i, "name": "柔和棕調眼影", "category": "eye", "type": "eyeshadows",
             "seasonTags": [season], "inStock": True} for i, season in [(1, "spring"), (2, "autumn")]]
    assert recommend_products(package("spring"), rows)["products"][0]["id"] == 1
    assert recommend_products(package("autumn"), rows)["products"][0]["id"] == 2


def test_dynamic_weights_and_scores_are_bounded():
    for category in ["base", "lip", "eye", "brow"]:
        assert abs(sum(get_dynamic_weights(category, "港風").values()) - 1) < 1e-9


def test_same_face_different_style_changes_eye_selection():
    rows = [{"id": i, "name": name, "category": "eye", "type": "eyeshadows", "inStock": True}
            for i, name in [(1, "柔和棕調眼影"), (2, "玫瑰花園眼影")]]
    assert recommend_products(package(style="hongKong"), rows)["products"][0]["id"] == 1
    assert recommend_products(package(style="yandere"), rows)["products"][0]["id"] == 2


def test_text_terms_change_ranking_and_expose_real_hits():
    rows = [{"id": i, "name": name, "category": "eye", "type": "eyeshadows", "inStock": True}
            for i, name in [(1, "柔和棕調霧面眼影"), (2, "柔和棕調珠光眼影")]]
    for term, expected in [("霧面", 1), ("珠光", 2)]:
        result = recommend_products(package(generated={"finishTags": [term]}), rows)
        item = result["products"][0]
        assert item["id"] == expected
        assert item["ollamaMatch"]["matchedPreferredTerms"][0]["term"] == term
        assert item["scoreBreakdown"]["textPreferenceScore"] == item["ollamaMatch"]["preferenceScore"]


def test_low_evidence_is_not_primary_or_claimed_personal_fit():
    result = recommend_products(package(), [{"id": 1, "name": "Generic", "category": "contour",
        "type": "contouring", "inStock": True}])
    assert result["primary"] == []
    assert result["products"][0]["recommendationRole"] == "alternative"
    assert "依據有限" in result["products"][0]["recommendationPresentation"]["headline"]
