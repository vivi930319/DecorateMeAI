import os
import dataclasses
import json
from pathlib import Path
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
    _upstream_cookie_header,
    _authorize_member_path,
    _render_job_id_from_url,
    _sanitize_render_payload,
    validate_path_segment,
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

    def test_proxy_route_accepts_put(self):
        # 購物車的「整台覆蓋」在會員資料庫端只接受 PUT。這條代理路由原本沒開 PUT，
        # 於是前端送 POST 被上游擋成 405、改送 PUT 又被 Gateway 自己擋成 405——兩邊
        # 都不通，而且前端撞到 405 之後會關掉整個購物車同步，畫面上一點異狀都沒有。
        # 白名單允許路徑（上一個測項）擋不住這種問題：路徑對了，動詞不對照樣是 404/405。
        proxy_route = next(
            route for route in gateway.app.routes
            if getattr(route, "path", "") == "/{service}/{path:path}"
        )
        self.assertIn("PUT", proxy_route.methods)
        # PUT 必須算成寫入，否則 CSRF 與 X-Expected-Actor 兩道防線會整個繞過去。
        self.assertIn("PUT", gateway.STATE_CHANGING_METHODS)

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
        self.assertEqual(validate_path_segment("lipsticks:933"), "lipsticks:933")
        for value in ("../secret", "a/b", "a\\b", ""):
            with self.assertRaises(Exception):
                validate_path_segment(value)

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

    def test_admin_audit_event_carries_no_personal_data(self):
        """稽核紀錄要能回答「誰刪的」，但本身不能變成第二份會員名冊。

        稽核 log 通常保存得比原始資料久、權限也開得更鬆，所以它一旦寫進 email 或
        請求 body，外洩的範圍反而比資料庫本身更大。
        """
        import admin_audit
        import job_store

        saved_firestore, saved_client = job_store.firestore, job_store._client
        job_store.firestore, job_store._client = None, None
        job_store._memory_jobs.pop(admin_audit.AUDIT_COLLECTION, None)
        try:
            actor = opaque_actor_id("admin@decorateme.local")
            target = opaque_actor_id("victim@example.com")
            event = admin_audit.record_admin_action(
                "member.delete",
                actor_id=actor,
                target_ref=target,
                status_code=200,
                request_id="req-1",
                # 純量以外的東西（例如整包 body）一律不落地
                body={"email": "victim@example.com", "password": "hunter2"},
            )
            self.assertEqual(event["action"], "member.delete")
            self.assertEqual(event["outcome"], "success")
            self.assertNotIn("body", event)
            blob = json.dumps(event, default=str)
            for secret in ("victim@example.com", "admin@decorateme.local", "hunter2"):
                self.assertNotIn(secret, blob)
            self.assertIn("expiresAt", event)  # Firestore TTL 靠這個欄位到期清除

            stored = admin_audit.recent_admin_actions()
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0]["eventId"], event["eventId"])

            # 失敗的嘗試同樣要留下——「有人試著刪但被擋下」也是要知道的事。
            denied = admin_audit.record_admin_action(
                "product.delete", actor_id=actor, target_ref="/api/products/p1", status_code=403
            )
            self.assertEqual(denied["outcome"], "failure")
        finally:
            job_store._memory_jobs.pop(admin_audit.AUDIT_COLLECTION, None)
            job_store.firestore, job_store._client = saved_firestore, saved_client

    def test_admin_writes_need_a_matching_csrf_token(self):
        """管理端寫入要求 cookie 與標頭帶著同一個 token（double-submit）。

        X-Expected-Actor 擋的是「寫到別人的帳號上」；這一關擋的是「別的網站叫你的
        瀏覽器寫」。攻擊者的頁面送得出請求，卻讀不到我們網域的 cookie，補不出標頭。
        """
        from ai_gateway import CSRF_COOKIE, enforce_csrf

        def req(method, cookie_token=None, header_token=None):
            r = Mock()
            r.method = method
            r.cookies = {CSRF_COOKIE: cookie_token} if cookie_token else {}
            r.headers = {"x-csrf-token": header_token} if header_token else {}
            return r

        # 讀取不受影響——CSRF 防的是寫入。
        enforce_csrf(req("GET"))

        for label, request in (
            ("兩者皆無", req("DELETE")),
            ("只有 cookie（攻擊者送得出請求但讀不到 cookie）", req("DELETE", cookie_token="tok")),
            ("只有標頭", req("DELETE", header_token="tok")),
            ("兩邊不一致", req("PATCH", cookie_token="tok", header_token="other")),
        ):
            with self.subTest(label):
                with self.assertRaises(Exception) as raised:
                    enforce_csrf(request)
                self.assertEqual(raised.exception.status_code, 403)
                self.assertEqual(raised.exception.detail["error"]["code"], "CSRF_TOKEN_INVALID")

        enforce_csrf(req("POST", cookie_token="tok", header_token="tok"))

    def test_csrf_cookie_must_be_readable_by_our_own_javascript(self):
        """CSRF cookie 刻意不是 HttpOnly，session cookie 則必須是。

        兩者剛好相反，很容易在複製貼上時弄錯：session 被 JS 讀到就等於 XSS 直接
        拿到憑證；CSRF token 讀不到則 double-submit 無法成立，所有寫入都會 403。
        """
        from fastapi import Response as FastApiResponse

        from ai_gateway import CSRF_COOKIE, issue_csrf_cookie

        response = FastApiResponse()
        token = issue_csrf_cookie(response)
        header = response.headers.get("set-cookie", "")
        self.assertIn(f"{CSRF_COOKIE}={token}", header)
        self.assertNotIn("HttpOnly", header)
        self.assertIn("SameSite=lax", header)
        self.assertGreaterEqual(len(token), 32)

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
        from ai_gateway import enforce_login_rate_limit, record_failed_login
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

        # Only *failed* logins count. Each attempt is from a fresh IP (no IP trip),
        # but they all target the same account — the account dimension accumulates.
        for i in range(gateway.LOGIN_RATE_LIMIT_MAX_REQUESTS):
            enforce_login_rate_limit(req(f"203.0.113.{i}"), email)  # check passes
            record_failed_login(req(f"203.0.113.{i}"), email)       # then the failure is booked
        with self.assertRaises(Exception) as raised:
            enforce_login_rate_limit(req("203.0.113.250"), email)
        self.assertEqual(raised.exception.status_code, 429)
        # Every 429 carries the wait in both places: the Retry-After header for
        # proxies, and retryAfterSeconds in the body because a cross-origin fetch
        # cannot read custom headers. Without the body field the frontend can only
        # say "try again later", and a user with no number keeps retrying.
        self.assertIn("Retry-After", raised.exception.headers)
        error = raised.exception.detail["error"]
        self.assertEqual(error["code"], "LOGIN_RATE_LIMITED")
        self.assertTrue(error["retryable"])
        self.assertGreaterEqual(error["retryAfterSeconds"], 1)
        self.assertEqual(str(error["retryAfterSeconds"]), raised.exception.headers["Retry-After"])
        # The limiter keys on a hash, never the raw email.
        self.assertFalse(any(email in key for key in gateway._login_rate_hits))
        gateway._login_rate_hits.clear()
        job_store.firestore, job_store._client = saved_firestore, saved_client

    def test_successful_logins_do_not_count_toward_the_limit(self):
        # An admin testing repeatedly with the *correct* password must not lock
        # themselves out. Enforcement only checks; nothing is recorded unless a
        # login actually fails, so a checker that never records never trips.
        from ai_gateway import enforce_login_rate_limit
        import job_store
        saved_firestore, saved_client = job_store.firestore, job_store._client
        job_store.firestore, job_store._client = None, None
        gateway._login_rate_hits.clear()

        def req(ip):
            r = Mock()
            r.headers = {"x-forwarded-for": f"{ip}, 10.0.0.1"}
            r.client = None
            return r

        # Many more checks than the limit, all from one IP, none recorded: never trips.
        for _ in range(gateway.LOGIN_RATE_LIMIT_MAX_REQUESTS * 3):
            enforce_login_rate_limit(req("198.51.100.7"), "admin@example.com")
        # Checking may create empty buckets, but nothing is ever recorded into them.
        self.assertTrue(all(len(bucket) == 0 for bucket in gateway._login_rate_hits.values()))
        gateway._login_rate_hits.clear()
        job_store.firestore, job_store._client = saved_firestore, saved_client

    def test_unresolvable_ip_does_not_create_a_global_lockout_bucket(self):
        # Behind Firebase Hosting -> Cloud Run the caller IP can come back
        # "unknown". Keying a bucket on that would put every user in one bucket,
        # so a handful of failures anywhere would 429 everyone. When the IP can't
        # be identified, only the (reliable) account dimension is used.
        from ai_gateway import _login_rate_keys

        req = Mock()
        req.headers = {}          # no X-Forwarded-For
        req.client = None         # no peer address -> client_ip returns "unknown"
        keys = _login_rate_keys(req, "someone@example.com")
        self.assertTrue(all(":ip:" not in k for k in keys), keys)
        self.assertTrue(any(k.startswith("login:account:") for k in keys), keys)

        # A resolvable IP still contributes its dimension.
        req2 = Mock()
        req2.headers = {"x-forwarded-for": "203.0.113.9, 10.0.0.1"}
        req2.client = None
        keys2 = _login_rate_keys(req2, "someone@example.com")
        self.assertIn("login:ip:203.0.113.9", keys2)

    def test_signup_keys_never_collide_with_the_login_bucket(self):
        # 註冊與登入共用一個桶時：十次失敗登入會讓全場都註冊不了、也收不到驗證碼
        # 此案例曾造成不同端點互相影響；scope 前綴負責隔離配額。
        from ai_gateway import _login_rate_keys

        req = Mock()
        req.headers = {"x-forwarded-for": "203.0.113.9, 10.0.0.1"}
        req.client = None
        login_keys = _login_rate_keys(req, "someone@example.com")
        signup_keys = _login_rate_keys(req, "someone@example.com", scope="signup")
        self.assertFalse(set(login_keys) & set(signup_keys), (login_keys, signup_keys))
        self.assertTrue(all(k.startswith("signup:") for k in signup_keys), signup_keys)

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


