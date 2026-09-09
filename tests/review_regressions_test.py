"""Offline behavioral regressions for the September frontend/backend review.

Synthetic images and in-memory stores only; no model inference or provider calls.
"""
import asyncio
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import cv2
import httpx
import numpy as np
import pytest

from ai_gateway_test import gateway  # installs the suite's fake session/key fixtures before import
import Face_analyzer_BASIC as basic
import Face_analyzer_PRO as pro
import face_contributions
import face_corrections
import job_store
# Reuse the existing offline provider stub before importing the render API.
from render_api_test import render_api, TINY_PNG


@pytest.fixture
def memory(monkeypatch):
    monkeypatch.setattr(job_store, "firestore", None)
    monkeypatch.setattr(job_store, "_client", None)
    monkeypatch.setattr(job_store, "_memory_jobs", {})
    monkeypatch.setattr(render_api, "_dedup_cache", {})
    monkeypatch.setattr(render_api, "_dedup_inflight", {})


def request_fixture():
    request = Mock()
    request.method = "POST"
    request.headers = {"accept": "application/json", "x-user-id": "spoofed", "x-user-role": "admin"}
    request.client.host = "127.0.0.1"
    request.query_params.multi_items.return_value = []
    request.body = AsyncMock(return_value=b"{}")
    request.app.state.http_client.request = AsyncMock(return_value=httpx.Response(200, json={"status": "queued"}))
    return request


@pytest.mark.parametrize("service,mode", [("face-basic", "basic"), ("face-pro", "pro")])
def test_face_proxy_uses_verified_owner_not_browser(monkeypatch, memory, service, mode):
    request = request_fixture()
    monkeypatch.setitem(gateway.UPSTREAMS, service, replace(gateway.UPSTREAMS[service], base_url="https://offline.invalid", requires_cloud_run_iam=False))
    monkeypatch.setattr(gateway, "SESSION_ONLY_MODE", True)
    monkeypatch.setattr(gateway, "GUEST_TRIAL_ENABLED", False)
    monkeypatch.setattr(gateway, "MULTI_SESSION_ENABLED", False)
    monkeypatch.setattr(gateway, "require_member_access", lambda _: {"sub": "member@example.invalid", "role": "member"})
    monkeypatch.setattr(gateway, "enforce_expected_actor", lambda *_: None)
    monkeypatch.setattr(gateway, "require_pro_analysis_access", AsyncMock(return_value=("", "")))
    response = asyncio.run(gateway.proxy(service, f"v1/face/jobs/{mode}", request))
    assert response.status_code == 200
    owner = request.app.state.http_client.request.call_args.kwargs["headers"]["X-User-ID"]
    assert owner == gateway.opaque_actor_id("member@example.invalid")
    monkeypatch.setattr(face_corrections, "ENABLED", True)
    face_corrections.remember("fixture-photo", {"眉型": "一字眉"}, owner_id=owner)
    result = face_corrections.apply({"眉型": "拱形眉"}, "fixture-photo", owner_id=owner)
    assert result["眉型"] == "一字眉"
    assert face_corrections.apply({"眉型": "拱形眉"}, "fixture-photo", owner_id="another")["眉型"] == "拱形眉"


@pytest.mark.parametrize("member,allowed", [
    ({"level": "一般會員"}, False),
    ({"level": "VIP會員"}, True),
    ({"level": "PRO會員"}, True),
    ({"permission": {"allowedPages": ["analysisPro"]}}, True),
    ({"allowedPages": "analysisPro"}, False),
    ({"level": "VIP會員", "status": "suspended"}, False),
    ({"level": "VIP會員", "permission": {"status": "suspended"}}, False),
])
def test_pro_permission_comes_from_member_service(monkeypatch, member, allowed):
    request = request_fixture()
    request.app.state.http_client.get = AsyncMock(return_value=httpx.Response(200, json={"member": {"email": "member@example.invalid", **member}}, request=httpx.Request("GET", "https://member.invalid/api/members/fixture")))
    monkeypatch.setattr(gateway, "MEMBER_DATABASE_URL", "https://member.invalid")
    monkeypatch.setattr(gateway, "MULTI_SESSION_ENABLED", False)
    monkeypatch.setattr(gateway, "require_upstream_member_cookie", lambda _: "session=verified")
    claims = {"sub": "member@example.invalid", "role": "member", "level": "VIP會員"}
    if allowed:
        assert asyncio.run(gateway.require_pro_analysis_access(request, claims)) == ("session=verified", "session=verified")
    else:
        with pytest.raises(gateway.HTTPException) as exc:
            asyncio.run(gateway.require_pro_analysis_access(request, claims))
        assert exc.value.status_code == 403
    assert request.app.state.http_client.get.call_args.kwargs["headers"]["Cookie"] == "session=verified"


