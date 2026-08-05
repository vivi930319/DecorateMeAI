"""BASIC／PRO 契約（派工書核心介面第 3、4 列）。

打的是已部署的 face-basic／face-pro，經 `gcloud run services proxy` 的本機通道
（服務私有）並帶服務層 x-api-key。
"""
import time

import requests

from conftest import TIMEOUT, body, error_of, face_headers, png_bytes


def _run_job(base, path, files, timeout=200):
    r = requests.post(f"{base}{path}", files=files, headers=face_headers(), timeout=TIMEOUT)
    if r.status_code >= 400:
        return {"_http": r.status_code, "_body": body(r)}
    sub = r.json()
    h = face_headers({"X-Job-Token": sub["resultToken"]} if sub.get("resultToken") else None)
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = requests.get(f"{base}/v1/face/jobs/{sub['jobId']}", headers=h, timeout=TIMEOUT).json()
        if s.get("status") in ("completed", "failed"):
            s["_token"] = sub.get("resultToken")
            return s
        time.sleep(2)
    return {"_timeout": True}


def test_health(basic_url, pro_url):
    for url in (basic_url, pro_url):
        h = requests.get(f"{url}/health", timeout=TIMEOUT).json()
        assert h.get("status") == "ok", h
        models = h.get("models") or {}
        flat = models if "ready" in models else models.get("basic", {})
        assert flat.get("ready") is True, f"模型未就緒：{models}"
        assert not flat.get("missing"), f"模型缺件：{flat.get('missing')}"


def test_basic_sync_returns_expected_fields(basic_url, face_image):
    r = requests.post(f"{basic_url}/v1/face/analyze/basic",
                      files={"file": ("front.png", face_image, "image/png")},
                      headers=face_headers(), timeout=TIMEOUT)
    assert r.status_code == 200, body(r)
    data = r.json()
    for key in ("臉型", "眼型", "鼻型", "膚色"):
        assert data.get(key), f"缺 {key}"
    rel = (data["膚色"] or {}).get("可信度")
    assert isinstance(rel, dict), f"膚色缺可信度物件：{data['膚色']}"
    for key in ("measured", "reliable", "threshold"):
        assert key in rel, f"可信度缺 {key}：{rel}"


def test_pro_skin_tone_comes_from_front_photo_only(pro_url, basic_url, face_image, side_image):
    """2026-08-05 起 PRO 不再做正面+側面平均，膚色必須等於正面照的結果。"""
    b = requests.post(f"{basic_url}/v1/face/analyze/basic",
                      files={"file": ("front.png", face_image, "image/png")},
                      headers=face_headers(), timeout=TIMEOUT).json()
    p = requests.post(f"{pro_url}/v1/face/analyze/pro",
                      files={"front": ("front.png", face_image, "image/png"),
                             "side": ("side.jpg", side_image, "image/jpeg")},
                      headers=face_headers(), timeout=TIMEOUT)
    assert p.status_code == 200, body(p)
    pj = p.json()
    assert pj["膚色"]["LAB"] == b["膚色"]["LAB"], "PRO 膚色與正面照不同，側面照仍被混入"
    assert "LAB來源" not in pj["膚色"], "仍有 LAB來源，代表還在做雙角度平均"
    assert pj.get("側面照已使用") is True, "缺 側面照已使用 欄位"


def test_unusable_photo_reports_its_own_code(basic_url):
    """反項：照片問題要回 FACE_IMAGE_UNUSABLE，訊息原樣傳給使用者。"""
    job = _run_job(basic_url, "/v1/face/jobs/basic",
                   {"file": ("blank.png", png_bytes(), "image/png")})
    assert job.get("status") == "failed", job
    assert job.get("stage") == "unusable_image", job
    err = job.get("error") or {}
    assert err.get("code") == "FACE_IMAGE_UNUSABLE", err
    assert err.get("message") == "沒偵測到人臉", err
    assert err.get("retryable") is True, err


def test_missing_api_key_is_rejected(basic_url, face_image):
    """反項：未帶服務金鑰不得放行。"""
    r = requests.post(f"{basic_url}/v1/face/analyze/basic",
                      files={"file": ("front.png", face_image, "image/png")}, timeout=TIMEOUT)
    assert r.status_code in (401, 403), f"未帶金鑰卻回 {r.status_code}"
    assert error_of(body(r)).get("code") == "FORBIDDEN"


def test_job_result_requires_correct_token(basic_url, face_image):
    """反項：job 結果要綁 token，換一個就不得取得。"""
    job = _run_job(basic_url, "/v1/face/jobs/basic",
                   {"file": ("front.png", face_image, "image/png")})
    assert job.get("status") == "completed", job
    jid = job["jobId"]
    bad = requests.get(f"{basic_url}/v1/face/jobs/{jid}/result",
                       headers=face_headers({"X-Job-Token": "wrong"}), timeout=TIMEOUT)
    assert bad.status_code == 403, f"錯 token 竟回 {bad.status_code}"
    good = requests.get(f"{basic_url}/v1/face/jobs/{jid}/result",
                        headers=face_headers({"X-Job-Token": job["_token"]}), timeout=TIMEOUT)
    assert good.status_code == 200
