import unittest
from unittest.mock import patch

import app as app_module


def foundation(product_id, brand, lab, shade, ready=True):
    return {
        "id": product_id,
        "sourceId": product_id + 1000,
        "type": "foundations",
        "candidateKey": f"foundations:{product_id + 1000}",
        "name": f"{brand} Foundation {shade}",
        "brand": brand,
        "shadeCode": shade,
        "shadeName": shade,
        "seriesId": f"{brand}::series",
        "lab": lab,
        "inStock": True,
        "status": "active",
        "reviewStatus": "approved",
        "recommendationReady": ready,
    }


class CrossBrandShadeMatchTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        self.source = foundation(10, "MAC", [70.0, 10.0, 15.0], "NC25")

    @patch.object(app_module, "_catalog_rows")
    @patch.object(app_module, "_catalog_item_by_id")
    def test_target_brand_returns_nearest_shades_by_full_delta_e(self, by_id, rows):
        by_id.return_value = self.source
        closest = foundation(20, "YSL", [70.1, 10.0, 15.0], "LN4")
        farther = foundation(21, "YSL", [72.0, 10.0, 15.0], "LN5")
        other_brand = foundation(30, "CHANEL", [70.0, 10.0, 15.0], "B30")
        same_brand = foundation(11, "MAC", [70.0, 10.0, 15.0], "NC25-alt")
        not_ready = foundation(22, "YSL", [70.0, 10.0, 15.0], "TEST", ready=False)
        rows.return_value = [self.source, farther, same_brand, other_brand, not_ready, closest]

        response = self.client.get("/api/products/10/shade-matches?targetBrand=ysl&limit=5")

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["comparisonMethod"], "CIEDE2000")
        self.assertEqual(body["source"]["shadeCode"], "NC25")
        self.assertEqual(body["availableTargetBrands"], ["CHANEL", "YSL"])
        self.assertEqual([item["id"] for item in body["items"]], [20, 21])
        self.assertEqual(body["totalCandidates"], 2)
        self.assertTrue(body["items"][0]["shadeMatch"]["displayScore"])

    @patch.object(app_module, "_catalog_rows")
    @patch.object(app_module, "_catalog_item_by_id")
    def test_low_confidence_match_still_exposes_percentage(self, by_id, rows):
        by_id.return_value = self.source
        distant = foundation(20, "YSL", [90.0, 50.0, 50.0], "Distant")
        rows.return_value = [self.source, distant]

        response = self.client.get("/api/products/10/shade-matches")

        match = response.get_json()["items"][0]["shadeMatch"]
        self.assertTrue(match["displayScore"])
        self.assertIsInstance(match["matchPercent"], int)
        self.assertEqual(match["recommendationLabel"], f"推薦契合度 {match['matchPercent']}%")

    @patch.object(app_module, "_catalog_item_by_id")
    def test_non_foundation_is_rejected(self, by_id):
        by_id.return_value = {**self.source, "type": "lipsticks"}

        response = self.client.get("/api/products/10/shade-matches")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["error"]["code"], "SHADE_MATCH_NOT_SUPPORTED")

    @patch.object(app_module, "_catalog_item_by_id")
    def test_source_without_lab_is_rejected(self, by_id):
        by_id.return_value = {**self.source, "lab": None}

        response = self.client.get("/api/products/10/shade-matches")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["error"]["code"], "SHADE_COLOR_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
