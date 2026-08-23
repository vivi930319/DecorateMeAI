"""POST /render（單次）與 POST /render/jobs（非同步）— render 契約。

實際 URL 經 Gateway 同源代理：`/<gateway>/render-service/render` 與
`/<gateway>/render-service/render/jobs`（見 js/api.js `renderMakeup` /
`renderMakeupAsync`）。介面預期渲染需等待 60–150 秒，因此完整成功案例
預設不執行，只在明確要求時才跑：

    $env:DM_RUN_SLOW_RENDER_TEST = "1"
"""
import os
import time

import pytest

from conftest import error_payload

RENDER_PATH = "/render-service/render"
RENDER_JOBS_PATH = "/render-service/render/jobs"

# 1x1 白色 PNG 的 data URL，足夠讓 Gateway 做欄位驗證，不代表真的能渲染成功。
TINY_PNG_DATA_URL = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _run_slow_tests():
    return os.environ.get("DM_RUN_SLOW_RENDER_TEST", "").strip() == "1"


def test_unauthenticated_render_returns_401(http, gateway_base_url):
    res = http.request(
        "POST", f"{gateway_base_url}{RENDER_PATH}",
        json={"image": TINY_PNG_DATA_URL, "prompt": "test prompt", "strength": 0.4},
    )
    assert res.status_code == 401, res.text
    err = error_payload(res)
    assert err and err.get("code") == "MEMBER_AUTH_REQUIRED", err


def test_unauthenticated_render_jobs_returns_401(http, gateway_base_url):
    res = http.request(
        "POST", f"{gateway_base_url}{RENDER_JOBS_PATH}",
        json={"image": TINY_PNG_DATA_URL, "styleId": "natural", "strength": 0.35},
    )
    assert res.status_code == 401, res.text
    err = error_payload(res)
    assert err and err.get("code") == "MEMBER_AUTH_REQUIRED", err


def test_missing_image_field_returns_4xx(member_session, gateway_base_url):
    res = member_session.post(f"{gateway_base_url}{RENDER_JOBS_PATH}", json={"styleId": "natural"})
    assert 400 <= res.status_code < 500, f"缺少 image 應回 4xx，實際 {res.status_code}：{res.text}"


def test_wrong_type_image_field_returns_4xx(member_session, gateway_base_url):
    res = member_session.post(
        f"{gateway_base_url}{RENDER_JOBS_PATH}", json={"image": 12345, "styleId": "natural"}
    )
    assert 400 <= res.status_code < 500, f"image 型別錯誤應回 4xx，實際 {res.status_code}：{res.text}"


def test_job_creation_returns_job_id_and_progress(member_session, gateway_base_url):
    """只驗證 job 建立契約（jobId／progress／status 是否存在），不等待渲染完成。"""
    res = member_session.post(
        f"{gateway_base_url}{RENDER_JOBS_PATH}",
        json={"image": TINY_PNG_DATA_URL, "styleId": "natural", "strength": 0.35},
    )
    if res.status_code >= 500:
        pytest.skip(f"下游渲染服務目前不可用（HTTP {res.status_code}），視為 BLOCKED：{res.text[:200]}")
    if res.status_code == 429:
        # 渲染有每小時配額（實測 10 次/3600 秒）。被限流時驗證 429 契約本身即可，
        # 不視為失敗——這正是 RATE_LIMITED 錯誤格式該長的樣子。
        err = error_payload(res)
        assert err and err.get("code") == "RATE_LIMITED", err
        assert err.get("retryAfterSeconds") is not None, f"429 應提供 retryAfterSeconds：{err}"
        pytest.skip(f"渲染配額已用盡（429 RATE_LIMITED，{err.get('retryAfterSeconds')}s 後重置），已驗證限流契約")
    assert res.status_code in (200, 202), f"合法請求應被接受，實際 {res.status_code}：{res.text}"
    data = res.json()
    if data.get("status") == "completed":
        assert data.get("afterImageUrl"), "status=completed 卻沒有 afterImageUrl"
    else:
        assert data.get("jobId"), f"未完成的渲染應回傳 jobId 供輪詢：{data}"


@pytest.mark.skipif(not _run_slow_tests(), reason="預設不執行完整渲染流程（60–150 秒），需要 DM_RUN_SLOW_RENDER_TEST=1")
def test_full_render_job_completes_within_5_minutes(member_session, gateway_base_url):
    submit = member_session.post(
        f"{gateway_base_url}{RENDER_JOBS_PATH}",
        json={"image": TINY_PNG_DATA_URL, "styleId": "natural", "strength": 0.35},
    )
    assert submit.status_code in (200, 202), submit.text
    submitted = submit.json()
    if submitted.get("status") == "completed":
        assert submitted.get("afterImageUrl")
        return
    job_id = submitted.get("jobId")
    assert job_id, f"缺少 jobId 無法輪詢：{submitted}"

    deadline = time.time() + 5 * 60
    poll_url = f"{gateway_base_url}{RENDER_JOBS_PATH}/{job_id}"
    last = None
    while time.time() < deadline:
        time.sleep(5)
        poll_res = member_session.get(poll_url)
        assert poll_res.status_code == 200, poll_res.text
        last = poll_res.json()
        if last.get("status") == "completed":
            assert last.get("afterImageUrl"), f"完成卻沒有 afterImageUrl：{last}"
            return
        if last.get("status") == "failed":
            pytest.fail(f"渲染 job 回報失敗：{last}")
    pytest.fail(f"渲染在 5 分鐘內未完成，最後狀態：{last}")