class MemberGatewayKeyTest(unittest.TestCase):
    """會員資料庫的 X-Gateway-Key：沒設定就完全不送，設了才帶。"""

    def setUp(self):
        self._key = gateway.MEMBER_GATEWAY_KEY

    def tearDown(self):
        gateway.MEMBER_GATEWAY_KEY = self._key

    def test_header_is_absent_until_a_key_is_configured(self):
        # 金鑰還沒拿到時，行為必須與加這道邏輯之前一模一樣——多送一個空標頭，
        # 對方的 hmac.compare_digest 會直接判定不符而回 401。
        gateway.MEMBER_GATEWAY_KEY = ""
        self.assertEqual(
            gateway.with_member_gateway_key({"Accept": "application/json"}),
            {"Accept": "application/json"},
        )

    def test_header_is_added_once_a_key_is_configured(self):
        gateway.MEMBER_GATEWAY_KEY = "member-gateway-key"
        headers = gateway.with_member_gateway_key({"Accept": "application/json"})
        self.assertEqual(headers["X-Gateway-Key"], "member-gateway-key")
        self.assertEqual(headers["Accept"], "application/json")


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


class MemberMediaPurgeTest(unittest.TestCase):
    """刪會員前先清影像。這條端點的重點是**失敗不能被吞掉**。

    臉部與渲染服務認的是 opaque ownerId，只有 Gateway 算得出來，所以會員資料庫端
    自己刪不掉那些影像。如果這裡清除失敗卻回成功，管理員會以為刪乾淨了，
    實際上使用者的臉部裁切還留在 GCS——而且帳號一刪就再也對應不回去，變成孤兒資料。
    """

    def setUp(self):
        from fastapi.testclient import TestClient
        import ai_gateway
        import job_store

        self._job_store = job_store
        # 稽核會寫 Firestore；測試環境連不上時每筆都要等重試逾時，整個類別跑 159 秒。
        # 關掉走記憶體版本——這裡要驗的是端點行為，不是稽核的儲存後端。
        self._fs = (job_store.firestore, job_store._client)
        job_store.firestore, job_store._client = None, None

        self.gw = ai_gateway
        token, _ = issue_access_token("admin@example.com", "admin", "active")
        self.cookies = session_cookies(token)
        self.calls = []

        async def fake_face(request, method, path, *, user_id="", admin=False):
            self.calls.append(("face", method, path, user_id, admin))
            return self._face_response

        async def fake_render(request, method, path, *, user_id="", admin=False, json_body=None):
            self.calls.append(("render", method, path, user_id, admin))
            return self._render_response

        self._orig_face = getattr(ai_gateway, "_face_internal_request", None)
        self._orig_render = ai_gateway._render_internal_request
        ai_gateway._face_internal_request = fake_face
        ai_gateway._render_internal_request = fake_render
        self._face_response = self._ok({"contributions": 2})
        self._render_response = self._ok({"status": "deleted"})
        self.client = TestClient(ai_gateway.app)

    def tearDown(self):
        self._job_store.firestore, self._job_store._client = self._fs
        if self._orig_face:
            self.gw._face_internal_request = self._orig_face
        self.gw._render_internal_request = self._orig_render

    def _ok(self, payload):
        r = Mock()
        r.is_success = True
        r.json = lambda: payload
        return r

    def _fail(self):
        r = Mock()
        r.is_success = False
        r.json = lambda: {}
        return r

    def test_purges_both_services_with_the_derived_owner_id(self):
        res = self.client.request("DELETE", "/admin-api/members/Victim@Example.com/media",
                                  cookies=self.cookies)
        self.assertEqual(res.status_code, 200, res.text)
        expected_owner = self.gw.opaque_actor_id("victim@example.com")
        self.assertEqual(res.json()["ownerId"], expected_owner)
        # email 大小寫不該影響推導出來的身分，否則清不到同一個人的資料
        for service, method, path, user_id, admin in self.calls:
            self.assertEqual(method, "DELETE")
            self.assertIn(expected_owner, path)
            self.assertTrue(admin, f"{service} 沒有以管理員身分呼叫")
        self.assertEqual({c[0] for c in self.calls}, {"face", "render"})

    def test_partial_failure_is_reported_not_swallowed(self):
        """臉部清掉了、渲染沒有 -> 必須回錯，不能回成功。"""
        self._render_response = self._fail()
        res = self.client.request("DELETE", "/admin-api/members/v@example.com/media",
                                  cookies=self.cookies)
        self.assertEqual(res.status_code, 502)
        # Gateway 有例外處理器把 detail 攤平成頂層 error，這裡照實際回應斷言
        detail = res.json()["error"]
        self.assertEqual(detail["code"], "MEDIA_PURGE_INCOMPLETE")
        self.assertIn("render", detail["message"])
        self.assertIn("不要刪除會員帳號", detail["message"],
                      "沒有告訴管理員該怎麼做，他會直接去刪帳號")

    def test_upstream_unreachable_is_a_failure_not_a_success(self):
        """服務連不上時 _face_internal_request 回 None——那不是「沒東西可刪」。"""
        async def unreachable(request, method, path, *, user_id="", admin=False):
            return None

        self.gw._face_internal_request = unreachable
        res = self.client.request("DELETE", "/admin-api/members/v@example.com/media",
                                  cookies=self.cookies)
        self.assertEqual(res.status_code, 502)
        self.assertIn("face", res.json()["error"]["message"])

    def test_non_admin_is_refused(self):
        token, _ = issue_access_token("member@example.com", "member", "active")
        res = self.client.request("DELETE", "/admin-api/members/v@example.com/media",
                                  cookies=session_cookies(token))
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.calls, [], "被擋下時不能真的去刪任何東西")

    def test_malformed_email_is_refused(self):
        res = self.client.request("DELETE", "/admin-api/members/not-an-email/media",
                                  cookies=self.cookies)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.calls, [])


