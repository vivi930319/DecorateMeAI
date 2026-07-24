import os
import json
import unittest
import asyncio
from http.cookies import SimpleCookie
from unittest.mock import AsyncMock, Mock

import httpx

# 這些金鑰是測試自己的 fixture，測項會直接對字面值斷言，所以必須「覆寫」而不是
# setdefault。用 setdefault 的話，CI 注入的 GATEWAY_FACE_API_KEY 會贏過這裡的值，
# test_client_key_is_required 就會拿 face-client-key 去比 CI 的金鑰而噴 401——
# 本機跑得過、CI 一定紅，而且看起來像是被測程式壞掉。
os.environ["GATEWAY_FACE_API_KEY"] = "face-client-key"
os.environ["GATEWAY_RENDER_API_KEY"] = "render-client-key"
os.environ["GATEWAY_SESSION_SECRET"] = "test-session-secret-that-is-at-least-32-bytes"

import ai_gateway as gateway  # noqa: E402
from ai_gateway import (  # noqa: E402
    UPSTREAMS,
    build_upstream_headers,
    client_ip,
    enforce_expected_actor,
    is_path_allowed,
    issue_access_token,
    opaque_actor_id,
    proxy,
    public_config,
    require_admin_access,
    require_client_api_key,
    require_member_access,
    require_upstream_member_cookie,
    seal_member_cookie,
    session_status,
    upstream_timeout,
    validate_upstream_member_session,
    _upstream_cookie_header,
    _authorize_member_path,
    _render_job_id_from_url,
    _sanitize_render_payload,
    validate_product_id,
)


def session_cookies(token: str = "", sealed: str = "") -> dict:
    """The single cookie Firebase Hosting forwards, carrying both session halves."""
    return {gateway.SESSION_COOKIE: f"{token}{gateway.SESSION_COOKIE_SEPARATOR}{sealed}"}