@pytest.mark.parametrize("response,status", [
    # 上游掛了、或回的不是能解析的 JSON——這才是真正的「暫時看不出來」，可重試。
    (httpx.Response(503), 503),
    (httpx.Response(200, text="not-json"), 503),
    # 指名要 A 卻拿回 B：這是權限問題，不是暫時故障。回可重試的 503 等於叫使用者
    # 去重試一個永遠不會改變的結果，畫面說「請稍後再試」但他等到天亮也一樣。
    (httpx.Response(200, json={"member": {"email": "other@example.invalid", "level": "VIP會員"}}), 403),
])
def test_pro_permission_fails_closed_for_missing_or_wrong_profile(monkeypatch, response, status):
    request = request_fixture()
    request.app.state.http_client.get = AsyncMock(return_value=response)
    monkeypatch.setattr(gateway, "MEMBER_DATABASE_URL", "https://member.invalid")
    monkeypatch.setattr(gateway, "MULTI_SESSION_ENABLED", False)
    monkeypatch.setattr(gateway, "require_upstream_member_cookie", lambda _: "session=verified")
    with pytest.raises(gateway.HTTPException) as exc:
        asyncio.run(gateway.require_pro_analysis_access(request, {"sub": "member@example.invalid"}))
    assert exc.value.status_code == status
    request.app.state.http_client.request.assert_not_called()


@pytest.mark.parametrize("field", ["email", "memberEmail", "account"])
def test_pro_permission_accepts_every_identity_field_spelling(monkeypatch, field):
    """會員名冊（member_directory_emails）三種拼法都認，權限這條也必須跟著。

    只認 `email` 的話，資料列用另外兩種存信箱的會員會被判成身分不符，然後拿到一個
    標著 retryable 的 503——他永遠開不了 PRO，而且畫面告訴他這只是暫時故障，
    所以他不會回報。兩處讀的是同一份上游資料，讀法不一致就會產生這種幽靈帳號。
    """
    request = request_fixture()
    request.app.state.http_client.get = AsyncMock(return_value=httpx.Response(
        200, json={"member": {field: "member@example.invalid", "level": "VIP會員"}},
        request=httpx.Request("GET", "https://member.invalid/api/members/fixture")))
    monkeypatch.setattr(gateway, "MEMBER_DATABASE_URL", "https://member.invalid")
    monkeypatch.setattr(gateway, "MULTI_SESSION_ENABLED", False)
    monkeypatch.setattr(gateway, "require_upstream_member_cookie", lambda _: "session=verified")
    granted = asyncio.run(gateway.require_pro_analysis_access(
        request, {"sub": "member@example.invalid", "role": "member"}))
    assert granted == ("session=verified", "session=verified")


def test_pro_denial_stops_proxy_before_forwarding(monkeypatch):
    request = request_fixture()
    request.app.state.http_client.get = AsyncMock(return_value=httpx.Response(
        200, json={"member": {"email": "member@example.invalid", "level": "一般會員"}}))
    monkeypatch.setattr(gateway, "SESSION_ONLY_MODE", True)
    monkeypatch.setattr(gateway, "GUEST_TRIAL_ENABLED", False)
    monkeypatch.setattr(gateway, "MULTI_SESSION_ENABLED", False)
    monkeypatch.setattr(gateway, "MEMBER_DATABASE_URL", "https://member.invalid")
    monkeypatch.setattr(gateway, "require_member_access", lambda _: {"sub": "member@example.invalid", "role": "member"})
    monkeypatch.setattr(gateway, "require_upstream_member_cookie", lambda _: "session=verified")
    monkeypatch.setattr(gateway, "enforce_expected_actor", lambda *_: None)
    with pytest.raises(gateway.HTTPException) as exc:
        asyncio.run(gateway.proxy("face-pro", "v1/face/jobs/pro", request))
    assert exc.value.status_code == 403
    request.app.state.http_client.request.assert_not_called()