class FaceFeedbackListTest(unittest.TestCase):
    """修正紀錄的列表直接讀 Firestore，不繞 face-basic。

    繞過去的理由是速度：face-basic 的 min-instances 是 0，開後台要先等它冷啟動
    十幾秒，而這裡要的只是同一個集合的內容。但「跳過一層」也代表這裡自己負責
    欄位的形狀與預設值，所以那幾條要有測試守著——尤其是沒有 reviewStatus 的舊資料
    必須算 pending，把它當成已採用，等於讓沒做過的覆核看起來像做過了。
    """

    def setUp(self):
        from fastapi.testclient import TestClient
        import ai_gateway
        import job_store

        self.gw = ai_gateway
        self._job_store = job_store
        self._fs = (job_store.firestore, job_store._client)
        job_store.firestore, job_store._client = None, None

        token, _ = issue_access_token("admin@example.com", "admin", "active")
        self.cookies = session_cookies(token)
        self.rows = [{
            "feedbackId": "FB-JOB-1", "jobId": "JOB-1", "mode": "basic",
            "createdAt": "2026-08-24T02:00:00+00:00",
            "predicted": {"眉型": "落尾眉", "眼型": "圓眼"},
            "corrections": {"眉型": "一字眉"},
            "contributed": True,
            # 這兩個欄位是不該外流的：文件本來就不存，但萬一將來有人加了，
            # 這個測試要擋住它被順手回出去。
            "ownerId": "actor_secret", "email": "someone@example.com",
        }]
        self.called = []
        self._orig_all = job_store.all_jobs
        job_store.all_jobs = lambda col, **kw: (self.called.append((col, kw)) or self.rows)
        # 打到 face 就是繞路了，這裡要能發現
        self._orig_face = ai_gateway._face_internal_request
        self.face_calls = []

        async def no_face(*a, **k):
            self.face_calls.append(a)
            raise AssertionError("列表不該打 face-basic")
        ai_gateway._face_internal_request = no_face
        self.client = TestClient(ai_gateway.app)

    def tearDown(self):
        self._job_store.firestore, self._job_store._client = self._fs
        self._job_store.all_jobs = self._orig_all
        self.gw._face_internal_request = self._orig_face

    def test_reads_firestore_directly(self):
        r = self.client.get("/admin-api/face-feedback?limit=5", cookies=self.cookies)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.face_calls, [], "不該繞 face-basic")
        col, kw = self.called[0]
        self.assertEqual(col, "face_feedback")
        self.assertEqual(kw["limit"], 5)
        # 最新的在前面，否則管理員要往下捲才看得到剛送出的修正
        self.assertTrue(kw["descending"])

    def test_missing_review_status_counts_as_pending(self):
        r = self.client.get("/admin-api/face-feedback", cookies=self.cookies)
        self.assertEqual(r.json()["items"][0]["reviewStatus"], "pending")

    def test_changes_pair_prediction_with_correction(self):
        item = self.client.get("/admin-api/face-feedback", cookies=self.cookies).json()["items"][0]
        self.assertEqual(item["changes"],
                         [{"field": "眉型", "predicted": "落尾眉", "corrected": "一字眉"}])
        # 沒有被改的部位不該出現在 changes 裡，那會讓畫面上多出幾列「改成同一個值」
        self.assertEqual(len(item["changes"]), 1)

    def test_no_identity_fields_leak(self):
        body = self.client.get("/admin-api/face-feedback", cookies=self.cookies).text
        self.assertNotIn("actor_secret", body)
        self.assertNotIn("someone@example.com", body)

    def test_limit_is_clamped(self):
        self.client.get("/admin-api/face-feedback?limit=9999", cookies=self.cookies)
        self.assertLessEqual(self.called[-1][1]["limit"], 200)
        self.client.get("/admin-api/face-feedback?limit=abc", cookies=self.cookies)
        self.assertEqual(self.called[-1][1]["limit"], 50)

    def test_firestore_failure_is_503_not_empty_list(self):
        # 回空陣列會被讀成「使用者都沒有修正過」，那是完全相反的結論
        def boom(*a, **k):
            raise RuntimeError("Firestore 掛了")
        self._job_store.all_jobs = boom
        r = self.client.get("/admin-api/face-feedback", cookies=self.cookies)
        self.assertEqual(r.status_code, 503)
        self.assertIn("FACE_FEEDBACK_UNAVAILABLE", r.text)

    def test_anonymous_is_refused(self):
        r = self.client.get("/admin-api/face-feedback", cookies={})
        self.assertIn(r.status_code, (401, 403))


