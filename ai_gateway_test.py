import os
import unittest
from unittest.mock import Mock

os.environ.setdefault("GATEWAY_FACE_API_KEY", "face-client-key")
os.environ.setdefault("GATEWAY_RENDER_API_KEY", "render-client-key")
os.environ.setdefault("GATEWAY_SESSION_SECRET", "test-session-secret-that-is-at-least-32-bytes")

from ai_gateway import (  # noqa: E402
    UPSTREAMS,
    build_upstream_headers,
    client_ip,
    is_path_allowed,
    issue_access_token,
    require_admin_access,
    require_client_api_key,
    require_member_access,
    validate_product_id,
)


class AiGatewayTest(unittest.TestCase):
    def test_only_known_routes_are_allowed(self):
        basic = UPSTREAMS["face-basic"]
        render = UPSTREAMS["render-service"]

        self.assertTrue(is_path_allowed(basic, "v1/face/jobs/JOB-012345abcdef/result"))
        self.assertTrue(is_path_allowed(render, "render/jobs/0123456789abcdef0123456789abcdef"))
        self.assertFalse(is_path_allowed(basic, "../health"))
        self.assertFalse(is_path_allowed(render, "render/jobs/not-a-job-id"))
        self.assertFalse(is_path_allowed(render, "openapi.json"))

    def test_client_key_is_required(self):
        basic = UPSTREAMS["face-basic"]
        require_client_api_key(basic, "face-client-key")
        with self.assertRaises(Exception) as raised:
            require_client_api_key(basic, "wrong")
        self.assertEqual(raised.exception.status_code, 401)

    def test_forwarded_ip_uses_cloud_run_caller_position(self):
        request = Mock()
        request.headers = {"x-forwarded-for": "198.51.100.8, 203.0.113.7, 169.254.1.1"}
        request.client.host = "127.0.0.1"
        self.assertEqual(client_ip(request), "203.0.113.7")

    def test_headers_strip_untrusted_identity(self):
        request = Mock()
        request.headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "x-job-token": "job-token",
            "x-user-email": "spoofed@example.com",
            "authorization": "Bearer browser-token",
            "x-forwarded-for": "203.0.113.7, 169.254.1.1",
        }
        request.client.host = "127.0.0.1"

        headers = build_upstream_headers(request, UPSTREAMS["render-service"], "google-token")

        self.assertEqual(headers["X-Serverless-Authorization"], "Bearer google-token")
        self.assertEqual(headers["X-Forwarded-For"], "203.0.113.7")
        self.assertEqual(headers["X-Job-Token"], "job-token")
        self.assertNotIn("X-User-Email", headers)
        self.assertNotIn("Authorization", headers)

    def test_member_access_token_is_required_and_verified(self):
        token, expires_at = issue_access_token("Member@Example.com", "member")
        self.assertGreater(expires_at, 0)

        request = Mock()
        request.headers = {"authorization": f"Bearer {token}"}
        claims = require_member_access(request)
        self.assertEqual(claims["sub"], "member@example.com")

        request.headers = {"authorization": "Bearer invalid"}
        with self.assertRaises(Exception) as raised:
            require_member_access(request)
        self.assertEqual(raised.exception.status_code, 401)

    def test_http_only_cookie_token_is_accepted(self):
        token, _ = issue_access_token("admin@example.com", "admin", "active")
        request = Mock()
        request.headers = {}
        request.cookies = {"dm_session": token}
        claims = require_admin_access(request)
        self.assertEqual(claims["sub"], "admin@example.com")

    def test_non_admin_and_suspended_admin_are_rejected(self):
        request = Mock()
        member_token, _ = issue_access_token("member@example.com", "member", "active")
        request.headers = {"authorization": f"Bearer {member_token}"}
        request.cookies = {}
        with self.assertRaises(Exception) as member_error:
            require_admin_access(request)
        self.assertEqual(member_error.exception.status_code, 403)

        suspended_token, _ = issue_access_token("admin@example.com", "admin", "suspended")
        request.headers = {"authorization": f"Bearer {suspended_token}"}
        with self.assertRaises(Exception) as suspended_error:
            require_admin_access(request)
        self.assertEqual(suspended_error.exception.detail["error"]["code"], "ADMIN_SUSPENDED")

    def test_product_id_validation(self):
        self.assertEqual(validate_product_id("lipsticks:933"), "lipsticks:933")
        for value in ("../secret", "a/b", "a\\b", ""):
            with self.assertRaises(Exception):
                validate_product_id(value)


if __name__ == "__main__":
    unittest.main()
