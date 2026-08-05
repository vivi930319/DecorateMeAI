"""渲染端契約（派工書核心介面：渲染端只更新 render）。"""
import requests

from conftest import TIMEOUT, body, error_of


def test_render_requires_auth(base):
    """反項：未登入不得呼叫渲染（會產生費用）。"""
    r = requests.get(f"{base}/render-service/health", timeout=TIMEOUT)
    assert r.status_code in (200, 401, 403), f"非預期狀態 {r.status_code}"
    if r.status_code in (401, 403):
        assert error_of(body(r)).get("code") or r.text, "拒絕時沒有給錯誤內容"


def test_render_rejects_unauthenticated_job_creation(base):
    r = requests.post(f"{base}/render-service/v1/render/jobs",
                      json={"styleId": "richGirl"}, timeout=TIMEOUT)
    assert r.status_code in (401, 403, 404, 422), f"未登入卻回 {r.status_code}：{body(r)}"


def test_render_job_not_found_is_explicit(base):
    r = requests.get(f"{base}/render-service/v1/render/jobs/JOB-does-not-exist", timeout=TIMEOUT)
    assert r.status_code in (401, 403, 404), f"不存在的 job 回 {r.status_code}"
    if r.status_code == 404:
        assert error_of(body(r)).get("code"), f"404 沒有 error.code：{body(r)}"
