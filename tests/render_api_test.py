import asyncio
import os
import sys
import types
import unittest
from unittest import mock


# Keep this unit test deterministic and offline.
os.environ["RENDER_DURABLE_DEDUP_ENABLED"] = "0"
os.environ["SUGGESTION_SERVICE_URL"] = ""

# The repository's default test environment does not install the optional
# Render provider SDK. These tests cover validation and state handling only.
if "replicate" not in sys.modules:
    replicate_stub = types.ModuleType("replicate")
    replicate_stub.Client = object
    sys.modules["replicate"] = replicate_stub

import job_store
import replicate_render_api as render_api
from fastapi import FastAPI
from api_errors import (
    enforce_service_api_key,
    error_payload,
    require_service_api_key,
    secret_equals,
)
from replicate_render import data_url_to_bytes, delete_permanent_storage_url, fetch_remote_image_bytes


TINY_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class RenderApiTest(unittest.TestCase):
    def setUp(self):
        job_store.firestore = None
        job_store._client = None
        job_store._memory_jobs.clear()
        render_api._dedup_cache.clear()
        render_api._dedup_inflight.clear()

    def test_member_deletion_removes_before_images_and_every_batch(self):
        """刪除會員時，妝前圖也要刪，而且不能只處理第一批。

        舊版只收集 afterImageUrl，所以使用者刪掉帳號之後，他上傳的原始照片
        還留在 GCS 上——帳號都不存在了，臉還在。而且單次 limit=500，超過的
        job 連紀錄都被刪掉，那些圖片就此失去任何追蹤依據。
        """
        deleted_urls = []
        original = render_api.delete_permanent_storage_url
        render_api.delete_permanent_storage_url = lambda url: deleted_urls.append(url) or True
        try:
            for index in range(3):
                job_store.create(render_api.RENDER_JOBS_COLLECTION, f"job{index}", {
                    "jobId": f"job{index}", "ownerId": "actor_test", "status": "completed",
                    "isPermanent": True,
                    "afterImageUrl": f"https://storage.googleapis.com/decorate-me-renders/retained/after{index}.png",
                    "beforeImageUrl": f"https://storage.googleapis.com/decorate-me-renders/retained/before{index}.jpg",
                })
            import asyncio
            result = asyncio.run(render_api.delete_member_render_artifacts(
                "actor_test", x_user_id="actor_test", x_admin_request=None
            ))
        finally:
            render_api.delete_permanent_storage_url = original

        self.assertEqual(result["jobsDeleted"], 3)
        self.assertEqual(len([u for u in deleted_urls if "before" in u]), 3, deleted_urls)
        self.assertEqual(len([u for u in deleted_urls if "after" in u]), 3, deleted_urls)
        self.assertEqual(job_store.find_by_field(render_api.RENDER_JOBS_COLLECTION, "ownerId", "actor_test", limit=10), [])

    def test_dedup_hit_still_carries_a_before_image(self):
        """去重命中時妝前圖不能消失。

        命中去重會用 _response_from_completed_job 建立一個新的 job。舊版它沒有
        帶 beforeImageUrl，於是那個新 job 從出生就沒有妝前圖——妝後圖正常出現，
        所以症狀看起來像「妝前圖偶爾會壞」，實際上是同一張照片同一個風格重渲染
        必然發生。
        """
        completed = {
            "jobId": "a" * 32,
            "status": "completed",
            "afterImageUrl": "https://storage.googleapis.com/decorate-me-renders/temporary/after.png",
            "beforeImageUrl": "https://storage.googleapis.com/decorate-me-renders/temporary/before.jpg",
            "isPermanent": True,
        }
        response = render_api._response_from_completed_job(completed, TINY_PNG)
        self.assertEqual(response["beforeImageUrl"], completed["beforeImageUrl"])
        self.assertEqual(response["afterImageUrl"], completed["afterImageUrl"])

    def test_dedup_hit_on_a_job_without_a_before_image_rebuilds_one(self):
        """舊 job 沒有妝前圖時，用這次請求的原圖補建。

        妝前圖是 2026-07-22 才開始保存的，在那之前完成的 job 都沒有。放棄快取重新
        渲染會浪費一次昂貴又緩慢的模型呼叫——去重的目的是省下那個，不是省一次上傳。
        """
        uploaded = {}

        def fake_upload(image_bytes, content_type="image/png"):
            uploaded["bytes"] = image_bytes
            uploaded["type"] = content_type
            return "https://storage.googleapis.com/decorate-me-renders/temporary/rebuilt.png"

        original = render_api.upload_bytes_to_permanent_storage
        render_api.upload_bytes_to_permanent_storage = fake_upload
        try:
            response = render_api._response_from_completed_job(
                {"status": "completed", "afterImageUrl": "https://storage.googleapis.com/decorate-me-renders/temporary/a.png"},
                TINY_PNG,
            )
        finally:
            render_api.upload_bytes_to_permanent_storage = original

        self.assertTrue(response["beforeImageUrl"].endswith("rebuilt.png"))
        self.assertGreater(len(uploaded["bytes"]), 0)
        self.assertEqual(uploaded["type"], "image/png")

    def test_dedup_hit_without_an_image_leaves_the_before_empty(self):
        """補建失敗或拿不到原圖時，妝前圖留空而不是讓整次渲染失敗。

        少一張對比圖是可以接受的降級；因為補不出妝前圖就讓使用者的渲染整個失敗，
        代價完全不成比例。
        """
        response = render_api._response_from_completed_job(
            {"status": "completed", "afterImageUrl": "https://storage.googleapis.com/decorate-me-renders/temporary/a.png"},
            None,
        )
        self.assertIsNone(response["beforeImageUrl"])
        self.assertEqual(response["status"], "completed")

    def test_validates_real_image_bytes(self):
        image_bytes, content_type = data_url_to_bytes(TINY_PNG)
        self.assertGreater(len(image_bytes), 0)
        self.assertEqual(content_type, "image/png")

    def test_rejects_invalid_image_bytes(self):
        with self.assertRaises(ValueError):
            data_url_to_bytes("data:image/png;base64,not-valid")

    def test_job_polling_rejects_another_members_token(self):
        """拿到別人的 job token 也不能讀他的渲染結果（P0-8）。

        簽名網址那條路徑一直有擋擁有者，輪詢這條舊版只驗 token——同一份資料
        兩個入口，門檻卻一鬆一緊。token 只要外流一次（分享連結、log、瀏覽器歷史）
        就足以把別人的臉部渲染整包讀走。
        """
        job_store.create(render_api.RENDER_JOBS_COLLECTION, "job-owned", {
            "jobId": "job-owned", "ownerId": "actor_owner", "status": "completed",
            "resultToken": "token-owner",
            "afterImageUrl": "https://storage.googleapis.com/decorate-me-renders/temporary/a.png",
        })

        with self.assertRaises(Exception) as raised:
            asyncio.run(render_api.get_render_job(
                "job-owned", x_job_token="token-owner", x_user_id="actor_intruder"
            ))
        self.assertEqual(raised.exception.status_code, 403)

        # 沒帶會員身分也不行——否則把標頭拿掉就能繞過。
        with self.assertRaises(Exception) as raised:
            asyncio.run(render_api.get_render_job("job-owned", x_job_token="token-owner"))
        self.assertEqual(raised.exception.status_code, 403)

        owner_view = asyncio.run(render_api.get_render_job(
            "job-owned", x_job_token="token-owner", x_user_id="actor_owner"
        ))
        self.assertEqual(owner_view["jobId"], "job-owned")

    def test_job_polling_rejects_a_wrong_token_from_the_owner(self):
        """擁有者對、token 錯，一樣要擋——兩個條件是 AND 不是 OR。"""
        job_store.create(render_api.RENDER_JOBS_COLLECTION, "job-owned2", {
            "jobId": "job-owned2", "ownerId": "actor_owner", "status": "completed",
            "resultToken": "token-owner",
        })
        with self.assertRaises(Exception) as raised:
            asyncio.run(render_api.get_render_job(
                "job-owned2", x_job_token="guessed", x_user_id="actor_owner"
            ))
        self.assertEqual(raised.exception.status_code, 403)

    def test_render_input_image_is_stripped_of_metadata(self):
        """送往第三方供應商的圖必須先去掉 EXIF／GPS（P0-9）。"""
        import io

        from PIL import Image
        from PIL.TiffImagePlugin import IFDRational
        from replicate_render import image_from_frontend_package

        exif = Image.Exif()
        exif[0x010F] = "TestPhone"
        exif[0x8825] = {1: "N", 2: (IFDRational(25, 1), IFDRational(2, 1), IFDRational(0, 1))}
        buffer = io.BytesIO()
        Image.new("RGB", (24, 24), (9, 9, 9)).save(buffer, format="JPEG", exif=exif)
        import base64

        raw = buffer.getvalue()
        self.assertIn(b"TestPhone", raw)
        data_url = "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")

        cleaned_url = image_from_frontend_package({"imageDataUrl": data_url})
        cleaned = base64.b64decode(cleaned_url.split(",", 1)[1])
        self.assertNotIn(b"TestPhone", cleaned)
        with Image.open(io.BytesIO(cleaned)) as image:
            self.assertFalse(image.info.get("exif"))

    def test_render_rejects_a_forged_image_type(self):
        """檔頭宣稱 JPEG、內容其實是 PNG 的偽 MIME 上傳要擋下來。"""
        import base64
        import io

        from PIL import Image

        png = io.BytesIO()
        Image.new("RGB", (8, 8)).save(png, format="PNG")
        forged = b"\xff\xd8\xff\xe0" + png.getvalue()
        data_url = "data:image/jpeg;base64," + base64.b64encode(forged).decode("ascii")
        with self.assertRaises(ValueError):
            data_url_to_bytes(data_url)

    def test_render_request_rejects_untrusted_style(self):
        request = render_api.RenderRequest(image=TINY_PNG, styleId="untrusted-prompt")
        with self.assertRaises(Exception) as raised:
            render_api._server_render_prompt(request)
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(raised.exception.detail["error"]["code"], "INVALID_RENDER_STYLE")

    def test_suggestion_outage_falls_back_to_safe_style_prompt(self):
        request = render_api.RenderRequest(image=TINY_PNG, styleId="natural")
        with mock.patch.object(
            render_api,
            "build_personalized_render_prompt",
            side_effect=render_api.SuggestionServiceUnavailable("offline"),
        ):
            prompt, source = render_api._server_render_prompt(request)
        self.assertEqual(source, "style_allowlist_fallback")
        self.assertIn("makeup-only edit", prompt)

    def test_production_suggestion_outage_stops_before_provider_call(self):
        """正式環境不能把 Ollama 掛掉偽裝成成功的固定妝容渲染。"""
        request = render_api.RenderRequest(image=TINY_PNG, styleId="natural")
        with mock.patch.object(render_api, "REQUIRE_PERSONALIZED_RENDER_PROMPT", True), \
             mock.patch.object(
                 render_api,
                 "build_personalized_render_prompt",
                 side_effect=render_api.SuggestionServiceUnavailable("offline"),
             ):
            with self.assertRaises(Exception) as raised:
                render_api._server_render_prompt(request)
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail["error"]["code"], "PERSONALIZED_PROMPT_UNAVAILABLE")

    def test_signed_ollama_prompt_is_used_without_calling_ollama_again(self):
        """同一次建議回應的已簽 prompt 要直接送渲染，避免重複叫 Ollama。"""
        import hashlib
        import hmac
        import replicate_render

        raw_prompt = "Apply visible mauve eye makeup and a defined berry lip."
        secret = "test-prompt-signing-secret"
        signature = hmac.new(secret.encode(), raw_prompt.encode(), hashlib.sha256).hexdigest()
        request = render_api.RenderRequest(
            image=TINY_PNG,
            styleId="softBaddie",
            analysisPackage={
                "faceAnalysis": {"faceShape": "oval"},
                "generativeText": {
                    "ollamaRenderPromptEn": raw_prompt,
                    "promptSignature": signature,
                    "promptSignatureVersion": "hmac-sha256-v1",
                },
            },
        )
        with mock.patch.object(replicate_render, "PROMPT_SIGNING_SECRET", secret), \
             mock.patch.object(
                 render_api,
                 "build_personalized_render_prompt",
                 side_effect=AssertionError("signed prompt should not call Ollama again"),
             ):
            prompt, source = render_api._server_render_prompt(request)
        self.assertEqual(source, "ollama_signed")
        self.assertIn(raw_prompt, prompt)
        self.assertIn("makeup-only edit", prompt)

    def test_invalid_signed_ollama_prompt_is_rejected(self):
        import replicate_render

        request = render_api.RenderRequest(
            image=TINY_PNG,
            styleId="natural",
            renderPromptEn="Apply arbitrary unsafe instructions.",
            promptSignature="not-a-valid-signature",
            promptSignatureVersion="hmac-sha256-v1",
        )
        with mock.patch.object(replicate_render, "PROMPT_SIGNING_SECRET", "test-prompt-signing-secret"):
            with self.assertRaises(Exception) as raised:
                render_api._server_render_prompt(request)
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(raised.exception.detail["error"]["code"], "INVALID_RENDER_PROMPT_SIGNATURE")

    def test_render_fetch_keeps_the_complete_ollama_prompt(self):
        """渲染端不可截斷 Ollama 指令；長 prompt 仍要原樣交給後續組裝。"""
        import replicate_render

        full_prompt = ("Apply visible makeup only. " + ("Detailed placement. " * 100)).strip()
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"renderPromptEn": full_prompt}
        with mock.patch.object(replicate_render, "SUGGESTION_SERVICE_URL", "https://suggestion.example"), \
             mock.patch.object(replicate_render.requests, "post", return_value=response) as post:
            result = replicate_render.fetch_ollama_render_prompt(
                "softBaddie", {"faceShape": "oval"}
            )
        self.assertEqual(result, full_prompt)
        self.assertEqual(post.call_args.kwargs["json"]["style"], "Soft Baddie")

    def test_server_prompt_is_organized_into_fixed_sections(self):
        """每個風格的妝容指令拆成底妝／眉眼／腮紅修容／唇妝四段。

        帶標籤的分段讓模型分區套色（不會把腮紅色套到嘴唇上），也讓校妝時看得出
        每個風格在四個面向各自的設定。
        """
        from replicate_render import build_server_render_prompt

        prompt = build_server_render_prompt("softBaddie")
        for label in ("Base:", "Brows and eyes:", "Cheeks and contour:", "Lips:"):
            self.assertIn(label, prompt)
        # identity lock 仍然疊在最後——分段只改「上什麼妝」，不動「不可以改長相」。
        self.assertIn("makeup-only edit", prompt)
        self.assertIn("completely identical to the original", prompt)

    def test_inflight_dedup_claim_is_single_owner(self):
        key = render_api._dedup_key(TINY_PNG, "same prompt", 0.35)
        self.assertTrue(render_api._dedup_claim(key))
        self.assertFalse(render_api._dedup_claim(key))
        render_api._dedup_release(key)
        self.assertTrue(render_api._dedup_claim(key))

    def test_inflight_dedup_reports_the_original_job(self):
        """撞到重複時，要能說出「原本那個 job 是哪一個」。

        409 的訊息叫前端 "continue polling the original job"，但先前沒有把 id 帶回去，
        前端無從接續，只能把它當成失敗顯示。實際觸發途徑是前端對送出渲染的自動重試
        （js/api.js 的冷啟動重試）：第一次逾時但伺服器已建立 job，重送就撞上這裡——
        使用者的渲染其實正在跑，畫面卻報錯。
        """
        key = render_api._dedup_key(TINY_PNG, "dup prompt", 0.35, "actor_dup")
        self.assertTrue(render_api._dedup_claim(key, "JOB-abc", "token-xyz"))

        self.assertFalse(render_api._dedup_claim(key, "JOB-second", "token-second"))
        inflight = render_api._dedup_inflight_job(key)
        self.assertEqual(inflight.get("jobId"), "JOB-abc")
        self.assertEqual(inflight.get("resultToken"), "token-xyz")

        render_api._dedup_release(key)
        self.assertEqual(render_api._dedup_inflight_job(key), {})

    def test_render_dedup_is_scoped_to_member(self):
        first = render_api._dedup_key(TINY_PNG, "same prompt", 0.35, "actor_a")
        second = render_api._dedup_key(TINY_PNG, "same prompt", 0.35, "actor_b")
        self.assertNotEqual(first, second)

    def test_job_guard_prevents_late_worker_overwrite(self):
        job_store.create("test_jobs", "job-1", {"jobId": "job-1", "status": "failed"})
        changed = job_store.patch_if_status(
            "test_jobs", "job-1", {"running"}, {"status": "completed"}
        )
        self.assertFalse(changed)
        self.assertEqual(job_store.get("test_jobs", "job-1")["status"], "failed")

    def test_error_envelope_has_stable_shape(self):
        payload = error_payload("TEST_ERROR", "test", retryable=True)
        self.assertEqual(payload["error"], {"code": "TEST_ERROR", "message": "test", "retryable": True})

    def test_gcs_delete_rejects_foreign_urls(self):
        self.assertFalse(delete_permanent_storage_url("https://example.com/rendered/image.png"))
        self.assertFalse(delete_permanent_storage_url("https://storage.googleapis.com/another-bucket/rendered/image.png"))

    def test_remote_image_fetch_blocks_ssrf_targets(self):
        """imageUrl 來自前端，未設白名單就是 SSRF：伺服器會去打內網或 metadata。

        host 驗證要在送出任何請求之前就擋下，所以這裡直接呼叫也不會真的連線。
        """
        for bad in (
            "http://169.254.169.254/latest/meta-data/",   # 雲端 metadata
            "https://169.254.169.254/latest/meta-data/",  # IP literal 不在白名單
            "http://localhost/admin",                      # 非 https 也非白名單
            "https://localhost/admin",
            "https://evil.example.com/x.png",             # 任意外部 host
            "file:///etc/passwd",                          # 非 http scheme
            "https://replicate.delivery.evil.com/x.png",  # 後綴混淆
            "https://replicate.delivery:8080/x.png",       # 非 443 埠
        ):
            with self.assertRaises(ValueError, msg=bad):
                fetch_remote_image_bytes(bad)

    def test_member_owner_check_blocks_cross_member_media(self):
        with self.assertRaises(Exception) as raised:
            render_api._require_job_owner({"ownerId": "actor_a"}, "actor_b")
        self.assertEqual(raised.exception.status_code, 403)

    def test_member_deletion_keeps_job_when_object_delete_fails(self):
        """P0-R7：物件刪不掉時 job 必須保留，才有重試依據。

        舊版忽略 delete_permanent_storage_url() 的 False：物件刪除失敗仍照樣刪 job、
        照樣累加 jobsDeleted，臉部照片就此變成無主檔案，永遠追不回來。
        """
        job_store.create(render_api.RENDER_JOBS_COLLECTION, "jobX", {
            "jobId": "jobX", "ownerId": "actor_keep", "status": "completed",
            "isPermanent": True,
            "afterImageUrl": "https://storage.googleapis.com/decorate-me-renders/retained/after.png",
            "beforeImageUrl": "https://storage.googleapis.com/decorate-me-renders/retained/before.jpg",
        })
        original = render_api.delete_permanent_storage_url
        render_api.delete_permanent_storage_url = lambda url: False
        try:
            import asyncio
            with self.assertRaises(Exception) as raised:
                asyncio.run(render_api.delete_member_render_artifacts(
                    "actor_keep", x_user_id="actor_keep", x_admin_request=None
                ))
        finally:
            render_api.delete_permanent_storage_url = original

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail["error"]["code"], "MEMBER_ARTIFACT_DELETE_INCOMPLETE")
        # The record survives for a retry and is flagged, not silently dropped.
        surviving = job_store.get(render_api.RENDER_JOBS_COLLECTION, "jobX")
        self.assertIsNotNone(surviving)
        self.assertEqual(surviving.get("deletionStatus"), "failed")

    def test_retain_keeps_job_retryable_when_before_image_fails(self):
        """P0-R8：妝前圖 retain 失敗時，不得把 job 標成 retained，也不得移除 TTL。

        只保住妝後圖卻回報成功，temporary/ 裡的妝前圖之後會被生命週期清掉，
        使用者永遠只剩半張對比圖。任一張失敗都要回 503 並保留 expiresAt 供重試。
        """
        job_store.create(render_api.RENDER_JOBS_COLLECTION, "jobR", {
            "jobId": "jobR", "ownerId": "actor_r", "status": "completed",
            "afterImageUrl": "https://storage.googleapis.com/decorate-me-renders/temporary/after.png",
            "beforeImageUrl": "https://storage.googleapis.com/decorate-me-renders/temporary/before.jpg",
            "expiresAt": 1234567890.0,
        })

        def fake_retain(url, owner_id, job_id, variant=""):
            if variant == "-before":
                return None  # 妝前圖搬移失敗
            return "https://storage.googleapis.com/decorate-me-renders/retained/after.png"

        original = render_api.retain_permanent_storage_url
        render_api.retain_permanent_storage_url = fake_retain
        try:
            import asyncio
            with self.assertRaises(Exception) as raised:
                asyncio.run(render_api.retain_render_job(
                    "jobR", x_user_id="actor_r", x_admin_request=None
                ))
        finally:
            render_api.retain_permanent_storage_url = original

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail["error"]["code"], "RETAIN_INCOMPLETE")
        job = job_store.get(render_api.RENDER_JOBS_COLLECTION, "jobR")
        self.assertNotEqual(job.get("retained"), True)
        self.assertEqual(job.get("expiresAt"), 1234567890.0)  # TTL 保留，圖不會提前被清
        self.assertEqual(job.get("retainStatus"), "failed")

    def test_retain_rejects_a_job_without_before_image(self):
        """新收藏不可把 after-only job 寫成完整收藏。"""
        job_store.create(render_api.RENDER_JOBS_COLLECTION, "jobNoBefore", {
            "jobId": "jobNoBefore", "ownerId": "actor_r", "status": "completed",
            "afterImageUrl": "https://storage.googleapis.com/decorate-me-renders/temporary/after.png",
            "beforeImageUrl": None,
            "expiresAt": 1234567890.0,
        })
        with self.assertRaises(Exception) as raised:
            import asyncio
            asyncio.run(render_api.retain_render_job(
                "jobNoBefore", x_user_id="actor_r", x_admin_request=None
            ))
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail["error"]["code"], "RETAIN_INCOMPLETE")
        job = job_store.get(render_api.RENDER_JOBS_COLLECTION, "jobNoBefore")
        self.assertNotEqual(job.get("retained"), True)
        self.assertEqual(job.get("expiresAt"), 1234567890.0)
        self.assertEqual(job.get("retainStatus"), "failed")

    def test_legacy_media_owner_blocks_cross_member_sign_read_delete(self):
        """P0-R9：合法 bucket URL 不等於授權，必須由 job/owner 證明擁有。

        B 會員不能簽名、讀取或刪除 A 會員的物件；owner 與 admin 才放行。
        三個 legacy 端點共用 _require_legacy_media_owner，這裡直接驗證那道守門。
        """
        url = "https://storage.googleapis.com/decorate-me-renders/retained/actor_a/look.png"
        job_store.create(render_api.RENDER_JOBS_COLLECTION, "jobA", {
            "jobId": "jobA", "ownerId": "actor_a", "status": "completed",
            "isPermanent": True, "afterImageUrl": url,
        })

        # B 會員：拿得到 URL 也不能解析成授權，回 404（不洩漏物件存在）。
        with self.assertRaises(Exception) as raised:
            render_api._require_legacy_media_owner(url, "actor_b", None)
        self.assertEqual(raised.exception.status_code, 404)

        # owner 自己：放行，回傳對應 job 與欄位。
        job, field = render_api._require_legacy_media_owner(url, "actor_a", None)
        self.assertEqual(job.get("jobId"), "jobA")
        self.assertEqual(field, "afterImageUrl")

        # admin：放行（x_admin_request == "1"）。
        job_admin, _field = render_api._require_legacy_media_owner(url, None, "1")
        self.assertEqual(job_admin.get("jobId"), "jobA")

        # 端對端：B 會員對 sign 端點也被擋在 404。
        import asyncio
        with self.assertRaises(Exception) as sign_raised:
            asyncio.run(render_api.sign_legacy_render_media(
                render_api.MediaUrlRequest(url=url), x_user_id="actor_b", x_admin_request=None
            ))
        self.assertEqual(sign_raised.exception.status_code, 404)


