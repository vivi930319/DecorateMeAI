import unittest
from unittest.mock import patch

import app as app_module


class ProductAdminContractTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()

    @patch.object(app_module, "PRODUCT_ADMIN_API_KEY", "test-product-key")
    def test_product_key_reaches_create_validation_and_lists_allowed_types(self):
        response = self.client.post(
            "/api/products",
            headers={"Authorization": "Bearer test-product-key"},
            json={"type": "not-a-category"},
        )

        self.assertEqual(response.status_code, 422)
        error = response.get_json()["error"]
        self.assertEqual(error["code"], "INVALID_CATEGORY")
        self.assertIn("lipsticks", error["details"]["allowed"])
        self.assertIn("foundations", error["details"]["allowed"])

    @patch.object(app_module, "PRODUCT_ADMIN_API_KEY", "test-product-key")
    def test_product_key_reaches_new_staging_route(self):
        response = self.client.get(
            "/api/crawler-staging/products?status=wrong",
            headers={"Authorization": "Bearer test-product-key"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["error"]["code"], "INVALID_STATUS")

    @patch.object(app_module, "PRODUCT_ADMIN_API_KEY", "test-product-key")
    def test_missing_product_key_is_rejected(self):
        response = self.client.post("/api/products", json={"type": "not-a-category"})

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