def test_pro_multi_account_check_uses_selected_cookie_and_returns_rotation(monkeypatch):
    request = request_fixture()
    request.app.state.http_client.get = AsyncMock(return_value=httpx.Response(
        200, json={"email": "member@example.invalid", "allowedPages": ["analysisPro"]},
        headers={"Set-Cookie": "session=rotated; Path=/; HttpOnly"},
        request=httpx.Request("GET", "https://member.invalid/api/members/fixture")))
    monkeypatch.setattr(gateway, "MEMBER_DATABASE_URL", "https://member.invalid")
    monkeypatch.setattr(gateway, "MULTI_SESSION_ENABLED", True)
    unseal = Mock(return_value="session=selected-account")
    monkeypatch.setattr(gateway, "unseal_member_cookie", unseal)
    old, new = asyncio.run(gateway.require_pro_analysis_access(request, {"sub": "member@example.invalid"}, "sealed-selected"))
    unseal.assert_called_once_with("sealed-selected")
    assert old == "session=selected-account"
    assert new == "session=rotated"
    assert request.app.state.http_client.get.call_args.kwargs["headers"]["Cookie"] == old


def synthetic_image():
    return cv2.imencode(".png", np.zeros((32, 48, 3), np.uint8))[1].tobytes()


def test_pose_order_matches_insightface(monkeypatch):
    face = SimpleNamespace(pose=np.array([0.0, 30.0, 0.0]), det_score=0.99)
    monkeypatch.setattr(basic, "_get_insight", lambda: SimpleNamespace(get=lambda _: [face]))
    pose = basic._detect_pose(synthetic_image())
    assert (pose["yaw"], pose["pitch"], pose["captureRole"]) == (30, 0, "side")
    landmarks = SimpleNamespace(landmark=[SimpleNamespace(x=0.5, y=0.5)] * 468)
    monkeypatch.setattr(basic, "_process_face_mesh", lambda _: SimpleNamespace(multi_face_landmarks=[landmarks]))
    analyzer = basic.FaceAnalyzer(synthetic_image(), strict_angle=False)
    assert (analyzer.pose_yaw, analyzer.pose_pitch) == (30, 0)
    face.pose = np.array([20.0, 0.0, 0.0])
    with pytest.raises(ValueError, match="鏡頭"):
        basic.FaceAnalyzer(synthetic_image())


def _detects_a_face(found=True):
    """側面照的人臉存在檢查。只問偵測結果空不空，不看角度也不看 landmark。"""
    faces = [SimpleNamespace(det_score=0.9)] if found else []
    return lambda: SimpleNamespace(get=lambda _: faces)


def test_side_model_does_not_require_face_mesh(monkeypatch):
    monkeypatch.setattr(pro, "FaceAnalyzer", Mock(side_effect=AssertionError("must not need landmarks")))
    monkeypatch.setattr(pro, "_get_insight", _detects_a_face())
    nose = {"label": "直挺鼻", "caveat": "fixture"}
    predict = Mock(return_value=nose)
    monkeypatch.setattr(pro.pro_nose_side_model, "predict", predict)
    result = pro._analyze_side_supplementary(synthetic_image())
    assert result["側臉鼻型"] == nose
    assert predict.call_args.args[0].shape == (32, 48, 3)
    assert pro._merge_basic_and_pro({}, result)["側面照已使用"] is True


def test_side_photo_without_a_face_is_not_reported_as_a_nose_type(monkeypatch):
    """風景照、截圖、隨手拍的桌面都解得開，而分類器對它們照樣回一個帶 label 的結果。

    沒有這道閘門的話，那個結果會被當成真的「側臉鼻型」報出去，還標上「側面照已使用」
    —— 使用者看到一個看起來很確定的分析，但它跟他的臉毫無關係。
    """
    predict = Mock(return_value={"label": "直挺鼻", "caveat": "fixture"})
    monkeypatch.setattr(pro.pro_nose_side_model, "predict", predict)
    monkeypatch.setattr(pro, "_get_insight", _detects_a_face(found=False))
    result = pro._analyze_side_supplementary(synthetic_image())
    assert result == {}
    predict.assert_not_called()
    merged = pro._merge_basic_and_pro({}, result)
    # 照片確實收到了，只是沒有結果——這兩件事在回應上必須分得開。
    assert merged["側面照已接收"] is True
    assert merged["側面照已使用"] is False