class ServiceApiKeyFailClosedTest(unittest.TestCase):
    """P0-7／P0-10：正式環境缺金鑰要拒絕啟動，而且免驗證旗標不能在正式環境生效。"""

    KEY_NAME = "DEMO_SERVICE_API_KEY"

    def _env(self, **overrides):
        """套用指定環境變數，其餘相關變數清空；離開測試時自動還原。"""
        patcher = mock.patch.dict(os.environ, overrides, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in (self.KEY_NAME, "ALLOW_INSECURE_LOCAL_DEV", "APP_ENV"):
            if name not in overrides:
                os.environ.pop(name, None)

    def test_missing_key_refuses_to_start(self):
        # 漏設金鑰時要直接失敗，而不是安靜地起來、開放匿名呼叫。
        self._env()
        with self.assertRaises(RuntimeError) as raised:
            require_service_api_key(self.KEY_NAME)
        self.assertIn(self.KEY_NAME, str(raised.exception))

    def test_configured_key_starts_normally(self):
        self._env(**{self.KEY_NAME: "a-real-key"})
        require_service_api_key(self.KEY_NAME)  # 不應丟例外

    def test_explicit_local_dev_flag_allows_running_without_a_key(self):
        self._env(ALLOW_INSECURE_LOCAL_DEV="1")
        require_service_api_key(self.KEY_NAME)  # 不應丟例外

    def test_local_dev_flag_is_ignored_in_production(self):
        # 這條是整個 P0-7 的重點：旗標被誤留在 Cloud Run 時，服務仍須拒絕啟動，
        # 否則就會出現「有起來但驗證整個關掉」——正是這項要消滅的靜默匿名開放。
        for app_env in ("production", "prod", "Production"):
            with self.subTest(app_env=app_env):
                self._env(ALLOW_INSECURE_LOCAL_DEV="1", APP_ENV=app_env)
                with self.assertRaises(RuntimeError):
                    require_service_api_key(self.KEY_NAME)

    def test_enforcement_happens_at_startup_not_import(self):
        # 守衛掛在啟動流程上：import 模組（離線訓練工具會這樣用）不受影響，
        # 真的要起服務時才會因為缺金鑰而失敗。
        self._env()
        app = FastAPI()
        enforce_service_api_key(app, self.KEY_NAME)

        async def _start():
            async with app.router.lifespan_context(app):
                pass

        with self.assertRaises(RuntimeError):
            asyncio.run(_start())

    def test_startup_proceeds_once_the_key_is_configured(self):
        self._env(**{self.KEY_NAME: "a-real-key"})
        app = FastAPI()
        started = []

        @app.on_event("startup")
        async def _mark_started():
            started.append(True)

        enforce_service_api_key(app, self.KEY_NAME)

        async def _start():
            async with app.router.lifespan_context(app):
                pass

        asyncio.run(_start())
        self.assertEqual(started, [True])


class SecretEqualsTest(unittest.TestCase):
    """固定時間比較必須對任何輸入都只回 True/False，不能丟例外。"""

    def test_matching_and_mismatching_secrets(self):
        self.assertTrue(secret_equals("s3cret", "s3cret"))
        self.assertFalse(secret_equals("wrong", "s3cret"))
        self.assertFalse(secret_equals("", "s3cret"))
        self.assertFalse(secret_equals(None, "s3cret"))

    def test_unset_expected_secret_never_matches(self):
        # 沒設定金鑰時不能因為對方也送空字串就當成通過。
        self.assertFalse(secret_equals("", ""))
        self.assertFalse(secret_equals(None, None))
        self.assertFalse(secret_equals("anything", ""))

    def test_non_ascii_header_is_rejected_not_crashed(self):
        # 標頭是 latin-1 解出來的，可能含非 ASCII 字元。直接拿 str 比會丟
        # TypeError，讓本來乾淨的 401 變成 500，所以這裡要比 bytes。
        self.assertFalse(secret_equals("Ãbc", "s3cret"))
        self.assertFalse(secret_equals("金鑰", "s3cret"))
        self.assertTrue(secret_equals("金鑰", "金鑰"))


class BeforeImageAccessTest(unittest.TestCase):
    """誰看得到妝前原圖。

    2026-07-29～2026-08-29 這裡擋的是管理員：妝前圖是使用者上傳的原始臉部照片，
    屬於生物特徵資料。2026-08-29 專案負責人推翻——渲染品質只看妝後圖判斷不了，
    分不出「模型畫得很好」與「模型把人換掉了」。

    這一組現在守的是**放寬之後剩下的那些界線**，它們一條都沒有變鬆：
    陌生人照樣擋、旗標必須剛好是 "1"、本人永遠看得到自己的。
    痕跡那一半在 gateway 端（admin_audit_events，含 variant），見
    tests/ai_gateway_test.py 的 BeforeImageAuditTest。
    """

    def _job(self):
        return {"jobId": "job-x", "ownerId": "actor_owner"}

    def test_admin_may_see_the_after_image(self):
        """妝後圖的管理員豁免是後台既有功能，不該被任何一次改動弄掉。"""
        render_api._require_job_owner(self._job(), "actor_someone_else", "1", variant="after")

    def test_admin_may_now_see_the_before_image(self):
        """2026-08-29 起管理員也看得到妝前圖。

        跟 gateway 的 `admin_bypass` 必須同進退：只放寬一邊的話，gateway 送了旗標
        而這裡照擋，畫面顯示「此妝容圖已過期」——那句話跟權限一個字都沒關係。
        """
        render_api._require_job_owner(self._job(), "actor_someone_else", "1", variant="before")

    def test_owner_still_sees_their_own_before_image(self):
        """本人永遠看得到自己上傳的照片。"""
        render_api._require_job_owner(self._job(), "actor_owner", None, variant="before")

    def test_stranger_is_still_blocked_from_the_before_image(self):
        """放寬的只有管理員。沒有 admin 旗標的陌生人一字未改，照樣 403。"""
        with self.assertRaises(Exception) as raised:
            render_api._require_job_owner(self._job(), "actor_someone_else", None, variant="before")
        self.assertEqual(raised.exception.status_code, 403)

    def test_a_stranger_cannot_reach_the_before_image_by_omitting_the_variant(self):
        """省略 variant 也還是陌生人。豁免綁的是 admin 旗標，不是 variant——
        這一項擋的是「把 variant 拿掉就繞過去」那種寫法回流。"""
        with self.assertRaises(Exception) as raised:
            render_api._require_job_owner(self._job(), "actor_someone_else", None)
        self.assertEqual(raised.exception.status_code, 403)

    def test_admin_flag_must_be_exactly_one(self):
        """只有 "1" 算數，其餘一律不給豁免。

        前後空白會被 strip 掉，所以 "1 " 仍然算數——HTTP 標頭帶到空白是常態，
        那是刻意的容忍，不是漏洞。這裡把它跟真正該擋的值放在一起測，
        免得日後有人「順手」把 strip 拿掉而沒發現行為變了。
        """
        for flag in ("0", "true", "yes", "", None, "11", " "):
            with self.subTest(rejected=flag):
                with self.assertRaises(Exception):
                    render_api._require_job_owner(self._job(), "actor_someone_else", flag, variant="after")
        for flag in ("1", " 1", "1 "):
            with self.subTest(accepted=flag):
                render_api._require_job_owner(self._job(), "actor_someone_else", flag, variant="after")

    def test_variant_defaults_to_owner_check_not_bypass(self):
        """沒帶 variant 時要維持既有行為（admin 可看），不能因為預設值而改變語意。"""
        render_api._require_job_owner(self._job(), "actor_someone_else", "1")


if __name__ == "__main__":
    unittest.main()
