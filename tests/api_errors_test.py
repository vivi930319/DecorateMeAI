"""統一錯誤 envelope 契約測試（api_errors.normalize_error_response）。

驗證不論錯誤從哪一種途徑產生，對外都是同一份形狀：
    {"success": false, "status": "error",
     "error": {"code", "message", "retryable", "details", "requestId", ...}}
且 error.requestId 與 X-Request-ID 標頭一致。
"""
import os
import unittest

os.environ.setdefault("GATEWAY_FACE_API_KEY", "face-client-key")
os.environ.setdefault("GATEWAY_RENDER_API_KEY", "render-client-key")
os.environ.setdefault("GATEWAY_SESSION_SECRET", "test-session-secret-that-is-at-least-32-bytes")

from fastapi.testclient import TestClient  # noqa: E402

import ai_gateway  # noqa: E402
from api_errors import normalize_error_body  # noqa: E402


class UnifiedErrorEnvelopeTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(ai_gateway.app)

    def _assert_envelope(self, res, expected_status, expected_code=None):
        self.assertEqual(res.status_code, expected_status, res.text)
        body = res.json()
        # 頂層形狀
        self.assertIs(body.get("success"), False, body)
        self.assertEqual(body.get("status"), "error", body)
        self.assertEqual(set(body.keys()), {"success", "status", "error"},
                         f"錯誤回應不應夾帶額外頂層欄位：{body}")
        err = body["error"]
        for key in ("code", "message", "retryable", "details", "requestId"):
            self.assertIn(key, err, f"error 缺少 {key}：{err}")
        # requestId 與標頭一致
        self.assertEqual(err["requestId"], res.headers.get("x-request-id"),
                         "body 的 requestId 必須等於 X-Request-ID 標頭")
        if expected_code:
            self.assertEqual(err["code"], expected_code, err)

    def test_401_unauthenticated_session(self):
        res = self.client.get("/auth/session")
        self._assert_envelope(res, 401, "MEMBER_AUTH_REQUIRED")

    def test_422_login_validation(self):
        res = self.client.post("/auth/login", json={"email": "a@b.com"})
        self._assert_envelope(res, 422, "VALIDATION_ERROR")
        # 驗證細節仍保留在 error 內（欄位錯誤不因正規化而遺失）
        self.assertTrue(res.json()["error"].get("fields"), "validation 錯誤應保留 fields")

    def test_404_route_not_found(self):
        res = self.client.get("/no-such-route-xyz")
        self._assert_envelope(res, 404)

    def test_success_responses_are_untouched(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        # 成功回應不應被包成錯誤 envelope：沒有 error 鍵、success 不會被塞成 False，
        # 且保留 health 自己的 status（ok 或 degraded，視下游而定）。
        self.assertNotIn("error", body)
        self.assertIsNot(body.get("success"), False)
        self.assertIn(body.get("status"), ("ok", "degraded"))

    def test_normalize_strips_stray_data_fields(self):
        # 代理下游把 products 夾在錯誤回應裡：正規化後只留 success/status/error
        raw = {"error": {"code": "INVALID_ANALYSIS_PACKAGE", "message": "缺少臉部分析資料包",
                         "retryable": False}, "products": [], "success": False}
        out = normalize_error_body(raw, "req-xyz", 400)
        self.assertEqual(set(out.keys()), {"success", "status", "error"})
        self.assertNotIn("products", out)
        self.assertEqual(out["error"]["requestId"], "req-xyz")
        self.assertEqual(out["error"]["details"], {})

    def test_normalize_unwraps_nested_detail(self):
        raw = {"detail": {"error": {"code": "PRODUCT_UPSTREAM_TIMEOUT", "message": "timeout",
                                    "retryable": True}}}
        out = normalize_error_body(raw, "req-abc", 504)
        self.assertEqual(out["error"]["code"], "PRODUCT_UPSTREAM_TIMEOUT")
        self.assertEqual(out["error"]["requestId"], "req-abc")


if __name__ == "__main__":
    unittest.main()