@pytest.mark.parametrize("failure", [None, RuntimeError("offline unavailable")])
def test_pro_received_photo_without_prediction_is_not_reported_as_missing(monkeypatch, failure):
    # 臉是有的——這條測的是「分類器沒給答案」，不是「照片裡沒有臉」（那條在上面）。
    monkeypatch.setattr(pro, "_get_insight", _detects_a_face())
    monkeypatch.setattr(pro.pro_nose_side_model, "predict", Mock(return_value=None, side_effect=failure))
    merged = pro._merge_basic_and_pro({}, pro._analyze_side_supplementary(synthetic_image()))
    assert merged["側面照已接收"] is True
    assert merged["側面照已使用"] is False
    assert "未提供" not in merged["精細分析狀態"]["多角度照片"]
    assert pro._merge_basic_and_pro({}, None)["側面照已接收"] is False


def test_failed_member_image_deletion_does_not_report_success(monkeypatch):
    monkeypatch.setattr(face_contributions, "_client", Mock(side_effect=OSError("offline storage failure")))
    endpoint = next(r.endpoint for r in basic.app.routes if getattr(r, "path", "") == "/v1/face/users/{owner_id}")
    with pytest.raises(gateway.HTTPException) as exc:
        asyncio.run(endpoint("actor_fixture", x_user_id="actor_fixture", x_admin_request=None))
    assert exc.value.status_code == 503
    assert exc.value.detail["error"]["code"] == "FACE_DATA_DELETE_INCOMPLETE"


def test_partial_deletion_failure_propagates_and_can_retry(monkeypatch):
    blobs = [SimpleNamespace(metadata={"ownerId": "actor_fixture"}, delete=Mock()),
             SimpleNamespace(metadata={"ownerId": "actor_fixture"}, delete=Mock(side_effect=OSError("offline")))]
    monkeypatch.setattr(face_contributions, "_client", lambda: SimpleNamespace(list_blobs=lambda *a, **k: iter(blobs)))
    with pytest.raises(OSError):
        face_contributions.delete_for_owner("actor_fixture")
    blobs.pop(0)
    blobs[0].delete.side_effect = None
    assert face_contributions.delete_for_owner("actor_fixture") == 1


def test_retained_capacity_never_evicts_active_jobs(monkeypatch, memory):
    now = time.time()
    col = render_api.RENDER_JOBS_COLLECTION
    monkeypatch.setattr(render_api, "RENDER_JOB_MAX_COUNT", 200)
    for i in range(200):
        job_store.create(col, f"saved-{i}", {"jobId": f"saved-{i}", "status": "completed", "retained": True, "createdAt": now-10, "finishedAt": now-5})
    for state in ("queued", "running"):
        job_store.create(col, state, {"jobId": state, "status": state, "createdAt": now, "startedAt": now})
    render_api._cleanup_render_jobs()
    for state in ("queued", "running"):
        assert job_store.get(col, state)["status"] == state


def test_capacity_still_prunes_oldest_unretained_terminal_job(monkeypatch, memory):
    now = time.time()
    col = render_api.RENDER_JOBS_COLLECTION
    monkeypatch.setattr(render_api, "RENDER_JOB_MAX_COUNT", 2)
    for i in range(3):
        job_store.create(col, str(i), {"jobId": str(i), "status": "failed", "createdAt": now-10+i, "finishedAt": now})
    render_api._cleanup_render_jobs()
    assert job_store.get(col, "0") is None
    assert job_store.get(col, "1") and job_store.get(col, "2")


