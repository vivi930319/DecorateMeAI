"""上游失敗時，Gateway 該送回什麼。

自架的三個上游（會員資料庫、商品、建議文案）都掛在 trycloudflare 的快速通道上，
斷線是常態不是例外——2026-09-02 到 09-04 三天的日誌裡約四十筆 502/503/530。

斷線本身修不掉（要換具名通道，那是另一件事）。這一支守的是「斷線的時候，
送回瀏覽器的東西不能是 Cloudflare 那頁 HTML」，理由有兩個：

  1. 那頁 HTML 裡印著 tunnel 的主機名稱，而 Gateway 存在的理由之一就是
     瀏覽器永遠不會知道上游網址——那些 tunnel 沒有 Gateway 這一層的授權檢查。
  2. 前端在等 JSON。拿到 7KB 的 HTML 之後 res.json() 直接爆，於是使用者看到的
     永遠是一句沒有資訊的通用錯誤。

同時要守住反面：上游**自己**的 JSON 錯誤必須原樣保留。
「收藏妝容已達 50 筆上限」是使用者唯一能據以行動的訊息，2026-09-04 就是因為
它被吃掉，一個明確的上限訊息被查了兩天才查出來。
"""
import asyncio
import os
import sys
import unittest
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway"))
sys.path.insert(0, str(ROOT / "shared"))

os.environ.setdefault("GATEWAY_SESSION_SECRET", "test-session-secret-that-is-at-least-32-bytes")

import ai_gateway as gateway  # noqa: E402

# 真的那頁的形狀：Cloudflare 1033，整頁 HTML，主機名稱印在裡面好幾次。
TUNNEL_HOST = "approve-election-mainly-instead.trycloudflare.com"
CLOUDFLARE_1033 = (
    "<!DOCTYPE html><html><head><title>Cloudflare Tunnel error | "
    f"{TUNNEL_HOST} | Cloudflare</title></head><body>"
    f"<p>You've requested a page on a website ({TUNNEL_HOST}) that is on the "
    "Cloudflare network. Error 1033.</p></body></html>"
).encode("utf-8")


def _response(status, *, content=b"", content_type=None):
    headers = {"content-type": content_type} if content_type else {}
    return httpx.Response(status, headers=headers, content=content)


class SanitisesUpstreamFailuresTest(unittest.TestCase):
    def test_a_tunnel_error_page_never_reaches_the_browser(self):
        result = gateway.upstream_failure_payload(
            _response(530, content=CLOUDFLARE_1033, content_type="text/html; charset=UTF-8"))

        self.assertIsNotNone(result, "530 帶著一整頁 HTML，不能原樣轉出去")
        status, payload = result
        self.assertEqual(status, 502, "530 是 Cloudflare 專用碼，對前端沒有意義")
        self.assertEqual(payload["error"]["code"], "UPSTREAM_UNAVAILABLE")

    def test_the_tunnel_hostname_is_not_in_what_we_send_back(self):
        """這是這支測試最重要的一項：上游網址不能因為上游掛掉就洩漏出去。"""
        _status, payload = gateway.upstream_failure_payload(
            _response(530, content=CLOUDFLARE_1033, content_type="text/html; charset=UTF-8"))

        self.assertNotIn(TUNNEL_HOST, str(payload))
        self.assertNotIn("trycloudflare", str(payload).lower())

    def test_an_upstream_json_error_is_passed_through_untouched(self):
        """上游把話講清楚時不要蓋掉它。

        「收藏妝容已達 50 筆上限」這種訊息換成「服務暫時無法使用」，
        使用者就完全不知道自己該去刪幾筆。
        """
        body = (b'{"success":false,"error":{"code":"SAVED_LOOK_LIMIT",'
                b'"message":"\\u6536\\u85cf\\u5993\\u5bb9\\u5df2\\u9054 50 \\u7b46\\u4e0a\\u9650"}}')
        self.assertIsNone(gateway.upstream_failure_payload(
            _response(409, content=body, content_type="application/json")))

    def test_a_success_is_never_touched(self):
        self.assertIsNone(gateway.upstream_failure_payload(
            _response(200, content=b'{"ok":true}', content_type="application/json")))

    def test_json_content_type_but_broken_body_is_still_replaced(self):
        """宣稱是 JSON 卻解不開時，前端一樣會爆——要換掉。"""
        result = gateway.upstream_failure_payload(
            _response(502, content=b"<html>gateway timeout</html>",
                      content_type="application/json"))
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 502)

    def test_a_4xx_html_body_keeps_its_status(self):
        """4xx 是上游對這次請求的判斷，狀態碼有意義，只換掉 body。"""
        status, payload = gateway.upstream_failure_payload(
            _response(404, content=b"<html>not found</html>", content_type="text/html"))
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "UPSTREAM_ERROR")

    def test_an_upstream_500_collapses_to_502(self):
        status, _payload = gateway.upstream_failure_payload(
            _response(500, content=b"<html>oops</html>", content_type="text/html"))
        self.assertEqual(status, 502)


