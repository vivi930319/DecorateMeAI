import os
import unittest
import asyncio
from unittest.mock import AsyncMock, Mock

import httpx

os.environ.setdefault("GATEWAY_FACE_API_KEY", "face-client-key")
os.environ.setdefault("GATEWAY_RENDER_API_KEY", "render-client-key")
os.environ.setdefault("GATEWAY_SESSION_SECRET", "test-session-secret-that-is-at-least-32-bytes")

import ai_gateway as gateway  # noqa: E402
from ai_gateway import (  # noqa: E402
    UPSTREAMS,
    build_upstream_headers,
    client_ip,
    is_path_allowed,
    issue_access_token,
    opaque_actor_id,
    public_config,
    require_admin_access,
    require_client_api_key,
    require_member_access,
    require_upstream_member_cookie,
    seal_member_cookie,
    session_status,
    validate_upstream_member_session,
    _upstream_cookie_header,
    _authorize_member_path,
    _render_job_id_from_url,
    _sanitize_render_payload,
    validate_product_id,
)


class AiGatewayTest(unittest.TestCase):
    def test_only_known_routes_are_allowed(self):
        basic = UPSTREAMS["face-basic"]
        render = UPSTREAMS["render-service"]

        self.assertTrue(is_path_allowed(basic, "v1/face/jobs/JOB-012345abcdef/result"))
        self.assertTrue(is_path_allowed(render, "render/jobs/0123456789abcdef0123456789abcdef"))
        self.assertTrue(is_path_allowed(render, "render/jobs/0123456789abcdef0123456789abcdef/signed-url"))
        self.assertTrue(is_path_allowed(render, "render/jobs/0123456789abcdef0123456789abcdef/retain"))
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

    def test_session_status_requires_both_http_only_sessions(self):
        gateway.MEMBER_DATABASE_URL = "https://member.test"
        token, _ = issue_access_token("member@example.com", "member", "active")
        request = Mock()
        request.headers = {}
        request.cookies = {
            "dm_session": token,
            "dm_member_session": seal_member_cookie("session=private-upstream-value"),
        }
        request.app.state.http_client.get = AsyncMock(return_value=httpx.Response(200))
        result = asyncio.run(session_status(request))
        self.assertTrue(result["ok"])
        self.assertEqual(result["role"], "member")
        self.assertNotIn("email", result)
        request.app.state.http_client.get.assert_awaited_once()

        request.cookies = {"dm_session": token}
        with self.assertRaises(Exception) as missing_upstream:
            asyncio.run(session_status(request))
        self.assertEqual(missing_upstream.exception.status_code, 401)

    def test_session_status_rejects_revoked_upstream_cookie(self):
        gateway.MEMBER_DATABASE_URL = "https://member.test"
        token, _ = issue_access_token("member@example.com", "member", "active")
        request = Mock()
        request.headers = {}
        request.cookies = {
            "dm_session": token,
            "dm_member_session": seal_member_cookie("session=revoked-upstream-value"),
        }
        request.app.state.http_client.get = AsyncMock(return_value=httpx.Response(401))
        with self.assertRaises(Exception) as revoked:
            asyncio.run(session_status(request))
        self.assertEqual(revoked.exception.status_code, 401)

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

    def test_member_database_cookie_is_sealed_before_browser_storage(self):
        response = httpx.Response(200, headers={"set-cookie": "session=private-upstream-value; HttpOnly; Path=/"})
        upstream = _upstream_cookie_header(response)
        self.assertEqual(upstream, "session=private-upstream-value")
        sealed = seal_member_cookie(upstream)
        self.assertNotIn("private-upstream-value", sealed)

        request = Mock()
        request.cookies = {"dm_member_session": sealed}
        self.assertEqual(require_upstream_member_cookie(request), upstream)

    def test_public_config_never_reveals_upstream_urls(self):
        config = asyncio.run(public_config())
        self.assertEqual(config["memberDatabaseUrl"], "/member-database")
        self.assertEqual(config["productUrl"], "/product-api")
        self.assertFalse(any("trycloudflare.com" in str(value) for value in config.values()))

    def test_admin_actor_is_opaque(self):
        actor = opaque_actor_id("Admin@Example.com")
        self.assertTrue(actor.startswith("actor_"))
        self.assertNotIn("admin", actor.lower())

    def test_member_path_cannot_cross_accounts(self):
        claims = {"sub": "member@example.com", "role": "member"}
        self.assertEqual(
            _authorize_member_path(claims, "api/members/member@example.com/saved-looks"),
            "member@example.com",
        )
        with self.assertRaises(Exception) as raised:
            _authorize_member_path(claims, "api/members/other@example.com/saved-looks")
        self.assertEqual(raised.exception.status_code, 403)

    def test_render_response_uses_stable_gateway_media_path(self):
        request = Mock()
        job_id = "0123456789abcdef0123456789abcdef"
        payload = _sanitize_render_payload(
            request,
            {"jobId": job_id, "afterImageUrl": "https://storage.googleapis.com/private/image.png", "replicateTempUrl": "https://provider.invalid/temp"},
        )
        self.assertEqual(payload["afterImageUrl"], f"/media/render/{job_id}")
        self.assertNotIn("replicateTempUrl", payload)
        self.assertEqual(_render_job_id_from_url(payload["afterImageUrl"]), job_id)


if __name__ == "__main__":
    unittest.main()