class AiGatewayTest(unittest.TestCase):
    def test_only_known_routes_are_allowed(self):
        basic = UPSTREAMS["face-basic"]
        render = UPSTREAMS["render-service"]

        self.assertTrue(is_path_allowed(basic, "v1/face/jobs/JOB-012345abcdef/result"))
        self.assertTrue(is_path_allowed(render, "render/jobs/0123456789abcdef0123456789abcdef"))
        self.assertFalse(is_path_allowed(basic, "../health"))
        self.assertFalse(is_path_allowed(render, "render/jobs/not-a-job-id"))
        self.assertFalse(is_path_allowed(render, "openapi.json"))

        # The render service does not owner-check these, so they must never be
        # reachable from a browser session — only from the Gateway itself.
        job = "0123456789abcdef0123456789abcdef"
        for internal in (
            f"render/jobs/{job}/signed-url",
            f"render/jobs/{job}/content",
            f"render/jobs/{job}/retain",
            f"render/jobs/{job}/artifact",
            "render/media/sign",
            "render/media/content",
            "render/media",
            "render/users/actor_0123456789abcdef01234567",
        ):
            self.assertFalse(is_path_allowed(render, internal), internal)

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

        member_headers = build_upstream_headers(request, UPSTREAMS["member-database"], "")
        self.assertNotIn("X-API-Key", member_headers)

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
        request.cookies = session_cookies(token)
        claims = require_admin_access(request)
        self.assertEqual(claims["sub"], "admin@example.com")

    def test_session_rides_in_the_only_cookie_firebase_forwards(self):
        # Firebase Hosting drops every cookie except `__session` when it rewrites
        # to Cloud Run.  Splitting the session across two custom names meant it
        # never reached this service, so every signed-in request 401ed with
        # MEMBER_AUTH_REQUIRED while the browser was still sending both (S56).
        token, _ = issue_access_token("member@example.com", "member", "active")
        sealed = seal_member_cookie("session=abc; refresh=def")

        # Asserted as a literal, not via the constant: renaming the cookie is
        # exactly the regression this guards against, and comparing the constant
        # to itself would still pass.
        self.assertEqual(gateway.SESSION_COOKIE, "__session")

        response = gateway.JSONResponse(content={})
        gateway.set_session_cookie(response, token, sealed)
        written = SimpleCookie(response.headers.get("set-cookie", ""))
        self.assertEqual(list(written.keys()), ["__session"])

        request = Mock()
        request.headers = {}
        request.cookies = {gateway.SESSION_COOKIE: written[gateway.SESSION_COOKIE].value}
        self.assertEqual(require_member_access(request)["sub"], "member@example.com")
        self.assertEqual(require_upstream_member_cookie(request), "session=abc; refresh=def")

    def test_session_status_requires_both_http_only_sessions(self):
        gateway.MEMBER_DATABASE_URL = "https://member.test"
        token, _ = issue_access_token("member@example.com", "member", "active")
        request = Mock()
        request.headers = {}
        request.cookies = session_cookies(token, seal_member_cookie("session=private-upstream-value"))
        request.app.state.http_client.get = AsyncMock(
            return_value=httpx.Response(200, request=httpx.Request("GET", "https://member.test/api/members/member%40example.com"))
        )
        result = asyncio.run(session_status(request))
        payload = result.body.decode("utf-8")
        self.assertIn('"ok":true', payload)
        self.assertIn('"role":"member"', payload)
        self.assertIn(f"{gateway.SESSION_COOKIE}=", result.headers.get("set-cookie", ""))
        request.app.state.http_client.get.assert_awaited_once()

        request.cookies = session_cookies(token)
        with self.assertRaises(Exception) as missing_upstream:
            asyncio.run(session_status(request))
        self.assertEqual(missing_upstream.exception.status_code, 401)

    def test_before_image_travels_the_same_guarded_path_as_the_after_image(self):
        # 妝前圖是使用者的原始照片。渲染服務回的是 GCS 直連網址，那個網址一旦進了
        # 瀏覽器就繞過了擁有者檢查，所以 sanitize 必須把它改寫成需驗證的 Gateway 路徑。
        job = "0123456789abcdef0123456789abcdef"
        request = Mock()
        payload = _sanitize_render_payload(request, {
            "jobId": job,
            "afterImageUrl": "https://storage.googleapis.com/decorate-me-renders/temporary/a.png",
            "beforeImageUrl": "https://storage.googleapis.com/decorate-me-renders/temporary/b.jpg",
        })
        self.assertEqual(payload["afterImageUrl"], f"/media/render/{job}")
        self.assertEqual(payload["beforeImageUrl"], f"/media/render/{job}/before")
        self.assertNotIn("storage.googleapis.com", json.dumps(payload))

        # job 紀錄是整包轉出來的，內部欄位要在這裡濾掉——GCS 物件路徑會連帶
        # 洩漏擁有者的 actor id 與儲存結構。
        for internal in ("objectName", "beforeObjectName", "ownerId"):
            self.assertNotIn(internal, _sanitize_render_payload(request, {
                "jobId": job, "afterImageUrl": "https://storage.googleapis.com/decorate-me-renders/temporary/a.png",
                "objectName": "temporary/a.png", "beforeObjectName": "temporary/b.jpg",
                "ownerId": "actor_deadbeef0123456789abcdef",
            }))

        # 兩種形式都要解析得出 job id，否則刪除收藏時妝前圖那條網址會被當成
        # 不相干的外部網址略過，使用者的臉就留在 bucket 裡。
        self.assertEqual(_render_job_id_from_url(f"/media/render/{job}"), job)
        self.assertEqual(_render_job_id_from_url(f"/media/render/{job}/before"), job)

        # 取圖的內部端點仍然只有 Gateway 打得到，加了 variant 也不例外。
        render = UPSTREAMS["render-service"]
        for internal in (
            f"render/jobs/{job}/signed-url",
            f"render/jobs/{job}/signed-url?variant=before",
            f"render/jobs/{job}/content?variant=before",
        ):
            self.assertFalse(is_path_allowed(render, internal), internal)

    def test_member_routes_cover_both_halves_of_favourites(self):
        # 收藏的寫與讀是兩條不同的路徑，白名單漏掉讀的那條時，寫入照樣成功、
        # 讀回永遠拿到 Gateway 的 404——前端把它當成「沒有收藏」靜靜吞掉，
        # 於是換一台裝置就看不到自己收藏過的東西，畫面上完全沒有異狀。
        member = UPSTREAMS["member-database"]
        self.assertTrue(is_path_allowed(member, "api/favorites/toggle"))
        self.assertTrue(is_path_allowed(member, "api/members/someone%40example.com/favorites"))

    def test_cart_is_proxied_and_scoped_to_its_owner(self):
        # 購物車跨裝置同步跟收藏同一個模式：白名單漏掉就會「寫得進 localStorage、
        # 同步不到伺服器」，換裝置車就空了，而且畫面完全正常不會報錯。
        member = UPSTREAMS["member-database"]
        self.assertTrue(is_path_allowed(member, "api/members/someone%40example.com/cart"))
        self.assertTrue(is_path_allowed(member, "api/members/someone@example.com/cart"))

        # 只准碰自己的車：本人放行，別人的擋 403，admin 例外。
        claims = {"sub": "someone@example.com"}
        self.assertEqual(
            _authorize_member_path(claims, "api/members/someone%40example.com/cart"),
            "someone@example.com",
        )
        with self.assertRaises(Exception) as raised:
            _authorize_member_path(claims, "api/members/other%40example.com/cart")
        self.assertEqual(raised.exception.status_code, 403)

    def test_only_the_stable_media_path_can_retain_a_render(self):
        # Saving a look is what promotes its render out of `temporary/`, and the
        # gateway finds the job to retain by parsing the submitted afterImageUrl.
        # A look stored before renders moved behind /media/render carries a raw
        # bucket URL instead, which yields no job id, so nothing is retained and
        # the lifecycle rule deletes the object two days later — the member opens
        # the look and the after image is simply gone.
        job = "0123456789abcdef0123456789abcdef"
        self.assertEqual(_render_job_id_from_url(f"/media/render/{job}"), job)
        self.assertEqual(_render_job_id_from_url(f"https://decorate-me.web.app/media/render/{job}"), job)

        for unretainable in (
            f"https://storage.googleapis.com/decorate-me-renders/temporary/{job}.png",
            f"https://storage.googleapis.com/decorate-me-renders/rendered/{job}.png",
            "data:image/jpeg;base64,/9j/4AAQSkZJRg==",
            "",
        ):
            self.assertIsNone(_render_job_id_from_url(unretainable), unretainable)

    def test_session_status_names_the_account_the_session_belongs_to(self):
        # Administrator and member sign-ins share one `__session` cookie, so
        # signing in as an administrator silently replaces a member session
        # while the page keeps the old profile in localStorage.  Every member
        # request then asks the database for another account's rows and comes
        # back 403, which reads exactly like a broken permission check.  The
        # browser can only notice the swap if the session names its own owner.
        gateway.MEMBER_DATABASE_URL = "https://member.test"
        token, _ = issue_access_token("admin@decorateme.local", "admin", "active")
        request = Mock()
        request.headers = {}
        request.cookies = session_cookies(token, seal_member_cookie("session=private-upstream-value"))
        request.app.state.http_client.get = AsyncMock(
            return_value=httpx.Response(200, request=httpx.Request("GET", "https://member.test/api/members/admin%40decorateme.local"))
        )
        payload = asyncio.run(session_status(request)).body.decode("utf-8")
        self.assertIn('"sub":"admin@decorateme.local"', payload)
        self.assertIn('"role":"admin"', payload)

    def test_session_status_rejects_revoked_upstream_cookie(self):
        gateway.MEMBER_DATABASE_URL = "https://member.test"
        token, _ = issue_access_token("member@example.com", "member", "active")
        request = Mock()
        request.headers = {}
        request.cookies = session_cookies(token, seal_member_cookie("session=revoked-upstream-value"))
        request.app.state.http_client.get = AsyncMock(return_value=httpx.Response(401))
        with self.assertRaises(Exception) as revoked:
            asyncio.run(session_status(request))
        self.assertEqual(revoked.exception.status_code, 401)

    def test_partial_cookie_rotation_keeps_the_whole_session_jar(self):
        jar = "session=abc; refresh=def"
        rotated = gateway.merge_upstream_cookies(
            jar, httpx.Response(200, headers=[("set-cookie", "csrf=zzz; Path=/")])
        )
        self.assertEqual(rotated, "session=abc; refresh=def; csrf=zzz")

        renewed = gateway.merge_upstream_cookies(
            jar, httpx.Response(200, headers=[("set-cookie", "session=new; Path=/")])
        )
        self.assertEqual(renewed, "session=new; refresh=def")

        cleared = gateway.merge_upstream_cookies(
            jar, httpx.Response(200, headers=[("set-cookie", "refresh=; Max-Age=0; Path=/")])
        )
        self.assertEqual(cleared, "session=abc")

    def test_session_preflight_does_not_drop_upstream_cookies(self):
        # The preflight runs before every private page.  Re-sealing only the
        # cookies echoed by that one response used to invalidate the session it
        # had just verified, so the next request 401ed.
        gateway.MEMBER_DATABASE_URL = "https://member.test"
        token, _ = issue_access_token("member@example.com", "member", "active")
        request = Mock()
        request.headers = {}
        request.cookies = session_cookies(token, seal_member_cookie("session=abc; refresh=def"))
        request.app.state.http_client.get = AsyncMock(
            return_value=httpx.Response(200, headers=[("set-cookie", "csrf=zzz; Path=/")])
        )
        result = asyncio.run(session_status(request))

        rewritten = SimpleCookie(result.headers.get("set-cookie", ""))[gateway.SESSION_COOKIE].value
        after = Mock()
        after.cookies = {gateway.SESSION_COOKIE: rewritten}
        self.assertEqual(require_upstream_member_cookie(after), "session=abc; refresh=def; csrf=zzz")

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
        request.cookies = session_cookies("", sealed)
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

    def test_unverified_email_is_distinguishable_from_a_wrong_password(self):
        # 「信箱尚未驗證」若被壓成「帳號或密碼錯誤」，使用者會一直重打密碼而永遠
        # 進不去——真正該做的是去收驗證信。資料庫端補上 403 EMAIL_NOT_VERIFIED 後，
        # 這個碼必須能穿過 Gateway 抵達前端。
        from ai_gateway import _upstream_error_code

        class _Resp:
            def __init__(self, payload):
                self._payload = payload

            def json(self):
                if self._payload is None:
                    raise ValueError("not json")
                return self._payload

        self.assertEqual(
            _upstream_error_code(_Resp({"error": {"code": "EMAIL_NOT_VERIFIED"}})),
            "EMAIL_NOT_VERIFIED")
        self.assertEqual(_upstream_error_code(_Resp({"code": "EMAIL_NOT_VERIFIED"})),
                         "EMAIL_NOT_VERIFIED")
        # 上游壞掉或回非 JSON 時不能讓登入整個爆掉，取不到就當作沒有。
        self.assertEqual(_upstream_error_code(_Resp(None)), "")
        self.assertEqual(_upstream_error_code(_Resp(["unexpected"])), "")
        self.assertEqual(_upstream_error_code(_Resp({"error": "not-a-dict"})), "")

    def test_member_path_cannot_cross_accounts(self):
        claims = {"sub": "member@example.com", "role": "member"}
        self.assertEqual(
            _authorize_member_path(claims, "api/members/member@example.com/saved-looks"),
            "member@example.com",
        )
        with self.assertRaises(Exception) as raised:
            _authorize_member_path(claims, "api/members/other@example.com/saved-looks")
        self.assertEqual(raised.exception.status_code, 403)

    def test_expected_actor_pins_the_tab_to_its_signed_in_account(self):
        # A tab records its opaque actor at login and echoes it on every write.
        # Matching the current session is allowed; a stale actor (the cookie was
        # replaced by another account in the same browser) is refused before the
        # write can reach the upstream. Missing actor headers fail closed on writes.
        actor = opaque_actor_id("member@example.com")
        request = Mock()
        request.method = "POST"

        request.headers = {"x-expected-actor": actor}
        enforce_expected_actor(request, actor)  # matching: no raise

        request.headers = {}
        with self.assertRaises(Exception) as missing:
            enforce_expected_actor(request, actor)
        self.assertEqual(missing.exception.status_code, 409)
        self.assertEqual(missing.exception.detail["error"]["code"], "EXPECTED_ACTOR_REQUIRED")

        request.headers = {"x-expected-actor": opaque_actor_id("intruder@example.com")}
        with self.assertRaises(Exception) as raised:
            enforce_expected_actor(request, actor)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["error"]["code"], "SESSION_OWNER_CHANGED")

        request.method = "GET"
        request.headers = {}
        enforce_expected_actor(request, actor)  # safe read: no actor header required

    def test_write_with_a_stale_actor_never_reaches_the_upstream(self):
        # End to end through the proxy: the 409 fires before any upstream call,
        # so the wrong account is never touched — not merely detected afterwards.
        token, _ = issue_access_token("member@example.com", "member", "active")
        request = Mock()
        request.method = "POST"
        request.headers = {
            "authorization": f"Bearer {token}",
            "x-expected-actor": opaque_actor_id("intruder@example.com"),
        }
        request.cookies = session_cookies(token, seal_member_cookie("session=x"))
        request.app.state.http_client.request = AsyncMock()
        with self.assertRaises(Exception) as raised:
            asyncio.run(proxy("member-database", "api/favorites/toggle", request))
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["error"]["code"], "SESSION_OWNER_CHANGED")
        request.app.state.http_client.request.assert_not_awaited()

    def test_write_without_expected_actor_never_reaches_the_upstream(self):
        token, _ = issue_access_token("member@example.com", "member", "active")
        request = Mock()
        request.method = "DELETE"
        request.headers = {"authorization": f"Bearer {token}"}
        request.cookies = session_cookies(token, seal_member_cookie("session=x"))
        request.app.state.http_client.request = AsyncMock()
        with self.assertRaises(Exception) as raised:
            asyncio.run(proxy("member-database", "api/members/member@example.com/saved-looks/7", request))
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["error"]["code"], "EXPECTED_ACTOR_REQUIRED")
        request.app.state.http_client.request.assert_not_awaited()

    def test_member_roster_is_administrator_only(self):
        # The bare roster path returns every account.  `_authorize_member_path`
        # only guards `api/members/<id>`, so without an explicit gate any signed-in
        # member could enumerate the whole membership.
        member_token, _ = issue_access_token("member@example.com", "member", "active")
        request = Mock()
        request.method = "GET"
        request.headers = {"authorization": f"Bearer {member_token}"}
        request.cookies = session_cookies(member_token, seal_member_cookie("session=x"))
        with self.assertRaises(Exception) as raised:
            asyncio.run(proxy("member-database", "api/members", request))
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail["error"]["code"], "ADMIN_REQUIRED")

        # An administrator passes the roster gate; with no upstream configured in
        # the test environment they land on NOT_CONFIGURED, proving the gate let
        # them through rather than blocking them.
        admin_token, _ = issue_access_token("admin@example.com", "admin", "active")
        request.headers = {"authorization": f"Bearer {admin_token}"}
        request.cookies = session_cookies(admin_token, seal_member_cookie("session=x"))
        with self.assertRaises(Exception) as admin_raised:
            asyncio.run(proxy("member-database", "api/members", request))
        self.assertNotEqual(admin_raised.exception.detail["error"]["code"], "ADMIN_REQUIRED")

    def test_upstream_timeouts_do_not_hold_the_full_connection_budget(self):
        # No single read should be able to pin a worker for the ten-minute connect
        # budget; the external text tunnel and the member DB get the tightest bounds.
        self.assertLessEqual(upstream_timeout("member-database"), gateway.UPSTREAM_TIMEOUT_SECONDS)
        self.assertLess(upstream_timeout("text-suggestion"), gateway.UPSTREAM_TIMEOUT_SECONDS)
        self.assertLess(upstream_timeout("member-database"), upstream_timeout("render-service"))
        self.assertGreaterEqual(upstream_timeout("text-suggestion"), 5)
        # An unknown service still gets a bounded default, never the full budget.
        self.assertLessEqual(upstream_timeout("mystery-service"), gateway.UPSTREAM_TIMEOUT_SECONDS)

    def test_login_rate_limit_has_an_account_dimension(self):
        # A distributed brute force uses one account across many IPs; an IP-only
        # limiter never trips on it. The account dimension must, and it must do so
        # without ever storing the email itself.
        from ai_gateway import enforce_login_rate_limit
        import job_store
        # Force the in-memory window: without credentials the Firestore client
        # would block on the metadata server. The durable path is exercised by
        # job_store's own tests.
        saved_firestore, saved_client = job_store.firestore, job_store._client
        job_store.firestore, job_store._client = None, None
        gateway._login_rate_hits.clear()
        email = "victim@example.com"

        def req(ip):
            r = Mock()
            r.headers = {"x-forwarded-for": f"{ip}, 10.0.0.1"}  # two hops: caller is <ip>
            r.client = None
            return r

        for i in range(gateway.LOGIN_RATE_LIMIT_MAX_REQUESTS):
            enforce_login_rate_limit(req(f"203.0.113.{i}"), email)  # each IP fresh: no IP trip
        with self.assertRaises(Exception) as raised:
            enforce_login_rate_limit(req("203.0.113.250"), email)
        self.assertEqual(raised.exception.status_code, 429)
        # The limiter keys on a hash, never the raw email.
        self.assertFalse(any(email in key for key in gateway._login_rate_hits))
        gateway._login_rate_hits.clear()
        job_store.firestore, job_store._client = saved_firestore, saved_client

    def test_access_log_path_never_carries_a_member_email(self):
        # Member and saved-look routes put the account's email straight in the
        # path. The access log must not become a second copy of the membership
        # list, so any email-bearing segment is masked before it is logged.
        from api_errors import redact_log_path

        self.assertEqual(
            redact_log_path("/member-database/api/members/user@example.com/saved-looks"),
            "/member-database/api/members/<member>/saved-looks",
        )
        # The browser sends the URL-encoded form; it must be masked too.
        self.assertEqual(
            redact_log_path("/member-database/api/members/user%40example.com/check-in"),
            "/member-database/api/members/<member>/check-in",
        )
        masked = redact_log_path("/member-database/api/members/admin@corp.co/points")
        self.assertNotIn("admin@corp.co", masked)
        self.assertNotIn("admin%40corp.co", masked)
        # Ordinary paths are left untouched.
        self.assertEqual(redact_log_path("/api/products"), "/api/products")

    def test_logs_scrub_query_strings_auth_and_upstream_urls(self):
        # An unhandled exception is often an httpx error whose text embeds the
        # upstream URL (token in the query) or an auth header. The redacting
        # formatter must scrub the fully rendered record, traceback included.
        import logging
        import sys
        from api_errors import redact_sensitive, RedactingFormatter

        scrubbed = redact_sensitive(
            # 主機名刻意用 example.com：CI 的 secret-scan 會擋掉可部署程式碼裡的
            # trycloudflare 網址，而這只是遮罩測試的樣本，不需要真的長成通道網址。
            "GET https://db.example.com/api/login?token=SECRET failed for user@example.com"
        )
        self.assertNotIn("SECRET", scrubbed)
        self.assertNotIn("user@example.com", scrubbed)
        self.assertIn("?<redacted>", scrubbed)
        self.assertIn("<member>", scrubbed)
        self.assertNotIn("abc.def.ghi", redact_sensitive("Authorization: Bearer abc.def.ghi"))
        self.assertNotIn("upstreamcookie", redact_sensitive("Cookie: session=upstreamcookie"))

        # The traceback (where httpx smuggles the URL in) is scrubbed too.
        formatter = RedactingFormatter("%(message)s")
        try:
            raise RuntimeError("connect https://up.example.com/x?sid=LEAKED failed")
        except RuntimeError:
            record = logging.LogRecord(
                "t", logging.ERROR, __file__, 1, "unhandled_exception", None, sys.exc_info()
            )
        rendered = formatter.format(record)
        self.assertNotIn("LEAKED", rendered)
        self.assertIn("?<redacted>", rendered)

    def test_session_status_exposes_an_opaque_actor_for_the_tab_to_pin(self):
        gateway.MEMBER_DATABASE_URL = "https://member.test"
        token, _ = issue_access_token("member@example.com", "member", "active")
        request = Mock()
        request.headers = {}
        request.cookies = session_cookies(token, seal_member_cookie("session=private-upstream-value"))
        request.app.state.http_client.get = AsyncMock(
            return_value=httpx.Response(200, request=httpx.Request("GET", "https://member.test/api/members/member%40example.com"))
        )
        payload = json.loads(asyncio.run(session_status(request)).body.decode("utf-8"))
        self.assertEqual(payload["actorId"], opaque_actor_id("member@example.com"))
        # The opaque actor must not embed the email it is derived from.
        self.assertNotIn("member@example.com", payload["actorId"])

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


