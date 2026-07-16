import os
import sys
import types
import unittest
from pathlib import Path


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

    def test_frontend_does_not_store_plaintext_password(self):
        api_source = Path("firebase-hosting-full/public/js/api.js").read_text(encoding="utf-8")
        router_source = Path("firebase-hosting-full/public/js/router.js").read_text(encoding="utf-8")
        self.assertNotIn("sessionStorage.setItem('beautyAuthCreds'", api_source)
        self.assertNotIn("password: n1", router_source)


if __name__ == "__main__":
    unittest.main()