def test_deleting_source_preserves_unretained_duplicate(monkeypatch, memory):
    now = time.time()
    req = render_api.RenderRequest(image=TINY_PNG, styleId="natural")
    key = render_api._dedup_key(req.image, "fixture", req.strength, "actor_fixture")
    original = {"jobId": "a"*32, "status": "completed", "retained": True, "ownerId": "actor_fixture", "createdAt": now, "finishedAt": now,
                "afterImageUrl": "https://storage.googleapis.com/decorate-me-renders/retained/a.png",
                "beforeImageUrl": "https://storage.googleapis.com/decorate-me-renders/retained/b.png", "isPermanent": True, "dedupKey": key}
    job_store.create(render_api.RENDER_JOBS_COLLECTION, original["jobId"], original)
    monkeypatch.setattr(render_api, "RENDER_DURABLE_DEDUP_ENABLED", True)
    monkeypatch.setattr(render_api, "_server_render_prompt", lambda _: ("fixture", "fixture"))
    delete = Mock(return_value=True)
    monkeypatch.setattr(render_api, "delete_permanent_storage_url", delete)
    duplicate = asyncio.run(render_api.create_render_job(req, Mock(), x_user_id="actor_fixture"))
    asyncio.run(render_api.delete_owned_render_artifact(original["jobId"], x_user_id="actor_fixture", x_admin_request=None))
    delete.assert_not_called()
    assert job_store.get(render_api.RENDER_JOBS_COLLECTION, duplicate["jobId"])["status"] == "completed"
    asyncio.run(render_api.delete_owned_render_artifact(duplicate["jobId"], x_user_id="actor_fixture", x_admin_request=None))
    assert delete.call_count == 2


def test_dedup_cache_checks_source_deleted_by_other_instance(monkeypatch, memory):
    monkeypatch.setattr(render_api, "RENDER_DEDUP_TTL_SECONDS", 600)
    job = {"jobId": "source", "status": "completed", "afterImageUrl": "old"}
    job_store.create(render_api.RENDER_JOBS_COLLECTION, "source", job)
    render_api._dedup_set("key", job, "source")
    job_store.patch(render_api.RENDER_JOBS_COLLECTION, "source", {"afterImageUrl": "retained"})
    assert render_api._dedup_get("key")["afterImageUrl"] == "retained"
    job_store.delete(render_api.RENDER_JOBS_COLLECTION, "source")
    assert render_api._dedup_get("key") is None


def test_expired_dedup_siblings_do_not_orphan_their_images(monkeypatch, memory):
    """兩個共用同一張圖的 job 在同一輪過期時，圖必須真的被刪掉。

    「引用」的定義是「還存在的其他 job」。如果先把要刪的文件收集起來、最後才一起
    刪，那麼掃描時兩個都會看到對方還在，於是各自判定有人共用而跳過刪除；文件接著被
    刪光，GCS 上的物件就再也沒有任何東西指得到它。漏掉的 beforeImageUrl 是使用者
    自己的臉，那是隱私事故，不只是佔空間。
    """
    after = "https://storage.googleapis.com/decorate-me-renders/shared/after.png"
    before = "https://storage.googleapis.com/decorate-me-renders/shared/before.png"
    stale = time.time() - render_api.RENDER_JOB_RETENTION_SECONDS - 60
    for job_id in ("source", "duplicate"):
        job_store.create(render_api.RENDER_JOBS_COLLECTION, job_id, {
            "jobId": job_id, "status": "completed", "retained": False,
            "createdAt": stale, "finishedAt": stale, "isPermanent": True,
            "afterImageUrl": after, "beforeImageUrl": before})
    delete = Mock(return_value=True)
    monkeypatch.setattr(render_api, "delete_permanent_storage_url", delete)
    render_api._cleanup_render_jobs()
    assert job_store.all_jobs(render_api.RENDER_JOBS_COLLECTION) == []
    assert {call.args[0] for call in delete.call_args_list} == {after, before}


def test_dedup_hit_backfills_a_missing_before_image(monkeypatch, memory):
    """去重命中時要把這次請求的原圖帶進來，補建來源缺少的妝前圖。

    妝前圖 2026-07-22 才上線，更早的 job 都沒有。不帶原圖的話補建分支在快取命中這條
    路上是死碼，建出來的新 job 從出生就缺妝前圖——而妝後圖正常出現，看起來像是
    「妝前圖偶爾會壞」，很難查。
    """
    monkeypatch.setattr(render_api, "RENDER_DEDUP_TTL_SECONDS", 600)
    backfilled = "https://storage.googleapis.com/decorate-me-renders/before/new.png"
    job = {"jobId": "source", "status": "completed", "afterImageUrl": "after", "beforeImageUrl": None}
    job_store.create(render_api.RENDER_JOBS_COLLECTION, "source", job)
    render_api._dedup_set("key", job, "source")
    monkeypatch.setattr(render_api, "upload_bytes_to_permanent_storage", lambda *_: backfilled)
    assert render_api._dedup_get("key", TINY_PNG)["beforeImageUrl"] == backfilled
    # 不帶原圖就補不起來——這正是修好之前每一次快取命中的樣子。
    assert render_api._dedup_get("key")["beforeImageUrl"] is None