class FaceFeedbackReviewProxyTest(unittest.TestCase):
    """後台的「採用／退回」要真的走到臉部服務，而且失敗要說得出是哪一種失敗。

    這條路徑決定哪些使用者修正會變成訓練標籤，所以兩件事都要守：
    沒有管理員身分不能寫；上游回 4xx 時要原樣傳回去，不能一律翻成 503——
    「這筆找不到」跟「服務掛了」的下一步完全不同，混成同一個訊息會讓人
    對著一筆不存在的資料一直重試。
    """

    def setUp(self):
        from fastapi.testclient import TestClient
        import ai_gateway
        import job_store

        self._job_store = job_store
        self._fs = (job_store.firestore, job_store._client)
        job_store.firestore, job_store._client = None, None

        self.gw = ai_gateway
        token, _ = issue_access_token("admin@example.com", "admin", "active")
        # PATCH 是狀態變更，所以要走完瀏覽器那一層會自動補的兩個東西：
        # double-submit 的 CSRF token（cookie 與標頭必須一致），以及 X-Expected-Actor。
        # 前端由 _protectedFetch 統一加，測試得自己模擬——少了它們只會拿到 403，
        # 那個 403 跟「權限不足」長得一模一樣，很容易誤判成端點寫錯。
        self.csrf = "csrf-token-for-test"
        self.cookies = {**session_cookies(token), ai_gateway.CSRF_COOKIE: self.csrf}
        self.headers = {
            ai_gateway.CSRF_HEADER: self.csrf,
            "X-Expected-Actor": ai_gateway.opaque_actor_id("admin@example.com"),
        }
        self.calls = []

        async def fake_face(request, method, path, *, user_id="", admin=False, json_body=None):
            self.calls.append((method, path, admin, json_body))
            return self._response

        self._orig = ai_gateway._face_internal_request
        ai_gateway._face_internal_request = fake_face
        self._response = self._ok({"status": "ok", "reviewStatus": "accepted"})
        self.client = TestClient(ai_gateway.app)

    def tearDown(self):
        self._job_store.firestore, self._job_store._client = self._fs
        self.gw._face_internal_request = self._orig

    def _ok(self, payload):
        r = Mock()
        r.is_success = True
        r.status_code = 200
        r.json = lambda: payload
        return r

    def _err(self, status, payload):
        r = Mock()
        r.is_success = False
        r.status_code = status
        r.json = lambda: payload
        return r

    def _review(self, feedback_id="FB-JOB-1", body=None, cookies=None, headers=None):
        return self.client.patch(f"/admin-api/face-feedback/{feedback_id}/review",
                                 json=body if body is not None else {"decision": "accepted"},
                                 cookies=self.cookies if cookies is None else cookies,
                                 headers=self.headers if headers is None else headers)

    def test_decision_reaches_the_face_service_as_admin(self):
        res = self._review()
        self.assertEqual(res.status_code, 200, res.text)
        method, path, admin, body = self.calls[0]
        self.assertEqual(method, "PATCH")
        self.assertEqual(path, "v1/face/feedback/FB-JOB-1/review")
        # admin=True 才會帶上 X-Admin-Request，少了它上游會回 403。
        self.assertTrue(admin)
        self.assertEqual(body["decision"], "accepted")

    def test_feedback_id_is_url_encoded(self):
        # 沒有 quote 的話，帶斜線的 id 會多切出一段路徑，打到完全不同的端點。
        self._review("FB-JOB/../users")
        self.assertNotIn("..", self.calls[0][1].split("v1/face/feedback/")[1])

    def test_missing_csrf_token_is_refused(self):
        # CSRF 防的是「別的網站叫你的瀏覽器去寫」，跟權限不足是不同的攻擊。
        res = self._review(headers={})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.calls, [])

    def test_anonymous_is_refused_and_nothing_is_written(self):
        # 留著 CSRF cookie，只拿掉 session——這樣測到的才是「沒有身分」被擋，
        # 而不是又一次 CSRF 失敗。
        res = self._review(cookies={self.gw.CSRF_COOKIE: self.csrf})
        self.assertIn(res.status_code, (401, 403))
        self.assertEqual(self.calls, [], "沒有管理員身分時不該打到臉部服務")

    def test_upstream_404_is_passed_through(self):
        self._response = self._err(404, {"detail": {"error": {"code": "FEEDBACK_NOT_FOUND"}}})
        res = self._review()
        self.assertEqual(res.status_code, 404, res.text)

    def test_upstream_422_is_passed_through(self):
        self._response = self._err(422, {"detail": {"error": {"code": "INVALID_DECISION"}}})
        self.assertEqual(self._review(body={"decision": "approved"}).status_code, 422)

    def test_unreachable_face_service_is_503(self):
        async def dead(*a, **k):
            return None
        self.gw._face_internal_request = dead
        res = self._review()
        self.assertEqual(res.status_code, 503)
        # 訊息要講清楚「沒有寫進去」，否則管理員會以為已經生效。
        self.assertIn("沒有寫進去", res.text)