class _RecordingClient:
    """照著給定的腳本回應，並記下被呼叫幾次。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def request(self, **kwargs):
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return _response(item)


class RetriesOnlyReplayableMethodsTest(unittest.TestCase):
    def _run(self, client, method):
        return asyncio.run(gateway.request_upstream(
            client, method=method, url="https://upstream.invalid/thing"))

    def setUp(self):
        # 重試之間的等待在測試裡沒有意義，只會讓整份測試變慢。
        self._real_backoff = gateway.UPSTREAM_RETRY_BACKOFF_SECONDS
        gateway.UPSTREAM_RETRY_BACKOFF_SECONDS = (0, 0)

    def tearDown(self):
        gateway.UPSTREAM_RETRY_BACKOFF_SECONDS = self._real_backoff

    def test_a_get_that_hits_a_blip_is_retried_and_succeeds(self):
        """孤立的單筆 530 正是重試要吃掉的那一種。"""
        client = _RecordingClient([530, 200])
        response = self._run(client, "GET")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(client.calls), 2)

    def test_a_post_is_never_retried(self):
        """上游可能已經做完才斷線，重放會長出第二筆收藏、第二次扣點。"""
        client = _RecordingClient([530, 200])
        response = self._run(client, "POST")

        self.assertEqual(response.status_code, 530)
        self.assertEqual(len(client.calls), 1, "寫入一次就是一次")

    def test_retries_give_up_and_return_the_last_failure(self):
        """斷得夠久時要停下來，不能一直重試把使用者晾在那裡。"""
        client = _RecordingClient([530, 530, 530])
        response = self._run(client, "GET")

        self.assertEqual(response.status_code, 530)
        self.assertEqual(len(client.calls), 3)

    def test_a_business_error_is_not_retried(self):
        """409 是上游想清楚後的答案，重試三次答案還是一樣，只是慢三倍。"""
        client = _RecordingClient([409, 200])
        response = self._run(client, "GET")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(client.calls), 1)

    def test_a_transport_error_on_the_last_attempt_is_re_raised(self):
        """要讓呼叫端既有的 except 照常決定回 502 還是 504。"""
        client = _RecordingClient([httpx.ConnectError("boom"), httpx.ConnectError("boom"),
                                   httpx.ConnectError("boom")])
        with self.assertRaises(httpx.HTTPError):
            self._run(client, "GET")
        self.assertEqual(len(client.calls), 3)

    def test_a_post_transport_error_is_raised_immediately(self):
        client = _RecordingClient([httpx.ConnectError("boom"), 200])
        with self.assertRaises(httpx.HTTPError):
            self._run(client, "POST")
        self.assertEqual(len(client.calls), 1)


if __name__ == "__main__":
    unittest.main()