@pytest.mark.parametrize("absent", [
    ImportError("google.cloud is not installed"),
    __import__("google.auth.exceptions", fromlist=["x"]).DefaultCredentialsError("no credentials"),
])
def test_unconfigured_contribution_store_does_not_block_account_deletion(monkeypatch, absent):
    """沒有儲存空間＝從來沒存過樣本，該回 0 筆，不是刪除失敗。

    貢獻功能預設就是關的（FACE_CONTRIB_ENABLED 預設 "0"），這台機器因此沒有 GCS
    憑證。把那個當成刪除失敗的話，face 服務回 503、Gateway 轉成
    MEMBER_MEDIA_DELETE_INCOMPLETE，於是**每一位會員都刪不掉自己的帳號**。
    """
    monkeypatch.setattr(face_contributions, "_client", Mock(side_effect=absent))
    endpoint = next(r.endpoint for r in basic.app.routes if getattr(r, "path", "") == "/v1/face/users/{owner_id}")
    result = asyncio.run(endpoint("actor_fixture", x_user_id="actor_fixture", x_admin_request=None))
    assert result == {"status": "deleted", "contributions": 0}


def test_pro_session_rotation_survives_an_upstream_timeout(monkeypatch):
    """PRO 預檢輪替出來的 session，在失敗路徑上也必須封回瀏覽器。

    輪替之後舊的那份在上游已經作廢。只在成功路徑封回去的話，face-pro 逾時（上游
    timeout 120 秒，PRO 工作很容易撞到）回 504 時，瀏覽器留著一份作廢的 cookie，
    下一個請求就被登出——而使用者看到的是「分析逾時」，兩件事之間沒有任何線索。
    """
    request = request_fixture()
    # 真的物件而不是 Mock：`getattr(state, ..., None)` 在 Mock 上永遠拿得到東西，
    # 那樣這條測試就算修正被拿掉也會過。
    request.state = SimpleNamespace()
    request.cookies = {}
    request.app.state.http_client.get = AsyncMock(return_value=httpx.Response(
        200, json={"email": "member@example.invalid", "allowedPages": ["analysisPro"]},
        headers={"Set-Cookie": "session=rotated; Path=/; HttpOnly"},
        request=httpx.Request("GET", "https://member.invalid/api/members/fixture")))
    request.app.state.http_client.request = AsyncMock(side_effect=httpx.TimeoutException("upstream slow"))
    monkeypatch.setitem(gateway.UPSTREAMS, "face-pro", replace(
        gateway.UPSTREAMS["face-pro"], base_url="https://offline.invalid", requires_cloud_run_iam=False))
    monkeypatch.setattr(gateway, "SESSION_ONLY_MODE", True)
    monkeypatch.setattr(gateway, "GUEST_TRIAL_ENABLED", False)
    monkeypatch.setattr(gateway, "MULTI_SESSION_ENABLED", False)
    monkeypatch.setattr(gateway, "MEMBER_DATABASE_URL", "https://member.invalid")
    monkeypatch.setattr(gateway, "require_member_access", lambda _: {"sub": "member@example.invalid", "role": "member"})
    monkeypatch.setattr(gateway, "require_upstream_member_cookie", lambda _: "session=verified")
    monkeypatch.setattr(gateway, "enforce_expected_actor", lambda *_: None)
    seal = Mock(return_value="sealed-rotated")
    monkeypatch.setattr(gateway, "seal_member_cookie", seal)
    set_cookie = Mock()
    monkeypatch.setattr(gateway, "set_session_cookie", set_cookie)

    response = asyncio.run(gateway.proxy("face-pro", "v1/face/jobs/pro", request))
    assert response.status_code == 504

    # 出口的 middleware 靠這個把輪替後的 session 封回去。沒有它就是靜默登出。
    apply = getattr(request.state, "apply_member_cookie", None)
    assert apply is not None, "逾時路徑沒有留下重新封裝 session 的方法"
    apply(Mock())
    seal.assert_called_once_with("session=rotated")
    set_cookie.assert_called_once()


def _live_metrics():
    return {"model": "ConvNeXt-Tiny", "source": "promotion", "parts": {
        "face_shape": {"macroAccuracy": 0.534},
        "brow_shape": {"macroAccuracy": 0.592},
    }}