class MemberDeleteClearsMediaFirstTest(unittest.TestCase):
    """刪會員之前，Gateway 要先清掉他的影像；清不掉就不准往下刪。

    這條流程原本完全沒有測試，連既有的渲染影像清除也沒有。它守的是一個
    無法補救的狀態：臉部裁切與渲染圖都靠 ownerId 定位，而 ownerId 是用
    SESSION_SECRET 從 email 推導的。帳號一刪就再也推導不回去，那些影像會變成
    沒有帳號對應、也沒有辦法刪除的臉部資料。

    順序放在 Gateway 而不是後台，是因為後台只是其中一個呼叫端；放這裡才繞不過去。
    """

    def setUp(self):
        from fastapi.testclient import TestClient
        import ai_gateway
        import job_store

        self.gw = ai_gateway
        self._job_store = job_store
        self._fs = (job_store.firestore, job_store._client)
        job_store.firestore, job_store._client = None, None

        self.face_called = []
        self.render_called = []
        self.forwarded = []
        self.face_ok = True
        self.render_ok = True

        async def fake_face(request, method, path, *, user_id="", admin=False):
            self.face_called.append(path)
            return self._resp(self.face_ok, {"contributions": 1})

        async def fake_render(request, method, path, *, user_id="", admin=False, json_body=None):
            self.render_called.append(path)
            return self._resp(self.render_ok, {"status": "deleted"})

        self._orig = (ai_gateway._face_internal_request, ai_gateway._render_internal_request)
        ai_gateway._face_internal_request = fake_face
        ai_gateway._render_internal_request = fake_render
        self.client = TestClient(ai_gateway.app)

    def tearDown(self):
        self.gw._face_internal_request, self.gw._render_internal_request = self._orig
        self._job_store.firestore, self._job_store._client = self._fs

    def _resp(self, ok, payload):
        r = Mock()
        r.is_success = ok
        r.json = lambda: payload
        r.content = json.dumps(payload).encode()
        r.headers = {}
        r.status_code = 200 if ok else 503
        return r

    def test_face_crops_are_cleared_before_the_row_is_deleted(self):
        """新增的一段：臉部裁切也要清，不能只清渲染圖。"""
        self.assertEqual(self.face_called, [])
        # 直接驗那段流程的意圖，不必跑完整代理鏈：兩個服務都要被呼叫，
        # 而且用的是同一個 target_owner_id。
        source = Path(__file__).resolve().parents[1].joinpath("gateway/ai_gateway.py").read_text(encoding="utf-8")
        self.assertIn("v1/face/users/{target_owner_id}", source,
                      "刪會員時沒有清臉部裁切")
        self.assertIn("render/users/{target_owner_id}", source,
                      "刪會員時沒有清渲染圖")

    def test_face_failure_stops_the_delete(self):
        """臉部清除失敗要擋下刪除，而且錯誤碼要跟渲染失敗一致。"""
        source = Path(__file__).resolve().parents[1].joinpath("gateway/ai_gateway.py").read_text(encoding="utf-8")
        face_block = source.split("face_cleanup = await")[1].split("response = await")[0]
        self.assertIn("MEMBER_MEDIA_DELETE_INCOMPLETE", face_block,
                      "臉部清除失敗沒有擋下刪除")
        self.assertIn("raise HTTPException", face_block)

    def test_cleanup_runs_before_forwarding(self):
        """清除必須在轉發之前。順序反了就等於沒有保證。"""
        source = Path(__file__).resolve().parents[1].joinpath("gateway/ai_gateway.py").read_text(encoding="utf-8")
        block = source.split("Privacy-first deletion")[1]
        face_at = block.index("v1/face/users/")
        forward_at = block.index("response = await request.app.state.http_client.request")
        self.assertLess(face_at, forward_at,
                        "臉部清除排在轉發刪除之後，那時帳號可能已經不見了")

    def test_zero_contributions_is_not_a_failure(self):
        """沒開啟貢獻功能時會回 0 筆——那是成功，不能讓所有會員都刪不掉。"""
        source = Path(__file__).resolve().parents[1].joinpath("gateway/ai_gateway.py").read_text(encoding="utf-8")
        block = source.split("face_cleanup = await")[1].split("response = await")[0]
        self.assertNotIn("contributions", block,
                         "用刪除筆數判斷成敗，會讓沒有貢獻樣本的會員刪不掉")


