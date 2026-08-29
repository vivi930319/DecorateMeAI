import unittest
from unittest.mock import patch

import app as app_module


def product(product_id, product_type, brand, price, name=None):
    categories = {
        "foundations": "底妝", "lipsticks": "唇彩", "blushes": "腮紅",
        "eyeshadows": "眼影", "eyeliner_mascara": "眼線/睫毛",
        "eyebrows": "眉毛彩妝", "contouring": "修容", "highlighters": "打亮",
    }
    return {
        "id": product_id, "type": product_type, "brand": brand,
        "price": f"NT${price}", "name": name or f"{brand} {product_id}",
        "description": "", "salePageId": str(product_id), "category": categories[product_type],
        "inStock": True,
    }


class CatalogFilterTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()
        self.rows = [
            product(1, "foundations", "MAC", 1800),
            product(2, "foundations", "YSL", 2500),
            product(3, "lipsticks", "CHANEL", 1600),
            product(4, "eyeliner_mascara", "CHANEL", 1400),
        ]

    @patch.object(app_module, "_catalog_rows")
    def test_multi_brand_category_price_and_sort(self, rows):
        rows.return_value = self.rows
        response = self.client.get(
            "/api/products?brand=MAC,YSL&category=底妝&minPrice=1700&maxPrice=3000&sort=price_desc&limit=20"
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual([item["id"] for item in body["items"]], [2, 1])
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["facets"]["brands"], ["MAC", "YSL"])

    @patch.object(app_module, "_catalog_rows")
    def test_eight_category_type_is_exact(self, rows):
        rows.return_value = self.rows
        response = self.client.get("/api/products?type=eyeliner_mascara&limit=20")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.get_json()["items"]], [4])

    @patch.object(app_module, "_catalog_rows")
    def test_sorted_cursor_is_opaque_offset(self, rows):
        rows.return_value = self.rows
        first = self.client.get("/api/products?sort=price_asc&limit=2").get_json()
        second = self.client.get(
            f"/api/products?sort=price_asc&limit=2&cursor={first['nextCursor']}"
        ).get_json()
        self.assertEqual([item["id"] for item in first["items"]], [4, 3])
        self.assertEqual([item["id"] for item in second["items"]], [1, 2])

    @patch.object(app_module, "_catalog_rows")
    def test_invalid_price_range_and_sort_are_rejected(self, rows):
        rows.return_value = self.rows
        self.assertEqual(self.client.get("/api/products?minPrice=10&maxPrice=5").status_code, 422)
        self.assertEqual(self.client.get("/api/products?sort=random").status_code, 422)


if __name__ == "__main__":
    unittest.main()
