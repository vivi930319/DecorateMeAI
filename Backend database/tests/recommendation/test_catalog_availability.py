import unittest
from unittest.mock import patch

import app as app_module
from app import _catalog_availability_sets, recommendation_candidates


class CatalogAvailabilityTests(unittest.TestCase):
    def test_source_and_global_catalog_references_are_distinct(self):
        sources, global_ids = _catalog_availability_sets([
            {"id": 9001, "type": "lipsticks", "sourceId": 2813},
            {"id": 9002, "type": "foundations", "sourceId": 42},
        ])
        self.assertIn(("lipsticks", 2813), sources)
        self.assertNotIn(("lipsticks", 901), sources)
        self.assertIn(9001, global_ids)
        self.assertNotIn(2813, global_ids)

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