def _multi_cookie(*pairs):
    return {gateway.SESSION_COOKIE: gateway.serialize_session_slots(list(pairs))}


def _set_cookie_value(response):
    jar = SimpleCookie()
    for name, value in response.raw_headers:
        if name.decode("latin-1").lower() == "set-cookie":
            jar.load(value.decode("latin-1"))
    return jar[gateway.SESSION_COOKIE].value if gateway.SESSION_COOKIE in jar else ""


class MultiSessionTest(unittest.TestCase):
    """Multiple accounts signed in across tabs of one browser (flag on)."""

    def setUp(self):
        import job_store
        self._flag = gateway.MULTI_SESSION_ENABLED
        self._url = gateway.MEMBER_DATABASE_URL
        self._session_only = gateway.SESSION_ONLY_MODE
        self._fs, self._cl = job_store.firestore, job_store._client
        gateway.MULTI_SESSION_ENABLED = True
        gateway.SESSION_ONLY_MODE = True  # multi-session is cookie/session-only
        gateway.MEMBER_DATABASE_URL = "https://member.test"
        job_store.firestore, job_store._client = None, None  # keep the login limiter in memory
        gateway._login_rate_hits.clear()

    def tearDown(self):
        import job_store
        gateway.MULTI_SESSION_ENABLED = self._flag
        gateway.MEMBER_DATABASE_URL = self._url
        gateway.SESSION_ONLY_MODE = self._session_only
        job_store.firestore, job_store._client = self._fs, self._cl
        gateway._login_rate_hits.clear()

    # ── selection ────────────────────────────────────────────────────────────
    def test_selector_picks_the_named_account_and_only_its_upstream_cookie(self):
        tok_a, _ = issue_access_token("a@example.com", "member", "active")
        tok_b, _ = issue_access_token("b@example.com", "member", "active")
        request = Mock()
        request.cookies = _multi_cookie(
            (tok_a, seal_member_cookie("session=AAA")),
            (tok_b, seal_member_cookie("session=BBB")),
        )
        request.headers = {"x-expected-actor": opaque_actor_id("b@example.com")}
        account = gateway.select_account(request, for_write=True)
        self.assertEqual(account["sub"], "b@example.com")
        self.assertEqual(gateway.unseal_member_cookie(account["sealed"]), "session=BBB")

        request.headers = {"x-expected-actor": opaque_actor_id("a@example.com")}
        self.assertEqual(gateway.unseal_member_cookie(
            gateway.select_account(request, for_write=True)["sealed"]), "session=AAA")

    def test_you_can_only_act_as_an_account_signed_in_on_this_browser(self):
        tok_a, _ = issue_access_token("a@example.com", "member", "active")
        request = Mock()
        request.cookies = _multi_cookie((tok_a, seal_member_cookie("session=AAA")))
        request.headers = {"x-expected-actor": opaque_actor_id("stranger@example.com")}
        with self.assertRaises(Exception) as raised:
            gateway.select_account(request, for_write=False)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["error"]["code"], "ACCOUNT_NOT_AVAILABLE")

    def test_write_without_a_selector_still_fails_closed(self):
        tok_a, _ = issue_access_token("a@example.com", "member", "active")
        tok_b, _ = issue_access_token("b@example.com", "member", "active")
        request = Mock()
        request.cookies = _multi_cookie((tok_a, "sA"), (tok_b, "sB"))
        request.headers = {}
        with self.assertRaises(Exception) as raised:
            gateway.select_account(request, for_write=True)
        self.assertEqual(raised.exception.detail["error"]["code"], "EXPECTED_ACTOR_REQUIRED")

    def test_single_account_read_needs_no_selector(self):
        tok_a, _ = issue_access_token("a@example.com", "member", "active")
        request = Mock()
        request.cookies = _multi_cookie((tok_a, "sA"))
        request.headers = {}
        self.assertEqual(gateway.select_account(request, for_write=False)["sub"], "a@example.com")

    # ── login accumulation ────────────────────────────────────────────────────
    def _login(self, request, email):
        request.app.state.http_client.post = AsyncMock(return_value=httpx.Response(
            200,
            json={"success": True, "member": {"email": email, "role": "member", "status": "active"}},
            headers=[("set-cookie", f"session=up-{email}; Path=/")],
            request=httpx.Request("POST", "https://member.test/api/login"),
        ))
        request.app.state.http_client.get = AsyncMock(return_value=httpx.Response(
            200, request=httpx.Request("GET", "https://member.test/api/members/x")))
        from ai_gateway import LoginRequest, login
        return asyncio.run(login(LoginRequest(email=email, password="password1"), request))

    def test_a_second_login_adds_a_slot_instead_of_replacing(self):
        request = Mock()
        request.headers = {}
        request.client = None
        request.cookies = {}
        cookie_a = _set_cookie_value(self._login(request, "a@example.com"))
        self.assertTrue(cookie_a.startswith(gateway.MULTI_SESSION_PREFIX))
        request.cookies = {gateway.SESSION_COOKIE: cookie_a}
        cookie_b = _set_cookie_value(self._login(request, "b@example.com"))
        probe = Mock()
        probe.cookies = {gateway.SESSION_COOKIE: cookie_b}
        subs = sorted(a["sub"] for a in gateway.session_accounts(probe))
        self.assertEqual(subs, ["a@example.com", "b@example.com"])

    # ── logout is per-account ─────────────────────────────────────────────────
    def test_logging_out_one_account_keeps_the_others_signed_in(self):
        tok_a, _ = issue_access_token("a@example.com", "member", "active")
        tok_b, _ = issue_access_token("b@example.com", "member", "active")
        request = Mock()
        request.cookies = _multi_cookie((tok_a, "sA"), (tok_b, "sB"))
        request.query_params = {"actor": opaque_actor_id("a@example.com")}
        result = asyncio.run(gateway.logout(request))
        probe = Mock()
        probe.cookies = {gateway.SESSION_COOKIE: _set_cookie_value(result)}
        remaining = [a["sub"] for a in gateway.session_accounts(probe)]
        self.assertEqual(remaining, ["b@example.com"])

    # ── session status lists the accounts for the switcher ────────────────────
    def test_session_status_lists_every_signed_in_account(self):
        tok_a, _ = issue_access_token("a@example.com", "member", "active")
        tok_b, _ = issue_access_token("b@example.com", "member", "active")
        request = Mock()
        request.cookies = _multi_cookie(
            (tok_a, seal_member_cookie("session=AAA")),
            (tok_b, seal_member_cookie("session=BBB")),
        )
        request.headers = {"x-expected-actor": opaque_actor_id("a@example.com")}
        request.app.state.http_client.get = AsyncMock(return_value=httpx.Response(
            200, request=httpx.Request("GET", "https://member.test/api/members/a")))
        payload = json.loads(asyncio.run(session_status(request)).body.decode("utf-8"))
        self.assertEqual(payload["sub"], "a@example.com")
        listed = sorted(a["sub"] for a in payload["accounts"])
        self.assertEqual(listed, ["a@example.com", "b@example.com"])
        # No email of another account leaks beyond the caller's own listing intent.
        self.assertNotIn("session=BBB", asyncio.run(session_status(request)).body.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
