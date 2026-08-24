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

    def test_brow_without_brow_lab_is_normal_style_ranking(self):
        brow = {"id": 7, "type": "eyebrows", "category": "brow", "name": "淺棕眉彩", "inStock": True,
                "lab": [71.17, 9.14, 13.73]}
        result = recommend_products({"style": "richGirl", "faceAnalysis": {"skinTone": {"lab": [71.17, 9.14, 13.73]}}}, [brow])
        product = result["products"][0]
        self.assertEqual(product["colorMethod"], "brow_color_unavailable")
        self.assertEqual(product["scoreBreakdown"]["colorScore"], 0.5)
        self.assertFalse(any(reason["code"] == "BROW_COLOR_UNAVAILABLE" for reason in result["fallbackReasons"]))
        self.assertNotIn("膚色", product["matchReason"])
        self.assertEqual(result["primary"][0]["type"], "eyebrows")

    def test_brow_lab_enables_ciede2000_for_brow(self):
        brow = {"id": 8, "type": "eyebrows", "category": "brow", "name": "深棕眉彩", "inStock": True,
                "lab": [30, 4, 8]}
        result = recommend_products({"style": "richGirl", "faceAnalysis": {"browLab": [30, 4, 8]}}, [brow])
        self.assertEqual(result["products"][0]["colorMethod"], "ciede2000")

    def test_explicit_brand_and_budget_preferences_are_explainable(self):
        candidate = {**self.candidate, "brand": "Preferred", "price": "NT$800"}
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
        candidate = {**self.candidate, "category": "lip", "brand": "Demo"}
        result = recommend_products(
            {"style": "richGirl", "faceAnalysis": {}}, [candidate],
            behavior_profile={
                "interactionCount": 5,
                "categoryAffinities": {"lip": 1.0},
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
        plain = {**self.candidate, "id": 130, "name": "matte eye color"}
        glitter = {**self.candidate, "id": 131, "name": "glitter eye color"}
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


if __name__ == "__main__":
    unittest.main()