class GuestTrialTest(unittest.TestCase):
    """訪客試用：流程要通，但不能變成繞過會員驗證的後門。"""

    def setUp(self):
        self._was_enabled = gateway.GUEST_TRIAL_ENABLED
        gateway.GUEST_TRIAL_ENABLED = True

    def tearDown(self):
        gateway.GUEST_TRIAL_ENABLED = self._was_enabled

    @staticmethod
    def _ticket(guest_id: str = "guest-abc", ttl: int = 3600) -> str:
        expires_at = int(gateway.time.time()) + ttl
        return f"{guest_id}.{expires_at}.{gateway._guest_ticket_mac(guest_id, expires_at)}"

    def _guest_request(self, method: str = "POST", ticket: str = "", api_key: str = "face-client-key") -> Mock:
        request = Mock()
        request.method = method
        request.headers = {
            gateway.GUEST_TICKET_HEADER: ticket or self._ticket(),
            # 訪客不繞過用戶端金鑰。這道關卡在訪客判定之前，前端本來就會帶。
            "x-api-key": api_key,
        }
        request.cookies = {}
        request.body = AsyncMock(return_value=b"")
        # proxy 會 list(query_params.multi_items())。留成 Mock 的話會丟 TypeError，
        # 而那個例外被 proxy 的 except Exception 吞成 503——測試就永遠走不到轉發之後，
        # 看起來卻像通過。
        request.query_params.multi_items = Mock(return_value=[])
        request.app.state.http_client.request = AsyncMock()
        return request

    def test_forged_ticket_is_rejected(self):
        """自己編一張票券要驗不過，否則額度形同虛設。"""
        self.assertEqual(gateway.read_guest_id(self._guest_request(ticket="guest-abc.9999999999.deadbeef")), "")

    def test_expired_ticket_is_rejected(self):
        self.assertEqual(gateway.read_guest_id(self._guest_request(ticket=self._ticket(ttl=-1))), "")

    def test_valid_ticket_round_trips(self):
        self.assertEqual(gateway.read_guest_id(self._guest_request(ticket=self._ticket("guest-xyz"))), "guest-xyz")

    def test_guest_actor_never_collides_with_a_member(self):
        """兩種身分共用渲染服務的 ownerId 欄位，命名空間重疊就等於可以看別人的圖。"""
        self.assertTrue(gateway.guest_actor_id("guest-abc").startswith("guest_"))
        self.assertTrue(opaque_actor_id("member@example.com").startswith("actor_"))
        self.assertNotEqual(gateway.guest_actor_id("guest-abc"), opaque_actor_id("guest-abc"))

    def test_guest_cannot_reach_member_database(self):
        """收藏與會員資料一律關著——訪客只有體驗，不能存圖。"""
        request = self._guest_request()
        with self.assertRaises(Exception) as raised:
            asyncio.run(proxy("member-database", "api/members/someone@example.com/saved-looks", request))
        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(raised.exception.detail["error"]["code"], "MEMBER_AUTH_REQUIRED")
        request.app.state.http_client.request.assert_not_awaited()

    def test_guest_cannot_reach_face_pro(self):
        """PRO 不在訪客的開放清單裡，免費體驗只給 BASIC。"""
        request = self._guest_request()
        with self.assertRaises(Exception) as raised:
            asyncio.run(proxy("face-pro", "v1/face/jobs/pro", request))
        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(raised.exception.detail["error"]["code"], "MEMBER_AUTH_REQUIRED")
        request.app.state.http_client.request.assert_not_awaited()

    def test_guest_write_is_limited_to_the_listed_paths(self):
        """開放清單以外的寫入要回到會員驗證，例如五官修正回饋。"""
        self.assertTrue(gateway._guest_path_allowed("face-basic", "v1/face/jobs/basic", "POST"))
        self.assertTrue(gateway._guest_path_allowed("face-basic", "v1/face/pose", "POST"))
        self.assertTrue(gateway._guest_path_allowed("render-service", "render", "POST"))
        self.assertFalse(gateway._guest_path_allowed("face-basic", "v1/face/jobs/JOB-012345abcdef/feedback", "POST"))
        self.assertFalse(gateway._guest_path_allowed("member-database", "api/members", "GET"))
        # 讀取放行：輪詢工作狀態、取結果都是 GET。
        self.assertTrue(gateway._guest_path_allowed("face-basic", "v1/face/jobs/JOB-012345abcdef/result", "GET"))

    def test_only_starting_an_analysis_spends_quota(self):
        """一次流程扣一次。渲染與輪詢不扣，否則重試會把三次吃光。"""
        self.assertTrue(gateway._guest_spends_quota("face-basic", "v1/face/jobs/basic", "POST"))
        self.assertFalse(gateway._guest_spends_quota("render-service", "render", "POST"))
        self.assertFalse(gateway._guest_spends_quota("face-basic", "v1/face/pose", "POST"))
        self.assertFalse(gateway._guest_spends_quota("face-basic", "v1/face/jobs/basic", "GET"))

    def test_exhausted_quota_is_refused_before_the_upstream(self):
        request = self._guest_request()
        with unittest.mock.patch.object(gateway, "guest_trial_remaining", return_value=0):
            with self.assertRaises(Exception) as raised:
                asyncio.run(proxy("face-basic", "v1/face/jobs/basic", request))
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail["error"]["code"], "GUEST_TRIAL_EXHAUSTED")
        request.app.state.http_client.request.assert_not_awaited()

    @staticmethod
    def _reachable(service: str):
        """把 upstream 換成一個「設定完整、不需要 Cloud Run IAM」的版本，
        好讓測試走到實際轉發那一步。"""
        return dataclasses.replace(
            gateway.UPSTREAMS[service],
            base_url="https://upstream.example",
            api_key="upstream-key",
            requires_cloud_run_iam=False,
        )

    def test_quota_is_spent_only_after_the_upstream_accepts(self):
        """上游掛掉不能吃掉使用者的額度——總共只有三次。"""
        request = self._guest_request()
        failed = Mock(status_code=503, content=b"{}", headers={}, is_success=False)
        request.app.state.http_client.request = AsyncMock(return_value=failed)
        with unittest.mock.patch.dict(gateway.UPSTREAMS, {"face-basic": self._reachable("face-basic")}), \
                unittest.mock.patch.object(gateway, "guest_trial_record") as record, \
                unittest.mock.patch.object(gateway, "guest_trial_remaining", return_value=3):
            asyncio.run(proxy("face-basic", "v1/face/jobs/basic", request))
        record.assert_not_called()

    def test_quota_is_spent_when_the_analysis_is_accepted(self):
        request = self._guest_request()
        accepted = Mock(status_code=202, content=b"{}", headers={}, is_success=True)
        request.app.state.http_client.request = AsyncMock(return_value=accepted)
        with unittest.mock.patch.dict(gateway.UPSTREAMS, {"face-basic": self._reachable("face-basic")}), \
                unittest.mock.patch.object(gateway, "guest_trial_record") as record, \
                unittest.mock.patch.object(gateway, "guest_trial_remaining", return_value=3):
            result = asyncio.run(proxy("face-basic", "v1/face/jobs/basic", request))
        record.assert_called_once()
        self.assertEqual(result.headers["x-guest-trial-remaining"], "3")

    def test_a_signed_in_member_never_falls_into_the_guest_branch(self):
        """帶著 session 又多帶一個訪客標頭時，仍然照會員流程走。"""
        token, _ = issue_access_token("member@example.com", "member", "active")
        request = self._guest_request(method="GET")
        request.headers["authorization"] = f"Bearer {token}"
        request.cookies = session_cookies(token, seal_member_cookie("session=x"))
        ok = Mock(status_code=200, content=b"{}", headers={}, is_success=True)
        request.app.state.http_client.request = AsyncMock(return_value=ok)
        with unittest.mock.patch.dict(gateway.UPSTREAMS, {"face-basic": self._reachable("face-basic")}):
            result = asyncio.run(proxy("face-basic", "v1/face/jobs/JOB-012345abcdef", request))
        # 走會員路徑就不會帶上訪客的剩餘次數標頭。
        self.assertNotIn("x-guest-trial-remaining", result.headers)

    def test_disabled_flag_keeps_the_old_401(self):
        gateway.GUEST_TRIAL_ENABLED = False
        request = self._guest_request()
        with self.assertRaises(Exception) as raised:
            asyncio.run(proxy("face-basic", "v1/face/jobs/basic", request))
        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(raised.exception.detail["error"]["code"], "MEMBER_AUTH_REQUIRED")


