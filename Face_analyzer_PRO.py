import os
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api_errors import (
    enforce_service_api_key,
    error_payload,
    install_api_error_handling,
    secret_equals,
)
import job_store
import face_feedback
import face_corrections
import basic_roi_shadow
import pro_nose_side_model
from Face_analyzer_BASIC import FaceAnalyzer, MAX_IMAGE_PIXELS, MAX_UPLOAD_BYTES, unusable_image_message
from dev_server_utils import get_cors_origins, run_dev_server
from image_safety import sanitize_upload


app = FastAPI(title="Face Analyzer PRO")
_COL = "face_jobs_pro"

FACE_JOB_TIMEOUT_SECONDS = int(os.getenv("FACE_JOB_TIMEOUT_SECONDS", "180"))
FACE_JOB_RETENTION_SECONDS = int(os.getenv("FACE_JOB_RETENTION_SECONDS", "3600"))
FACE_JOB_MAX_COUNT = int(os.getenv("FACE_JOB_MAX_COUNT", "200"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

# 分析端點 API key 保護，比照 BASIC；/health、根路徑、OPTIONS 放行。
# 缺金鑰就拒絕啟動（fail closed），檢查掛在啟動流程而非 import 時（P0-7）。
FACE_API_KEY = os.getenv("FACE_API_KEY", "")
enforce_service_api_key(app, "FACE_API_KEY")
_API_KEY_OPEN_PATHS = {"/health", "/"}


@app.middleware("http")
async def _api_key_guard(request, call_next):
    if (FACE_API_KEY and request.method != "OPTIONS"
            and request.url.path not in _API_KEY_OPEN_PATHS):
        if not secret_equals(request.headers.get("x-api-key"), FACE_API_KEY):
            return JSONResponse(
                status_code=401,
                content={"detail": error_payload("FORBIDDEN", "Invalid or missing API key.", retryable=False)},
            )
    return await call_next(request)


install_api_error_handling(app, "face-analyzer-pro")


async def _read_image(file: UploadFile, label: str) -> bytes:
    """讀一張 PRO 照片：分段讀取、驗格式、卡像素、去掉 EXIF／GPS 後才往下送。

    PRO 一次收最多四張照片，每一張都走同一條路——多角度採集的照片同樣是手機原圖，
    帶著拍攝地點的機率比正面照更高。

    `sanitize_upload` 回傳的是 `(bytes, mime)`，要解包。2026-07-24 它從
    「只回 bytes」改成回 tuple 時，BASIC 的 `_read_clean_image` 跟著改了，
    這裡漏掉——於是 tuple 被原樣丟給 `FaceAnalyzer`，撞上型別檢查，
    PRO 的每一次分析都回 400，一路壞到 2026-07-31 才被發現。
    型別註記寫著 `-> bytes` 卻回傳 tuple，靜態檢查也沒攔下來。
    """
    contents, _mime = await sanitize_upload(
        file,
        max_bytes=MAX_UPLOAD_BYTES,
        max_pixels=MAX_IMAGE_PIXELS,
        label=f"{label}照片",
    )
    return contents


def _analyze_side_supplementary(side_bytes: bytes) -> dict | None:
    """
    對側面照做輔助分析：膚色、對稱性確認，以及側臉鼻型分類。
    使用 strict_angle=False 跳過正面角度驗證。
    失敗時靜默回傳 None，不中斷主流程。
    """
    try:
        analyzer = FaceAnalyzer(side_bytes, strict_angle=False, require_insight=False)
        lip_L, lip_a, lip_b, season, shade_label, L, a, b = analyzer.get_skin_color()
        result = {
            "膚色": {
                "四季型": season,
                "膚色分級": shade_label,
                "LAB": {
                    "L": float(round(L, 2)),
                    "a": float(round(a, 2)),
                    "b": float(round(b, 2)),
                },
                # 側面照的可信度一定要帶出去。_merge_basic_and_pro 靠它判斷平均後的 LAB
                # 能不能信；先前這裡沒放，那邊讀到的永遠是 {}，於是 side_ok 恆為 False，
                # **每一次帶側面照的 PRO 分析都被標成不可信**——等於關掉了所有 PRO 使用者
                # 的粉底 ΔE 比色，而那正是規格書說 reliable:false 時不可做的事。
                "可信度": getattr(analyzer, "skin_reliability",
                                  {"measured": False, "reliable": True, "hint": ""}),
            },
        }

        # 側臉鼻型（2026-07-31 接上）。餵整張圖，不做 landmark 裁切——
        # 側臉 FaceMesh 只認得 73.5%，而且失敗率依類別偏斜（塌鼻 60.4%、翹鼻 93.4%），
        # 用裁切會把類別分布扭曲（見 pro_nose_side_model 的說明）。
        #
        # 這是加值資訊，不是主要答案：除了塌鼻，各類驗證樣本只有 36~46 張。
        # predict 自帶 caveat 欄位，回應要原樣帶出去，不要在這裡拿掉。
        side_nose = pro_nose_side_model.predict(analyzer.frame)
        if side_nose:
            result["側臉鼻型"] = side_nose
        return result
    except Exception:
        return None


def _merge_basic_and_pro(front_result: dict, side_result: dict | None = None) -> dict:
    result = dict(front_result)
    result["分析版本"] = "PRO"

    side_available = side_result is not None

    # 側面照膚色成功分析時，與正面取平均以減少光線誤差
    if side_available:
        fs = front_result.get("膚色", {})
        ss = side_result.get("膚色", {})
        fl = fs.get("LAB", {})
        sl = ss.get("LAB", {})
        if fl and sl and all(k in fl and k in sl for k in ("L", "a", "b")):
            avg_lab = {
                "L": round((fl["L"] + sl["L"]) / 2, 2),
                "a": round((fl["a"] + sl["a"]) / 2, 2),
                "b": round((fl["b"] + sl["b"]) / 2, 2),
            }
            # 可信度要合併，不能直接沿用正面那張的。
            #
            # `{**fs, ...}` 會把正面照算出來的 可信度 原樣帶到一個「一半來自側面照」的
            # LAB 上，而側面照從來沒做過遮擋檢查——正面乾淨、側面被頭髮蓋住時，平均值
            # 已經被污染，旗標卻還說可信。兩張都判定可信才算可信；側面沒量過（measured
            # 為 False）就不能替它背書，一律降為不可信並說明原因。
            front_rel = fs.get("可信度") or {}
            side_rel = ss.get("可信度") or {}
            side_ok = bool(side_rel.get("measured")) and side_rel.get("reliable") is not False
            if front_rel.get("reliable") is not False and not side_ok:
                merged_rel = {
                    **front_rel,
                    "reliable": False,
                    "hint": "側面照的膚色取樣未經遮擋檢查，這個平均值請當作參考；"
                            "想要準確的膚色請確認兩張照片都沒有頭髮或陰影蓋住臉頰。",
                }
            elif front_rel.get("reliable") is False:
                merged_rel = front_rel
            else:
                merged_rel = {**front_rel, "reliable": True}
            result["膚色"] = {**fs, "LAB": avg_lab, "LAB來源": "正面+側面平均", "可信度": merged_rel}

        # 側臉模型的輸出屬於 PRO 結果的一部分，不能只停留在 side_result。
        # 保留完整物件（label／confidence／classes／caveat），讓前端既能顯示答案，
        # 也能誠實呈現目前驗證樣本較少的限制。
        side_nose = side_result.get("側臉鼻型")
        if isinstance(side_nose, dict) and side_nose.get("label"):
            result["側臉鼻型"] = side_nose
            # 舊版前端讀這個鍵；過渡期同時提供，避免後端先上線時 UI 看不到。
            result["鼻型_側面"] = side_nose

    has_symmetry = bool(front_result.get("臉部對稱性"))
    result["精細分析狀態"] = {
        "多角度照片": "已接收，膚色已雙角度平均" if side_available else "未提供側面照",
        "臉部對稱性": "已計算" if has_symmetry else "無法計算",
        "鼻型精細分類": (
            "已完成側臉鼻型分類（僅供參考）"
            if result.get("側臉鼻型")
            else ("已收到側面照，但側臉鼻型模型未能產生結果" if side_available else "未提供側面照")
        ),
    }
    result["精細分析備註"] = (
        "PRO 流程採正面照 + 單側側面照。"
        "側面照用於膚色雙角度平均與側臉鼻型輔助分類；"
        "側臉鼻型資料量仍有限，結果會附可信度與限制說明。"
    )
    return result


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _seconds_since(value, now):
    dt = _parse_iso(value)
    if not dt:
        return None
    return (now - dt).total_seconds()


def _cleanup_jobs():
    now = datetime.now(timezone.utc)
    jobs = job_store.all_jobs(_COL)
    to_delete = []
    for job in jobs:
        job_id = job.get("jobId")
        status = job.get("status")
        if status in {"queued", "processing"}:
            anchor = job.get("startedAt") or job.get("createdAt")
            age = _seconds_since(anchor, now)
            if age is not None and age > FACE_JOB_TIMEOUT_SECONDS:
                job_store.patch_if_status(_COL, job_id, {"queued", "processing"}, {
                    "status": "failed", "stage": "timeout",
                    "completedAt": _now_iso(),
                    "updatedAt": _now_iso(),
                    "error": {
                        "code": "FACE_ANALYSIS_TIMEOUT",
                        "message": f"臉部分析逾時，已超過 {FACE_JOB_TIMEOUT_SECONDS} 秒",
                        "retryable": True,
                    },
                })
        elif status in {"completed", "failed"}:
            age = _seconds_since(job.get("completedAt"), now)
            if age is not None and age > FACE_JOB_RETENTION_SECONDS:
                to_delete.append(job_id)
    for job_id in to_delete:
        job_store.delete(_COL, job_id)
    remaining = job_store.all_jobs(_COL)
    if len(remaining) > FACE_JOB_MAX_COUNT:
        ordered = sorted(remaining, key=lambda j: j.get("createdAt") or "")
        for job in ordered[: len(remaining) - FACE_JOB_MAX_COUNT]:
            job_store.delete(_COL, job.get("jobId"))


def _job_stats():
    jobs = job_store.all_jobs(_COL)
    stats = {"total": len(jobs), "queued": 0, "processing": 0, "completed": 0, "failed": 0}
    for job in jobs:
        status = job.get("status")
        if status in stats:
            stats[status] += 1
    return stats


def _job_view(job, include_token=False):
    hidden = {"result", "imageHash", "ownerId"}
    if not include_token:
        hidden.add("resultToken")
    return {k: v for k, v in job.items() if k not in hidden}


def _verify_job_token(job, x_job_token=None, result_token=None):
    expected = job.get("resultToken")
    if expected and (x_job_token or result_token) != expected:
        raise HTTPException(
            status_code=403,
            detail={"error": {"message": "job token 不正確或未提供"}},
        )


def _run_pro_job(job_id, front_bytes, angle_bytes, owner_id=None):
    if not job_store.patch_if_status(
        _COL,
        job_id,
        {"queued"},
        {"status": "processing", "stage": "front_analysis", "progress": 30, "startedAt": _now_iso(), "updatedAt": _now_iso()},
    ):
        return
    # 分析與封裝分開包，理由同 BASIC 的 _run_basic_job：封裝失敗時分析其實已經成功，
    # 標成 FACE_ANALYSIS_ERROR 會誤導使用者重拍一張本來就分析得出來的照片。
    try:
        front_result = FaceAnalyzer(front_bytes).export_json()
        # 套用這張臉已儲存的修正；模型原始輸出保留在 front_result["_modelRaw"]，
        # 回饋一律回報那一份——否則訓練資料會變成模型在確認自己。
        front_result = face_corrections.apply(
            front_result,
            face_corrections.image_hash(front_bytes),
            owner_id=owner_id,
        )
        job_store.patch_if_status(_COL, job_id, {"processing"}, {"stage": "side_analysis", "progress": 65, "updatedAt": _now_iso()})
        side_bytes = angle_bytes.get("side")
        side_result = _analyze_side_supplementary(side_bytes) if side_bytes else None
    except ValueError as exc:
        # 與 BASIC 的 _run_basic_job 同一個理由：FaceAnalyzer 對「這張照片本身有問題」一律
        # raise ValueError，訊息就是要給使用者看的可行動指引（pose_guidance 的「請把頭轉向
        # 你的右邊」、「沒偵測到人臉」、「膚色區域不足」）。PRO 用的是同一個 FaceAnalyzer、
        # 同樣 strict_angle=True，先前卻只有 BASIC 把訊息傳出去，PRO 這邊照舊吞掉——
        # 同一張斜臉走 BASIC 會被告知怎麼喬，走 PRO 只會拿到「請稍後再試」。
        hint = unusable_image_message(exc)
        if hint is None:
            # 同 BASIC：內部錯誤不能偽裝成重拍建議，要留 traceback。
            logging.exception("PRO 臉部分析 job 失敗 job_id=%s", job_id)
            job_store.patch_if_status(_COL, job_id, {"processing"}, {
                "status": "failed", "stage": "failed",
                "completedAt": _now_iso(), "updatedAt": _now_iso(),
                "error": {"code": "FACE_ANALYSIS_ERROR", "message": "臉部分析失敗，請稍後再試", "retryable": True},
            })
            return
        logging.info("PRO 臉部分析 job 因照片問題中止 job_id=%s: %s", job_id, hint)
        job_store.patch_if_status(_COL, job_id, {"processing"}, {
            "status": "failed", "stage": "unusable_image",
            "completedAt": _now_iso(), "updatedAt": _now_iso(),
            "error": {"code": "FACE_IMAGE_UNUSABLE", "message": hint, "retryable": True},
        })
        return
    except Exception:
        logging.exception("PRO 臉部分析 job 失敗 job_id=%s", job_id)
        job_store.patch_if_status(_COL, job_id, {"processing"}, {
            "status": "failed", "stage": "failed",
            "completedAt": _now_iso(), "updatedAt": _now_iso(),
            "error": {"code": "FACE_ANALYSIS_ERROR", "message": "臉部分析失敗，請稍後再試", "retryable": True},
        })
        return

    try:
        result = _merge_basic_and_pro(front_result, side_result=side_result)
        job_store.patch_if_status(_COL, job_id, {"processing"}, {
            "status": "completed", "stage": "done", "progress": 100,
            "completedAt": _now_iso(), "updatedAt": _now_iso(), "result": result, "error": None,
        })
    except Exception:
        logging.exception("PRO 分析結果封裝失敗 job_id=%s（分析已成功）", job_id)
        job_store.patch_if_status(_COL, job_id, {"processing"}, {
            "status": "failed", "stage": "analysis_completed",
            "completedAt": _now_iso(), "updatedAt": _now_iso(),
            "error": {"code": "PACKAGE_BUILD_FAILED",
                      "message": "臉部分析已完成，但結果封裝失敗，請稍後再試（不需重拍）。",
                      "retryable": True},
        })


@app.get("/health")
async def health():
    _cleanup_jobs()
    model_state = {
        "basic": basic_roi_shadow.model_status(),
        "proNoseSide": pro_nose_side_model.model_status(),
    }
    models_ready = model_state["basic"]["ready"] and model_state["proNoseSide"]["ready"]
    return {
        "status": "ok" if models_ready else "degraded",
        "service": "face-analyzer-pro",
        "models": model_state,
        "jobs": _job_stats(),
        "limits": {
            "timeoutSeconds": FACE_JOB_TIMEOUT_SECONDS,
            "retentionSeconds": FACE_JOB_RETENTION_SECONDS,
            "maxCount": FACE_JOB_MAX_COUNT,
        },
    }


@app.post("/analyze-pro")
@app.post("/v1/face/analyze/pro")
async def analyze_pro(
    front: UploadFile = File(...),
    left45: UploadFile | None = File(default=None),
    right45: UploadFile | None = File(default=None),
    side: UploadFile | None = File(default=None),
    x_user_id: str | None = Header(default=None),
):
    """
    PRO 檔案上傳版。

    目前可用流程：
    - front：必填正面照，先沿用 BASIC 的穩定分析。
    - side：正式 PRO 流程的必填側面照，用於未來側臉輪廓與鼻型精細分類。
    - left45/right45：保留欄位，作為未來 45 度多角度採集展望。

    掃描版預留：
    - 未來前端使用 getUserMedia 開鏡頭。
    - 依 yaw 自動擷取 front / side。
    - 擷取完成後仍送到這個 API，避免掃描版和檔案上傳版後端邏輯分裂。
    """
    try:
        front_bytes = await _read_image(front, "正面")
        front_result = FaceAnalyzer(front_bytes).export_json()
        front_result = face_corrections.apply(
            front_result,
            face_corrections.image_hash(front_bytes),
            owner_id=x_user_id,
        )

        side_bytes = None
        for label, role, upload in (
            ("左45度", "left45", left45),
            ("右45度", "right45", right45),
            ("側面", "side", side),
        ):
            if upload is None:
                continue
            b = await _read_image(upload, label)
            if role == "side" and side_bytes is None:
                side_bytes = b

        side_result = _analyze_side_supplementary(side_bytes) if side_bytes else None
        return _merge_basic_and_pro(front_result, side_result=side_result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logging.exception("PRO 臉部分析失敗")
        raise HTTPException(status_code=500, detail="臉部分析服務發生錯誤，請稍後再試")


@app.post("/v1/face/jobs/pro")
async def create_pro_job(
    background_tasks: BackgroundTasks,
    front: UploadFile = File(...),
    left45: UploadFile | None = File(default=None),
    right45: UploadFile | None = File(default=None),
    side: UploadFile | None = File(default=None),
    x_user_id: str | None = Header(default=None),
):
    _cleanup_jobs()
    try:
        front_bytes = await _read_image(front, "正面")
        angle_bytes = {}
        for label, role, upload in (("左45度", "left45", left45), ("右45度", "right45", right45), ("側面", "side", side)):
            angle_bytes[role] = await _read_image(upload, label) if upload is not None else None
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": {"message": str(e)}})

    job_id = f"JOB-{uuid.uuid4().hex[:12]}"
    result_token = uuid.uuid4().hex
    job_data = {
        # 正面照的穩定識別碼（SHA-256，不是影像本身）。PRO 收多角度，但五官判斷與修正
        # 都只出自正面那張，所以快取鍵跟 BASIC 用同一個定義——同一張正面照在兩種模式
        # 之間也因此共用同一份修正。見 face_corrections 的模組說明。
        "imageHash": face_corrections.image_hash(front_bytes),
        "ownerId": str(x_user_id or "").strip() or None,
        "jobId": job_id, "analysisPackageId": None, "status": "queued",
        "progress": 0, "stage": "upload", "createdAt": _now_iso(),
        "startedAt": None, "completedAt": None, "updatedAt": _now_iso(), "error": None, "result": None,
        "resultToken": result_token,
        "expiresAt": datetime.now(timezone.utc) + timedelta(seconds=FACE_JOB_RETENTION_SECONDS),
    }
    job_store.create(_COL, job_id, job_data)
    background_tasks.add_task(
        _run_pro_job,
        job_id,
        front_bytes,
        angle_bytes,
        job_data["ownerId"],
    )
    return _job_view(job_data, include_token=True)


@app.get("/v1/face/jobs/{job_id}")
async def get_pro_job(
    job_id: str,
    x_job_token: str | None = Header(default=None),
    result_token: str | None = Query(default=None),
):
    job = job_store.get(_COL, job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"error": {"message": "找不到 job"}})
    _verify_job_token(job, x_job_token=x_job_token, result_token=result_token)
    return _job_view(job)


@app.get("/v1/face/jobs/{job_id}/result")
async def get_pro_job_result(
    job_id: str,
    x_job_token: str | None = Header(default=None),
    result_token: str | None = Query(default=None),
):
    job = job_store.get(_COL, job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"error": {"message": "找不到 job"}})
    _verify_job_token(job, x_job_token=x_job_token, result_token=result_token)
    if job["status"] != "completed":
        raise HTTPException(status_code=409, detail={"error": {"message": "job 尚未完成", "status": job["status"]}})
    return {
        "jobId": job_id,
        "analysisPackageId": job["analysisPackageId"],
        "status": "completed",
        "result": job["result"],
    }


# 五官判斷回饋的路由由 face_feedback 統一提供——BASIC 與 PRO 的內容一模一樣，
# 各抄一份的結果是註解已經先分歧了。真正不同的只有 job 集合與 token 驗證，
# 所以那兩樣用參數傳進去。
face_feedback.register_route(app, mode="pro", jobs_collection=_COL, verify_job_token=_verify_job_token)


if __name__ == "__main__":
    run_dev_server(app, service_name="Face Analyzer PRO", env_prefix="FACE_PRO", default_port=8002)
