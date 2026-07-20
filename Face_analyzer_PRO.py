import json
import os
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api_errors import error_payload, install_api_error_handling
import job_store
from Face_analyzer_BASIC import FaceAnalyzer, _reject_if_too_large
from dev_server_utils import get_cors_origins, run_dev_server


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

# 分析端點 API key 保護，比照 BASIC；FACE_API_KEY 沒設定不擋，/health、根路徑、OPTIONS 放行。
FACE_API_KEY = os.getenv("FACE_API_KEY", "")
_API_KEY_OPEN_PATHS = {"/health", "/"}


@app.middleware("http")
async def _api_key_guard(request, call_next):
    if (FACE_API_KEY and request.method != "OPTIONS"
            and request.url.path not in _API_KEY_OPEN_PATHS):
        if request.headers.get("x-api-key") != FACE_API_KEY:
            return JSONResponse(
                status_code=401,
                content={"detail": error_payload("FORBIDDEN", "Invalid or missing API key.", retryable=False)},
            )
    return await call_next(request)


install_api_error_handling(app, "face-analyzer-pro")


async def _read_image(file: UploadFile, label: str) -> bytes:
    contents = await file.read()
    if not contents:
        raise ValueError(f"{label}照片是空的")
    _reject_if_too_large(contents)
    return contents


def _analyze_side_supplementary(side_bytes: bytes) -> dict | None:
    """
    對側面照（約 10° yaw）做輔助分析：膚色、對稱性確認。
    使用 strict_angle=False 跳過正面角度驗證。
    失敗時靜默回傳 None，不中斷主流程。
    """
    try:
        analyzer = FaceAnalyzer(side_bytes, strict_angle=False, require_insight=False)
        lip_L, lip_a, lip_b, season, shade_label, L, a, b = analyzer.get_skin_color()
        return {
            "膚色": {
                "四季型": season,
                "膚色分級": shade_label,
                "LAB": {
                    "L": float(round(L, 2)),
                    "a": float(round(a, 2)),
                    "b": float(round(b, 2)),
                },
            },
        }
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
            result["膚色"] = {**fs, "LAB": avg_lab, "LAB來源": "正面+側面平均"}

    has_symmetry = bool(front_result.get("臉部對稱性"))
    result["精細分析狀態"] = {
        "多角度照片": "已接收，膚色已雙角度平均" if side_available else "未提供側面照",
        "臉部對稱性": "已計算" if has_symmetry else "無法計算",
        "鼻型精細分類": (
            "需 70-90° 側面輪廓照才能分類翹鼻／鷹鉤鼻／塌鼻，"
            "目前側面角度（約 10°）不足，保留為未來展望"
        ),
    }
    result["精細分析備註"] = (
        "PRO 流程採正面照 + 單側側面照。"
        "側面照目前約 10° yaw，用於膚色雙角度平均與對稱性輔助；"
        "側面鼻型等深度特徵需 70-90° 輪廓照，保留為未來展望。"
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
    hidden = {"result"}
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


def _run_pro_job(job_id, front_bytes, angle_bytes):
    if not job_store.patch_if_status(
        _COL,
        job_id,
        {"queued"},
        {"status": "processing", "stage": "front_analysis", "progress": 30, "startedAt": _now_iso(), "updatedAt": _now_iso()},
    ):
        return
    try:
        front_result = FaceAnalyzer(front_bytes).export_json()
        job_store.patch_if_status(_COL, job_id, {"processing"}, {"stage": "side_analysis", "progress": 65, "updatedAt": _now_iso()})
        side_bytes = angle_bytes.get("side")
        side_result = _analyze_side_supplementary(side_bytes) if side_bytes else None
        result = _merge_basic_and_pro(front_result, side_result=side_result)
        job_store.patch_if_status(_COL, job_id, {"processing"}, {
            "status": "completed", "stage": "done", "progress": 100,
            "completedAt": _now_iso(), "updatedAt": _now_iso(), "result": result, "error": None,
        })
    except Exception:
        logging.exception("PRO 臉部分析 job 失敗 job_id=%s", job_id)
        job_store.patch_if_status(_COL, job_id, {"processing"}, {
            "status": "failed", "stage": "failed",
            "completedAt": _now_iso(), "updatedAt": _now_iso(),
            "error": {"code": "FACE_ANALYSIS_ERROR", "message": "臉部分析失敗，請稍後再試", "retryable": True},
        })


@app.get("/health")
async def health():
    _cleanup_jobs()
    return {
        "status": "ok",
        "service": "face-analyzer-pro",
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
        "jobId": job_id, "analysisPackageId": None, "status": "queued",
        "progress": 0, "stage": "upload", "createdAt": _now_iso(),
        "startedAt": None, "completedAt": None, "updatedAt": _now_iso(), "error": None, "result": None,
        "resultToken": result_token,
        "expiresAt": datetime.now(timezone.utc) + timedelta(seconds=FACE_JOB_RETENTION_SECONDS),
    }
    job_store.create(_COL, job_id, job_data)
    background_tasks.add_task(_run_pro_job, job_id, front_bytes, angle_bytes)
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


if __name__ == "__main__":
    run_dev_server(app, service_name="Face Analyzer PRO", env_prefix="FACE_PRO", default_port=8002)