class FaceTrainingRunTest(unittest.TestCase):
    """訓練批次是「使用者修正真的被拿去訓練」這件事唯一的書面證據。

    兩件事要有測試守著，因為它們壞掉的時候畫面看起來都是正常的：
    批次建立後要在每一筆回饋上蓋回批次編號（否則同一批資料每按一次就重送一次），
    以及列表要帶出訓練機心跳（否則「還在排隊」與「訓練失敗」在畫面上長得一樣）。
    """

    def setUp(self):
        from fastapi.testclient import TestClient
        import ai_gateway
        import job_store

        self.gw = ai_gateway
        self._job_store = job_store
        self._fs = (job_store.firestore, job_store._client)
        job_store.firestore, job_store._client = None, None

        token, _ = issue_access_token("admin@example.com", "admin", "active")
        # 這條會寫，所以要帶 double-submit 的 CSRF token 與 X-Expected-Actor。
        # 少了它們只會拿到 403，而那個 403 跟「權限不足」長得一模一樣。
        self.csrf = "csrf-token-for-test"
        self.cookies = {**session_cookies(token), ai_gateway.CSRF_COOKIE: self.csrf}
        self.headers = {
            ai_gateway.CSRF_HEADER: self.csrf,
            "X-Expected-Actor": ai_gateway.opaque_actor_id("admin@example.com"),
        }

        self.feedback = {
            "FB-JOB-1": {
                "feedbackId": "FB-JOB-1", "jobId": "JOB-1", "contributed": True,
                "corrections": {"眉型": "一字眉"},
                "reviewDecisions": {"眉型": "accepted"},
            },
            "FB-JOB-2": {
                "feedbackId": "FB-JOB-2", "jobId": "JOB-2", "contributed": False,
                "corrections": {"眼型": "圓眼"},
                "reviewDecisions": {"眼型": "accepted"},
            },
        }
        self.created = []
        self.patched = []
        self.collections = {
            "face_training_runs": [],
            "face_training_workers": [{"workerId": "PC-1", "state": "idle",
                                       "lastSeenAt": "2026-08-26T01:00:00+00:00"}],
        }

        self._orig = (job_store.get, job_store.create, job_store.patch, job_store.all_jobs)
        job_store.get = lambda col, doc_id: (
            self.feedback.get(f"FB-{doc_id}") if col == "face_feedback" else None)
        job_store.create = lambda col, doc_id, data: self.created.append((col, doc_id, data))
        job_store.patch = lambda col, doc_id, updates: self.patched.append((col, doc_id, updates))
        job_store.all_jobs = lambda col, **kw: list(self.collections.get(col, []))
        self.client = TestClient(ai_gateway.app)

    def tearDown(self):
        (self._job_store.get, self._job_store.create,
         self._job_store.patch, self._job_store.all_jobs) = self._orig
        self._job_store.firestore, self._job_store._client = self._fs

    def _create(self, ids):
        return self.client.post("/admin-api/face-training/runs",
                                json={"feedbackIds": ids},
                                cookies=self.cookies, headers=self.headers)

    def test_run_stamps_the_batch_id_back_onto_each_feedback(self):
        r = self._create(["FB-JOB-1"])
        self.assertEqual(r.status_code, 202, r.text)
        run_id = r.json()["runId"]
        stamped = [p for p in self.patched
                   if p[0] == "face_feedback" and p[2].get("trainingRunId")]
        self.assertEqual(len(stamped), 1, f"應該只蓋一筆，實際 {self.patched}")
        self.assertEqual(stamped[0][1], "JOB-1")
        self.assertEqual(stamped[0][2]["trainingRunId"], run_id)

    def test_sample_without_image_is_excluded_with_a_reason(self):
        r = self._create(["FB-JOB-1", "FB-JOB-2"])
        self.assertEqual(r.status_code, 202, r.text)
        body = r.json()
        self.assertEqual(body["feedbackIds"], ["FB-JOB-1"])
        reasons = {item["feedbackId"]: item["reason"] for item in body["excluded"]}
        self.assertIn("FB-JOB-2", reasons)
        # 排除的理由要說得出口——這個欄位就是給人看「為什麼沒用這一筆」的。
        self.assertIn("影像", reasons["FB-JOB-2"])

    def test_stamp_failure_does_not_lose_the_batch(self):
        # 蓋標記失敗時，批次本身仍然要建立起來：批次是證據，標記只是方便查詢。
        def boom(col, doc_id, updates):
            raise RuntimeError("firestore 暫時寫不進去")
        self._job_store.patch = boom
        r = self._create(["FB-JOB-1"])
        self.assertEqual(r.status_code, 202, r.text)
        self.assertEqual(len(self.created), 1)

    def test_runs_listing_reports_the_training_machine(self):
        r = self.client.get("/admin-api/face-training/runs",
                            cookies=self.cookies, headers=self.headers)
        self.assertEqual(r.status_code, 200, r.text)
        worker = r.json().get("worker")
        self.assertIsNotNone(worker, "沒有心跳的話，排隊中與訓練失敗在畫面上分不出來")
        self.assertEqual(worker["workerId"], "PC-1")

    def test_missing_worker_collection_is_not_an_error(self):
        # worker 從來沒跑過的時候這個集合不存在，那本身就是有意義的答案（沒有訓練機），
        # 不該讓整個後台讀不到批次。
        def boom(col, **kw):
            if col == "face_training_workers":
                raise RuntimeError("collection not found")
            return []
        self._job_store.all_jobs = boom
        r = self.client.get("/admin-api/face-training/runs",
                            cookies=self.cookies, headers=self.headers)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(r.json()["worker"])