def _queue(run_id, part_key, macro, promotion_id, created_at, status="queued", part_zh="臉型"):
    job_store.create(gateway.FACE_TRAINING_RUNS_COL, run_id, {
        "runId": run_id, "status": "done",
        "modelAfter": {"parts": {part_key: {"macroAccuracy": macro}}}})
    job_store.create(gateway.FACE_MODEL_PROMOTIONS_COL, promotion_id, {
        "promotionId": promotion_id, "runId": run_id, "parts": [part_zh],
        "status": status, "createdAt": created_at})


def test_queued_promotions_move_the_comparison_baseline(memory):
    """按下換上線時要比的，是佇列跑完之後的分數，不是此刻線上的。

    換上線是排隊執行的。佇列裡已經有一筆要把臉型換成 61.0% 的話，現在登記的那一筆
    上線時前一手就是 61.0%，不是線上的 53.4%。拿線上的去比，畫面會說有進步，
    實際跑起來卻是退步——然後被 promote_model 用真實數字擋回來。
    """
    live = _live_metrics()
    _queue("TR-queued", "face_shape", 0.61, "PM-1", "2026-09-09T14:23:48+00:00")

    baseline, pending = asyncio.run(gateway._effective_model_baseline(live, []))

    assert baseline["parts"]["face_shape"]["macroAccuracy"] == 0.61
    # 佇列沒碰到的部位維持線上的數字，不能整份被換掉。
    assert baseline["parts"]["brow_shape"]["macroAccuracy"] == 0.592
    # 傳進去的那份是「線上此刻」，標題還要用它，不可以被就地改掉。
    assert live["parts"]["face_shape"]["macroAccuracy"] == 0.534
    assert [p["promotionId"] for p in pending] == ["PM-1"]


def test_last_queued_promotion_wins_for_the_same_part(memory):
    """同一個部位排了兩筆時，基準是**最後一筆**，不是分數最高的那筆。

    worker 照建立順序做，後做的覆蓋先做的。所以「兩筆都比現在高」不代表兩筆都算數，
    最終線上會是最後執行的那一版——即使它比前一筆低。
    """
    _queue("TR-first", "face_shape", 0.70, "PM-1", "2026-09-09T14:23:22+00:00")
    _queue("TR-second", "face_shape", 0.58, "PM-2", "2026-09-09T14:23:48+00:00")

    baseline, pending = asyncio.run(gateway._effective_model_baseline(_live_metrics(), []))

    assert baseline["parts"]["face_shape"]["macroAccuracy"] == 0.58
    assert [p["promotionId"] for p in pending] == ["PM-1", "PM-2"]


@pytest.mark.parametrize("status", ["deployed", "failed", "prepared"])
def test_finished_promotions_do_not_move_the_baseline(memory, status):
    """做完的不算。deployed 的結果已經反映在線上分數裡，再套一次是重複計算；
    failed 的根本沒上線。只有還沒做完的才會改變下一筆要比的對象。"""
    _queue("TR-done", "face_shape", 0.61, "PM-1", "2026-09-09T10:00:00+00:00", status=status)

    baseline, pending = asyncio.run(gateway._effective_model_baseline(_live_metrics(), []))

    assert baseline["parts"]["face_shape"]["macroAccuracy"] == 0.534
    assert pending == []


def test_baseline_survives_a_queue_entry_whose_run_is_missing(memory):
    """佇列裡的批次讀不到時，跳過那一筆就好，不能把其他筆的修正一起丟掉。

    批次不一定落在畫面取回的那幾筆裡（預設只取 5 筆），補讀也可能失敗。
    退回「完全不修正」等於悄悄回到舊行為，而畫面上看不出差別。
    """
    job_store.create(gateway.FACE_MODEL_PROMOTIONS_COL, "PM-ghost", {
        "promotionId": "PM-ghost", "runId": "TR-not-there", "parts": ["眉型"],
        "status": "running", "createdAt": "2026-09-09T14:00:00+00:00"})
    _queue("TR-real", "face_shape", 0.61, "PM-real", "2026-09-09T14:23:48+00:00")

    baseline, pending = asyncio.run(gateway._effective_model_baseline(_live_metrics(), []))

    assert baseline["parts"]["face_shape"]["macroAccuracy"] == 0.61
    assert baseline["parts"]["brow_shape"]["macroAccuracy"] == 0.592
    assert len(pending) == 2
