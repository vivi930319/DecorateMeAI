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

    def test_brow_without_brow_lab_never_uses_skin_lab(self):
        brow = {"id": 7, "type": "eyebrows", "category": "brow", "name": "淺棕眉彩", "inStock": True,
                "lab": [71.17, 9.14, 13.73]}
        result = recommend_products({"style": "richGirl", "faceAnalysis": {"skinTone": {"lab": [71.17, 9.14, 13.73]}}}, [brow])
        product = result["products"][0]
        self.assertEqual(product["colorMethod"], "brow_color_unavailable")
        self.assertEqual(product["scoreBreakdown"]["colorScore"], 0.5)
        self.assertEqual(result["fallbackReason"]["code"], "BROW_COLOR_UNAVAILABLE")

    def test_brow_lab_enables_ciede2000_for_brow(self):
        brow = {"id": 8, "type": "eyebrows", "category": "brow", "name": "深棕眉彩", "inStock": True,
                "lab": [30, 4, 8]}
        result = recommend_products({"style": "richGirl", "faceAnalysis": {"browLab": [30, 4, 8]}}, [brow])
        self.assertEqual(result["products"][0]["colorMethod"], "ciede2000")


if __name__ == "__main__":
    unittest.main()