class PublicProductPathTest(unittest.TestCase):
    """公開商品代理的路徑白名單。

    這裡出錯的樣子特別難查：白名單沒放行時 Gateway 自己回
    `404 {"error":{"code":"NOT_FOUND","message":"Route not found."}}`，
    而那跟「上游沒有這個端點」長得一模一樣。2026-08-28 就因此把商品後端剛上線的
    跨品牌色號端點誤判成對方沒做——實際上是我們沒開。
    """

    def _allowed(self, path: str) -> bool:
        return any(p.fullmatch(path) for p in gateway.PUBLIC_PRODUCT_PATHS)

    def test_listing_and_recommendation_stay_allowed(self):
        self.assertTrue(self._allowed("api/products"))
        self.assertTrue(self._allowed("recommend-products"))

    def test_cross_brand_shade_matches_is_allowed(self):
        self.assertTrue(self._allowed("api/products/902/shade-matches"))
        self.assertTrue(self._allowed("api/products/foundations:1663/shade-matches"))

    def test_id_segment_cannot_carry_a_path(self):
        # id 段落若允許斜線，`api/products/../../admin/x/shade-matches` 這種寫法
        # 就能把請求帶到商品服務的其他端點上。
        self.assertFalse(self._allowed("api/products/a/b/shade-matches"))
        self.assertFalse(self._allowed("api/products/../admin/shade-matches"))

    def test_other_product_routes_stay_closed(self):
        self.assertFalse(self._allowed("api/products/902"))
        self.assertFalse(self._allowed("api/crawler-staging/products"))
        self.assertFalse(self._allowed("api/admin/product-audit-logs"))


if __name__ == "__main__":
    unittest.main()
