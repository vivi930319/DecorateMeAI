import unittest

from recommendation import AnalysisContractError, recommend_products


class RecommendationContractTests(unittest.TestCase):
    candidate = {
        "id": 123, "type": "lipsticks", "category": "lip", "name": "水光緞光唇彩",
        "brand": "Demo", "description": "千金 水光", "specs": "緞光",
        "styleTags": ["luxury"], "inStock": True, "price": 1200,
    }

    def test_style_id_and_display_name_are_equivalent(self):
        base = {"faceAnalysis": {}}
        by_id = recommend_products({**base, "style": "richGirl"}, [self.candidate])
        by_name = recommend_products({**base, "style": "千金"}, [self.candidate])
        self.assertEqual(by_id["products"][0]["candidateKey"], by_name["products"][0]["candidateKey"])
        self.assertEqual(by_id["products"][0]["matchScore"], by_name["products"][0]["matchScore"])

    def test_unknown_style_is_rejected(self):
        with self.assertRaisesRegex(AnalysisContractError, "UNKNOWN_MAKEUP_STYLE"):
            recommend_products({"style": "not-a-style", "faceAnalysis": {}}, [self.candidate])

    def test_incomplete_or_disabled_product_is_not_returned(self):
        bad = {"id": 99, "category": "lip", "name": "", "inStock": False}
        result = recommend_products({"style": "richGirl", "faceAnalysis": {}}, [bad])
        self.assertEqual(result["products"], [])

    def test_result_is_deterministic_and_exposes_contract_fields(self):
        package = {"style": "richGirl", "faceAnalysis": {}}
        first = recommend_products(package, [self.candidate])
        second = recommend_products(package, [self.candidate])
        self.assertEqual(first["products"], second["products"])
        item = first["products"][0]
        self.assertIn("matchedKeywords", item)
        self.assertIn("matchScore", item)
        presentation = item["recommendationPresentation"]
        self.assertEqual(presentation["systemLabel"], "根據臉部分析結果")
        self.assertNotIn("AI", presentation["systemLabel"])
        self.assertTrue(item["displayScore"])
        self.assertIsInstance(item["matchScore"], float)
        self.assertIsInstance(item["matchPercent"], int)
        self.assertEqual(item["matchPercent"], presentation["matchPercent"])
        self.assertIn("推薦契合度", item["recommendationLabel"])

    def test_ollama_terms_are_exposed_globally_and_per_product(self):
        package = {
            "style": "richGirl", "faceAnalysis": {},
            "generativeText": {
                "preferredColors": ["水光"], "finishTags": ["緞光"],
                "avoidColors": ["冷紫"],
            },
        }
        result = recommend_products(package, [self.candidate])
        self.assertEqual(result["personalizationInputs"]["ollamaPreferredTerms"], ["水光", "緞光"])
        self.assertEqual(result["personalizationInputs"]["ollamaAvoidedTerms"], ["冷紫"])
        match = result["products"][0]["ollamaMatch"]
        self.assertEqual([row["term"] for row in match["matchedPreferredTerms"]], ["水光", "緞光"])
        self.assertEqual(match["matchedAvoidedTerms"], [])
        self.assertEqual(match["preferenceScore"], 0.86)
        # 理由要同時講出「命中哪個詞」與「配上哪個風格」，例如
        # 「「水光」與你所選的千金匹配（命中商品描述）。」
        reason_texts = result["products"][0]["recommendationPresentation"]["reasonTexts"]
        self.assertTrue(any("水光" in text and "千金" in text and "你所選的" in text
                            for text in reason_texts), reason_texts)
        # 結構化欄位讓前端可自行組句，不必解析中文字串。
        self.assertEqual(match["matchedStyle"], "千金")
        self.assertEqual(match["matchedPreferredTerms"][0]["matchedStyle"], "千金")
        self.assertEqual(match["matchedPreferredTerms"][0]["termSource"],
                         "analysisPackage.generativeText")

    def test_brow_without_brow_lab_is_normal_style_ranking(self):
        brow = {"id": 7, "type": "eyebrows", "category": "brow", "name": "淺棕眉彩", "inStock": True,
                "lab": [71.17, 9.14, 13.73]}
        result = recommend_products({"style": "richGirl", "faceAnalysis": {"skinTone": {"lab": [71.17, 9.14, 13.73]}}}, [brow])
        product = result["products"][0]
        self.assertEqual(product["colorMethod"], "style_only")
        self.assertTrue(product["displayScore"])
        self.assertIsInstance(product["matchPercent"], int)
        self.assertIsNotNone(product["scoreBreakdown"])
        self.assertFalse(any(reason["code"] == "BROW_COLOR_UNAVAILABLE" for reason in result["fallbackReasons"]))
        self.assertNotIn("膚色", product["matchReason"])
        self.assertEqual(result["primary"], [])
        self.assertEqual(product["recommendationRole"], "alternative")

    def test_brow_lab_is_not_used_because_brow_is_style_only(self):
        brow = {"id": 8, "type": "eyebrows", "category": "brow", "name": "深棕眉彩", "inStock": True,
                "lab": [30, 4, 8]}
        result = recommend_products({"style": "richGirl", "faceAnalysis": {"browLab": [30, 4, 8]}}, [brow])
        self.assertEqual(result["products"][0]["colorMethod"], "style_only")

    def test_arched_brow_shape_affects_brow_ranking_without_brow_lab(self):
        natural = {
            "id": 31, "type": "eyebrows", "category": "brow",
            "name": "自然柔和精細眉筆", "description": "細芯 precision soft natural",
            "inStock": True,
        }
        lifting = {
            "id": 32, "type": "eyebrows", "category": "brow",
            "name": "高眉峰拉提眉筆", "description": "lifting high arch 上揚",
            "inStock": True,
        }
        result = recommend_products(
            {"style": "richGirl", "faceAnalysis": {"faceShape": "oval", "browShape": "arched"}},
            [lifting, natural],
        )
        natural_result = next(item for item in result["products"] if item["id"] == 31)
        self.assertIn("挑眉", natural_result["recommendationPresentation"]["suitedTraits"])
        self.assertEqual(natural_result["colorMethod"], "style_only")
        lifting_result = next(item for item in result["products"] if item["id"] == 32)
        self.assertEqual(natural_result["matchScore"], lifting_result["matchScore"])

    def test_only_foundation_and_lip_use_input_color(self):
        eye = {"id": 60, "type": "eyeshadows", "category": "eye", "name": "自然眼影",
               "tags": ["luxury"], "lab": [20, 60, 40], "inStock": True}
        first = recommend_products(
            {"style": "richGirl", "faceAnalysis": {"skinTone": {"lab": [20, 60, 40]}}}, [eye]
        )["products"][0]
        second = recommend_products(
            {"style": "richGirl", "faceAnalysis": {"skinTone": {"lab": [90, -20, -20]}}}, [eye]
        )["products"][0]
        self.assertEqual(first["matchScore"], second["matchScore"])
        self.assertEqual(first["colorMethod"], "style_only")
        self.assertEqual(first["recommendationPresentation"]["comparisonBasis"], "makeup_style")
        self.assertIsNone(first["recommendationPresentation"]["colorDifferenceExplanation"])

        foundation = {"id": 61, "type": "foundations", "category": "base", "name": "粉底",
                      "lab": [65, 8, 14], "inStock": True}
        close = recommend_products(
            {"style": "richGirl", "faceAnalysis": {"skinTone": {"lab": [65, 8, 14]}}}, [foundation]
        )["products"][0]
        far_result = recommend_products(
            {"style": "richGirl", "faceAnalysis": {"skinTone": {"lab": [20, -40, -40]}}}, [foundation]
        )
        self.assertEqual(len(far_result["products"]), 1)
        self.assertEqual(far_result["foundationMatchStatus"]["status"], "closest_available")
        self.assertEqual(far_result["foundationMatchStatus"]["code"], "FOUNDATION_CLOSEST_AVAILABLE")
        self.assertTrue(far_result["products"][0]["displayScore"])
        self.assertIn("請以實際至實體專櫃試色", far_result["foundationMatchStatus"]["message"])
        self.assertEqual(far_result["colorDifferencePolicy"]["foundationSkinMatch"]["maxInclusive"], 2.0)
        self.assertTrue(close["foundationSkinMatch"]["accepted"])
        self.assertEqual(close["recommendationPresentation"]["comparisonBasis"], "skin_tone")
        self.assertIn("粉底會覆蓋大面積肌膚", close["recommendationPresentation"]
                      ["comparisonExplanation"]["text"])
        foundation_explanation = close["recommendationPresentation"]["colorDifferenceExplanation"]
        self.assertEqual(foundation_explanation["metric"], "CIEDE2000")
        self.assertEqual(foundation_explanation["comparisonTarget"], "膚色與粉底色號")
        self.assertEqual(foundation_explanation["acceptanceRule"]["maxInclusive"], 2.0)
        self.assertEqual(len(foundation_explanation["qa"]), 4)
        self.assertIn("請以實際至實體專櫃試色", close["recommendationPresentation"]["disclaimer"])

        lipstick = {"id": 62, "type": "lipsticks", "category": "lip", "name": "唇彩",
                    "lab": [45, 35, 20], "inStock": True}
        lip = recommend_products(
            {"style": "richGirl", "faceAnalysis": {"lipLab": [45, 35, 20]}}, [lipstick]
        )["products"][0]
        self.assertEqual(lip["colorMethod"], "style_only")
        self.assertEqual(lip["recommendationPresentation"]["comparisonBasis"], "makeup_style")
        self.assertIsNone(lip["recommendationPresentation"]["colorDifferenceExplanation"])
        self.assertTrue(lip["displayScore"])
        self.assertIsInstance(lip["matchPercent"], int)
        self.assertIsNotNone(lip["score"])
        self.assertIsNotNone(lip["scoreBreakdown"])
        self.assertNotIn("唇色色差", str(lip))

    def test_low_contour_score_still_has_a_recommendation_fit_percent(self):
        contour = {
            "id": 63, "type": "contouring", "category": "contour",
            "name": "一般修容", "tags": [], "inStock": True,
        }
        item = recommend_products(
            {"style": "richGirl", "faceAnalysis": {"faceShape": "oval"}}, [contour]
        )["products"][0]
        self.assertTrue(item["displayScore"])
        self.assertIn("推薦契合度", item["recommendationLabel"])
        self.assertIsInstance(item["matchPercent"], int)
        self.assertIsNotNone(item["matchScore"])
        self.assertIsNotNone(item["scoreBreakdown"])

    def test_explicit_brand_and_budget_preferences_are_explainable(self):
        candidate = {**self.candidate, "type": "eyeshadows", "category": "eye",
                     "brand": "Preferred", "price": "NT$800"}
        result = recommend_products(
            {"style": "richGirl", "faceAnalysis": {}}, [candidate],
            recommendation_options={
                "preferredBrands": ["Preferred"],
                "pricePreference": {"min": 500, "max": 1000, "mode": "value"},
            },
        )
        item = result["products"][0]
        self.assertTrue(result["personalization"]["applied"])
        self.assertEqual(item["scoreBreakdown"]["priceFit"], 1.0)
        self.assertEqual(item["scoreBreakdown"]["brandAffinity"], 1.0)

    def test_server_behavior_profile_is_blended_without_identity_input(self):
        candidate = {**self.candidate, "type": "eyeshadows", "category": "eye", "brand": "Demo"}
        result = recommend_products(
            {"style": "richGirl", "faceAnalysis": {}}, [candidate],
            behavior_profile={
                "interactionCount": 5,
                "categoryAffinities": {"eye": 1.0},
                "brandAffinities": {"demo": 1.0},
            },
        )
        self.assertTrue(result["personalization"]["applied"])
        self.assertEqual(result["personalization"]["behaviorWeight"], 0.15)
        self.assertEqual(result["products"][0]["scoreBreakdown"]["behaviorScore"], 1.0)

    def test_bad_skin_lab_is_marked_unreliable(self):
        foundation = {**self.candidate, "id": 20, "type": "foundations", "category": "base"}
        result = recommend_products({"style": "richGirl", "faceAnalysis": {
            "skinTone": {"lab": [999, -999, 999], "labReliable": True, "season": "warm"}
        }}, [foundation])
        self.assertFalse(result["skinToneLabReliable"])
        self.assertEqual(result["fallbackReasons"][0]["code"], "SKIN_TONE_LAB_UNRELIABLE")
        self.assertEqual(result["products"], [])
        self.assertEqual(result["foundationMatchStatus"]["status"], "unavailable")

    def test_closest_foundation_is_always_displayed_with_recommendation_fit_percent(self):
        foundation = {
            "id": 21, "type": "foundations", "category": "base",
            "brand": "Demo", "name": "Demo Foundation - Main", "shadeCode": "Main",
            "lab": [70.0, 10.5, 16.0], "inStock": True,
        }
        result = recommend_products({"style": "richGirl", "faceAnalysis": {
            "skinTone": {"lab": [72.5, 12.1, 18.3], "labReliable": True}
        }}, [foundation])
        self.assertEqual(result["foundationMatchStatus"]["status"], "closest_available")
        self.assertEqual(result["foundationMatchStatus"]["code"], "FOUNDATION_CLOSEST_AVAILABLE")
        self.assertIn("資料庫目前沒有", result["foundationMatchStatus"]["message"])
        self.assertIn("請以實際至實體專櫃試色", result["foundationMatchStatus"]["message"])
        self.assertEqual(len(result["products"]), 1)
        displayed = result["products"][0]
        self.assertFalse(displayed["foundationSkinMatch"]["accepted"])
        self.assertTrue(displayed["foundationSkinMatch"]["displayEligible"])
        self.assertEqual(displayed["foundationSkinMatch"]["displayStatus"], "closest_available")
        self.assertTrue(displayed["recommendationPresentation"]["showMatchPercent"])
        self.assertIn("推薦契合度", displayed["recommendationPresentation"]["matchLabel"])
        self.assertIsInstance(displayed["matchPercent"], int)
        self.assertIsNone(result["colorDifferencePolicy"]["foundationClosestAvailable"]["maxInclusive"])
        # 未達嚴格門檻時仍必須回三色階：使用者需要方向感，空白回應沒有幫助。
        # 改以最接近的粉底當錨點，並標示這是 closest_available 而非合格配對。
        ladder = result["shadeRecommendation"]
        self.assertIsNotNone(ladder)
        self.assertEqual(ladder["matchTier"], "closest_available")
        self.assertFalse(ladder["strictAnchorAvailable"])
        self.assertEqual(ladder["anchor"]["shadeCode"], "Main")
        # 這個案例只有一支粉底，因此沒有可比的淺／深色階——不可硬補。
        self.assertIsNone(ladder["lighter"])
        self.assertIsNone(ladder["darker"])

    def test_explicit_unreliable_lab_is_respected(self):
        foundation = {
            "id": 25, "type": "foundations", "category": "base",
            "brand": "Demo", "name": "Demo Foundation", "shadeCode": "N20",
            "lab": [70.0, 10.0, 18.0], "inStock": True,
        }
        result = recommend_products({"style": "richGirl", "faceAnalysis": {
            "skinTone": {"lab": [70.0, 10.0, 18.0], "labReliable": False}
        }}, [foundation])

        self.assertFalse(result["skinToneLabReliable"])
        self.assertEqual(result["foundationMatchStatus"]["status"], "unavailable")
        self.assertTrue(any(reason["code"] == "SKIN_TONE_LAB_UNRELIABLE"
                            for reason in result["fallbackReasons"]))

    def test_mac_anchors_primary_and_closer_brand_stays_a_cross_brand_option(self):
        # 規格：MAC 是主推薦錨點（給前端_商品與推薦正式接口_2026-08-30 §5.1）。
        # 別的品牌數值上更接近時不會取代主推薦，但必須仍以跨品牌選項提供，
        # 使用者才能自己換品牌看最相近色號。
        mac = {
            "id": 26, "type": "foundations", "category": "base",
            "brand": "MAC", "name": "MAC Foundation", "shadeCode": "NC30",
            "lab": [70.0, 10.0, 18.8], "inStock": True,
        }
        numerically_closer_other_brand = {
            "id": 27, "type": "foundations", "category": "base",
            "brand": "Other", "name": "Other Foundation", "shadeCode": "O1",
            "lab": [70.0, 10.0, 19.0], "inStock": True,
        }
        result = recommend_products({"style": "richGirl", "faceAnalysis": {
            "skinTone": {"lab": [70.0, 10.0, 19.0], "labReliable": True}
        }}, [numerically_closer_other_brand, mac])

        foundations = [item for item in result["products"] if item["category"] == "base"]
        self.assertEqual(foundations[0]["brand"], "MAC")
        self.assertEqual(result["foundationMatchStatus"]["anchorBrand"], "MAC")
        self.assertEqual(result["colorDifferencePolicy"]["foundationAnchor"]["mode"],
                         "mac_first_verified")
        self.assertIn(("Other", "O1"),
                      [(item.get("brand"), item.get("shadeCode"))
                       for item in result["foundationCrossBrandAlternatives"]])

    def test_nearest_is_not_automatically_lightened_and_drives_cross_brand_matches(self):
        candidates = [
            {"id": 260, "type": "foundations", "category": "base", "brand": "MAC",
             "name": "Studio Fix - N20", "shadeCode": "N20", "seriesId": "MAC::studio",
             "depthIndex": 4, "depthIndexOfficial": False,
             "lab": [70.0, 10.0, 18.0], "inStock": True},
            {"id": 261, "type": "foundations", "category": "base", "brand": "MAC",
             "name": "Studio Fix - N18", "shadeCode": "N18", "seriesId": "MAC::studio",
             "depthIndex": 3, "depthIndexOfficial": False,
             "lab": [71.5, 10.0, 18.0], "inStock": True},
            {"id": 263, "type": "foundations", "category": "base", "brand": "MAC",
             "name": "Studio Fix - N16", "shadeCode": "N16", "seriesId": "MAC::studio",
             "depthIndex": 2, "depthIndexOfficial": False,
             "lab": [73.0, 10.0, 18.0], "inStock": True},
            {"id": 264, "type": "foundations", "category": "base", "brand": "MAC",
             "name": "Studio Fix - N14", "shadeCode": "N14", "seriesId": "MAC::studio",
             "depthIndex": 1, "depthIndexOfficial": False,
             "lab": [74.5, 10.0, 18.0], "inStock": True},
            {"id": 262, "type": "foundations", "category": "base", "brand": "MAC",
             "name": "Studio Fix - N25", "shadeCode": "N25", "seriesId": "MAC::studio",
             "depthIndex": 5, "depthIndexOfficial": False,
             "lab": [67.0, 10.0, 18.0], "inStock": True},
            {"id": 270, "type": "foundations", "category": "base", "brand": "YSL",
             "name": "YSL Foundation - LN4", "shadeCode": "LN4", "seriesId": "YSL::allhours",
             "depthIndex": 2, "lab": [71.4, 10.1, 18.1], "inStock": True},
        ]

        result = recommend_products({"style": "richGirl", "faceAnalysis": {
            "skinTone": {"lab": [70.0, 10.0, 18.0], "labReliable": True}
        }}, candidates)

        foundation = next(item for item in result["products"] if item["category"] == "base")
        self.assertEqual(foundation["shadeCode"], "N20")
        self.assertEqual(foundation["foundationSkinMatch"]["deltaE"], 0.0)
        self.assertEqual(result["shadeRecommendation"]["anchor"]["shadeCode"], "N20")
        self.assertEqual(result["shadeRecommendation"]["lighter"]["shadeCode"], "N18")
        ysl = next(item for item in result["foundationCrossBrandAlternatives"] if item["brand"] == "YSL")
        self.assertEqual(ysl["comparisonAnchor"]["shadeCode"], "N20")

    def test_mac_lighter_calibration_never_crosses_n_nc_nw_undertone_lanes(self):
        # In the real Studio Fix family, N16 and NW7 are near each other in a
        # Lab-lightness sort but differ by ΔE00 about 9.2.  They are not one
        # another's adjacent shade.  The safer N16 -> N18 hop is allowed.
        candidates = [
            {"id": 300, "type": "foundations", "category": "base", "brand": "MAC",
             "name": "Studio Fix - N16", "shadeCode": "N16", "seriesId": "MAC::studio",
             "depthIndex": 12, "lab": [77.65, 4.0, 19.0], "inStock": True},
            {"id": 301, "type": "foundations", "category": "base", "brand": "MAC",
             "name": "Studio Fix - NW7", "shadeCode": "NW7", "seriesId": "MAC::studio",
             "depthIndex": 11, "lab": [78.43, 14.0, 20.0], "inStock": True},
            {"id": 302, "type": "foundations", "category": "base", "brand": "MAC",
             "name": "Studio Fix - N18", "shadeCode": "N18", "seriesId": "MAC::studio",
             "depthIndex": 8, "lab": [80.39, 7.0, 15.0], "inStock": True},
        ]

        result = recommend_products({"style": "richGirl", "faceAnalysis": {
            "skinTone": {"lab": [77.65, 4.0, 19.0], "labReliable": True}
        }}, candidates)

        foundation = next(item for item in result["products"] if item["category"] == "base")
        self.assertEqual(foundation["shadeCode"], "N16")
        self.assertNotEqual(foundation["shadeCode"], "NW7")

    def test_nw7_primary_keeps_same_series_and_same_brand_foundation_alternatives(self):
        candidates = [
            {"id": 330, "type": "foundations", "category": "base", "brand": "MAC",
             "name": "Studio Fix 粉底液 - NW7", "shadeCode": "NW7", "seriesId": "MAC::studio",
             "lab": [78.4, 14.0, 20.0], "inStock": True},
            {"id": 331, "type": "foundations", "category": "base", "brand": "MAC",
             "name": "Studio Fix 粉底液 - NW10", "shadeCode": "NW10", "seriesId": "MAC::studio",
             "lab": [76.8, 13.0, 19.0], "inStock": True},
            {"id": 332, "type": "foundations", "category": "base", "brand": "MAC",
             "name": "超持妝濾鏡粉底液 - N12", "shadeCode": "N12", "seriesId": "MAC::filter",
             "lab": [77.1, 10.0, 18.0], "inStock": True},
            {"id": 333, "type": "foundations", "category": "base", "brand": "Other",
             "name": "Other Foundation", "shadeCode": "LIGHT", "seriesId": "Other::one",
             "lab": [78.3, 14.0, 20.0], "inStock": True},
        ]

        result = recommend_products({"style": "richGirl", "faceAnalysis": {
            "skinTone": {"lab": [78.4, 14.0, 20.0], "labReliable": True}
        }}, candidates, limit=4,
            recommendation_options={"foundationShadePreference": "closest_skin_match"})

        foundations = [item for item in result["products"] if item["category"] == "base"]
        self.assertEqual(foundations[0]["shadeCode"], "NW7")
        self.assertIn("NW10", [item["shadeCode"] for item in foundations])
        self.assertIn("N12", [item["shadeCode"] for item in foundations])
        # 跨品牌選項自 2026-08-30 起獨立成 foundationCrossBrandAlternatives，
        # 不再混進清單主體；清單只留主推薦與同品牌色階，避免首次載入過重。
        self.assertNotIn("LIGHT", [item["shadeCode"] for item in foundations])
        self.assertIn(("Other", "LIGHT"),
                      [(item.get("brand"), item.get("shadeCode"))
                       for item in result["foundationCrossBrandAlternatives"]])
        statuses = {item["shadeCode"]: item["foundationSkinMatch"]["displayStatus"]
                    for item in foundations}
        self.assertEqual(statuses["NW10"], "same_series_alternative")
        self.assertEqual(statuses["N12"], "same_brand_alternative")

    def test_far_raw_anchor_is_not_forced_to_a_lighter_shade(self):
        candidates = [
            {"id": 310, "type": "foundations", "category": "base", "brand": "MAC",
             "name": "Studio Fix - N16", "shadeCode": "N16", "seriesId": "MAC::studio",
             "depthIndex": 12, "lab": [77.65, 4.0, 19.0], "inStock": True},
            {"id": 311, "type": "foundations", "category": "base", "brand": "MAC",
             "name": "Studio Fix - N18", "shadeCode": "N18", "seriesId": "MAC::studio",
             "depthIndex": 8, "lab": [80.39, 7.0, 15.0], "inStock": True},
        ]

        result = recommend_products({"style": "richGirl", "faceAnalysis": {
            "skinTone": {"lab": [68.0, 4.0, 19.0], "labReliable": True}
        }}, candidates)

        foundation = next(item for item in result["products"] if item["category"] == "base")
        self.assertEqual(foundation["shadeCode"], "N16")
        self.assertEqual(result["foundationMatchStatus"]["status"], "closest_available")

    def test_mac_liquid_foundation_outranks_a_closer_dot_pen(self):
        candidates = [
            {"id": 280, "type": "foundations", "category": "base", "brand": "MAC",
             "name": "超持妝全能點點筆 - NC15", "shadeCode": "NC15",
             "seriesId": "MAC::dot-pen", "depthIndex": 1,
             "lab": [70.0, 10.0, 18.0], "inStock": True},
            {"id": 281, "type": "foundations", "category": "base", "brand": "MAC",
             "name": "超持妝濾鏡粉底液 - NC15", "shadeCode": "NC15",
             "seriesId": "MAC::liquid", "depthIndex": 1,
             "lab": [70.8, 10.0, 18.0], "inStock": True},
        ]

        result = recommend_products({"style": "richGirl", "faceAnalysis": {
            "skinTone": {"lab": [70.0, 10.0, 18.0], "labReliable": True}
        }}, candidates)

        foundation = next(item for item in result["products"] if item["category"] == "base")
        self.assertIn("粉底液", foundation["name"])

    def test_strict_foundation_matches_are_ranked_by_smallest_delta_e(self):
        farther_first = {
            "id": 22, "type": "foundations", "category": "base",
            "brand": "Earlier Brand", "name": "Earlier Foundation",
            "shadeCode": "EARLY", "lab": [70.0, 10.0, 18.0], "inStock": True,
        }
        closer_second = {
            "id": 23, "type": "foundations", "category": "base",
            "brand": "Closer Brand", "name": "Closer Foundation",
            "shadeCode": "CLOSE", "lab": [70.0, 10.0, 20.0], "inStock": True,
        }

        result = recommend_products(
            {"style": "richGirl", "faceAnalysis": {
                "skinTone": {"lab": [70.0, 10.0, 20.2], "labReliable": True}
            }},
            [farther_first, closer_second],
        )

        self.assertTrue(all(item["foundationSkinMatch"]["accepted"]
                            for item in result["products"]))
        self.assertEqual(result["products"][0]["shadeCode"], "CLOSE")
        self.assertEqual(result["shadeRecommendation"]["anchor"]["shadeCode"], "CLOSE")
        self.assertGreater(result["products"][0]["scoreBreakdown"]["colorScore"],
                           result["products"][1]["scoreBreakdown"]["colorScore"])
        self.assertNotIn("_foundationDeltaE", result["products"][0])

    def test_avoided_brand_is_hard_filtered(self):
        other = {**self.candidate, "id": 124, "brand": "Other"}
        result = recommend_products(
            {"style": "richGirl", "faceAnalysis": {}}, [self.candidate, other],
            recommendation_options={"avoidedBrands": ["Demo"]},
        )
        self.assertEqual([item["brand"] for item in result["products"]], ["Other"])

    def test_avoid_tag_in_product_text_reduces_score(self):
        package = {"style": "richGirl", "faceAnalysis": {}, "generativeText": {
            "styleTags": ["luxury"], "avoidTags": ["glitter"]}}
        plain = {**self.candidate, "id": 130, "type": "eyeshadows", "category": "eye",
                 "name": "matte eye color"}
        glitter = {**self.candidate, "id": 131, "type": "eyeshadows", "category": "eye",
                   "name": "glitter eye color"}
        result = recommend_products(package, [plain, glitter])
        scores = {item["id"]: item["scoreBreakdown"]["styleScore"] for item in result["products"]}
        self.assertLess(scores[131], scores[130])

    def test_invalid_preferences_are_rejected(self):
        with self.assertRaisesRegex(AnalysisContractError, "INVALID_REQUEST"):
            recommend_products({"style": "richGirl", "faceAnalysis": {}}, [self.candidate],
                               recommendation_options={"pricePreference": {"min": 1000, "max": 100}})
        with self.assertRaisesRegex(AnalysisContractError, "INVALID_REQUEST"):
            recommend_products({"style": "richGirl", "faceAnalysis": {}}, [self.candidate],
                               recommendation_options={"preferredBrands": [str(i) for i in range(21)]})

    def test_identity_fields_are_rejected_recursively(self):
        with self.assertRaisesRegex(AnalysisContractError, "IDENTITY_DATA_NOT_ALLOWED"):
            recommend_products({"style": "richGirl", "faceAnalysis": {"photoBase64": "data"}}, [self.candidate])
        with self.assertRaisesRegex(AnalysisContractError, "IDENTITY_DATA_NOT_ALLOWED"):
            recommend_products({"style": "richGirl", "faceAnalysis": {}}, [self.candidate],
                               recommendation_options={"token": "secret"})

    def test_official_foundation_depth_returns_adjacent_shades_in_same_series(self):
        foundations = [
             {"id": 201, "type": "foundations", "category": "base", "brand": "Brand A", "name": "F10",
             "shadeCode": "10", "seriesId": "brand-a-foundation", "depthIndex": 10,
             "lab": [69, 8, 14], "inStock": True},
            {"id": 202, "type": "foundations", "category": "base", "brand": "Brand A", "name": "F20",
             "shadeCode": "20", "seriesId": "brand-a-foundation", "depthIndex": 20,
             "lab": [65, 8, 14], "inStock": True},
             {"id": 203, "type": "foundations", "category": "base", "brand": "Brand A", "name": "F30",
             "shadeCode": "30", "seriesId": "brand-a-foundation", "depthIndex": 30,
             "lab": [61, 8, 14], "inStock": True},
            {"id": 204, "type": "foundations", "category": "base", "brand": "Other", "name": "Other",
             "shadeCode": "X", "seriesId": "other-series", "depthIndex": 15,
             "lab": [64, 8, 14], "inStock": True},
        ]
        result = recommend_products(
            {"style": "richGirl", "faceAnalysis": {"skinTone": {"lab": [65, 8, 14]}}},
            foundations,
        )
        shades = result["shadeRecommendation"]
        self.assertEqual(shades["method"], "official_depth_index")
        self.assertEqual(shades["anchor"]["shadeCode"], "20")
        self.assertEqual(shades["lighter"]["label"], "淺一階")
        self.assertEqual(shades["lighter"]["shadeCode"], "10")
        self.assertEqual(shades["lighter"]["depthIndex"], 10)
        self.assertIsInstance(shades["lighter"]["matchScore"], float)
        self.assertEqual(shades["darker"]["label"], "深一階")
        self.assertEqual(shades["darker"]["shadeCode"], "30")
        self.assertEqual(shades["alternativeMaxDeltaE"], 5.0)

    def test_official_adjacent_shade_also_respects_delta_e_cap(self):
        foundations = [
            {"id": 205, "type": "foundations", "category": "base", "brand": "Brand A", "name": "F10",
             "shadeCode": "10", "seriesId": "brand-a-foundation", "depthIndex": 10,
             "lab": [66, 28, 34], "inStock": True},
            {"id": 206, "type": "foundations", "category": "base", "brand": "Brand A", "name": "F20",
             "shadeCode": "20", "seriesId": "brand-a-foundation", "depthIndex": 20,
             "lab": [65, 8, 14], "inStock": True},
            {"id": 207, "type": "foundations", "category": "base", "brand": "Brand A", "name": "F30",
             "shadeCode": "30", "seriesId": "brand-a-foundation", "depthIndex": 30,
             "lab": [64, -12, -6], "inStock": True},
        ]
        result = recommend_products(
            {"style": "richGirl", "faceAnalysis": {"skinTone": {"lab": [65, 8, 14]}}},
            foundations,
        )
        shades = result["shadeRecommendation"]
        self.assertEqual(shades["method"], "official_depth_index")
        self.assertEqual(shades["anchor"]["shadeCode"], "20")
        # 官方相鄰色階即使色差偏大仍要回傳——它就是品牌自己定義的上下一階。
        # 以 withinAlternativeCap=False 告知前端跨度較大，而不是讓三色階留空。
        self.assertEqual(shades["lighter"]["shadeCode"], "10")
        self.assertFalse(shades["lighter"]["withinAlternativeCap"])
        self.assertEqual(shades["darker"]["shadeCode"], "30")
        self.assertFalse(shades["darker"]["withinAlternativeCap"])

    def test_lab_fallback_does_not_claim_official_adjacent_shade(self):
        foundations = [
            {"id": 211, "type": "foundations", "category": "base", "brand": "Demo",
             "name": "Demo Foundation - Light", "shadeCode": "Light",
             "lab": [68, 8, 14], "inStock": True},
            {"id": 212, "type": "foundations", "category": "base", "brand": "Demo",
             "name": "Demo Foundation - Main", "shadeCode": "Main",
             "lab": [65, 8, 14], "inStock": True},
            {"id": 213, "type": "foundations", "category": "base", "brand": "Demo",
             "name": "Demo Foundation - Deep", "shadeCode": "Deep",
             "lab": [62, 8, 14], "inStock": True},
        ]
        result = recommend_products(
            {"style": "richGirl", "faceAnalysis": {"skinTone": {"lab": [65, 8, 14]}}},
            foundations,
        )
        shades = result["shadeRecommendation"]
        self.assertEqual(shades["method"], "lab_lightness_approximation")
        # 沒有品牌官方色階時不得冒稱「淺一階／深一階」，只能說是相近色參考。
        self.assertEqual(shades["lighter"]["label"], "較淺相近色")
        self.assertEqual(shades["darker"]["label"], "較深相近色")
        self.assertFalse(shades["lighter"]["officialShadeLadder"])
        self.assertFalse(shades["depthReferencePolicy"]["officialShadeLadder"])
        self.assertEqual(shades["selectionScope"], "same_brand_any_series_then_cross_brand")
        self.assertEqual(shades["lighter"]["scope"], "same_brand_any_series")
        self.assertEqual(shades["alternativeMaxDeltaE"], 5.0)
        self.assertLessEqual(shades["lighter"]["anchorDeltaE"], 5.0)
        self.assertLessEqual(shades["darker"]["anchorDeltaE"], 5.0)
        self.assertFalse(shades["lighter"]["product"]["foundationSkinMatch"]["accepted"])
        self.assertFalse(shades["darker"]["product"]["foundationSkinMatch"]["accepted"])
        self.assertEqual([item["shadeCode"] for item in result["products"]], ["Main"])
        self.assertEqual(result["colorDifferencePolicy"]["foundationSkinMatch"]["maxInclusive"], 2.0)
        self.assertEqual(result["colorDifferencePolicy"]["shadeAlternative"]["maxInclusive"], 5.0)

    def test_lab_fallback_prefers_same_brand_across_series_before_other_brands(self):
        # 系列是上架時的資料切分，不是顏色事實：同品牌的另一條產品線可以比。
        # 同品牌該方向沒有色號時才跨品牌，並以 scope 標明來源。
        foundations = [
            {"id": 221, "type": "foundations", "category": "base", "brand": "Brand A",
             "name": "Foundation Alpha - Main", "shadeCode": "Main",
             "lab": [65, 8, 14], "inStock": True},
            {"id": 222, "type": "foundations", "category": "base", "brand": "Brand B",
             "name": "Foundation Alpha - Light", "shadeCode": "Light",
             "lab": [66.5, 8, 14], "inStock": True},
            {"id": 223, "type": "foundations", "category": "base", "brand": "Brand A",
             "name": "Foundation Beta - Deep", "shadeCode": "Deep",
             "lab": [63, 8, 14], "inStock": True},
        ]
        result = recommend_products(
            {"style": "richGirl", "faceAnalysis": {"skinTone": {"lab": [65, 8, 14]}}},
            foundations,
        )
        shades = result["shadeRecommendation"]
        self.assertEqual(shades["anchor"]["shadeCode"], "Main")
        # 同品牌只有較深的色號，較深就取同品牌跨系列的 Beta。
        self.assertEqual(shades["darker"]["shadeCode"], "Deep")
        self.assertEqual(shades["darker"]["scope"], "same_brand_any_series")
        # 較淺方向同品牌沒有色號，才退而取別的品牌，且標明是跨品牌。
        self.assertEqual(shades["lighter"]["shadeCode"], "Light")
        self.assertEqual(shades["lighter"]["scope"], "cross_brand")

    def test_lab_fallback_rejects_shades_whose_undertone_does_not_match(self):
        foundations = [
            {"id": 231, "type": "foundations", "category": "base", "brand": "Demo",
             "name": "Demo Foundation - Main", "shadeCode": "Main",
             "lab": [65, 8, 14], "inStock": True},
            {"id": 232, "type": "foundations", "category": "base", "brand": "Demo",
             "name": "Demo Foundation - Light", "shadeCode": "Light",
             "lab": [66, 28, 34], "inStock": True},
            {"id": 233, "type": "foundations", "category": "base", "brand": "Demo",
             "name": "Demo Foundation - Deep", "shadeCode": "Deep",
             "lab": [64, -12, -6], "inStock": True},
        ]
        result = recommend_products(
            {"style": "richGirl", "faceAnalysis": {"skinTone": {"lab": [65, 8, 14]}}},
            foundations,
        )
        shades = result["shadeRecommendation"]
        # 較淺／較深先看冷暖：明度只差 1，底調卻完全不同的色號不是另一階，
        # 給了反而會讓使用者買到換底調的粉底。這裡寧可留空。
        self.assertIsNone(shades["lighter"])
        self.assertIsNone(shades["darker"])

    def test_limit_exhaustion_is_not_reported_as_missing_database_data(self):
        categories = [
            ("foundations", "base"), ("lipsticks", "lip"), ("eyeshadows", "eye"),
            ("blushes", "blush"), ("contouring", "contour"),
            ("highlighters", "highlight"), ("eyebrows", "brow"),
            ("other", "other"),
        ]
        candidates = [{
            "id": 400 + index, "type": product_type, "coverageCategory": product_type,
            "category": category, "name": f"商品 {index}", "inStock": True,
        } for index, (product_type, category) in enumerate(categories)]
        next(item for item in candidates if item["category"] == "base")["lab"] = [65, 8, 14]
        result = recommend_products(
            {"style": "richGirl", "faceAnalysis": {"skinTone": {"lab": [65, 8, 14]}}},
            candidates, limit=5,
        )
        self.assertEqual(result["coverage"]["returned"], len({item["type"] for item in result["products"]}))
        self.assertEqual(result["coverage"]["returned"], 5)
        self.assertTrue(result["coverage"]["skipped"])
        self.assertTrue(all(reason == "本次 limit 已用完，未涵蓋此類別"
                            for reason in result["coverage"]["skipped"].values()))


if __name__ == "__main__":
    unittest.main()
