import os
import sys
import types
import unittest


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
from api_errors import error_payload
from replicate_render import data_url_to_bytes, delete_permanent_storage_url


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

        先前只收集 afterImageUrl，所以使用者刪掉帳號之後，他上傳的原始照片
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

        命中去重會用 _response_from_completed_job 建立一個**新的** job。先前它沒有
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

    def test_render_request_rejects_untrusted_style(self):
        request = render_api.RenderRequest(image=TINY_PNG, styleId="untrusted-prompt")
        with self.assertRaises(Exception) as raised:
            render_api._server_render_prompt(request)
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(raised.exception.detail["error"]["code"], "INVALID_RENDER_STYLE")

    def test_inflight_dedup_claim_is_single_owner(self):
        key = render_api._dedup_key(TINY_PNG, "same prompt", 0.35)
        self.assertTrue(render_api._dedup_claim(key))
        self.assertFalse(render_api._dedup_claim(key))
        render_api._dedup_release(key)
        self.assertTrue(render_api._dedup_claim(key))

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

    def test_member_owner_check_blocks_cross_member_media(self):
        with self.assertRaises(Exception) as raised:
            render_api._require_job_owner({"ownerId": "actor_a"}, "actor_b")
        self.assertEqual(raised.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
