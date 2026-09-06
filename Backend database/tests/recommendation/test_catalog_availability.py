import unittest
from unittest.mock import patch

import app as app_module
from app import (_attach_foundation_shades, _catalog_availability_sets, _price_for_frontend,
                 _catalog_item_is_publishable, cat_to_product_category,
                 recommendation_candidates, _cross_brand_shade_presentation)


class CatalogAvailabilityTests(unittest.TestCase):
    def test_cross_brand_shade_match_always_exposes_a_percentage(self):
        presentation = _cross_brand_shade_presentation(8.3)
        self.assertEqual(presentation["matchPercent"], 67)
        self.assertTrue(presentation["displayScore"])
        self.assertEqual(presentation["recommendationLabel"], "推薦契合度 67%")

    def test_foreign_catalog_price_is_returned_as_disclosed_twd_conversion(self):
        price = _price_for_frontend(100, "USD")
        self.assertEqual(price["amount"], 3169.0)
        self.assertEqual(price["currency"], "TWD")
        self.assertTrue(price["converted"])
        self.assertEqual(price["conversion"]["originalCurrency"], "USD")
        self.assertIn("本站依臺灣銀行", price["note"])
        self.assertEqual(price["conversion"]["calculation"], "US$100.00 × 31.685 = NT$3,169")

    def test_twd_catalog_price_is_not_marked_as_converted(self):
        price = _price_for_frontend(1200, "TWD")
        self.assertEqual(price["display"], "NT$1,200")
        self.assertFalse(price["converted"])
        self.assertIsNone(price["conversion"])

    def test_chinese_eyebrow_catalog_labels_use_brow_display_policy(self):
        self.assertEqual(cat_to_product_category("眉毛彩妝"), "brow")
        self.assertEqual(cat_to_product_category("染眉膏"), "brow")

    def test_source_and_global_catalog_references_are_distinct(self):
        sources, global_ids = _catalog_availability_sets([
            {"id": 9001, "type": "lipsticks", "sourceId": 2813},
            {"id": 9002, "type": "foundations", "sourceId": 42},
        ])
        self.assertIn(("lipsticks", 2813), sources)
        self.assertNotIn(("lipsticks", 901), sources)
        self.assertIn(9001, global_ids)
        self.assertNotIn(2813, global_ids)

    def test_foundation_payload_includes_complete_ordered_shade_family(self):
        rows = [
            {"id": 12, "sourceId": 102, "type": "foundations", "seriesId": "MAC::studio",
             "shadeCode": "NC20", "shadeName": "NC20", "depthIndex": 1,
             "lab": [76.0, 7.0, 16.0], "hex_primary": "#d6b69a", "imageUrl": "two.png", "inStock": True,
             "colorRepresentation": "single"},
            {"id": 11, "sourceId": 101, "type": "foundations", "seriesId": "MAC::studio",
             "shadeCode": "NC15", "shadeName": "NC15", "depthIndex": 0,
             "lab": [81.0, 6.0, 14.0], "hex_primary": "#e4c6aa", "imageUrl": "one.png", "inStock": True,
             "colorRepresentation": "single"},
            {"id": 13, "sourceId": 103, "type": "lipsticks", "seriesId": None},
        ]

        _attach_foundation_shades(rows)

        self.assertEqual([shade["shadeCode"] for shade in rows[0]["shades"]], ["NC15", "NC20"])
        self.assertEqual(rows[0]["shadeCount"], 2)
        self.assertFalse(rows[0]["depthIndexOfficial"])
        self.assertEqual(rows[0]["shadeOrderSource"], "lab_lightness")
        self.assertEqual(rows[0]["shades"][0]["lab"], [81.0, 6.0, 14.0])
        self.assertNotIn("shades", rows[2])

    def test_colourless_foundation_is_not_attached_to_shade_family(self):
        rows = [{
            "id": 14, "type": "foundations", "seriesId": "NARS::primer",
            "shadeCode": "ONE-SIZE", "shadeName": "官方單一規格",
            "depthIndex": None, "lab": None, "hex_primary": None,
            "colorRepresentation": "not_applicable",
        }]

        _attach_foundation_shades(rows)

        self.assertNotIn("shadeCount", rows[0])
        self.assertNotIn("depthIndexOfficial", rows[0])

    def test_eyeliner_may_publish_without_a_colour_but_lipstick_may_not(self):
        complete = {
            "status": "active", "reviewStatus": "approved", "name": "Official item",
            "brand": "Demo", "description": "Official description",
            "imageUrl": "https://example.com/item.png",
            "sourceUrl": "https://example.com/item", "salePageId": "item-1",
            "category": "眼線/睫毛", "currency": "TWD", "sku": "SKU-1",
            "sourceProductId": "SOURCE-1", "priceValue": 500,
            "shadeName": "", "shadeCode": None,
            "colorRepresentation": "official_name_only",
        }

        self.assertTrue(_catalog_item_is_publishable({**complete, "type": "eyeliner_mascara"}))
        self.assertFalse(_catalog_item_is_publishable({**complete, "type": "lipsticks"}))

    def test_sensitive_catalog_product_needs_complete_shade_identity_and_verified_colour(self):
        foundation = {
            "status": "active", "reviewStatus": "approved", "name": "Official foundation",
            "brand": "MAC", "description": "Official description",
            "imageUrl": "https://example.com/item.png", "sourceUrl": "https://example.com/item",
            "salePageId": "official-foundation-n15", "category": "底妝", "currency": "TWD",
            "sku": "SKU-N15", "sourceProductId": "SOURCE-N15", "priceValue": 1500,
            "type": "foundations", "shadeName": "N15", "shadeCode": "N15",
            "colorRepresentation": "single",
        }
        self.assertTrue(_catalog_item_is_publishable(foundation))
        self.assertFalse(_catalog_item_is_publishable({**foundation, "shadeCode": ""}))
        self.assertFalse(_catalog_item_is_publishable({**foundation, "colorRepresentation": "official_name_only"}))
        self.assertFalse(_catalog_item_is_publishable({**foundation, "sourceUrl": ""}))

    @patch.object(app_module, "_catalog_rows")
    def test_recommendation_candidates_use_catalog_projection(self, catalog_rows):
        catalog_rows.return_value = [{
            "id": 9002,
            "sourceId": 42,
            "type": "foundations",
            "candidateKey": "foundations:42",
            "name": "Test Foundation - N20",
            "brand": "Test Brand",
            "price": "NT$1,200",
            "description": "Test product",
            "imageUrl": "https://example.com/foundation.png",
            "sourceUrl": "https://example.com/foundation",
            "salePageId": "test-foundation-n20",
            "category": "foundations",
            "seasonTags": [],
            "undertone": "neutral",
            "shadeCode": "N20",
            "shadeName": "N20",
            "seriesId": "test-series",
            "depthIndex": 2,
            "hex_primary": "#d4a07c",
            "lab": [70.0, 10.0, 20.0],
            "inStock": True,
            "status": "active",
            "reviewStatus": "approved",
            "recommendationReady": True,
        }]

        candidates = recommendation_candidates()

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["id"], 9002)
        self.assertEqual(candidates[0]["category"], "base")
        self.assertEqual(candidates[0]["coverageCategory"], "foundations")
        self.assertEqual(candidates[0]["shadeCode"], "N20")


if __name__ == "__main__":
    unittest.main()
